# -*- coding: utf-8 -*-
import os
import socket
import tempfile
import threading
from tornado.tcpserver import TCPServer
from forwarder import ForwardServer
from tornado.ioloop import IOLoop
from tornado.testing import AsyncTestCase, bind_unused_port, gen_test


class TCPEchoServer(TCPServer):
    def handle_stream(self, stream, address):
        stream.read_until_close(lambda _: stream.close(), stream.write)


class ForwarderIntegrationTest(AsyncTestCase):
    """
    We set up a simple TCP echo server, and test that data
    successfully goes through Forwarder server.
    """
    def setUp(self):
        super(ForwarderIntegrationTest, self).setUp()

        # Set up echo TCP server
        self.echo_ioloop = IOLoop()
        self.echo_server = TCPEchoServer(io_loop=self.echo_ioloop)
        sock, self.echo_port = bind_unused_port()
        self.echo_server.listen(self.echo_port)
        self.echo_thread = threading.Thread(target=self.echo_ioloop.start)
        self.echo_thread.start()

        # Set up forwarder
        sock, self.forwarder_port = bind_unused_port()
        sock.close()
        self.confpath = tempfile.mkstemp()[1]
        with open(self.confpath, 'w') as f:
            f.write('127.0.0.1:{0} => 127.0.0.1:{1}'.format(self.forwarder_port, self.echo_port))
        self.forwarder_ioloop = IOLoop()
        self.forwarder_server = ForwardServer(confpath=self.confpath, io_loop=self.forwarder_ioloop)
        self.forwarder_server.bind_from_conf()

        self.forwarder_thread = threading.Thread(target=self.forwarder_ioloop.start)
        self.forwarder_thread.start()

    def tearDown(self):
        def stop_forwarder():
            self.forwarder_server.stop()
            self.forwarder_ioloop.stop()
        self.forwarder_ioloop.add_callback(stop_forwarder)
        self.forwarder_thread.join()
        self.forwarder_ioloop.close(all_fds=True)
        os.remove(self.confpath)

        def stop_echo_server():
            self.echo_server.stop()
            self.echo_ioloop.stop()
        self.echo_ioloop.add_callback(stop_echo_server)
        self.echo_thread.join()
        self.echo_ioloop.close(all_fds=True)

        super(ForwarderIntegrationTest, self).tearDown()

    def test_ping(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('localhost', self.forwarder_port))
        sock.sendall('Hello world!')
        data = sock.recv(1024)
        self.assertEqual(data, 'Hello world!')
