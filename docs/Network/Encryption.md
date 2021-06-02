# ![Authentication](../images/icons/authentication.png) Encryption

Access to Xpra's sessions over `TCP` and unix domain sockets (see [network](./README.md)) can be protected using [authentication modules](../Usage/Authentication.md) but those do not protect the network connection itself from man in the middle attacks.

For that, you need to use one of these three options:
* [SSL](./SSL.md)
* [AES](./AES.md)
* [SSH](./SSH.md)
