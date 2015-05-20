# -*- coding: utf-8 -*-
import functools
import mock
import os
import tempfile

from contextlib import closing
from textwrap import dedent
from tornado.tcpclient import TCPClient
from tornado.tcpserver import TCPServer
from tornado.testing import AsyncTestCase, bind_unused_port, unittest, gen_test

from forwarder import ForwardServer, get_forwarding_str, ParseError
from forwarder.utils import DictDiff

TEST_FILE_SUFFIX = '_fwdtest'


def make_config_file(config, config_file=None):
    """
    Creates a configuration file with specified data. ``config`` must be a dict object
    describing list of connections {('host_from', port_from): ('host_to', port_to),} or
    a string with raw forwarder configuration data.
    If optional ``config_file`` parameter is not set a new temproary file will be generated.
    Returns ``config_file`` - system path of written configuration file.
    """
    if not config_file:
        config_file = tempfile.mkstemp(TEST_FILE_SUFFIX)[1]
    with open(config_file, 'w') as f:
        if isinstance(config, dict):
            for k in config:
                v = config[k]
                f.write('{0}\n'.format(get_forwarding_str(k[0], k[1], v[0], v[1])))
        else:
            f.write(config)
    return config_file


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
        s = get_forwarding_str('1.2.3.4', 21, '5.6.7.8', 22)
        self.assertEqual("1.2.3.4:21 => 5.6.7.8:22", s)

    def test_parse_config_files(self):
        config = dedent('''
            127.0.0.1:5000 => 127.0.0.1:5001
            127.0.0.1:5002, 127.0.0.1:5003
            #127.0.0.1:5004 => 127.0.0.1:5005
            127.0.0.1:5006    127.0.0.1:5007
        ''')
        config_file = make_config_file(config)
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
            ('127.0.0.1', 5006): ('127.0.0.1', 5007),
        }
        parsedconf = self.forwarder_server.parse_config(filename=config_file)
        self.assertEqual(parsedconf, conf)

    def test_parse_config_string(self):
        data = dedent('''
            127.0.0.1:5000 => 127.0.0.1:5001
            127.0.0.1:5002, 127.0.0.1:5003

            #127.0.0.1:5004 => 127.0.0.1:5005
            127.0.0.1:5006    127.0.0.1:5007
        ''')
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
            ('127.0.0.1', 5006): ('127.0.0.1', 5007),
        }
        parsedconf = self.forwarder_server.parse_config(data=data)
        self.assertEqual(parsedconf, conf)

    def test_parse_config_fails(self):
        data = dedent('''
            127.0.0.1:5000 => 127.0.0.1:5001
            bad config
            127.0.0.1:5002 => 127.0.0.1:5001
        ''')
        self.assertRaises(ParseError, self.forwarder_server.parse_config, data=data)

    @mock.patch('forwarder.ForwardServer.bind_conf')
    def test_handle_config_reload(self, bind_conf):
        d = tempfile.mkdtemp(TEST_FILE_SUFFIX)
        make_config_file({('127.0.0.1', 5000): ('127.0.0.1', 5001)}, os.path.join(d, '0.conf'))
        make_config_file({('127.0.0.1', 5002): ('127.0.0.1', 5003)}, os.path.join(d, '1.conf'))
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
        }

        self.forwarder_server._config_file = os.path.join(d, '*')
        self.forwarder_server._handle_config_reload()
        self.assertEqual(bind_conf.call_count, 1)
        self.assertEqual(bind_conf.call_args, mock.call(conf))

        self.forwarder_server._handle_config_reload()
        self.assertEqual(bind_conf.call_count, 1)

        make_config_file({('127.0.0.1', 5004): ('127.0.0.1', 5005)}, os.path.join(d, '2.conf'))
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
            ('127.0.0.1', 5004): ('127.0.0.1', 5005),
        }

        self.forwarder_server._handle_config_reload()
        self.assertEqual(bind_conf.call_count, 2)
        self.assertEqual(bind_conf.call_args, mock.call(conf))

    @mock.patch('forwarder.ForwardServer.bind_conf')
    def test_handle_config_reload_dir(self, bind_conf):
        d = tempfile.mkdtemp(TEST_FILE_SUFFIX)
        make_config_file({('127.0.0.1', 5000): ('127.0.0.1', 5001)}, os.path.join(d, '0.conf'))
        make_config_file({('127.0.0.1', 5002): ('127.0.0.1', 5003)}, os.path.join(d, '1.conf'))
        conf = {
            ('127.0.0.1', 5000): ('127.0.0.1', 5001),
            ('127.0.0.1', 5002): ('127.0.0.1', 5003),
        }

        self.forwarder_server._config_file = d
        self.forwarder_server._handle_config_reload()
        self.assertEqual(bind_conf.call_count, 1)
        self.assertEqual(bind_conf.call_args, mock.call(conf))

    @mock.patch('forwarder.ForwardServer.unbind')
    @mock.patch('forwarder.ForwardServer.listen')
    @mock.patch('forwarder.ForwardServer.close_connections')
    def test_bind_conf(self, close_connections, listen, unbind):
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


class TestEchoServer(TCPServer):
    def __init__(self, *args, **kwargs):
        super(TestEchoServer, self).__init__(*args, **kwargs)
        self.port = None
        self.address = ""
        self.recived_data = b""

    def listen(self, port, address=""):
        super(TestEchoServer, self).listen(port, address)
        self.port = port
        self.address = address

    def handle_stream(self, stream, address):
        callback = lambda _: stream.close()
        streaming_callback = functools.partial(self.handle_data, stream)
        stream.read_until_close(callback, streaming_callback)

    def handle_data(self, stream, data):
        self.recived_data += data
        stream.write(data)


class ForwarderIntegrationTest(AsyncTestCase):
    """
    We set up a simple TCP echo server, and test that data
    successfully goes through Forwarder server.
    """
    def setUp(self):
        super(ForwarderIntegrationTest, self).setUp()

        self.client = TCPClient()
        self.echo_server = self.start_echo_server()
        self.additional_servers = []  # additional test servers

        # Set up forwarder
        self.forwarder_port = self.get_unused_port()
        self.config = {
            ('127.0.0.1', self.forwarder_port): ('127.0.0.1', self.echo_server.port)
        }
        self.config_file = make_config_file(self.config)
        self.forwarder_server = ForwardServer()
        self.forwarder_server.bind_from_config_file(self.config_file)

    def tearDown(self):
        self.forwarder_server.stop()
        self.echo_server.stop()
        for server in self.additional_servers:
            server.stop()
        os.remove(self.config_file)
        super(ForwarderIntegrationTest, self).tearDown()

    def start_echo_server(self):
        server = TestEchoServer()
        port = self.get_unused_port()
        server.listen(port)
        return server

    def get_unused_port(self):
        sock, port = bind_unused_port()
        sock.close()
        return port

    @gen_test
    def test_connect_and_response(self):
        stream = yield self.client.connect('localhost', self.forwarder_port)
        with closing(stream):
            stream.write(b'Hello')
            data = yield stream.read_bytes(5)
            self.assertEqual(data, b'Hello')
            self.assertEqual(self.echo_server.recived_data, b'Hello')

    def test_periodic_config_reload_calback(self):
        with mock.patch.object(self.forwarder_server._config_reload_callback, 'callback') as callback:
            self.io_loop.call_later(1, self.stop)
            self.wait()
            self.assertTrue(callback.called)