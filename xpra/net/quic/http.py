# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Callable, Dict, Union

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h0.connection import H0Connection
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import H3Event

from xpra.net.quic.common import SERVER_NAME, http_date
from xpra.net.http.directory_listing import list_directory
from xpra.net.http.http_handler import (
    DIRECTORY_LISTING,
    translate_path, load_path, may_reload_headers,
    )
from xpra.util import ellipsizer
from xpra.os_util import strtobytes
from xpra.log import Logger
log = Logger("quic")

HttpConnection = Union[H0Connection, H3Connection]


class HttpRequestHandler:
    def __init__(self, xpra_server : object,
                 authority: bytes,
                 connection: HttpConnection,
                 protocol: QuicConnectionProtocol,
                 scope: Dict,
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


    def send_http3_response(self, code, headers : Dict = None, body : bytes = b""):
        self.send_response_header(code, headers)
        if body:
            self.send_response_body(body)
        self.transmit()

    def send_response_header(self, status : int = 200, headers : Dict = None) -> None:
        headers = [
                (b":status", str(status).encode()),
                (b"server", SERVER_NAME.encode()),
                (b"date", http_date().encode()),
                ] + list((strtobytes(k).lower(), strtobytes(v)) for k,v in (headers or {}).items())
        self.connection.send_headers(stream_id=self.stream_id, headers=headers)

    def send_response_body(self, body : bytes = b"", more_body : bool = False) -> None:
        self.connection.send_data(stream_id=self.stream_id, data=body, end_stream=not more_body)


    def http_event_received(self, event: H3Event) -> None:
        log(f"http_event_received(%s) scope={self.scope}", ellipsizer(event))
        http_version = self.scope.get("http_version", "0")
        if http_version!="3":
            log.error(f"Error: http version {http_version} is not supported")
            self.protocol.close()
            return
        method = self.scope.get("method", "")
        req_path = self.scope.get("path", "")
        log.info(f"HTTP request {method} {req_path}")
        scripts = self.xpra_server.get_http_scripts()
        script = scripts.get(req_path)
        log(f"req_path={req_path}, scripts={scripts}")
        if script:
            log(f"request for {req_path} handled using {script}")
            self.send_http3_response(*script(req_path))
            return
        if method!="GET":
            log.warn(f"Warning: http {method} requests are not supported")
            self.protocol.close()
            return
        self.handle_get_request(req_path)

    def handle_get_request(self, req_path):
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
        code, path_headers, body = load_path(self.scope.get("headers", {}), path)
        headers.update(path_headers)
        self.send_http3_response(code, headers, body)
