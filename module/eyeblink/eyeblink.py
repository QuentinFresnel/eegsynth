#!/usr/bin/env python

import time
import ConfigParser # this is version 2.x specific, on version 3.x it is called "configparser" and has a different API
import redis
import sys
import os
import FieldTrip
import multiprocessing
import threading

import numpy as np

from nilearn import signal

if hasattr(sys, 'frozen'):
    basis = sys.executable
else:
    basis = sys.argv[0]
installed_folder = os.path.split(basis)[0]

config = ConfigParser.ConfigParser()
config.read(os.path.join(installed_folder, 'eyeblink.ini'))

r = redis.StrictRedis(host=config.get('redis','hostname'), port=config.getint('redis','port'), db=0)
try:
    response = r.client_list()
except redis.ConnectionError:
    print "Error: cannot connect to redis server"
    exit()

class TriggerThread(threading.Thread):
    def __init__(self, r, config):
        threading.Thread.__init__(self)
        self.r = r
        self.config = config
        self.stopped = False
        lock.acquire()
        self.time = 0
        self.last = 0
        lock.release()
    def stop_thread(self):
        self.stopped = True
    def run(self):
        pubsub = self.r.pubsub()
        channel = self.config.get('input','calibrate')
        pubsub.subscribe(channel)
        for item in pubsub.listen():
            if self.stopped:
                break
            else:
                print item['channel'], ":", item['data']
                lock.acquire()
                self.last = self.time
                lock.release()

# start the background thread
lock = threading.Lock()
trigger = TriggerThread(r, config)
trigger.start()

ftc = FieldTrip.Client()

H = None
while H is None:
    print 'Trying to connect to buffer on %s:%i ...' % (config.get('fieldtrip','hostname'), config.getint('fieldtrip','port'))
    ftc.connect(config.get('fieldtrip','hostname'), config.getint('fieldtrip','port'))
    print '\nConnected - trying to read header...'
    H = ftc.getHeader()

print H
print H.labels

blocksize = round(config.getfloat('general','blocksize') * H.fSample)
print blocksize

channel = config.getint('input','channel')-1

minval = None
maxval = None

t = 0

while True:
    time.sleep(config.getfloat('general','blocksize')/10)
    t += 1

    lock.acquire()
    if trigger.last == trigger.time:
        minval = None
        maxval = None
    trigger.time = t
    lock.release()

    H = ftc.getHeader()
    endsample = H.nSamples - 1
    if endsample<blocksize:
        continue

    begsample = endsample-blocksize+1
    D = ftc.getData([begsample, endsample])


    D = D[:,channel]

    try:
        low_pass = config.getint('general', 'low_pass')
    except:
        low_pass = None


    try:
        high_pass = config.getint('general', 'high_pass')
    except:
        high_pass = None


    # TODO : test detection with filtering (following line)
    # D = signal.butterworth(D,H.fSample, low_pass=low_pass, high_pass=high_pass, order=config.getint('general', 'order'))

    if minval is None:
        minval = np.min(D)

    if maxval is None:
        maxval = np.max(D)

    minval = min(minval,np.min(D))
    maxval = max(maxval,np.max(D))

    spread = np.max(D) - np.min(D)
    if spread > float(config.get('input','thresh_ratio'))*(maxval-minval):
        val = 1
    else:
        val = 0

    print('spread ' + str(spread) +
          '\t  max_spread : ' + str(maxval-minval) +
          '\t  output ' + str(val))

    key = "%s.channel%d" % (config.get('output','prefix'), channel)
    r.publish(key,val)
