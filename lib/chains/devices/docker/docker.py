# -*- coding: utf-8 -*-
import socket
import json
import time

# import requests_unixsocket
# import requests
# requests_unixsocket.monkeypatch()
# r = requests.get('http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/')


def pretty(jobj):
    print json.dumps(jobj, sort_keys=True, indent=4, separators=(',', ': '))

def reader():
    while True:
        data = docker.recv(1024)
        if not data:
            break
        else:
            print '%s' % data

if __name__ != '__main__':
    pass
else:
    print "trying to read from docker socket"
