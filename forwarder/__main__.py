#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging

from tornado.options import options

from forwarder import ForwardServer


logging.basicConfig(level=logging.INFO, format='%(levelname)s - - %(asctime)s %(message)s', datefmt='[%d/%b/%Y %H:%M:%S]')


def main():
    options.define('certfile', help="Path to SSL certificate to enable TSL")
    options.define('keyfile', help="Path to SSL key to enable TSL")
    unparsed = options.parse_command_line()
    if len(unparsed) == 1:
        config_file = options.parse_command_line()[0]
    else:
        raise ValueError("Configuration file is not specified")
    if options.certfile and options.keyfile:
        ssl_options = {
            "certfile": options.certfile,
            "keyfile": options.keyfile,
        }
    else:
        ssl_options = None
    server = ForwardServer(ssl_options=ssl_options)
    server.bind_from_config_file(config_file)


if __name__ == '__main__':
    main()