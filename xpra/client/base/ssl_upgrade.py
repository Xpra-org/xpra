# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.base.stub import StubClientSubsystem
from xpra.net.common import Packet, packet_handler
from xpra.util.thread import start_thread
from xpra.util.objects import typedict
from xpra.exit_codes import ExitCode
from xpra.config import InitExit
from xpra.net.packet_type import SSL_UPGRADE
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("ssl")
MAX_CERT_DATA_SIZE = max(4096, envint("XPRA_SSL_UPGRADE_MAX_CERT_DATA_SIZE", 256 * 1024))
MAX_CERTIFICATES = max(1, envint("XPRA_SSL_UPGRADE_MAX_CERTIFICATES", 16))


def get_ssl_upgrade_pin(conn, server_cert_data: bytes) -> bytes:
    """Return the existing host pin when it matches the advertised certificate."""
    from hmac import compare_digest
    from xpra.net.tls.file import certificate_digest, find_ssl_config_file, validate_certificates
    from xpra.util.io import load_binary_file

    ssl_options = conn.options.get("ssl-options", {})
    server_hostname = ssl_options.get("server-hostname") or conn.options.get("host", "")
    port = conn.options.get("port", 0)
    if not server_hostname or not port:
        raise ValueError("cannot identify the SSL upgrade server")
    cert_file = find_ssl_config_file(server_hostname, port)
    if not cert_file:
        raise ValueError(f"no certificate has been accepted for {server_hostname}:{port}")
    pin_data = load_binary_file(cert_file)
    try:
        pin_data = validate_certificates(pin_data, MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
    except ValueError as e:
        raise ValueError(f"invalid certificate pin for {server_hostname}:{port}: {e}") from e
    if not compare_digest(certificate_digest(server_cert_data), certificate_digest(pin_data)):
        raise ValueError(f"certificate does not match the pin for {server_hostname}:{port}")
    return pin_data


def get_ssl_upgrade_options(options: dict, pin_data: bytes) -> dict:
    from base64 import b64encode
    from xpra.net.tls.file import certificate_der, get_ssl_attributes
    from xpra.net.tls.common import SSL_UPGRADE_DEFAULTS

    overrides = dict(SSL_UPGRADE_DEFAULTS)
    overrides.update(options.get("ssl-options", {}))
    # The selected host pin cannot be weakened by the opportunistic-upgrade
    # defaults or connection options.
    overrides.update({
        "server-verify-mode": "required",
        "ca-certs": "",
        "ca-data": "base64:" + b64encode(certificate_der(pin_data)).decode("ascii"),
    })
    return {k.replace("-", "_"): v for k, v in get_ssl_attributes(None, False, overrides).items() if v is not None}


def verify_ssl_upgrade_socket(ssl_sock, pin_data: bytes) -> None:
    from hmac import compare_digest
    from xpra.net.tls.file import certificate_der

    peer_certificate = ssl_sock.getpeercert(binary_form=True)
    if not peer_certificate or not compare_digest(peer_certificate, certificate_der(pin_data)):
        raise InitExit(ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE, "SSL upgrade server certificate does not match the accepted pin")


class SSLUpgrade(StubClientSubsystem):
    """
    Adds ability to upgrade connections to ssl
    """
    __slots__ = ("server_cert_data", "server_pin_data")
    PREFIX = "ssl-upgrade"

    def __init__(self, client=None) -> None:
        super().__init__(client)
        self.server_cert_data = b""
        self.server_pin_data = b""

    def get_caps(self) -> dict[str, bool]:
        return {"ssl-upgrade": True}

    def parse_server_capabilities(self, c: typedict) -> bool:  # pylint: disable=unused-argument
        self.remove_packet_handlers(SSL_UPGRADE)
        return True

    @packet_handler(SSL_UPGRADE, early=True)
    def _process_ssl_upgrade(self, packet: Packet) -> None:
        ssl_attrs = typedict(packet.get_dict(1))
        cert_data = ssl_attrs.get("cert-data")
        if not isinstance(cert_data, bytes):
            self.client.warn_and_quit(ExitCode.SSL_FAILURE, "invalid SSL upgrade certificate data: expected bytes")
            return
        from xpra.net.tls.file import validate_certificates
        try:
            self.server_cert_data = validate_certificates(cert_data, MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
        except ValueError as e:
            self.client.warn_and_quit(ExitCode.SSL_FAILURE, f"invalid SSL upgrade certificate data: {e}")
            return
        try:
            self.server_pin_data = get_ssl_upgrade_pin(self.client._protocol._conn, self.server_cert_data)
        except ValueError as e:
            self.client.warn_and_quit(ExitCode.SSL_FAILURE, f"untrusted SSL upgrade certificate: {e}")
            return
        ssl_attrs["cert-data"] = self.server_cert_data
        start_thread(self.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs,))

    def ssl_upgrade(self, ssl_attrs: typedict) -> None:
        # send ssl-upgrade request!
        log("ssl-upgrade(%i certificate bytes)", len(self.server_cert_data))
        conn = self.client._protocol._conn
        socktype = conn.socktype
        new_socktype = {"tcp": "ssl", "ws": "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        log.info(f"upgrading {conn} to {new_socktype}")
        self.send(SSL_UPGRADE, {})
        from xpra.net.tls.socket import ssl_handshake, ssl_wrap_socket
        kwargs = get_ssl_upgrade_options(conn.options, self.server_pin_data)
        # wait for the 'ssl-upgrade' packet to be sent...
        # this should be done by watching the IO and formatting threads instead
        import time
        time.sleep(1)

        def read_callback(packet) -> None:
            if packet:
                log.error("Error: received another packet during ssl socket upgrade:")
                log.error(" %s", packet)
                self.quit(ExitCode.INTERNAL_ERROR)

        conn = self.client._protocol.steal_connection(read_callback)
        if not self.client._protocol.wait_for_io_threads_exit(1):
            log.error("Error: failed to terminate network threads for ssl upgrade")
            self.quit(ExitCode.INTERNAL_ERROR)
            # noinspection PyUnreachableCode
            return
        ssl_sock = None
        try:
            ssl_sock = ssl_wrap_socket(conn._socket, **kwargs)
            if not ssl_sock:
                # `None` means the server closed the connection during the TLS setup:
                raise InitExit(ExitCode.SSL_FAILURE, "the connection was closed")
            ssl_handshake(ssl_sock)
            verify_ssl_upgrade_socket(ssl_sock, self.server_pin_data)
        except Exception as e:
            log("ssl_upgrade(%s)", ssl_attrs, exc_info=True)
            log.error("Error: ssl upgrade failed")
            log.estr(e)
            # once wrapped, the ssl socket owns the file descriptor:
            (ssl_sock or conn).close()
            self.quit(e.status if isinstance(e, InitExit) else ExitCode.SSL_FAILURE)
            return
        log("ssl handshake complete")
        from xpra.net.tls.connection import SSLSocketConnection
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, new_socktype)
        # `make_protocol` sets `self.client._protocol` itself:
        protocol = self.client.make_protocol(ssl_conn)
        protocol.start()
