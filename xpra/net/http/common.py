# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from urllib.parse import urlsplit
from collections.abc import Sequence

from xpra.net.common import HttpResponse

EXTENSION_TO_MIMETYPE: dict[str, str] = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".css": "text/css",
}

# values of the `http-origin` option which disable the origin check,
# or which reject every request that carries an `Origin` header:
ORIGIN_ANY: Sequence[str] = ("any", "all", "*")
ORIGIN_NONE: Sequence[str] = ("none", "no", "off", "false")

DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}


def parse_origin(origin: str) -> tuple[str, str, int]:
    """
    Parse an origin (ie: `https://desktop.example:8443`) into a `(scheme, hostname, port)` tuple.
    The `ws` and `wss` schemes are normalized to their http equivalents,
    and the port is filled in from the scheme when it is not specified.
    Origins we cannot parse - ie: the `null` origin sent by sandboxed iframes - return empty values.
    """
    try:
        parts = urlsplit(origin.strip().lower())
        hostname = parts.hostname or ""
        port = parts.port or 0
    except ValueError:  # invalid port
        return "", "", 0
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    if not scheme or not hostname:
        return "", "", 0
    return scheme, hostname, port or DEFAULT_PORTS.get(scheme, 0)


def same_origin(origin: str, host: str) -> bool:
    """
    Verify that the `Origin` header matches the `Host` header of the same request.
    The scheme is not compared: the server may be behind a TLS terminating proxy,
    in which case the browser's origin is `https` even though the connection we see is not.
    The port is only compared when the `Host` header specifies one explicitly,
    which browsers always do for non-default ports - ie: `--bind-ws=localhost:14500`.
    """
    oscheme, ohost, oport = parse_origin(origin)
    if not oscheme or not ohost:
        return False
    try:
        hparts = urlsplit(f"//{host.strip().lower()}")
        hhost = hparts.hostname or ""
        hport = hparts.port or 0
    except ValueError:
        return False
    if not hhost or hhost != ohost:
        return False
    return not hport or hport == oport


def check_origin(origin: str, host: str, policy: str) -> bool:
    """
    Verify the `Origin` header of an http request against the `http-origin` policy.
    Browsers always send an `Origin` header when initiating a websocket connection,
    and scripts cannot omit or forge it,
    so requests without one are never cross-site requests from a browser.
    """
    pol = (policy or "auto").strip().lower()
    if pol in ORIGIN_ANY:
        return True
    if not origin:
        return True
    if pol in ORIGIN_NONE:
        return False
    parsed = parse_origin(origin)
    if not parsed[1]:
        # unparsable, ie: `null` from a sandboxed iframe or a `file://` page
        return False
    if pol == "auto":
        return same_origin(origin, host)
    return parsed in tuple(parse_origin(x) for x in pol.split(",") if x.strip())


def http_response(content, content_type: str = "text/plain") -> HttpResponse:
    if not content:
        return 404, {}, b""
    if isinstance(content, str):
        content = content.encode("latin1")
    return 200, {
        "Content-type": content_type,
        "Content-Length": len(content),
    }, content


def http_status_request(_uri: str, _post_data: bytes) -> HttpResponse:
    return http_response("ready")


def json_response(data) -> HttpResponse:
    import json  # pylint: disable=import-outside-toplevel
    return http_response(json.dumps(data), "application/json")
