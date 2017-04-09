# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import zlib
import posixpath
import urllib

from xpra.log import Logger
log = Logger("network", "websocket")

from xpra.util import AdHocStruct, envbool, std
from xpra.os_util import memoryview_to_bytes
from xpra.net.bytestreams import SocketConnection
from websockify.websocket import WebSocketRequestHandler

WEBSOCKET_TCP_NODELAY = envbool("WEBSOCKET_TCP_NODELAY", True)
WEBSOCKET_TCP_KEEPALIVE = envbool("WEBSOCKET_TCP_KEEPALIVE", True)
WEBSOCKET_DEBUG = envbool("XPRA_WEBSOCKET_DEBUG", False)
HTTP_NOCACHE = envbool("XPRA_HTTP_NOCACHE", True)


class WSRequestHandler(WebSocketRequestHandler):

    disable_nagle_algorithm = WEBSOCKET_TCP_NODELAY
    keep_alive = WEBSOCKET_TCP_KEEPALIVE
    server_version = "Xpra-WebSockify"

    def __init__(self, sock, addr, new_websocket_client, web_root="/usr/share/xpra/www/"):
        self.web_root = web_root
        self._new_websocket_client = new_websocket_client
        server = AdHocStruct()
        server.logger = log
        server.run_once = True
        server.verbose = WEBSOCKET_DEBUG
        WebSocketRequestHandler.__init__(self, sock, addr, server)

    def new_websocket_client(self):
        self._new_websocket_client(self)

    def translate_path(self, path):
        #code duplicated from superclass since we can't easily inject the web_root..
        s = path
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        # Don't forget explicit trailing slash when normalizing. Issue17324
        trailing_slash = path.rstrip().endswith('/')
        path = posixpath.normpath(urllib.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = self.web_root
        for word in words:
            word = os.path.splitdrive(word)[1]
            word = os.path.split(word)[1]
            if word in (os.curdir, os.pardir):
                continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        log("translate_path(%s)=%s", s, path)
        return path


    def log_error(self, fmt, *args):
        #don't log 404s at error level:
        if len(args)==2 and args[0]==404:
            log(fmt, *args)
        else:
            log.error(fmt, *args)

    def log_message(self, fmt, *args):
        #log.warn("%s", (fmt, args))
        log(fmt, *args)

    def print_traffic(self, token="."):
        """ Show traffic flow mode. """
        if self.traffic:
            log(token)


    def end_headers(self):
        #magic for querying request header values:
        if self.path.endswith("?echo-headers"):
            #ie: "en-GB,en-US;q=0.8,en;q=0.6"
            accept = self.headers.getheader("Accept-Language")
            if accept:
                self.send_header("Echo-Accept-Language", std(accept, extras="-,./:;="))
        if HTTP_NOCACHE:
            self.send_nocache_headers()
        WebSocketRequestHandler.end_headers(self)

    def send_nocache_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")


    def do_POST(self):
        try:
            length = int(self.headers.getheader('content-length'))
            data = self.rfile.read(length)
            log("POST data=%s (%i bytes)", data, length)
            self.do_GET()
        except Exception:
            log.error("Error processing POST request", exc_info=True)

    def do_GET(self):
        """Handle GET request. Calls handle_websocket(). If unsuccessful,
        and web server is enabled, SimpleHTTPRequestHandler.do_GET will be called."""
        if not self.handle_websocket():
            if self.only_upgrade:
                self.send_error(405, "Method Not Allowed")
            else:
                content = self.send_head()
                if content:
                    self.wfile.write(content)

    def do_HEAD(self):
        if self.only_upgrade:
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_head()

    #code taken from MIT licensed code in GzipSimpleHTTPServer.py
    def send_head(self):
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            if not path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                #self.send_error(403, "Directory listing forbidden")
                return self.list_directory(path).read()            
        ctype = self.guess_type(path)
        _, ext = os.path.splitext(path)
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
            fs = os.fstat(f.fileno())
            content_length = fs[6]
            headers = {
                "Content-type"      : ctype,
                "Content-Length"    : content_length,
                }
            accept = self.headers.get('accept-encoding', []).split(",")
            accept = [x.split(";")[0].strip() for x in accept]
            content = None
            log("accept-encoding=%s", accept)
            for enc in ("br", "gzip"):
                #find a matching pre-compressed file:
                if enc not in accept:
                    continue
                compressed_path = "%s.%s" % (path, enc)     #ie: "/path/to/index.html.br"
                if os.path.exists(compressed_path):
                    log("sending pre-compressed file '%s'", compressed_path)
                    #read pre-gzipped file:
                    f.close()
                    f = open(compressed_path, 'rb')
                    content = f.read()
                    headers["Content-Encoding"] = enc
                    break
            if (not content) and content_length>128 and ("gzip" in accept) and (ext not in (".png", )):
                #gzip it on the fly:
                content = f.read()
                gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
                compressed_content = gzip_compress.compress(content) + gzip_compress.flush()
                if len(compressed_content)<content_length:
                    log("gzip compressed '%s': %i down to %i bytes", path, content_length, len(compressed_content))
                    headers["Content-Encoding"] = "gzip"
                    content = compressed_content
            f.close()
            headers["Last-Modified"] = self.date_time_string(fs.st_mtime)
            #send back response headers:
            self.send_response(200)
            for k,v in headers.items():
                self.send_header(k, v)
            self.end_headers()
        except IOError:
            self.send_error(404, "File not found")
            return None
        return content


class WebSocketConnection(SocketConnection):

    def __init__(self, socket, local, remote, target, info, ws_handler):
        SocketConnection.__init__(self, socket, local, remote, target, info)
        self.protocol_type = "websocket"
        self.ws_handler = ws_handler

    def read(self, n):
        while self.is_active():
            bufs, closed_string = self.ws_handler.recv_frames()
            if closed_string:
                self.active = False
            if len(bufs) == 1:
                self.input_bytecount += len(bufs[0])
                return bufs[0]
            elif len(bufs) > 1:
                buf = b''.join(bufs)
                self.input_bytecount += len(buf)
                return buf

    def write(self, buf):
        self.ws_handler.send_frames([memoryview_to_bytes(buf)])
        self.output_bytecount += len(buf)
        return len(buf)
