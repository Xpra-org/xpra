This service is often referred to as the "system wide proxy server".

Posix packages should install this [proxy server](./Proxy-Server.md) as a system service and update the firewall rules to allow access to its IANA assigned TCP port (`14500`).

This service makes it possible to start and access sessions through a single authenticated port.


# Start via proxy
The `start-via-proxy=yes` option allows servers to start their sessions via this service so that they are registered correctly with the local seats management system (`pam` / `logind`), which should prevent early termination if their controlling shell is destroyed (ie: if the `SSH` session they are started from is terminated).


# Links
* [proxy server](./Proxy-Server.md)
* [authentication](./Authentication.md)
* [system service for the proxy server](https://github.com/Xpra-org/xpra/issues/1335) - original feature ticket
* [systemd socket activation](https://github.com/Xpra-org/xpra/issues/1521)
* [systemd multi seat support](https://github.com/Xpra-org/xpra/issues/1105)
* [`peercred` authentication module](https://github.com/Xpra-org/xpra/issues/1524)
* [IANA registration and default port](https://github.com/Xpra-org/xpra/issues/731)
