# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence

from xpra.util.env import envbool
from xpra.util.str_fn import is_valid_hostname, strtobytes
from xpra.net.common import HttpResponse
from xpra.net.websockets.common import make_websocket_accept_hash
from xpra.net.http.handler import HTTPRequestHandler, AUTH_USERNAME, AUTH_PASSWORD
from xpra.log import Logger

log = Logger("network", "websocket")

WEBSOCKET_ONLY_UPGRADE = envbool("XPRA_WEBSOCKET_ONLY_UPGRADE", False)
HTTPS_REDIRECT_PERMANENT = envbool("XPRA_HTTPS_REDIRECT_PERMANENT", True)

# HyBi-07 report version 7
# HyBi-08 - HyBi-12 report version 8
# HyBi-13 reports version 13
SUPPORT_HyBi_PROTOCOLS: Sequence[str] = ("7", "8", "13")


class WebSocketRequestHandler(HTTPRequestHandler):
    server_version = "Xpra-WebSocket-Server"

    def __init__(self, sock, addr, new_websocket_client,
                 web_root="/usr/share/xpra/www/",
                 http_headers_dir="/etc/xpra/http-headers",
                 script_paths: dict[str, Callable[[str], HttpResponse]] = None,
                 redirect_https=False,
                 username=AUTH_USERNAME,
                 password=AUTH_PASSWORD,
                 ):
        self.new_websocket_client: Callable = new_websocket_client
        self.only_upgrade = WEBSOCKET_ONLY_UPGRADE
        self.redirect_https = redirect_https
        self.finish = self.finish_and_close
        super().__init__(sock, addr,
                         web_root, http_headers_dir, script_paths,
                         username, password)

    def handle_websocket(self) -> None:
        log("handle_websocket() calling %s, request=%s (%s)",
            self.new_websocket_client, self.request, type(self.request))
        log("headers:")
        for k, v in self.headers.items():
            log(f" {k}={v}")
        ver = self.headers.get("Sec-WebSocket-Version", "")
        if not ver:
            raise ValueError("Missing Sec-WebSocket-Version header")

        if ver not in SUPPORT_HyBi_PROTOCOLS:
            raise ValueError(f"Unsupported protocol version {ver}")

        protocols = self.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if "binary" not in protocols:
            raise ValueError("client does not support 'binary' protocol")

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            raise ValueError("Missing Sec-WebSocket-Key header")
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
        self.new_websocket_client(self)
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
            except Exception as e:
                log("do_GET()", exc_info=True)
                log.error("Error: cannot handle websocket upgrade:")
                log.estr(e)
                self.send_error(403, f"failed to handle websocket: {e}")
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
