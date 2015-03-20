# -*- coding: utf-8 -*-
import mock
import os
import socket
import tempfile
import threading

from tornado.ioloop import IOLoop
from tornado.tcpserver import TCPServer
from tornado.testing import AsyncTestCase, bind_unused_port, gen_test, unittest

from forwarder import ForwardServer, _get_forwarding_str
from forwarder.utils import DictDiff


class TCPEchoServer(TCPServer):
    def handle_stream(self, stream, address):
        stream.read_until_close(lambda _: stream.close(), stream.write)


class DictDiffTest(unittest.TestCase):
    def setUp(self):
        self.d1 = {
            'a': 1,
            'b': 2,
            'c': 3,
            'd': 4,
        }
        self.d2 = {
            # removed 'a'
            # changed valued of 'b'
            'b': 10,
            'c': 3,
            'd': 4,
            # added 'e'
            'e': 5,
        }
        self.diff = DictDiff(self.d1, self.d2)

    def test_added(self):
        self.assertEqual(self.diff.added, set(['e']))

    def test_removed(self):
        self.assertEqual(self.diff.removed, set(['a']))

    def test_changed(self):
        self.assertEqual(self.diff.changed, set(['b']))

    def test_unchanged(self):
        self.assertEqual(self.diff.unchanged, set(['c', 'd']))


class ForwarderConfigTest(unittest.TestCase):
    def setUp(self):
        self.forwarder_server = ForwardServer()

    def test_get_forwarding_str(self):
        s = _get_forwarding_str('1.2.3.4', 21, '5.6.7.8', 22)
        self.assertEqual("1.2.3.4:21 => 5.6.7.8:22", s)

    def test_parse_config_files(self):
        self.config_file = tempfile.mkstemp()[1]
        with open(self.config_file, 'w') as f:
            f.write('127.0.0.1:5000 => 127.0.0.1:5001')
            f.write('127.0.0.1:5002, 127.0.0.1:5003')
            f.write('#127.0.0.1:5004 => 127.0.0.1:5005')
            f.write('127.0.0.1:5006    127.0.0.1:5007')

        #
        pass

    def test_parse_config_string(self):
        data = '''
127.0.0.1:5000 => 127.0.0.1:5001
127.0.0.1:5002, 127.0.0.1:5003

#127.0.0.1:5004 => 127.0.0.1:5005
127.0.0.1:5006    127.0.0.1:5007
'''
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
            ('127.0.0.1', 5006): ('127.0.0.1', 5007),
        }
        parsedconf = self.forwarder_server.parse_config(data)
        self.assertEqual(parsedconf, conf)

    def test_bind_conf(self):
        with mock.patch.multiple(self.forwarder_server, close_connections=mock.DEFAULT,
                                 listen=mock.DEFAULT, unbind=mock.DEFAULT) as values:
            close_connections = values['close_connections']
            listen = values['listen']
            unbind = values['unbind']

            first_conf = {
                ('127.0.0.1', 5000): ('127.0.0.1', 5001),
                ('127.0.0.1', 5002): ('127.0.0.1', 5003),
            }
            self.forwarder_server.bind_conf(first_conf)
            self.assertEqual(self.forwarder_server.conf, first_conf)
            self.assertEqual(close_connections.call_count, 0)
            self.assertEqual(listen.call_count, 2)
            self.assertIn(mock.call(5000, '127.0.0.1'), listen.call_args_list)
            self.assertIn(mock.call(5002, '127.0.0.1'), listen.call_args_list)
            self.assertEqual(unbind.call_count, 0)

            close_connections.reset_mock()
            listen.reset_mock()
            unbind.reset_mock()
            second_conf = {
                # ('127.0.0.1', 5000): ('127.0.0.1', 5001), This one is removed from conf
                ('127.0.0.1', 5002): ('127.0.0.1', 5005),  # This one is changed
                ('127.0.0.1', 5006): ('127.0.0.1', 5007),  # This one is new added
            }
            self.forwarder_server.bind_conf(second_conf)
            self.assertEqual(self.forwarder_server.conf, second_conf)
            self.assertEqual(close_connections.call_count, 2)
            self.assertIn(mock.call(('127.0.0.1', 5000)), close_connections.call_args_list)
            self.assertIn(mock.call(('127.0.0.1', 5002)), close_connections.call_args_list)
            self.assertEqual(listen.call_count, 1)
            self.assertEqual(mock.call(5006, '127.0.0.1'), listen.call_args)
            self.assertEqual(unbind.call_count, 1)
            self.assertEqual(mock.call(5000, '127.0.0.1'), unbind.call_args)


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
        sock.close()
        self.echo_server.listen(self.echo_port)
        self.echo_thread = threading.Thread(target=self.echo_ioloop.start)
        self.echo_thread.start()

        # Set up forwarder
        sock, self.forwarder_port = bind_unused_port()
        sock.close()
        self.config_file = tempfile.mkstemp()[1]
        with open(self.config_file, 'w') as f:
            f.write('127.0.0.1:{0} => 127.0.0.1:{1}'.format(self.forwarder_port, self.echo_port))
        self.forwarder_ioloop = IOLoop()
        self.forwarder_server = ForwardServer(io_loop=self.forwarder_ioloop)
        self.forwarder_server.bind_from_config_file(self.config_file)

        self.forwarder_thread = threading.Thread(target=self.forwarder_ioloop.start)
        self.forwarder_thread.start()

    def tearDown(self):
        def stop_forwarder():
            self.forwarder_server.stop()
            self.forwarder_ioloop.stop()
        self.forwarder_ioloop.add_callback(stop_forwarder)
        self.forwarder_thread.join()
        self.forwarder_ioloop.close(all_fds=True)
        os.remove(self.config_file)

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
        sock.sendall(b'Hello world!')
        data = sock.recv(1024)
        self.assertEqual(data, b'Hello world!')
