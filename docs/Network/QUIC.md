# ![QUIC](../images/icons/quic.png) QUIC Transport

See also [network](README.md)

***

## Overview

The [xpra.org RPM repositories](https://github.com/Xpra-org/xpra/wiki/Download) include the dependencies required
for running QUIC servers and clients, namely `aioquic` and its dependencies.

## SSL Options
SSL encryption is built into the QUIC protocol, so you need to provide the same
configuration options as [SSL](SSL.md).

## Notes
* QUIC is UDP based, you need to open the UDP port of your choosing on your firewall.
* [some tuning](https://github.com/Xpra-org/xpra/issues/3376#issuecomment-1311271256) may be needed
* xpra version 5.0 or later is required
