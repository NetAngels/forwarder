#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys

from tornado.ioloop import IOLoop, PeriodicCallback

from forwarder import ForwardServer


logging.basicConfig(level=logging.INFO, format='%(levelname)s - - %(asctime)s %(message)s', datefmt='[%d/%b/%Y %H:%M:%S]')


def main():
    server = ForwardServer(sys.argv[1])
    server.bind_from_conf()
    PeriodicCallback(server.bind_from_conf, 500).start()
    IOLoop.instance().start()


if __name__ == '__main__':
    main()