# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.base.stub import StubClientMixin
from xpra.net.common import Packet, SSL_UPGRADE
from xpra.util.thread import start_thread
from xpra.util.objects import typedict
from xpra.exit_codes import ExitCode
from xpra.log import Logger

log = Logger("ssl")


class SSLUpgradeClient(StubClientMixin):
    """
    Adds ability to upgrade connections to ssl
    """

    def _process_ssl_upgrade(self, packet: Packet) -> None:
        assert SSL_UPGRADE
        ssl_attrs = typedict(packet.get_dict(1))
        start_thread(self.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs,))

    def ssl_upgrade(self, ssl_attrs: typedict) -> None:
        # send ssl-upgrade request!
        log = Logger("client", "ssl")
        log(f"ssl-upgrade({ssl_attrs})")
        conn = self._protocol._conn
        socktype = conn.socktype
        new_socktype = {"tcp": "ssl", "ws": "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        log.info(f"upgrading {conn} to {new_socktype}")
        self.send("ssl-upgrade", {})
        from xpra.net.ssl.socket import ssl_handshake, ssl_wrap_socket
        from xpra.net.ssl.file import get_ssl_attributes
        overrides = {
            "verify_mode": "none",
            "check_hostname": "no",
        }
        overrides.update(conn.options.get("ssl-options", {}))
        ssl_options = get_ssl_attributes(None, False, overrides)
        kwargs = {k.replace("-", "_"): v for k, v in ssl_options.items()}
        # wait for the 'ssl-upgrade' packet to be sent...
        # this should be done by watching the IO and formatting threads instead
        import time
        time.sleep(1)

        def read_callback(packet) -> None:
            if packet:
                log.error("Error: received another packet during ssl socket upgrade:")
                log.error(" %s", packet)
                self.quit(ExitCode.INTERNAL_ERROR)

        conn = self._protocol.steal_connection(read_callback)
        if not self._protocol.wait_for_io_threads_exit(1):
            log.error("Error: failed to terminate network threads for ssl upgrade")
            self.quit(ExitCode.INTERNAL_ERROR)
            # noinspection PyUnreachableCode
            return
        ssl_sock = ssl_wrap_socket(conn._socket, **kwargs)
        ssl_handshake(ssl_sock)
        log("ssl handshake complete")
        from xpra.net.bytestreams import SSLSocketConnection
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, new_socktype)
        self._protocol = self.make_protocol(ssl_conn)
        self._protocol.start()

    def init_packet_handlers(self) -> None:
        self.add_packets("ssl-upgrade")
