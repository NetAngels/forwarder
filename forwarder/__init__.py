# -*- coding: utf-8 -*-
import glob
import logging
import os
import socket

from tornado.ioloop import PeriodicCallback
from tornado.iostream import IOStream
from tornado.util import basestring_type
try:
    # tornado>=3.0
    from tornado.tcpserver import TCPServer
except ImportError:
    # tornado<3.0
    from tornado.netutil import TCPServer

from forwarder.utils import DictDiff


def _get_forwarding_str(addr_from, port_from, addr_to, port_to):
    """
    Returns log string for connection forwarding.
    """
    return "{addr_from}:{port_from} => {addr_to}:{port_to}".format(
        addr_from=addr_from,
        port_from=port_from,
        addr_to=addr_to,
        port_to=port_to
    )


class ForwardServer(TCPServer):
    def __init__(self, *args, **kwargs):
        super(ForwardServer, self).__init__(*args, **kwargs)
        self.conf = {}
        self._config_file = None
        self._config_files_mtime_cache = {}
        self._connections = []  # List of server active connections. Each exposed by tuple (addr, port).
        self._fds = {}  # List of sockets descriptors. Each exposed by tuple (addr, port).
        self._config_reload_callback = None

    def bind_from_config_file(self, config_file, autoreload=True):
        """
        Sets `Forwarder` instance config file and binds config from it.
        Checks for configuration file changes and applies them if `autoreload`
        parameter is True.
        """
        self._config_file = config_file
        self._handle_config_reload()
        if autoreload:
            self._config_reload_callback = PeriodicCallback(self._handle_config_reload, 500)
            self._config_reload_callback.start()

    def _handle_config_reload(self):
        """
        Reloads config files and binds parsed configuration.
        """
        config_files_mtime = {}
        config_file = self._config_file
        if os.path.isdir(self._config_file):
            config_file = os.path.join(config_file, '*')
        for path in glob.iglob(config_file):
            config_files_mtime[path] = os.path.getmtime(path)
        if config_files_mtime != self._config_files_mtime_cache:
            logging.info("Configuration reload")
            config_files = config_files_mtime.keys()
            config = {}
            for path in config_files:
                with open(path) as f:
                    config.update(self.parse_config(f))
            self.bind_conf(config)

    def parse_config(self, config_data):
        """
        Loads and parses configuration files list.
        Each configuration file follows such format:

            # Lines with leading # character are comments.
            # Each line must contain 4 values: addr and port of
            # incoming connection and addr and port of forwarded connection
            # Values must be separated by spaces, commas or arrow
            # symbols (" ", ",", "=>")
            127.0.0.1 8089 => 127.0.0.1 8080
            127.0.0.1:8090, 127.0.0.1:8080
            127.0.0.1 8091    127.0.0.1 8080
        """
        conf = {}
        if isinstance(config_data, basestring_type):
            config_data = config_data.split('\n')
        for line in config_data:
            # Skip blank lines or commented lines
            if not line or line.startswith('#'):
                continue
            # Clear format
            for i in (',', '=>', ':'):
                line = line.replace(i, ' ')
            f_addr, f_port, t_addr, t_port = line.split()
            conf[f_addr, int(f_port)] = t_addr, int(t_port)
        return conf

    def bind_conf(self, conf):
        """
        Binds new added sockets, restarts changed and closes removed
        from new configuration dictionary.
        """
        if self.conf != conf:
            diff = DictDiff(self.conf, conf)
            for addr, port in diff.removed:
                logging.info('Forwarding %s removed from config. Closing all connections on it.',
                             _get_forwarding_str(addr, port, *self.conf[(addr, port)]))
                self.close_connections((addr, port))
                self.unbind(port, addr)
            for addr, port in diff.changed:
                logging.info('Forwarding %s was changed in config. Reinitialize all connections on it',
                             _get_forwarding_str(addr, port, *conf[(addr, port)]))
                self.close_connections((addr, port))
            for addr, port in diff.added:
                logging.info('New forwarding %s was added in config. Start listening on it',
                             _get_forwarding_str(addr, port, *conf[(addr, port)]))
                self.listen(port, addr)
            self.conf = conf

    def add_sockets(self, sockets):
        super(ForwardServer, self).add_sockets(sockets)
        for sock in sockets:
            self._fds[sock.getsockname()] = sock.fileno()

    def unbind(self, port, address):
        fd = self._fds[address, port]
        socket = self._sockets[fd]
        socket.close()
        self.io_loop.remove_handler(fd)
        del self._sockets[fd]

    def open_connection(self, stream, address):
        connection = ForwardConnection(self, stream, address)
        self._connections.append(connection)
        connection.set_close_callback(self.on_connection_closed)
        logging.info("Total connections: %s", len(self._connections))

    def on_connection_closed(self, connection):
        self._connections.remove(connection)
        del connection

    def close_connections(self, address):
        for c in self._connections:
            if c.address == address:
                c.close()

    def handle_stream(self, stream, address):
        # NB: adress is a reverse TCP connection
        self.open_connection(stream, address)


class ForwardConnection(object):
    def __init__(self, server, stream, address):
        self._close_callback = None
        self.server = server
        self.stream = stream
        self.reverse_address = address
        self.address = stream.socket.getsockname()
        self.remote_address = server.conf[self.address]
        sock = socket.socket()
        self.remote_stream = IOStream(sock)
        self.remote_stream.connect(self.remote_address, self._on_remote_connected)

    def close(self):
        self.remote_stream.close()

    def set_close_callback(self, callback):
        self._close_callback = callback

    def _on_remote_connected(self):
        ip_from = self.reverse_address[0]
        fwd_str = _get_forwarding_str(self.address[0], self.address[1],
                                      self.remote_address[0], self.remote_address[1])
        logging.info('Connected ip: %s, forward %s', ip_from, fwd_str)
        self.remote_stream.read_until_close(self._on_remote_read_close, self.stream.write)
        self.stream.read_until_close(self._on_read_close, self.remote_stream.write)

    def _on_remote_read_close(self, data):
        if self.stream.writing():
            self.stream.write(data, self.stream.close)
        else:
            if self.stream.closed():
                self._on_closed()
            else:
                self.stream.close()

    def _on_read_close(self, data):
        if self.remote_stream.writing():
            self.remote_stream.write(data, self.remote_stream.close)
        else:
            if self.remote_stream.closed():
                self._on_closed()
            else:
                self.remote_stream.close()

    def _on_closed(self):
        logging.info('Disconnected ip: %s', self.reverse_address[0])
        if self._close_callback:
            self._close_callback(self)
