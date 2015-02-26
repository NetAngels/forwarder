forwarder
=========

A simple TCP packages forwarder. It redirects TCP trafic between specified pairs of host and port.
It has a similar behaviour to a standard Linux `redir` utility.

`Forwarder` config looks like:

```
127.0.0.1 8097 => 127.0.0.1 9098
#127.0.0.1 8088 => 192.168.1.216 8080
```

A basic run looks like:
```
python -m forwarder /etc/forwarder.d/main.conf
```

You can also use  `*` и `?` as mask for `forwarder's` config:

```
python -m forwarder /etc/forwarder.d/*.conf
```

`Forwarder` automatically reloads configuration files and reinitializes/closes changed connections.
