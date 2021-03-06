# -*- coding: utf-8 -*-
import socket
import json
import time

# import requests_unixsocket
# import requests
# requests_unixsocket.monkeypatch()
# r = requests.get('http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/')


class Docker(object):

    def pretty(self, jobj):
        print json.dumps(jobj, sort_keys=True, indent=4, separators=(',', ': '))

    def container(self, cid):
        print "def container(cid)"
        cid = json.loads(cid)
        pretty(cid)
        if u'status' in cid:
            docker2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            docker2.connect("/var/run/docker.sock")
            message = 'GET /containers/%s/json HTTP/1.1\n\n' % cid['id']
            print message
            docker2.send(message)
            info = docker2.recv(1024)
            print "container info:"
            print info
            print "container info ends"
            docker2.close()
        else:
            print "couldn't find status in cid"
        print "def container(cid) ends"

    def reader(self):
        docker = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        docker.connect("/var/run/docker.sock")
        message = 'GET /events HTTP/1.1\n\n'
        # message = 'GET /events?since=1374067924'
        docker.send(message)
        # socat - UNIX-CONNECT:/var/run/docker.sock
        # GET /events HTTP/1.1
        while True:
            data = docker.recv(1024)
            if not data:
                break
            else:
                print '%s' % data
                for part in parts:
                    if part.startswith('{'):
                        container(part)
                #try:
                #    print "json - " + str(json.loads(part))
                #    if type(json.loads(part)) == int:
                #        print "status message ignoring"
                #    else:
                #        container(part)
                #except ValueError, e:
                #    print "non-json content: %s" % part
            if "QUIT" == data:
                break

        print "Shutting down..."
        docker.close()
        print "Done"


if __name__ != '__main__':
    pass
else:
    print "trying to read from docker socket"
    Docker.reader()
