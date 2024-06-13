# ![Authentication](../images/icons/authentication.png) Encryption

Access to Xpra's sessions over `TCP`, `websocket` and unix domain sockets (see [network](README.md)) can be protected using [authentication modules](../Usage/Authentication.md) but those do not protect the network connection itself from man in the middle attacks.

For that, you need to use one of these three options:
* [TLS](SSL.md)
* [AES](AES.md)
* [SSH](SSH.md)


[QUIC](QUIC.md) connections must use [TLS](SSL.md).

---

See also: [Security Considerations](../Usage/Security.md)
