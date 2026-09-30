# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from base64 import b64decode
from binascii import Error as Base64Error
from collections.abc import Callable, Sequence

from xpra.util.env import envbool
from xpra.util.str_fn import is_valid_hostname, strtobytes, std
from xpra.net.common import HttpResponse
from xpra.net.websockets.common import make_websocket_accept_hash
from xpra.net.http.common import check_origin
from xpra.net.http.handler import HTTPRequestHandler, AUTH_USERNAME, AUTH_PASSWORD
from xpra.log import Logger

log = Logger("network", "websocket")

WEBSOCKET_ONLY_UPGRADE = envbool("XPRA_WEBSOCKET_ONLY_UPGRADE", False)
HTTPS_REDIRECT_PERMANENT = envbool("XPRA_HTTPS_REDIRECT_PERMANENT", True)

# HyBi-07 report version 7
# HyBi-08 - HyBi-12 report version 8
# HyBi-13 reports version 13
SUPPORT_HyBi_PROTOCOLS: Sequence[str] = ("7", "8", "13")


class UpgradeError(ValueError):
    """ a websocket upgrade failure, with the http error code and headers to reply with """

    def __init__(self, message: str, code: int = 400, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.headers = headers or {}


class WebSocketRequestHandler(HTTPRequestHandler):
    server_version = "Xpra-WebSocket-Server"

    def __init__(self, sock, addr, new_websocket_client: Callable,
                 web_root: str = "/usr/share/xpra/www/",
                 http_headers_dirs: Sequence[str] = ("/etc/xpra/http-headers",),
                 script_paths: dict[str, Callable[[str], HttpResponse]] | None = None,
                 redirect_https: bool = False,
                 origin: str = "auto",
                 username: str = AUTH_USERNAME,
                 password: str = AUTH_PASSWORD,
                 ):
        self.new_websocket_client: Callable = new_websocket_client
        self.only_upgrade = WEBSOCKET_ONLY_UPGRADE
        self.redirect_https = redirect_https
        self.origin = origin
        self.finish = self.finish_and_close
        super().__init__(sock, addr,
                         web_root, http_headers_dirs, script_paths,
                         username, password)

    def check_websocket_origin(self) -> None:
        """
        Prevent websites from hijacking the websocket connections of the browsers visiting them.
        The `Origin` header identifies the site the connection originates from,
        it is only sent by browsers - so requests without one are left alone.
        """
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if check_origin(origin, host, self.origin):
            return
        log.warn("Warning: rejected websocket connection")
        log.warn(" from origin %r", std(origin))
        log.warn(" the 'http-origin' option is set to %r", std(self.origin))
        log.warn(" add this origin to the 'http-origin' option to allow it")
        # don't echo the origin back to the client:
        raise UpgradeError("websocket connection from an unauthorized origin", 403)

    def handle_websocket(self) -> None:
        log("handle_websocket() calling %s, request=%s (%s)",
            self.new_websocket_client, self.request, type(self.request))
        log("headers:")
        for k, v in self.headers.items():
            log(f" {k}={v}")
        self.check_websocket_origin()
        # ie: Firefox sends "keep-alive, Upgrade"
        connection = [token.strip().lower() for token in self.headers.get("Connection", "").split(",")]
        if "upgrade" not in connection:
            raise UpgradeError("the 'Connection' header does not include 'Upgrade'", 400)
        ver = self.headers.get("Sec-WebSocket-Version", "")
        if not ver:
            raise UpgradeError("Missing Sec-WebSocket-Version header")

        if ver not in SUPPORT_HyBi_PROTOCOLS:
            # RFC 6455 section 4.4: tell the client which versions we do support
            raise UpgradeError(f"Unsupported protocol version {ver}", 426, {
                "Sec-WebSocket-Version": ", ".join(reversed(SUPPORT_HyBi_PROTOCOLS)),
            })

        # browsers separate the protocols with ", ":
        protocols = [protocol.strip() for protocol in self.headers.get("Sec-WebSocket-Protocol", "").split(",")]
        if "binary" not in protocols:
            raise UpgradeError("client does not support 'binary' protocol")

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            raise UpgradeError("Missing Sec-WebSocket-Key header")
        # RFC 6455 section 4.2.1: a base64 encoded 16 byte value
        try:
            valid = len(b64decode(key, validate=True)) == 16
        except (Base64Error, ValueError):
            valid = False
        if not valid:
            raise UpgradeError("invalid Sec-WebSocket-Key header")
        accept = make_websocket_accept_hash(strtobytes(key))
        log(f"websocket hash for key {key!r} = {accept!r}")
        self.write_byte_strings(
            b"HTTP/1.1 101 Switching Protocols",
            b"Upgrade: websocket",
            b"Connection: Upgrade",
            b"Sec-WebSocket-Accept: %s" % accept,
            b"Sec-WebSocket-Protocol: %s" % b"binary",
            b"",
            b"",
        )
        try:
            self.new_websocket_client(self)
        except Exception as e:
            # the upgrade response has already been sent,
            # so we can't reply with an http error without corrupting the websocket stream:
            log("new_websocket_client(%s)", self, exc_info=True)
            log.error("Error: failed to start the websocket connection:")
            log.estr(e)
            self.close_connection = True
            return
        # don't use our finish method that closes the socket,
        # but do call the superclass's finish() method:
        self.finish = super().finish

    def write_byte_strings(self, *bstrings) -> None:
        bdata = b"\r\n".join(bstrings)
        self.wfile.write(bdata)
        self.wfile.flush()

    def do_GET(self) -> None:
        log(f"do_GET() path={self.path!r}, headers={self.headers!r}")
        upgrade_requested = (self.headers.get('upgrade') or "").lower() == 'websocket'
        if self.only_upgrade or upgrade_requested:
            if not upgrade_requested:
                self.send_error(403, "only websocket connections are allowed")
                return
            try:
                self.handle_websocket()
            except UpgradeError as e:
                log("do_GET()", exc_info=True)
                log.error("Error: cannot handle websocket upgrade:")
                log.estr(e)
                self.extra_headers.update(e.headers)
                self.send_error(e.code, f"failed to handle websocket: {e}")
            except Exception:
                # a bug, don't send the details to the client:
                log.error("Error: websocket upgrade failure", exc_info=True)
                self.send_error(500, "websocket upgrade failure")
            return
        if self.headers.get("Upgrade-Insecure-Requests", "") == "1" and self.redirect_https:
            self.do_redirect_https()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.only_upgrade:
            self.send_error(405, "Method Not Allowed")
            return
        if self.redirect_https:
            self.do_redirect_https()
            return
        super().do_HEAD()

    def do_redirect_https(self) -> None:
        server_address = self.headers["Host"]
        if not server_address:
            log.warn("Warning: cannot redirect to https without a 'Host' header")
            self.send_error(400, "Client did not send a 'Host' header")
            return
        parts = server_address.split(":")
        if len(parts) == 2:
            host = parts[0]
        else:
            host = server_address
        if not is_valid_hostname(host):
            log.warn("Warning: cannot redirect to https using an invalid hostname")
            log.warn(f" {host!r}")
            self.send_error(400, "Client specified an invalid 'Host' header")
            return
        redirect = "301 Moved Permanently" if HTTPS_REDIRECT_PERMANENT else "307 Temporary Redirect"
        self.write_byte_strings(
            f"HTTP/1.1 {redirect}".encode("utf-8"),
            b"Connection: close",
            b"Location: https://%s%s" % (bytes(server_address, "utf-8"), bytes(self.path, "utf-8")),
            b"",
            b"",
        )

    def handle_request(self) -> None:
        if self.only_upgrade:
            self.send_error(405, "Method Not Allowed")
            return
        super().handle_request()

    def finish_and_close(self) -> None:
        super().finish()
        log(f"finish() close_connection={self.close_connection}, connection={self.connection}")
        if self.close_connection:
            self.connection.close()
