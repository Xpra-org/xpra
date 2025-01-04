# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import glob
import posixpath
import mimetypes
import socket
from urllib.parse import unquote
from http.server import BaseHTTPRequestHandler
from typing import Any
from collections.abc import Iterable, Callable

from xpra.common import FULL_INFO
from xpra.net.common import HttpResponse
from xpra.net.http.common import EXTENSION_TO_MIMETYPE
from xpra.net.http.directory_listing import list_directory
from xpra.net.bytestreams import pretty_socket
from xpra.util.objects import AdHocStruct
from xpra.util.str_fn import std, csv, repr_ellipsized
from xpra.util.env import envbool
from xpra.platform.paths import get_desktop_background_paths
from xpra.log import Logger

log = Logger("http")

HTTP_ACCEPT_ENCODING = os.environ.get("XPRA_HTTP_ACCEPT_ENCODING", "br,gzip").split(",")
DIRECTORY_LISTING = envbool("XPRA_HTTP_DIRECTORY_LISTING", False)

AUTH_REALM = os.environ.get("XPRA_HTTP_AUTH_REALM", "Xpra")
AUTH_USERNAME = os.environ.get("XPRA_HTTP_AUTH_USERNAME", "")
AUTH_PASSWORD = os.environ.get("XPRA_HTTP_AUTH_PASSWORD", "")


http_headers_cache: dict[str, str] = {}
http_headers_time: dict[str, float] = {}


def may_reload_headers(http_headers_dirs: Iterable[str]) -> dict[str, str]:
    mtimes: dict[str, float] = {}
    global http_headers_cache
    if http_headers_cache:
        # do we need to refresh the cache?
        for d in http_headers_dirs:
            if os.path.exists(d) and os.path.isdir(d):
                mtime = os.path.getmtime(d)
                if mtime > http_headers_time.get(d, -1):
                    mtimes[d] = mtime
        if not mtimes:
            return http_headers_cache.copy()
        log("headers directories have changed: %s", mtimes)
    headers: dict[str, str] = {}
    for d in http_headers_dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            continue
        mtime = os.path.getmtime(d)
        for f in sorted(os.listdir(d)):
            header_file = os.path.join(d, f)
            if not os.path.isfile(header_file):
                continue
            log("may_reload_headers() loading from '%s'", header_file)
            h: dict[str, str] = {}
            with open(header_file, encoding="latin1") as hf:
                for line in hf:
                    sline = line.strip().rstrip("\r\n").strip()
                    if sline.startswith("#") or not sline:
                        continue
                    parts = sline.split("=", 1)
                    if len(parts) != 2 and sline.find(":") > 0:
                        parts = sline.split(":", 1)
                    if len(parts) != 2:
                        continue
                    h[parts[0].strip()] = parts[1].strip()
            log(f"may_reload_headers() {header_file}={h!r}")
            headers.update(h)
        http_headers_time[d] = mtime
    log(f"may_reload_headers() headers={headers!r}, mtime={mtimes}")
    http_headers_cache = headers
    return headers.copy()


def translate_path(path: str, web_root: str = "/usr/share/xpra/www") -> str:
    # code duplicated from superclass since we can't easily inject the web_root..
    s = path
    # abandon query parameters
    path = path.split('?', 1)[0]
    path = path.split('#', 1)[0]
    # Don't forget explicit trailing slash when normalizing. Issue17324
    trailing_slash = path.rstrip().endswith('/')
    path = posixpath.normpath(unquote(path))
    words = path.split('/')
    words = list(filter(None, words))
    path = web_root
    for word in words:
        word = os.path.splitdrive(word)[1]
        word = os.path.split(word)[1]
        if word in (os.curdir, os.pardir):
            continue
        path = os.path.join(path, word)
    if trailing_slash:
        path += '/'
    # hack for locating the default desktop background at runtime:
    if not os.path.exists(path) and s.endswith("/background.png"):
        paths = get_desktop_background_paths()
        for p in paths:
            matches = glob.glob(p)
            if matches:
                path = matches[0]
                break
        if not os.path.exists(path):
            # better send something than a 404,
            # use a transparent 1x1 image:
            path = os.path.join(web_root, "icons", "empty.png")
    log("translate_path(%s)=%s", s, path)
    return path


def load_path(accept_encoding: list[str], path: str) -> tuple[int, dict[str, Any], bytes]:
    ext = os.path.splitext(path)[1]
    extra_headers: dict[str, Any] = {}
    with open(path, "rb") as f:
        # Always read in binary mode. Opening files in text mode may cause
        # newline translations, making the actual size of the content
        # transmitted *less* than the content-length!
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
            extra_headers["Content-type"] = content_type
        accept = tuple(accept_encoding)
        accept = tuple(x.split(";")[0].strip() for x in accept)
        content = None
        log("accept-encoding=%s", csv(accept))
        for enc in HTTP_ACCEPT_ENCODING:
            # find a matching pre-compressed file:
            if enc not in accept:
                continue
            compressed_path = f"{path}.{enc}"  # ie: "/path/to/index.html.br"
            if not os.path.exists(compressed_path):
                continue
            if not os.path.isfile(compressed_path):
                log.warn(f"Warning: {compressed_path!r} is not a file!")
                continue
            if not os.access(compressed_path, os.R_OK):
                log.warn(f"Warning: {compressed_path!r} is not readable")
                continue
            st = os.stat(compressed_path)
            if st.st_size == 0:
                log.warn(f"Warning: {compressed_path!r} is empty")
                continue
            log("sending pre-compressed file '%s'", compressed_path)
            # read pre-gzipped file:
            with open(compressed_path, "rb") as cf:
                content = cf.read()
            assert content, f"no data in {compressed_path!r}"
            extra_headers["Content-Encoding"] = enc
            break
        if not content:
            content = f.read()
            if len(content) != content_length:
                raise RuntimeError(f"expected {path!r} to contain {content_length} bytes but read {len(content)} bytes")
            if all((
                    content_length > 128,
                    "gzip" in accept,
                    "gzip" in HTTP_ACCEPT_ENCODING,
                    ext not in (".png",),
            )):
                # gzip it on the fly:
                import zlib  # pylint: disable=import-outside-toplevel
                gzip_compress = zlib.compressobj(9, zlib.DEFLATED, zlib.MAX_WBITS | 16)
                compressed_content = gzip_compress.compress(content) + gzip_compress.flush()
                if len(compressed_content) < content_length:
                    log("gzip compressed '%s': %i down to %i bytes", path, content_length, len(compressed_content))
                    extra_headers["Content-Encoding"] = "gzip"
                    content = compressed_content
        extra_headers |= {
            "Content-Length": len(content),
            "Last-Modified": fs.st_mtime,
        }
        return 200, extra_headers, content


# noinspection PyPep8Naming
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

    wbufsize = 0  # we flush explicitly when needed
    server_version = "Xpra-HTTP-Server"
    sys_version = "Python/" + ".".join(str(vnum) for vnum in sys.version_info[:FULL_INFO+1])

    def __init__(self, sock, addr,
                 web_root: str = "/usr/share/xpra/www/",
                 http_headers_dirs: Iterable[str] = ("/etc/xpra/http-headers", ),
                 script_paths: dict[str, Callable[[str], HttpResponse]] = None,
                 username: str = AUTH_USERNAME,
                 password: str = AUTH_PASSWORD):
        self.web_root = web_root
        self.http_headers_dirs = http_headers_dirs
        self.script_paths = script_paths or {}
        self.username = username
        self.password = password
        server = AdHocStruct()
        server.logger = log
        self.directory_listing = DIRECTORY_LISTING
        self.extra_headers: dict[str, Any] = {}
        super().__init__(sock, addr, server)

    def log_error(self, fmt, *args) -> None:  # pylint: disable=arguments-differ
        # don't log 404s at error level:
        if len(args) == 1 and isinstance(args[0], TimeoutError):
            log(fmt, *args)
        elif len(args) == 2 and args[0] == 404:
            log(fmt, *args)
        else:
            log.error(fmt, *args)

    def log_message(self, fmt, *args) -> None:  # pylint: disable=arguments-differ
        if args and len(args) == 3 and fmt == '"%s" %s %s' and args[1] == "400":
            fmt = '"%r" %s %s'
            largs = list(args)
            largs[0] = repr_ellipsized(args[0])
            args = tuple(largs)
        log(fmt, *args)

    def end_headers(self) -> None:
        # magic for querying request header values:
        path = getattr(self, "path", "")
        if path.endswith("?echo-headers"):
            # ie: "en-GB,en-US;q=0.8,en;q=0.6"
            accept = self.headers.get("Accept-Language")
            if accept:
                self.extra_headers["Echo-Accept-Language"] = std(accept, extras="-,./:;=")
        headers = self.get_headers()
        if self.extra_headers:
            headers.update(self.extra_headers)
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        super().end_headers()

    def get_headers(self) -> dict[str, str]:
        return may_reload_headers(self.http_headers_dirs)

    def do_POST(self) -> None:
        with log.trap_error("Error processing POST request"):
            length = int(self.headers.get('content-length'))
            data = self.rfile.read(length)
            log("POST data=%s (%i bytes)", data, length)
            self.handle_request()

    def do_GET(self) -> None:
        self.handle_request()

    def handle_authentication(self) -> bool:
        if not self.password:
            return True
        authlog = Logger("auth", "http")

        def auth_err(msg):
            self.do_AUTHHEAD()
            self.wfile.write(msg.encode("latin1"))
            authlog.warn(f"http authentication failed: {msg}")
            try:
                peername = self.request.getpeername()
                authlog.warn(" from %s", pretty_socket(peername))
            except (AttributeError, OSError):
                pass
            return False

        auth = self.headers.get("Authorization")
        authlog("handle_request() auth header=%s", auth)
        if not auth:
            return auth_err("missing authentication header")
        # ie: auth = 'Basic dGVzdDp0ZXN0'
        if not auth.startswith("Basic "):
            return auth_err("invalid authentication header")
        b64str = auth.split("Basic ", 1)[1]
        import base64
        try:
            s = base64.b64decode(b64str).decode("utf8")
        except ValueError:
            s = ""
        if s.find(":") < 0:
            return auth_err("invalid authentication format")
        username, password = s.split(":", 1)
        if (self.username and username != self.username) or password != self.password:
            authlog("http authentication: expected %s:%s but received %s:%s",
                    self.username or "", self.password, username, password)
            return auth_err("invalid credentials")
        authlog("http authentication passed")
        return True

    def handle_request(self) -> None:
        if not self.handle_authentication():
            return
        content = self.send_head()
        if content:
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                # ssl.SSLEOFError is a socket.error
                log("handle_request() %s", e)
            except TypeError:
                self.close_connection = True
                log("handle_request()", exc_info=True)
                log.error("Error handling http request")
                log.error(" for '%s'", self.path)
                log.error(" content type is %s", type(content))
            except Exception:
                self.close_connection = True
                log.error("Error handling http request")
                log.error(" for '%s'", self.path, exc_info=True)

    def do_HEAD(self) -> None:
        self.send_head()

    def do_AUTHHEAD(self) -> None:
        self.send_response(401)
        if self.password:
            self.send_header("WWW-Authenticate", f"Basic realm=\"{AUTH_REALM}\"")
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def send_error(self, code, message=None, explain=None) -> None:
        try:
            super().send_error(code, message, explain)
        except OSError:
            log(f"failed to send {code} error - maybe some of the headers were already sent?", exc_info=True)

    # code taken from MIT licensed code in GzipSimpleHTTPServer.py
    def send_head(self) -> bytes:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        # strip path after second slash:
        script_path = path
        while script_path.rfind("/", 1) > 0:
            script_path = script_path[:script_path.rfind("/", 1)]
        script = self.script_paths.get(script_path)
        log("send_head() script(%s)=%s", script_path, script)
        if script:
            log("request for %s handled using %s", path, script)
            try:
                code, headers, body = script(path)
            except Exception:
                log.error(f"Error calling script {script}", exc_info=True)
                self.send_error(500, "Server error")
                return b""
            self.send_response(code)
            self.extra_headers.update(headers or {})
            self.end_headers()
            return body
        path = translate_path(self.path, self.web_root)
        if not path or not os.path.exists(path):
            self.send_error(404, "Path not found")
            return b""
        if os.path.isdir(path):
            if not path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.end_headers()
                return b""
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                if not self.directory_listing:
                    self.send_error(403, "Directory listing forbidden")
                    return b""
                code, headers, body = list_directory(path)
                self.send_response(code)
                self.extra_headers.update(headers)
                self.end_headers()
                return body
        try:
            accept_encoding = self.headers.get("accept-encoding", "").split(",")
            code, extra_headers, content = load_path(accept_encoding, path)
            lm = extra_headers.get("Last-Modified")
            if lm:
                extra_headers["Last-Modified"] = self.date_time_string(lm)
            self.send_response(code)
            self.extra_headers.update(extra_headers)
            self.end_headers()
            return content
        except OSError as e:
            self.close_connection = True
            log("send_head()", exc_info=True)
            if not isinstance(e, ConnectionResetError):
                log.error("Error sending '%s':", path)
                emsg = str(e)
                if emsg.endswith(f": '{path}'"):
                    log.error(" %s", emsg.rsplit(":", 1)[0])
                else:
                    log.estr(e)
                self.send_error(404, "File not found")
            return b""
