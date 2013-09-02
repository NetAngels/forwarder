# -*- coding: utf-8 -*-
import glob
import logging
import os
import socket

from tornado.iostream import IOStream
try:
    # tornado>=3.0
    from tornado.tcpserver import TCPServer
except ImportError:
    # tornado<3.0
    from tornado.netutil import TCPServer

from forwarder.utils import DictDiff


class ForwardServer(TCPServer):
    def __init__(self, confpath, *args, **kwargs):
        super(ForwardServer, self).__init__(*args, **kwargs)
        self.conf = {}
        self._confpath = confpath
        self._confpaths = {}
        # Словарь активных подключений. В роли ключа - пара (addr, port), которые слушает сервер.
        self._connections = []
        # Словарь дескрипторов, открытых для прослушивания сокетов.
        # В роли ключа - пара (addr, port), которые слушает сервер.
        self._fds = {}

    def parse_conf(self):
        """
        Загружает и парсит конфиг из файла. Конфиг имеет следующий вид:

            # Строчки решеткой вначале - игнорируются, как комментарии.
            # В каждой строчке должно быть 4 значения: адрес и порт, которые
            # необходимо слушать и адрес и порт, на которые необходимо
            # перенаправлять TCP пакеты.
            # Значения могут разделяться символами: " ", ",", "=>" для наглядности:
            127.0.0.1 8089 => 127.0.0.1 8080
            127.0.0.1:8090, 127.0.0.1:8080
            127.0.0.1 8091    127.0.0.1 8080
        """
        conf = {}
        for path in self._confpaths:
            with open(path) as f:
                for line in f:
                    # Skip comment lines
                    if line.startswith('#'):
                        continue
                    # Clear format
                    for i in (',', '=>', ':'):
                        line = line.replace(i, '')
                    f_addr, f_port, t_addr, t_port = line.split()
                    conf[f_addr, int(f_port)] = t_addr, int(t_port)
        return conf

    def bind_from_conf(self):
        new_confpahts = {}
        for path in glob.glob(self._confpath):
            new_confpahts[path] = os.path.getmtime(path)
        if new_confpahts != self._confpaths:
            self._confpaths = new_confpahts
            new_conf = self.parse_conf()
            if self.conf != new_conf:
                diff = DictDiff(self.conf, new_conf)
                for addr, port in diff.removed:
                    self.close_connections((addr, port))
                    self.unbind(port, addr)
                for addr, port in diff.changed:
                    self.close_connections((addr, port))
                for addr, port in diff.added:
                    self.listen(port, addr)
                self.conf = new_conf

    def log_state(self):
        logging.info("Connections: %s", len(self._connections))

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
        #connection.set_close_callback(self.on_connection_closed)
        self._connections.append(connection)

    def on_connection_closed(self, connection):
        self._connections.remove(connection)
        del connection

    def close_connections(self, address):
        for c in self._connections:
            if c.address == address:
                c.close()

    def handle_stream(self, stream, address):
        # NB: adress - это обратный адрес TCP подключения
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
        logging.info('forward %r to %r', self.address, self.remote_address)
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
        if self._close_callback:
            self._close_callback(self)
        logging.info('Connection closed')
