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


def get_ssl_upgrade_target(conn) -> tuple[str, int]:
    ssl_options = conn.options.get("ssl-options", {})
    server_hostname = ssl_options.get("server-hostname") or conn.options.get("host", "")
    port = conn.options.get("port", 0)
    if not server_hostname or not port:
        raise ValueError("cannot identify the SSL upgrade server")
    return server_hostname, port


def confirm_ssl_upgrade_pin(server_hostname: str, port: int, server_cert_data: bytes, previous_pin_data: bytes = b"") -> bytes:
    """Ask whether an unverified upgrade certificate should become the host pin."""
    from xpra.net.tls.common import CERT_FILENAME
    from xpra.net.tls.file import save_ssl_config_file
    from xpra.net.tls.socket import SSL_RETRY, get_cert_fingerprint

    if not SSL_RETRY:
        raise ValueError("certificate confirmation is disabled")
    fingerprint = get_cert_fingerprint(server_cert_data.decode("ascii"))
    target = f"{server_hostname}:{port}"
    if previous_pin_data:
        previous_fingerprint = get_cert_fingerprint(previous_pin_data.decode("ascii"))
        title = "SSL Upgrade Certificate Changed"
        lines = (
            f"The unverified certificate offered by {target} does not match the certificate accepted previously.",
            "The server may have been re-configured, or the connection may have been intercepted.",
            f"Previous SHA256 fingerprint: {previous_fingerprint or 'unknown'}",
            f"New SHA256 fingerprint: {fingerprint or 'unknown'}",
        )
        prompt = "Do you want to replace the certificate accepted previously?"
    else:
        title = "Unverified SSL Upgrade Certificate"
        lines = (
            f"The certificate offered by {target} was received over an unencrypted connection.",
            "Accept it only if you recognize this server and have verified the fingerprint.",
            f"SHA256 fingerprint: {fingerprint or 'unknown'}",
        )
        prompt = "Do you want to accept and save this certificate?"
    from xpra.scripts import pinentry
    if not pinentry.confirm(lines, title, prompt):
        raise ValueError(f"certificate for {target} was rejected")
    filename = save_ssl_config_file(server_hostname, port, CERT_FILENAME, "certificate", server_cert_data)
    if not filename:
        raise ValueError(f"failed to save the certificate for {target}")
    return server_cert_data


def get_ssl_upgrade_pin(conn, server_cert_data: bytes, confirm: bool = False) -> bytes:
    """Return the matching host pin, optionally confirming a new or changed pin."""
    from hmac import compare_digest
    from xpra.net.tls.file import certificate_digest, find_ssl_config_file, validate_certificates
    from xpra.util.io import load_binary_file

    server_hostname, port = get_ssl_upgrade_target(conn)
    cert_file = find_ssl_config_file(server_hostname, port)
    if not cert_file:
        if confirm:
            return confirm_ssl_upgrade_pin(server_hostname, port, server_cert_data)
        raise ValueError(f"no certificate has been accepted for {server_hostname}:{port}")
    pin_data = load_binary_file(cert_file)
    try:
        pin_data = validate_certificates(pin_data, MAX_CERT_DATA_SIZE, MAX_CERTIFICATES)
    except ValueError as e:
        raise ValueError(f"invalid certificate pin for {server_hostname}:{port}: {e}") from e
    if not compare_digest(certificate_digest(server_cert_data), certificate_digest(pin_data)):
        if confirm:
            return confirm_ssl_upgrade_pin(server_hostname, port, server_cert_data, pin_data)
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
    __slots__ = ("server_cert_data", "server_pin_data", "upgrade_pending")
    PREFIX = "ssl-upgrade"

    def __init__(self, client=None) -> None:
        super().__init__(client)
        self.server_cert_data = b""
        self.server_pin_data = b""
        self.upgrade_pending = False

    def get_caps(self) -> dict[str, bool]:
        return {"ssl-upgrade": True}

    def parse_server_capabilities(self, c: typedict) -> bool:  # pylint: disable=unused-argument
        self.remove_packet_handlers(SSL_UPGRADE)
        return True

    @packet_handler(SSL_UPGRADE, early=True)
    def _process_ssl_upgrade(self, packet: Packet) -> None:
        if self.upgrade_pending:
            self.client.warn_and_quit(ExitCode.SSL_FAILURE, "received more than one SSL upgrade offer")
            return
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
        self.upgrade_pending = True
        self.client.cancel_verify_connected_timer()
        ssl_attrs["cert-data"] = self.server_cert_data
        # The packet handler runs on the network parse thread, whose seccomp
        # filter would be inherited by a child thread and forbid pinentry and
        # saving an accepted certificate. Start the worker via the main thread.
        self.idle_add(self.start_ssl_upgrade, ssl_attrs)

    def start_ssl_upgrade(self, ssl_attrs: typedict) -> bool:
        start_thread(self.ssl_upgrade, "ssl-upgrade", True, args=(ssl_attrs,))
        return False

    def ssl_upgrade(self, ssl_attrs: typedict) -> None:
        protocol = self.client._protocol
        conn = protocol._conn
        try:
            self.server_pin_data = get_ssl_upgrade_pin(conn, self.server_cert_data, confirm=True)
        except ValueError as e:
            self.client.warn_and_quit(ExitCode.SSL_FAILURE, f"untrusted SSL upgrade certificate: {e}")
            return
        if self.client._protocol is not protocol:
            log("SSL upgrade connection was closed while waiting for certificate confirmation")
            return
        # Do not acknowledge the upgrade until the advertised certificate has
        # matched an existing pin or the user has explicitly accepted it.
        log("ssl-upgrade(%i certificate bytes)", len(self.server_cert_data))
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

        conn = protocol.steal_connection(read_callback)
        if not protocol.wait_for_io_threads_exit(1):
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
