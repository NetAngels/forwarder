=========
Forwarder
=========

.. image:: https://travis-ci.org/NetAngels/forwarder.svg?branch=master
   :target: https://travis-ci.org/NetAngels/forwarder
   :alt: Travis-ci: continuous integration status.

A simple TCP packages forwarder built on top of python ``tornado`` framework.
It redirects TCP trafic between specified pairs of host and port.
It has a similar behaviour to a standard Linux ``redir`` utility.

``Forwarder`` config looks like:

.. code-block:: console

    127.0.0.1 8097 => 127.0.0.1 9098
    #127.0.0.1 8088 => 192.168.1.216 8080

A basic run looks like:

.. code-block:: console

    python -m forwarder /etc/forwarder.d/main.conf


You can also use  ``*`` и ``?`` as mask for ``forwarder's`` config:

.. code-block:: console

    python -m forwarder /etc/forwarder.d/*.conf


``Forwarder`` automatically reloads configuration files and reinitializes/closes changed connections.
