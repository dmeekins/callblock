#!/usr/bin/env python3
#
#  File name: callblock.py
#
#  Copyright:  Copyright (C) 2015 Daniel Meekins
#
#  Copy permission:
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You may view a copy of the GNU General Public License at:
#             <http://www.gnu.org/licenses/>.
#
# The code to communicate with the modem was ported to python from
# the "jcblock" project: http://jcblock.sourceforge.net/
#

import binascii
import fcntl
import logging
import os
import re
import resource
import signal
import sys
import termios
import time
from argparse import ArgumentParser, ArgumentError
from configparser import ConfigParser
from datetime import datetime

running = True
blacklist = {
    'numbers': [],
    'names': []
}
config = ConfigParser()
configFile = None

class Call:

    def __init__(self, dt=None, number='', name=''):
        self.datetime = dt or datetime.now()
        self.number = number
        self.name = name.upper()

        return

    def __str__(self):
        return 'date=%s, number=%s, name=%s' % (self.datetime.isoformat(),
                                                self.number,
                                                self.name)


class Modem:

    def __init__(self, device):
        self.device = device
        self.fd = -1
        self.MAX_READ = 255
        return

    def open(self):
        try:
            self.fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY)
            fcntl.fcntl(self.fd, fcntl.F_SETFL, 0)
            attrs = termios.tcgetattr(self.fd)
        except:
            return False

        # set options to 1200B/8/N/1, hardware flow control, raw input
        attrs[4] = termios.B1200
        attrs[5] = termios.B1200
        attrs[2] &= ~termios.PARENB
        attrs[2] &= ~termios.CSTOPB
        attrs[2] &= ~termios.CSIZE
        attrs[2] |= termios.CS8
        attrs[2] |= termios.CRTSCTS
        attrs[2] |= (termios.CLOCAL | termios.CREAD)
        attrs[3] &= ~(termios.ICANON | termios.ECHO |
                      termios.ECHOE | termios.ISIG)
        attrs[1] &= ~termios.OPOST

        # block reads until have 80 bytes or after 0.1s between chars
        attrs[6][termios.VMIN] = 80
        attrs[6][termios.VTIME] = 1

        # set attributes
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

        return self.reset()

    def send(self, cmd):
        if self.fd < 0:
            return False

        # send the command, adding a terminator if needed
        if not cmd[-1] in ['\r', '\n']:
            cmd += '\r'
        cmd = cmd.encode()
        num_sent = os.write(self.fd, cmd)
        if num_sent != len(cmd):
            return False

        # try to read at most 10 lines to get the 'OK'
        for i in range(0, 10):
            data = b''
            while True:
                bytes_ = os.read(self.fd, self.MAX_READ)
                if not bytes_:
                    break
                data += bytes_
                if data[-1:] in [b'\r', b'\n']:
                    break

            if b'OK' in data:
                return True

        return False

    def reset(self):
        if self.fd < 0:
            return False

        if not self.send('ATZ'):
            return False
        return self.send('AT+VCID=1')

    def close(self):
        if self.fd < 0:
            return

        self.send('ATZ')
        os.close(self.fd)
        self.fd = -1

        return

    def wait_for_call(self):
        while True:
            try:
                bytes_ = os.read(self.fd, self.MAX_READ)
            except InterruptedError:
                bytes_ = None

            if not bytes_:
                break
            data = bytes_.decode()

            # ignore responses with these strings
            if 'RING' in data or 'AT+VCID=1' in data:
                continue

            dict_ = {}
            for part in re.split('[\n\r]+', data.strip()):
                key, val = part.split(' = ')
                dict_[key] = val

            dt = datetime.strptime(dict_['DATE'] + dict_['TIME'], '%m%d%H%M')
            dt = dt.replace(datetime.today().year)

            return Call(dt, dict_['NMBR'], dict_['NAME'])

        return None

    def pickup(self):
        return self.send('ATH1')

    def hangup(self):
        return self.send('ATH0')


def daemonize():

    # double fork to get rid of parent
    try:
        if os.fork() > 0:
            os._exit(0)
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
    except:
        return False

    # close all the open file descriptors
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    maxfd = limits[1]
    if maxfd == resource.RLIM_INFINITY:
        maxfd = 2048
    for fd in reversed(range(maxfd)):
        try:
            os.close(fd)
        except:
            pass

    # reopen stdin/out/err to /dev/null
    try:
        fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(fd, sys.stdin.fileno())
        fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(fd, sys.stdout.fileno())
        os.dup2(fd, sys.stderr.fileno())
    except:
        return False

    return True


def call_loop(modem, blacklist):
    global running

    while running:
        block = False
        call = modem.wait_for_call()
        if not call:
            if not running:
                break
            continue

        logging.info('received call: {}'.format(str(call)))

        for num in blacklist['numbers']:
            if call.number.startswith(num):
                block = True
                break
        if not block:
            for name in blacklist['names']:
                if name in call.name:
                    block = True
                    break
        if block:
            logging.info('blocking call from %s/%s' % (call.number, call.name))
            modem.pickup()
            modem.hangup()
            modem.reset()

    return


def update_blacklist(config):
    global blacklist

    if 'Blacklist' in config:
        numbers = config['Blacklist'].get('Numbers', '').strip()
        num_list = [x for x in re.split('[\n\r]+', numbers) if x]
        blacklist['numbers'] = num_list
        names = config['Blacklist'].get('Names', '').strip()
        name_list = [x.upper() for x in re.split('[\n\r]+', names) if x]
        blacklist['names'] = name_list
    else:
        blacklist['numbers'] = []
        blacklist['names'] = []

    return


def signal_handler(signum, frame):
    global blacklist
    global config
    global configfile
    global running

    if signum == signal.SIGHUP:
        logging.info('received SIGHUP, updating blacklist')
        config.read(configfile)
        update_blacklist(config)
    elif signum in [signal.SIGINT, signal.SIGTERM]:
        logging.info('received SIGINT or SIGTERM, stopping')
        running = False

    return


def main():
    global blacklist
    global config
    global configfile

    parser = ArgumentParser(description='Call blocker daemon')
    parser.add_argument('-c', dest='config', metavar='FILE',
                        default='/etc/callblock.conf',
                        help='Specify the configuration file')
    parser.add_argument('-d', dest='device', metavar='DEV',
                        help='Specify the device to use (overrides config)')
    parser.add_argument('-f', dest='forground', action='store_true',
                        help='Run in the forground')
    parser.add_argument('-l', dest='logfile', metavar='FILE',
                        help='Specify logging file (overrides config)')
    parser.add_argument('-p', dest='pidfile', metavar='FILE',
                        help='Specify pid file (overrides config)')
    args = parser.parse_args()

    try:
        os.seteuid(0)
        os.setegid(0)
    except:
        print('ERROR: must run as root', file=sys.stderr)
        sys.exit(1)

    configfile = args.config
    if not os.path.exists(configfile):
        print('ERROR: config file not found', file=sys.stderr)
        sys.exit(1)

    config.read(configfile)
    if 'General' not in config:
        print('ERROR: "General" section not found in config', file=sys.stderr)
        sys.exit(1)

    pidfile = args.pidfile or \
              config['General'].get('PIDFile', '/var/run/callblock.pid')
    logfile = args.logfile or \
              config['General'].get('Log', '/var/log/callblock.log')

    if os.path.exists(pidfile):
        print('ERROR: pidfile %s exists' % pidfile)
        sys.exit(1)

    # logging params
    format='%(asctime)s - callblock[%(process)d] - %(levelname)s:%(message)s'
    datefmt='%Y-%m-%d %H:%M:%S'
    level=logging.INFO

    if not args.forground:
        if not daemonize():
            print('ERROR: failed to daemonize', file=sys.stderr)
            sys.exit(1)
        logging.basicConfig(format=format, datefmt=datefmt,
                            level=level, filename=logfile)
    else:
        logging.basicConfig(format=format, datefmt=datefmt,
                            level=level, stream=sys.stderr)

    with open(pidfile, 'w') as fd:
        fd.write('%d\n' % os.getpid())

    # set the signal handler after forking
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.device:
        device = args.device
    else:
        device = config['General'].get('Device', None)
        if not device:
            logging.error('no device specified')
            logging.shutdown()
            sys.exit(1)

    update_blacklist(config)

    modem = Modem(device)
    if not modem.open():
        logging.error('failed to open {}'.format(device))
        logging.shutdown()
        sys.exit(1)

    logging.info('callblock started')
    call_loop(modem, blacklist)
    modem.close()
    logging.info('callblock stopped')
    logging.shutdown()
    os.unlink(pidfile)

    return


if __name__ == '__main__':
    main()
