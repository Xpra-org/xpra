# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Union
from collections.abc import Callable

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import H3Event
from aioquic.quic.packet import QuicErrorCode

from xpra.net.quic.common import SERVER_NAME, http_date, binary_headers
from xpra.net.http.directory_listing import list_directory
from xpra.net.http.handler import DIRECTORY_LISTING, translate_path, load_path, may_reload_headers
from xpra.net.common import HttpResponse
from xpra.util.str_fn import Ellipsizer
from xpra.log import Logger

log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class HttpRequestHandler:
    def __init__(self, xpra_server: object,
                 authority: bytes,
                 connection: HttpConnection,
                 protocol: QuicConnectionProtocol,
                 scope: dict,
                 stream_id: int,
                 transmit: Callable[[], None],
                 ) -> None:
        self.xpra_server = xpra_server
        self.authority = authority
        self.connection = connection
        self.protocol = protocol
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit

    def send_http3_response(self, code, headers: dict, body: bytes = b"") -> None:
        self.send_response_header(code, headers)
        if body:
            self.send_response_body(body)
        self.transmit()

    def send_response_header(self, status: int, headers: dict) -> None:
        full_headers = {
            ":status": str(status),
            "server": SERVER_NAME.encode(),
            "date": http_date().encode(),
        }
        full_headers.update(headers)
        self.connection.send_headers(stream_id=self.stream_id, headers=binary_headers(full_headers))

    def send_response_body(self, body: bytes = b"", more_body: bool = False) -> None:
        self.connection.send_data(stream_id=self.stream_id, data=body, end_stream=not more_body)

    def http_event_received(self, event: H3Event) -> None:
        log(f"http_event_received(%s) scope={self.scope}", Ellipsizer(event))
        http_version = self.scope.get("http_version", "0")
        if http_version != "3":
            message = "http version {http_version} is not supported"
            log.error(f"Error: {message}")
            self.protocol.close(QuicErrorCode.APPLICATION_ERROR, message)
            return
        method = self.scope.get("method", "")
        req_path = self.scope.get("path", "")
        log.info(f"HTTP request {method} {req_path}")
        scripts = self.xpra_server.get_http_scripts()
        # script is a: Callable[[str], HttpResponse]
        script = scripts.get(req_path)
        log(f"req_path={req_path}, scripts={scripts}")
        if script:
            log(f"request for {req_path} handled using {script}")
            script_response: HttpResponse = script(req_path)
            self.send_http3_response(*script_response)
            return
        if method != "GET":
            message = f"http {method} requests are not supported"
            log.warn(f"Warning: {message}")
            self.protocol.close(QuicErrorCode.APPLICATION_ERROR, message)
            return
        self.handle_get_request(req_path)

    def handle_get_request(self, req_path: str) -> None:
        web_root = self.xpra_server._www_dir
        headers_dirs = self.xpra_server._http_headers_dirs
        headers = may_reload_headers(headers_dirs)
        log(f"handle_get_request({req_path}) web_root={web_root}, headers_dir={headers_dirs}")
        path = translate_path(req_path, web_root)
        if not path or not os.path.exists(path):
            self.send_http3_response(404, headers, body=b"Path not found")
            return
        if os.path.isdir(path):
            if not path.endswith('/'):
                # redirect browser - doing basically what apache does
                headers["Location"] = path + "/"
                self.send_http3_response(301, headers)
                return
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                if not DIRECTORY_LISTING:
                    self.send_http3_response(403, headers, body=b"Directory listing forbidden")
                    return
                code, extra_headers, body = list_directory(path)
                headers.update(extra_headers)
                self.send_http3_response(code, headers, body)
                return
        accept_encoding = self.scope.get("headers", {}).get("accept-encoding", "").split(",")
        code, path_headers, body = load_path(accept_encoding, path)
        headers.update(path_headers)
        self.send_http3_response(code, headers, body)
