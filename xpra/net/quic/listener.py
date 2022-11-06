# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import serve
from aioquic.quic.logger import QuicLogger
from aioquic.h3.connection import H3_ALPN
from aioquic.h0.connection import H0_ALPN
from xpra.net.quic.http3_server import HttpServerProtocol
from xpra.net.quic.session_ticket_store import SessionTicketStore

from xpra.net.http.directory_listing import list_directory
from xpra.net.quic.asyncio_thread import get_threaded_loop
from xpra.net.http.http_handler import (
    DIRECTORY_LISTING,
    translate_path, load_path, may_reload_headers,
    )
from xpra.util import envint
from xpra.os_util import strtobytes
from xpra.log import Logger
log = Logger("quic")

quic_logger = QuicLogger()

MAX_DATAGRAM_FRAME_SIZE = envint("XPRA_MAX_DATAGRAM_FRAME_SIZE", 65536)


#HttpRequestHandler
class ServerProtocol(HttpServerProtocol):
    async def app(self, scope, receive, send):
        log.warn(f"app({scope}, {receive}, {send})")
        http_version = scope.get("http_version", "0")
        if http_version!="3":
            log.warn(f"Warning: http version {http_version} is not supported")
            return
        method = scope.get("method", "")
        if method!="GET":
            log.warn(f"Warning: http {method} requests are not supported")
            return
        async def http3_response(code, headers=None, body=None):
            await self.send_http3_response(send, code, headers, body)
        req_path = scope.get("path", "")
        scripts = self.xpra_server.get_http_scripts()
        script = scripts.get(req_path)
        if script:
            log("request for %s handled using %s", req_path, script)
            await http3_response(*script(req_path))
            return
        web_root = self.xpra_server._www_dir
        headers_dirs = self.xpra_server._http_headers_dirs
        headers = may_reload_headers(headers_dirs)
        log(f"req_path={req_path}, web_root={web_root}, scripts={scripts}, headers_dir={headers_dirs}")
        path = translate_path(req_path, web_root)
        if not path or not os.path.exists(path):
            await http3_response(404, headers, body=b"Path not found")
            return
        if os.path.isdir(path):
            if not path.endswith('/'):
                # redirect browser - doing basically what apache does
                headers["Location"] = path + "/"
                await http3_response(301, headers)
                return
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                if not DIRECTORY_LISTING:
                    await http3_response(403, headers, body=b"Directory listing forbidden")
                    return
                return list_directory(path)
        code, path_headers, body = load_path(scope.get("headers", {}), path)
        headers.update(path_headers)
        await http3_response(code, headers, body)

    async def send_http3_response(self, send, code, headers, body):
        await send({
            "type"      : "http.response.start",
            "status"    : code,
            "headers"   : tuple((strtobytes(k).lower(), strtobytes(v)) for k,v in (headers or {}).items()),
            })
        await send({
            "type" : "http.response.body",
            "body" : body,
            })


async def do_listen(quic_sock, xpra_server):
    log.info(f"do_listen({quic_sock}, {xpra_server})")
    def make_protocol(*args, **kwargs):
        sp = ServerProtocol(*args, **kwargs)
        sp.xpra_server = xpra_server
        return sp
    try:
        configuration = QuicConfiguration(
            alpn_protocols=H3_ALPN + H0_ALPN + ["siduck"],
            is_client=False,
            max_datagram_frame_size=MAX_DATAGRAM_FRAME_SIZE,
            quic_logger=quic_logger,
        )
        configuration.load_cert_chain(quic_sock.ssl_cert, quic_sock.ssl_key)
        log(f"quic configuration={configuration}")
        session_ticket_store = SessionTicketStore()
        await serve(
            quic_sock.host,
            quic_sock.port,
            configuration=configuration,
            create_protocol=make_protocol,
            session_ticket_fetcher=session_ticket_store.pop,
            session_ticket_handler=session_ticket_store.add,
            retry=quic_sock.retry,
        )
    except Exception:
        log.error(f"Error: listening on {quic_sock}", exc_info=True)
        raise

def listen_quic(quic_sock, xpra_server=None):
    log(f"listen_quic({quic_sock})")
    t = get_threaded_loop()
    t.call(do_listen(quic_sock, xpra_server))
    return quic_sock.close
