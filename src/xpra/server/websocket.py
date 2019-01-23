# This file is part of Xpra.
# Copyright (C) 2016-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import warnings
import posixpath
import mimetypes
try:
    from urllib import unquote          #python2 @UnusedImport
except ImportError:
    from urllib.parse import unquote    #python3 @Reimport @UnresolvedImport

from xpra.util import envbool, std, AdHocStruct
from xpra.os_util import memoryview_to_bytes, nomodule_context, PYTHON2, Queue, DummyContextManager
from xpra.net.bytestreams import SocketConnection
from xpra.log import Logger

log = Logger("network", "websocket")
httplog = Logger("network", "http")

WEBSOCKIFY_NUMPY = envbool("XPRA_WEBSOCKIFY_NUMPY", False)
log("WEBSOCKIFY_NUMPY=%s", WEBSOCKIFY_NUMPY)
if WEBSOCKIFY_NUMPY:
    cm = DummyContextManager()
else:
    cm = nomodule_context("numpy")
    from xpra.codecs.xor.cyxor import hybi_unmask
    unmask = staticmethod(hybi_unmask)
with cm:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import websockify
        assert websockify
        try:
            #websockify 0.8.0 and earlier:
            from websockify.websocket import WebSocketRequestHandler    #@UnusedImport
            if not WEBSOCKIFY_NUMPY:
                WebSocketRequestHandler.unmask = unmask
        except ImportError:
            from websockify.websocketserver import WebSocketRequestHandler
            if not WEBSOCKIFY_NUMPY:
                WebSocketRequestHandler._unmask = unmask
            #in previous versions, this method was doing the socket upgrade work,
            #but now this is where we need to trigger our new_websocket_client code...
            def handle_websocket(handler):
                return handler.new_websocket_client()
            WebSocketRequestHandler.handle_websocket = handle_websocket
        log("WebSocketRequestHandler=%s", WebSocketRequestHandler)
        #print warnings except for numpy:
        for x in w:
            message = getattr(x, "message", None)
            if message:
                if str(message).find("numpy")>0 and not WEBSOCKIFY_NUMPY:
                    log("numpy warning suppressed:")
                    log(" %s", message)
                else:
                    log.warn("Warning: %s", message)
            else:
                log.warn("Warning: %s", x)


WEBSOCKET_DEBUG = envbool("XPRA_WEBSOCKET_DEBUG", False)
WEBSOCKET_ONLY_UPGRADE = envbool("XPRA_WEBSOCKET_ONLY_UPGRADE", False)
HTTP_ACCEPT_ENCODING = os.environ.get("XPRA_HTTP_ACCEPT_ENCODING", "br,gzip").split(",")


class WSRequestHandler(WebSocketRequestHandler):

    server_version = "Xpra-WebSockify"

    http_headers_cache = {}
    http_headers_time = {}

    def __init__(self, sock, addr, new_websocket_client, web_root="/usr/share/xpra/www/", http_headers_dir="/usr/share/xpra/http-headers", script_paths={}, disable_nagle=True):
        self.web_root = web_root
        self.http_headers_dir = http_headers_dir
        self._new_websocket_client = new_websocket_client
        self.script_paths = script_paths
        server = AdHocStruct()
        server.logger = log
        server.run_once = True
        server.verbose = WEBSOCKET_DEBUG
        self.only_upgrade = server.only_upgrade = WEBSOCKET_ONLY_UPGRADE
        self.disable_nagle_algorithm = disable_nagle
        WebSocketRequestHandler.__init__(self, sock, addr, server)

    def new_websocket_client(self):
        log("new_websocket_client() calling %s, request=%s (%s)", self._new_websocket_client, self.request, type(self.request))
        self._new_websocket_client(self)

    def translate_path(self, path):
        #code duplicated from superclass since we can't easily inject the web_root..
        s = path
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        # Don't forget explicit trailing slash when normalizing. Issue17324
        trailing_slash = path.rstrip().endswith('/')
        path = posixpath.normpath(unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = self.web_root
        for p in [self.web_root]+[os.path.join(x, "xpra", "www") for x in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]:
            if os.path.exists(p) and os.path.isdir(p):
                path = p
                break
        for word in words:
            word = os.path.splitdrive(word)[1]
            word = os.path.split(word)[1]
            if word in (os.curdir, os.pardir):
                continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        httplog("translate_path(%s)=%s", s, path)
        return path


    def log_error(self, fmt, *args):
        #don't log 404s at error level:
        if len(args)==2 and args[0]==404:
            httplog(fmt, *args)
        else:
            httplog.error(fmt, *args)

    def log_message(self, fmt, *args):
        httplog(fmt, *args)

    def print_traffic(self, token="."):
        """ Show traffic flow mode. """
        if self.traffic:
            log(token)


    def end_headers(self):
        #magic for querying request header values:
        path = getattr(self, "path", "")
        if path.endswith("?echo-headers"):
            #ie: "en-GB,en-US;q=0.8,en;q=0.6"
            accept = self.headers.get("Accept-Language")
            if accept:
                self.send_header("Echo-Accept-Language", std(accept, extras="-,./:;="))
        for k,v in self.get_headers().items():
            self.send_header(k, v)
        WebSocketRequestHandler.end_headers(self)

    def get_headers(self):
        return self.may_reload_headers(self.http_headers_dir)

    @classmethod
    def may_reload_headers(cls, http_headers_dir):
        if not os.path.exists(http_headers_dir) or not os.path.isdir(http_headers_dir):
            cls.http_headers_cache[http_headers_dir] = {}
            return {}
        mtime = os.path.getmtime(http_headers_dir)
        httplog("may_reload_headers() http headers time=%s, mtime=%s", cls.http_headers_time, mtime)
        if mtime<=cls.http_headers_time.get(http_headers_dir, -1):
            #no change
            return cls.http_headers_cache.get(http_headers_dir, {})
        if PYTHON2:
            mode = "rU"
        else:
            mode = "r"
        headers = {}
        for f in sorted(os.listdir(http_headers_dir)):
            header_file = os.path.join(http_headers_dir, f)
            if os.path.isfile(header_file):
                httplog("may_reload_headers() loading from '%s'", header_file)
                with open(header_file, mode) as f:
                    for line in f:
                        sline = line.strip().rstrip('\r\n').strip()
                        if sline.startswith("#") or sline=='':
                            continue
                        parts = sline.split("=", 1)
                        if len(parts)!=2:
                            continue
                        headers[parts[0]] = parts[1]
        httplog("may_reload_headers() headers=%s, mtime=%s", headers, mtime)
        cls.http_headers_cache[http_headers_dir] = headers
        cls.http_headers_time[http_headers_dir] = mtime
        return headers


    def do_POST(self):
        try:
            length = int(self.headers.get('content-length'))
            data = self.rfile.read(length)
            httplog("POST data=%s (%i bytes)", data, length)
            self.handle_request()
        except Exception:
            httplog.error("Error processing POST request", exc_info=True)

    def do_GET(self):
        if self.only_upgrade or (self.headers.get('upgrade') and
            self.headers.get('upgrade').lower() == 'websocket'):
            self.handle_websocket()
            return
        self.handle_request()

    def handle_request(self):
        if self.only_upgrade:
            self.send_error(405, "Method Not Allowed")
        else:
            content = self.send_head()
            if content:
                self.wfile.write(content)
            #self.wfile.close()

    def do_HEAD(self):
        if self.only_upgrade:
            self.send_error(405, "Method Not Allowed")
        else:
            self.send_head()

    #code taken from MIT licensed code in GzipSimpleHTTPServer.py
    def send_head(self):
        path = self.path.split("?",1)[0].split("#",1)[0]
        script = self.script_paths.get(path)
        httplog("send_head() script(%s)=%s", path, script)
        if script:
            httplog("request for %s handled using %s", path, script)
            content = script(self)
            return content
        path = self.translate_path(self.path)
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
        _, ext = os.path.splitext(path)
        f = None
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
            fs = os.fstat(f.fileno())
            content_length = fs[6]
            headers = {}
            ctype = mimetypes.guess_type(path, False)
            httplog("guess_type(%s)=%s", path, ctype)
            if ctype and ctype[0]:
                headers["Content-type"] = ctype[0]
            accept = self.headers.get('accept-encoding', '').split(",")
            accept = [x.split(";")[0].strip() for x in accept]
            content = None
            httplog("accept-encoding=%s", accept)
            for enc in HTTP_ACCEPT_ENCODING:
                #find a matching pre-compressed file:
                if enc not in accept:
                    continue
                compressed_path = "%s.%s" % (path, enc)     #ie: "/path/to/index.html.br"
                if not os.path.exists(compressed_path):
                    continue
                if not os.path.isfile(compressed_path):
                    httplog.warn("Warning: '%s' is not a file!", compressed_path)
                    continue
                if not os.access(compressed_path, os.R_OK):
                    httplog.warn("Warning: '%s' is not readable", compressed_path)
                    continue
                st = os.stat(compressed_path)
                if st.st_size==0:
                    httplog.warn("Warning: '%s' is empty", compressed_path)
                    continue
                httplog("sending pre-compressed file '%s'", compressed_path)
                #read pre-gzipped file:
                f.close()
                f = None
                f = open(compressed_path, 'rb')
                content = f.read()
                assert content, "no data in %s" % compressed_path
                headers["Content-Encoding"] = enc
                break
            if not content:
                content = f.read()
                assert len(content)==content_length, \
                    "expected %s to contain %i bytes but read %i bytes" % (path, content_length, len(content))
                if content_length>128 and ("gzip" in accept) and ("gzip" in HTTP_ACCEPT_ENCODING) and (ext not in (".png", )):
                    #gzip it on the fly:
                    import zlib
                    assert len(content)==content_length, \
                        "expected %s to contain %i bytes but read %i bytes" % (path, content_length, len(content))
                    gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
                    compressed_content = gzip_compress.compress(content) + gzip_compress.flush()
                    if len(compressed_content)<content_length:
                        httplog("gzip compressed '%s': %i down to %i bytes", path, content_length, len(compressed_content))
                        headers["Content-Encoding"] = "gzip"
                        content = compressed_content
            f.close()
            f = None
            headers["Content-Length"] = len(content)
            headers["Last-Modified"] = self.date_time_string(fs.st_mtime)
            #send back response headers:
            self.send_response(200)
            for k,v in headers.items():
                self.send_header(k, v)
            self.end_headers()
        except IOError as e:
            httplog("send_head()", exc_info=True)
            httplog.error("Error sending '%s':", path)
            emsg = str(e)
            if emsg.endswith(": '%s'" % path):
                httplog.error(" %s", emsg.rsplit(":", 1)[0])
            else:
                httplog.error(" %s", e)
            try:
                self.send_error(404, "File not found")
            except:
                httplog("failed to send 404 error - maybe some of the headers were already sent?")
            if f:
                try:
                    f.close()
                except:
                    pass
            return None
        return content


try:
    #websockify version > 0.8
    #patch WebSocket class so we always choose binary
    #(why isn't this the default!?)
    from websockify.websocket import WebSocket
    WebSocket.select_subprotocol = lambda _self,_protocols: "binary"
    class WebSocketConnection(SocketConnection):
        def __init__(self, socket, local, remote, target, socktype, ws_handler):
            SocketConnection.__init__(self, socket, local, remote, target, socktype)
            self.protocol_type = "websocket"
            self.request = ws_handler.request
        
        def close(self):
            SocketConnection.close(self)
            request = self.request
            if request:
                try:
                    request.close()
                except Exception:
                    log("error closing %s", request, exc_info=True)
        
        def read(self, n):
            #FIXME: we should try to honour n
            #from websockify.websocket import WebSocketWantReadError, WebSocketWantWriteError
            from websockify.websocket import WebSocketWantReadError
            request = self.request
            while self.is_active():
                if request.close_code:
                    log.warn("Warning: websocket connection already closed:")
                    log.warn(" %i: %s", request.close_code, request.close_reason)
                    self.close()
                    return None
                try:
                    buf = request.recv()
                except WebSocketWantReadError as e:
                    log("waiting for data: %s", e)
                    continue
                else:
                    if buf:
                        self.input_bytecount += len(buf)
                        return buf
            return None
        
        def write(self, buf):
            #log("write(%i bytes)", len(buf))
            from websockify.websocket import WebSocketWantWriteError
            request = self.request
            while self.is_active():
                try:
                    l = request.send(memoryview_to_bytes(buf))
                    self.output_bytecount += l
                    return l
                except WebSocketWantWriteError as e:
                    log("waiting to write: %s", e)
                    continue
            return None

except ImportError:
    #websockify version 0.8 or older:
    class WebSocketConnection(SocketConnection):
        def __init__(self, socket, local, remote, target, socktype, ws_handler):
            SocketConnection.__init__(self, socket, local, remote, target, socktype)
            self.protocol_type = "websocket"
            self.ws_handler = ws_handler
            self.pending_read = Queue()
    
        def close(self):
            self.pending_read = Queue()
            SocketConnection.close(self)
    
        def read(self, n):
            #FIXME: we should try to honour n
            while self.is_active():
                if self.pending_read.qsize():
                    buf = self.pending_read.get()
                    log("read() returning pending read buffer, len=%i", len(buf))
                    self.input_bytecount += len(buf)
                    return buf
                bufs, closed_string = self.ws_handler.recv_frames()
                if closed_string:
                    log("read() closed_string: %s", closed_string)
                    self.active = False
                log("read() got %i ws frames", len(bufs))
                if bufs:
                    buf = bufs[0]
                    if len(bufs) > 1:
                        for v in bufs[1:]:
                            self.pending_read.put(v)
                    self.input_bytecount += len(buf)
                    return buf
    
        def write(self, buf):
            self.ws_handler.send_frames((memoryview_to_bytes(buf),))
            self.output_bytecount += len(buf)
            return len(buf)
