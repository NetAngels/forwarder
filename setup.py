# -*- coding: utf-8 -*-
from distutils.core import setup

setup(
    name='forwarder',
    version='0.1',
    description='TCP packages forwarder',
    author='NetAngels team',
    author_email='info@netangels.ru',
    url='https://panel.netangels.ru',
    packages=['forwarder'],
    install_requires=['tornado']
)
