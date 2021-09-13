# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import glob
import posixpath
import mimetypes
from urllib.parse import unquote
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler

from xpra.common import DEFAULT_XDG_DATA_DIRS
from xpra.util import envbool, std, csv, AdHocStruct, repr_ellipsized
from xpra.platform.paths import get_desktop_background_paths
from xpra.log import Logger

log = Logger("http")

HTTP_ACCEPT_ENCODING = os.environ.get("XPRA_HTTP_ACCEPT_ENCODING", "br,gzip").split(",")
DIRECTORY_LISTING = envbool("XPRA_HTTP_DIRECTORY_LISTING", False)

EXTENSION_TO_MIMETYPE = {
    ".wasm" : "application/wasm",
    ".js"   : "text/javascript",
    ".css"  : "text/css",
    }


#should be converted to use standard library
def parse_url(handler):
    try:
        args_str = handler.path.split("?", 1)[1]
    except IndexError:
        return {}
    #parse args:
    args = {}
    for x in args_str.split("&"):
        v = x.split("=", 1)
        if len(v)==1:
            args[v[0]] = ""
        else:
            args[v[0]] = v[1]
    return args


class HTTPRequestHandler(BaseHTTPRequestHandler):
    """
    Xpra's builtin HTTP server.
    * locates the desktop background file at "/background.png" dynamically if missing,
    * supports the magic ?echo-headers query,
    * loads http headers from a directory (and caches the data),
    * sets cache headers on responses,
    * supports delegation to external script classes,
    * supports pre-compressed brotli and gzip, can gzip on-the-fly,
    (subclassed in WebSocketRequestHandler to add WebSocket support)
    """

    wbufsize = None     #we flush explicitly when needed
    server_version = "Xpra-HTTP-Server"
    http_headers_cache = {}
    http_headers_time = {}

    def __init__(self, sock, addr,
                 web_root="/usr/share/xpra/www/",
                 http_headers_dirs=("/etc/xpra/http-headers",), script_paths=None):
        self.web_root = web_root
        self.http_headers_dirs = http_headers_dirs
        self.script_paths = script_paths or {}
        server = AdHocStruct()
        server.logger = log
        self.directory_listing = DIRECTORY_LISTING
        self.extra_headers = {}
        super().__init__(sock, addr, server)

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
        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS)
        www_dir_options = [self.web_root]+[os.path.join(x, "xpra", "www") for x in xdg_data_dirs.split(":")]
        for p in www_dir_options:
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
        #hack for locating the default desktop background at runtime:
        if not os.path.exists(path) and s.endswith("/background.png"):
            paths = get_desktop_background_paths()
            for p in paths:
                matches = glob.glob(p)
                if matches:
                    path = matches[0]
                    break
            if not os.path.exists(path):
                #better send something than a 404,
                #use a transparent 1x1 image:
                path = os.path.join(self.web_root, "icons", "empty.png")
        log("translate_path(%s)=%s", s, path)
        return path


    def log_error(self, fmt, *args):  #pylint: disable=arguments-differ
        #don't log 404s at error level:
        if len(args)==2 and args[0]==404:
            log(fmt, *args)
        else:
            log.error(fmt, *args)

    def log_message(self, fmt, *args):  #pylint: disable=arguments-differ
        if args and len(args)==3 and fmt=='"%s" %s %s' and args[1]=="400":
            fmt = '"%r" %s %s'
            args = list(args)
            args[0] = repr_ellipsized(args[0])
        log(fmt, *args)


    def end_headers(self):
        #magic for querying request header values:
        path = getattr(self, "path", "")
        if path.endswith("?echo-headers"):
            #ie: "en-GB,en-US;q=0.8,en;q=0.6"
            accept = self.headers.get("Accept-Language")
            if accept:
                self.extra_headers["Echo-Accept-Language"] = std(accept, extras="-,./:;=")
        headers = self.get_headers()
        if self.extra_headers:
            headers.update(self.extra_headers)
        if headers:
            for k,v in headers.items():
                self.send_header(k, v)
        super().end_headers()

    def get_headers(self):
        return self.may_reload_headers(self.http_headers_dirs)

    @classmethod
    def may_reload_headers(cls, http_headers_dirs):
        mtimes = {}
        if cls.http_headers_cache:
            #do we need to refresh the cache?
            for d in http_headers_dirs:
                if os.path.exists(d) and os.path.isdir(d):
                    mtime = os.path.getmtime(d)
                    if mtime>cls.http_headers_time.get(d, -1):
                        mtimes[d] = mtime
            if not mtimes:
                return cls.http_headers_cache.copy()
            log("headers directories have changed: %s", mtimes)
        headers = {}
        for d in http_headers_dirs:
            if not os.path.exists(d) or not os.path.isdir(d):
                continue
            mtime = os.path.getmtime(d)
            for f in sorted(os.listdir(d)):
                header_file = os.path.join(d, f)
                if not os.path.isfile(header_file):
                    continue
                log("may_reload_headers() loading from '%s'", header_file)
                h = {}
                with open(header_file, "r") as hf:
                    for line in hf:
                        sline = line.strip().rstrip('\r\n').strip()
                        if sline.startswith("#") or not sline:
                            continue
                        parts = sline.split("=", 1)
                        if len(parts)!=2 and sline.find(":")>0:
                            parts = sline.split(":", 1)
                        if len(parts)!=2:
                            continue
                        h[parts[0].strip()] = parts[1].strip()
                log("may_reload_headers() '%s'=%s", header_file, h)
                headers.update(h)
            cls.http_headers_time[d] = mtime
        log("may_reload_headers() headers=%s, mtime=%s", headers, mtimes)
        cls.http_headers_cache = headers
        return headers.copy()


    def do_POST(self):
        try:
            length = int(self.headers.get('content-length'))
            data = self.rfile.read(length)
            log("POST data=%s (%i bytes)", data, length)
            self.handle_request()
        except Exception:
            log.error("Error processing POST request", exc_info=True)

    def do_GET(self):
        self.handle_request()

    def handle_request(self):
        content = self.send_head()
        if content:
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError) as e:
                log("handle_request() %s", e)
            except TypeError:
                log("handle_request()", exc_info=True)
                log.error("Error handling http request")
                log.error(" for '%s'", self.path)
                log.error(" content type is %s", type(content))
            except Exception:
                log.error("Error handling http request")
                log.error(" for '%s'", self.path, exc_info=True)

    def do_HEAD(self):
        self.send_head()

    #code taken from MIT licensed code in GzipSimpleHTTPServer.py
    def send_head(self):
        path = self.path.split("?",1)[0].split("#",1)[0]
        #strip path after second slash:
        while path.rfind("/", 1)>0:
            path = path[:path.rfind("/", 1)]
        script = self.script_paths.get(path)
        log("send_head() script(%s)=%s", path, script)
        if script:
            log("request for %s handled using %s", path, script)
            content = script(self)
            return content
        path = self.translate_path(self.path)
        if not path or not os.path.exists(path):
            self.send_error(404, "Path not found")
            return None
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
                if not self.directory_listing:
                    self.send_error(403, "Directory listing forbidden")
                    return None
                return SimpleHTTPRequestHandler.list_directory(self, path).read()
        ext = os.path.splitext(path)[1]
        f = None
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
            fs = os.fstat(f.fileno())
            content_length = fs[6]
            content_type = EXTENSION_TO_MIMETYPE.get(ext)
            if not content_type:
                if not mimetypes.inited:
                    mimetypes.init()
                ctype = mimetypes.guess_type(path, False)
                if ctype and ctype[0]:
                    content_type = ctype[0]
            log("guess_type(%s)=%s", path, content_type)
            if content_type:
                self.extra_headers["Content-type"] = content_type
            accept = self.headers.get('accept-encoding', '').split(",")
            accept = tuple(x.split(";")[0].strip() for x in accept)
            content = None
            log("accept-encoding=%s", csv(accept))
            for enc in HTTP_ACCEPT_ENCODING:
                #find a matching pre-compressed file:
                if enc not in accept:
                    continue
                compressed_path = "%s.%s" % (path, enc)     #ie: "/path/to/index.html.br"
                if not os.path.exists(compressed_path):
                    continue
                if not os.path.isfile(compressed_path):
                    log.warn("Warning: '%s' is not a file!", compressed_path)
                    continue
                if not os.access(compressed_path, os.R_OK):
                    log.warn("Warning: '%s' is not readable", compressed_path)
                    continue
                st = os.stat(compressed_path)
                if st.st_size==0:
                    log.warn("Warning: '%s' is empty", compressed_path)
                    continue
                log("sending pre-compressed file '%s'", compressed_path)
                #read pre-gzipped file:
                f.close()
                f = None
                f = open(compressed_path, 'rb')
                content = f.read()
                assert content, "no data in %s" % compressed_path
                self.extra_headers["Content-Encoding"] = enc
                break
            if not content:
                content = f.read()
                assert len(content)==content_length, \
                    "expected %s to contain %i bytes but read %i bytes" % (path, content_length, len(content))
                if content_length>128 and \
                ("gzip" in accept) and \
                ("gzip" in HTTP_ACCEPT_ENCODING) \
                and (ext not in (".png", )):
                    #gzip it on the fly:
                    import zlib
                    assert len(content)==content_length, \
                        "expected %s to contain %i bytes but read %i bytes" % (path, content_length, len(content))
                    gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
                    compressed_content = gzip_compress.compress(content) + gzip_compress.flush()
                    if len(compressed_content)<content_length:
                        log("gzip compressed '%s': %i down to %i bytes", path, content_length, len(compressed_content))
                        self.extra_headers["Content-Encoding"] = "gzip"
                        content = compressed_content
            f.close()
            f = None
            #send back response headers:
            self.send_response(200)
            self.extra_headers.update({
                "Content-Length"    : len(content),
                "Last-Modified"     : self.date_time_string(fs.st_mtime),
                })
            self.end_headers()
        except IOError as e:
            log("send_head()", exc_info=True)
            log.error("Error sending '%s':", path)
            emsg = str(e)
            if emsg.endswith(": '%s'" % path):
                log.error(" %s", emsg.rsplit(":", 1)[0])
            else:
                log.error(" %s", e)
            try:
                self.send_error(404, "File not found")
            except OSError:
                log("failed to send 404 error - maybe some of the headers were already sent?", exc_info=True)
            return None
        finally:
            if f:
                try:
                    f.close()
                except OSError:
                    log("failed to close", exc_info=True)
        return content
