# ![QUIC](../images/icons/quic.png) QUIC Transport

See also [network](README.md)

***

## Overview

QUIC is a new low-latency encrypted transport protocol, built on top of UDP.

## Packaging
The [xpra.org RPM repositories](https://github.com/Xpra-org/xpra/wiki/Download) include the dependencies required
for running QUIC servers and clients for most distributions, namely `aioquic` and its dependencies.

---

Some distributions (ie: [RHEL 8 / 9](https://github.com/Xpra-org/xpra/issues/4670)) may lack some of the dependencies,
in which case you may need to install them using pip:
```shell
pip3.XX install certifi pyOpenSSL cryptography
```
(be aware that these packages will not receive security updates from your package manager)

## SSL Options
SSL encryption is built into the QUIC protocol, so you need to provide the same
configuration options as [SSL](SSL.md).

## Notes
* QUIC is UDP based, you need to open the UDP port of your choosing on your firewall.
* [some tuning](https://github.com/Xpra-org/xpra/issues/3376#issuecomment-1311271256) may be needed
* xpra version 5.0 or later is required
