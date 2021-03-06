from chains.common import log, utils, amqp, config
from chains.service import config as serviceConfig
import time, threading, ConfigParser, os, uuid

class TimeoutThread(threading.Thread):
    '''
    Thread for checking if daemons have timed out.

    Will periodically check last heartbeat time for
    managers, services, and reactors, and if it is too old,
    the item in question will be set as offline.
    '''

    def __init__(self, orchestrator):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.orchestrator = orchestrator

    def run(self):
        while True:

            # Run thru all types (manager, service, reactor)
            for daemonType in self.orchestrator.data:

                # For each item (f.ex. for each manager)
                for daemonId in self.orchestrator.data[daemonType]:

                    self.handleDaemonItem(daemonType, daemonId)

            # Broadcst heartbeat request, to get fresh heartbeats for next run
            self.orchestrator.sendHeartBeatRequest()

            # Pause interval
            time.sleep(self.orchestrator.timeoutInterval)

    def handleDaemonItem(self, type, id):

        # If item is already offline, do nothing - but (re)start if applicable
        item = self.orchestrator.data[type][id]
        if item['online'] == False:

            if type == 'service':

                if not item.has_key('offlineTimer'):
                    item['offlineTimer'] = time.time()

                if item['main'].get('autostart'):
                    if item.get('manuallyStopped'):
                        log.debug('Do not auto-start service %s since manually stopped' % id)
                    else:
                        timeSinceOffline = time.time() - item['offlineTimer']
                        if timeSinceOffline > self.orchestrator.startInterval:
                            self.orchestrator.data[type][id]['offlineTimer'] = time.time()
                            try:
                                #self.orchestrator.action_startService(id)
                                serviceId, managerId = self.orchestrator.parseServiceParam(id)
                                if self.orchestrator.isOnline('manager', managerId):
                                    log.info('Auto-start service %s @ %s after %s secs offline' % (serviceId, managerId, timeSinceOffline))
                                    self.orchestrator.startService(managerId, serviceId)
                                else:
                                    log.debug('Do not auto-start service %s since manager %s is offline' % (id,managerId))
                            except Exception, e:
                                log.error('Error trying to autostart service %s: %s' % (id,e))
                        else:
                            log.debug('Do not auto-start service %s since %s secs offline is less than startinterval %s' % (id,timeSinceOffline,self.orchestrator.startInterval))
                else:
                    log.debug('Do not auto-start service %s since autostart not set in config' % (id,))

            return

        # If item is online...
        # Check if existing heartbeat is old, and if so, set to offline
        if not item.has_key('heartbeat'):
            item['heartbeat'] = 0
        else:
            now = time.time()
            if (now-item['heartbeat']) > self.orchestrator.timeout:
                log.info('now %s - hb %s > timeout %s' % (now,item['heartbeat'],self.orchestrator.timeout))
                self.orchestrator.setOffline(type, id)



class Orchestrator(amqp.AmqpDaemon):

    def __init__(self, id):
        log.info('Starting orchestator')
        amqp.AmqpDaemon.__init__(self, 'orchestrator', id)
        self.data = {
            'manager':      {},
            'service':       {},
            'reactor':      {},
            'orchestrator': {}
        }
        self.timeout = 30
        self.timeoutInterval = 5
        self.startInterval = 15
        self.timeoutThread = TimeoutThread(self)
        self.loadServiceConfigs()

    def run(self):
        self.sendEvent('online', {'value': True})
        self.timeoutThread.start()
        self.listen()
        self.sendEvent('online', {'value': False})

    def getConsumeKeys(self):
        return [
            # actions to orchestrator itself
            '%s%s.%s.*' % (amqp.PREFIX_ORCHESTRATOR, amqp.PREFIX_ACTION, self.id),

            # online/offline/heartbeat events
            '%s%s.*' % (amqp.PREFIX_SERVICE,  amqp.PREFIX_HEARTBEAT_RESPONSE),
            '%s%s.*' % (amqp.PREFIX_MANAGER, amqp.PREFIX_HEARTBEAT_RESPONSE),
            '%s%s.*' % (amqp.PREFIX_REACTOR, amqp.PREFIX_HEARTBEAT_RESPONSE),
        ]

    def prefixToType(self, prefix):
        if prefix == amqp.PREFIX_SERVICE:       return 'service'
        if prefix == amqp.PREFIX_MANAGER:      return 'manager'
        if prefix == amqp.PREFIX_REACTOR:      return 'reactor'
        if prefix == amqp.PREFIX_ORCHESTRATOR: return 'orchestrator'

    def typeToPrefix(self, type):
        return self.getDaemonTypePrefix(type)
        '''
        if type == 'service': return amqp.PREFIX_SERVICE
        if type == 'manager': return amqp.PREFIX_MANAGER
        if type == 'reactor': return amqp.PREFIX_REACTOR
        '''

    def sendHeartBeatRequest(self): #, type, id):
        #topic = '%s.%s' (self.getHeartBeatRequestPrefix(type), id)
        topic = self.getHeartBeatRequestPrefix()
        self.producer.put(topic, amqp.HEARTBEAT_VALUE_REQUEST)

    def onMessage(self, topic, data, correlationId):
        #log.info('MSG: %s = %s' % (topic,data))
        topic = topic.split('.')

        # Heartbeats
        if topic[0][1] == amqp.PREFIX_HEARTBEAT_RESPONSE:
            if data == amqp.HEARTBEAT_VALUE_OFFLINE:
                self.setOffline(self.prefixToType(topic[0][0]), topic[1])
            elif data == amqp.HEARTBEAT_VALUE_ONLINE:
                self.setOnline(self.prefixToType(topic[0][0]), topic[1], force=True)
            elif data == amqp.HEARTBEAT_VALUE_RESPONSE:
                self.setOnline(self.prefixToType(topic[0][0]), topic[1])
            else:
                log.warn('Unknown heartbeat event: %s' % (topic,))

        # Service list responses
        '''
        elif topic[0][1] == amqp.PREFIX_ACTION_RESPONSE and topic[2] == 'getServices':

            managerId = topic[1]

            # Remove existing services for the manager
            removeServices = []
            for serviceId in self.data['service']:
                if not self.data['service'][serviceId].has_key('manager') or self.data['service'][serviceId]['manager'] == managerId:
                    removeServices.append(serviceId)
            for serviceId in removeServices:
                del self.data['service'][serviceId]

            # Add services from manager reply
            for serviceId in data:
                if not self.data['service'].has_key(serviceId):
                    self.data['service'][serviceId] = data[serviceId]
                else:
                    self.data['service'][serviceId]['online'] = data[serviceId]['online']
                self.data['service'][serviceId]['manager'] = managerId
            self.data['manager'][managerId]['services'] = len(data)

        # Manager reconfigure events - should trigger refresh of service list
        elif topic[0][1] == amqp.PREFIX_EVENT and topic[2] == 'reconfigured':
            newServices = {}
            for id in self.data['service']:
                if self.data['service'][id]['manager'] == topic[1]:
                    continue
                newServices[id] = self.data['service'][id]
            self.data['service'] = newServices
            self.data['manager'][topic[1]]['services'] = None
            log.info('Ask manager %s for service list since reconfigured' % topic[1])
            self.sendManagerAction(topic[1], 'getServices')
        '''

    def setOnline(self, type, key, force=False):

        if not type or not key:
            log.warn('Ignore attempt to set type=%s id=%s as online' % (type,key))
            return

        # Init dict path if not set
        if not self.data[type].has_key(key):
            self.data[type][key] = {'online': None}
            #if type == 'manager':
            #    self.data[type][key]['services'] = None

        # If not already online (or force [re-]online)
        # Set online and send online-event
        if self.data[type][key]['online'] != True or force:
            log.info('%s %s changed status to online' % (type, key))
            self.data[type][key]['online'] = True
            '''
            if type == 'manager':
                log.info('Ask manager %s for service list since changed to online' % key)
                self.sendManagerAction(key, 'getServices')
            '''
            eventTopic = '%s%s.%s.online' % (
                self.typeToPrefix(type),
                amqp.PREFIX_EVENT,
                key
            )
            event = {'data': {'value': True}, 'key': 'online'}
            if type == 'service':
                event['service'] = key
            else:
                event['host'] = key
            self.producer.put(eventTopic, event)

        # Update last heartbeat time
        self.data[type][key]['heartbeat'] = time.time()

    def setOffline(self, type, key):

        if not type or not key:
            log.warn('Ignore attempt to set type=%s id=%s as offline' % (type,key))
            return

        # Init dict path if not set
        if not self.data[type].has_key(key):
            self.data[type][key] = {'online': None}
            #if type == 'manager':
            #    self.data[type][key]['services'] = None

        # If not already offline, set offline and send offline event
        if self.data[type][key]['online'] != False:
            log.info('%s %s changed status to offline' % (type, key))
            self.data[type][key]['online'] = False
            self.data[type][key]['offlineTimer'] = time.time()

            eventTopic = '%s%s.%s.online' % (
                self.typeToPrefix(type),
                amqp.PREFIX_EVENT,
                key
            )
            event = {'data': {'value': False}, 'key': 'online'}
            if type == 'service':
                event['service'] = key
            else:
                event['host'] = key
            self.producer.put(eventTopic, event)

    def isOnline(self, type, key):
        try:
            return self.data[type][key]['online']
        except KeyError:
            return False

    def reloadServiceConfigs(self):
        self.loadServiceConfigs(isReload=True)

    def loadServiceConfigs(self, isReload=False):
        if not isReload or not self.data.get('service'):
            self.data['service'] = {}
        for path in self.getServiceConfigList():
            self.loadServiceConfig(path, isReload=isReload)

    def loadServiceConfig(self, path, isReload=False):

        if isReload:
            log.info('Reload service config: %s' % path)
        else:
            log.info('Load service config: %s' % path)

        instanceConfig    = self.loadConfigFile(path)
        instanceData      = self.configParserToDict(instanceConfig)
        classDir          = '%s/config/service-classes' % config.get('libdir')
        classFile         = '%s/%s.conf' % (classDir, instanceData['main']['class'])
        classConfig       = self.loadConfigFile(classFile)
        classData         = self.configParserToDict(classConfig)
        hasChanges        = False

        if not instanceData['main'].get('id'):
            id = self.generateUuid()
            instanceData['main']['id'] = id
            instanceConfig.set('main', 'id', id)
            hasChanges = True

        if not instanceData['main'].get('name'):
            name = instanceData['main']['class'].lower()
            instanceData['main']['name'] = name
            instanceConfig.set('main', 'name', name)
            hasChanges = True

        if not instanceData['main'].get('manager'):
            manager = 'master'
            instanceData['main']['manager'] = manager
            instanceConfig.set('main', 'manager', manager)
            hasChanges = True

        if hasChanges:
            with open(path, 'w') as instanceFile:
                instanceConfig.write(instanceFile)

        data              = self.mergeDictionaries(classData, instanceData)

        data['online']    = False
        data['heartbeat'] = 0

        if isReload and self.data['service'].has_key( data['main']['id'] ):

            old               = self.data['service'][ data['main']['id'] ]
            data['online']    = old.get('online')
            data['heartbeat'] = old.get('heartbeat')

            if not data.get('online'):     data['online'] = False
            if not data.get('heartbeat'):  data['heartbeat'] = 0

        self.data['service'][ data['main']['id'] ] = data

    def loadConfigFile(self, path):
        conf = ConfigParser.ConfigParser()
        conf.read(path)
        return conf

    def configParserToDict(self, conf):
        data = {}
        for section in conf.sections():
            if not data.has_key(section):
                data[section] = {}
            for key in conf.options(section):
                data[section][key] = conf.get(section, key)
        return data

    def mergeDictionaries(self, dict1, dict2, result=None):
        if not result:
            result = {}
        for k in set(dict1.keys()).union(dict2.keys()):
            if k in dict1 and k in dict2:
                if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                    result[k] = self.mergeDictionaries(dict1[k], dict2[k])
                else:
                    # If one of the values is not a dict, you can't continue merging it.
                    # Value from second dict overrides one in first and we move on.
                    result[k] = dict2[k]
            elif k in dict1:
                result[k] = dict1[k]
            else:
                result[k] = dict2[k]
        return result



    def getServiceConfigList(self):
        ret = []
        dir = '%s/services' % config.get('confdir')
        for file in os.listdir(dir):
            if file.split('.')[-1:][0] != 'conf':
                continue
            ret.append('%s/%s' % (dir,file))
        ret.sort()
        return ret



    def getServiceManager(self, serviceId):
        try:
            item = self.data['service'][serviceId]
        except KeyError:
            return None
        else:
            return item['main']['manager']

    def sendManagerAction(self, managerId, action, args=None):
        if not self.isOnline('manager', managerId):
            raise Exception('Manager not online: %s' % managerId)
        amqp.AmqpDaemon.sendManagerAction(self, managerId, action, args)


    def action_getManagers(self):
        return self.data['manager']

    def action_getServices(self):
        '''
        ret = []
        for serviceId in self.data['service']:
            conf = self.data['service'][serviceId]
            main = conf.get('main')
            ret.append({
                'id':       main.get('id'),
                'class':    main.get('class'),
                'manager':  main.get('manager'),
                'online':   conf.get('online'),
                'hearbeat': conf.get('heartbeat')
            })
        return ret
        '''
        return self.data['service']

    def action_getReactors(self):
        return self.data['reactor']

    '''
    def action_reloadManager(self, managerId):
        self.sendManagerAction(managerId, 'reload')
    '''

    def action_getServiceConfig(self, service):
        serviceId, managerId = self.parseServiceParam(service)
        config = self.data['service'][serviceId]
        return config

    def action_reload(self):
        self.reloadServiceConfigs()


    # ===================================================
    # Manager proxy
    # @todo: use rpc so can get response result?
    # ===================================================

    def action_startService(self, service):
        #self.reloadServiceConfigs()
        serviceId, managerId = self.parseServiceParam(service)
        return self.startService(managerId, serviceId)

    def action_stopService(self, service):
        serviceId, managerId = self.parseServiceParam(service)
        #return self.callManagerAction(managerId, 'stopService', [serviceId])
        self.data['service'][serviceId]['manuallyStopped'] = True
        self.sendManagerAction(managerId, 'stopService', [serviceId])

    def startService(self, managerId, serviceId):
        config = self.data['service'][serviceId]
        #self.sendManagerAction(managerId, 'startService', [config])
        self.data['service'][serviceId]['manuallyStopped'] = False
        self.sendManagerAction(managerId, 'startService', [config])

    '''
    def action_enableService(self, serviceId):
        managerId = self.getServiceManager(serviceId)
        if not managerId:
            raise Exception('No such service: %s' % serviceId)
        self.sendManagerAction(managerId, 'enableService', [serviceId])

    def action_disableService(self, serviceId):
        managerId = self.getServiceManager(serviceId)
        if not managerId:
            raise Exception('No such service: %s' % serviceId)
        self.sendManagerAction(managerId, 'disableService', [serviceId])
    '''


    def generateUuid(self):
        return uuid.uuid4().hex

    def parseServiceParam(self, value):
        service, manager = self._parseServiceParam(value)
        log.debug('Parsed service id: %s => %s @ %s' % (value, service, manager))
        return service, manager

    def _parseServiceParam(self, value):

        # serviceId
        serviceConfig = self.data['service'].get(value)
        if serviceConfig:
            #log.info("parseServiceParam(1): %s => %s @ %s" % (value, value, serviceConfig['main'].get('manager')))
            return value, serviceConfig['main'].get('manager')

        # managerId.serviceName
        tmp = value.split('.')
        if len(tmp) == 2:
            managerId, serviceName = tmp
            for serviceId in self.data['service']:
                serviceConfig = self.data['service'][serviceId]
                if serviceConfig['main'].get('manager') != managerId:
                    continue
                if serviceConfig['main'].get('name') != serviceName:
                    continue
                #log.info("parseServiceParam(2): %s => %s @ %s" % (value, serviceId, managerId))
                return serviceId, managerId

        # serviceName
        serviceName = value
        items      = []
        for serviceId in self.data['service']:
            serviceConfig = self.data['service'][serviceId]
            if serviceConfig.get('main').get('name') == serviceName:
                items.append(serviceConfig)
        if len(items) == 1:
            serviceConfig = items[0]
            #log.info("parseServiceParam(3): %s => %s @ %s" % (value,serviceConfig['main'].get('id'), serviceConfig['main'].get('manager')))
            return serviceConfig['main'].get('id'), serviceConfig['main'].get('manager')

        # not found
        raise Exception('No such service: %s' % value)



def main(id):
    log.setFileName('orchestrator')
    amqp.runWithSignalHandler(Orchestrator(id))

if __name__ == '__main__':
    main('main')
