# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import HttpResponse

EXTENSION_TO_MIMETYPE: dict[str, str] = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".css": "text/css",
}


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
