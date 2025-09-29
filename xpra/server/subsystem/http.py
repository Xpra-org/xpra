# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from urllib.parse import unquote

from xpra.net.http.common import http_response, http_status_request, json_response
from xpra.util.str_fn import Ellipsizer
from xpra.util.io import load_binary_file
from xpra.util.parsing import FALSE_OPTIONS
from xpra.net.common import HttpResponse
from xpra.platform.paths import get_icon_filename
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("http")


def invalid_path(uri: str) -> HttpResponse:
    log(f"invalid request path {uri!r}")
    return 404, {}, b""


def http_icon_response(icon_type: str, icon_data: bytes) -> HttpResponse:
    log("http_icon_response%s", (icon_type, Ellipsizer(icon_data)))
    if not icon_data:
        icon_filename = get_icon_filename("noicon.png")
        icon_data = load_binary_file(icon_filename)
        icon_type = "png"
        log("using fallback transparent icon")
    if icon_type == "svg" and icon_data:
        from xpra.codecs.icon_util import svg_to_png  # pylint: disable=import-outside-toplevel
        # call svg_to_png via the main thread,
        # and wait for it to complete via an Event:
        icon: list[tuple[bytes, str]] = [(icon_data, icon_type)]
        from threading import Event
        event = Event()

        def convert() -> None:
            icon[0] = svg_to_png("", icon_data, 48, 48), "png"
            event.set()

        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        GLib.idle_add(convert)
        event.wait()
        icon_data, icon_type = icon[0]
    if icon_type in ("png", "jpeg", "svg", "webp"):
        mime_type = "image/" + icon_type
    else:
        mime_type = "application/octet-stream"
    return http_response(icon_data, mime_type)


def _filter_display_dict(display_dict: dict[str, Any], *whitelist: str) -> dict[str, Any]:
    displays_info = {}
    for display, info in display_dict.items():
        displays_info[display] = {k: v for k, v in info.items() if k in whitelist}
    log("_filter_display_dict(%s)=%s", display_dict, displays_info)
    return displays_info


class HttpServer(StubServerMixin):
    """
    Mixin for servers that can handle http requests
    """
    PREFIX = "http"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.menu_provider = None
        self._http_scripts = {}

    def init(self, opts) -> None:
        http_scripts = opts.http_scripts
        if http_scripts.lower() in FALSE_OPTIONS:
            return
        script_options: dict[str, Callable[[str, bytes], HttpResponse]] = {
            "/Status": http_status_request,
            "/Info": self.http_info_request,
            "/Sessions": self.http_sessions_request,
            "/Displays": self.http_displays_request,
        }
        if self.menu_provider:
            # we have menu data we can expose:
            script_options |= {
                "/Menu": self.http_menu_request,
                "/MenuIcon": self.http_menu_icon_request,
                "/DesktopMenu": self.http_desktop_menu_request,
                "/DesktopMenuIcon": self.http_desktop_menu_icon_request,
            }
        if http_scripts.lower() in ("all", "*"):
            self._http_scripts = script_options
        else:
            for script in http_scripts.split(","):
                if not script.startswith("/"):
                    script = "/" + script
                handler = script_options.get(script)
                if not handler:
                    log.warn(f"Warning: unknown script {script!r}")
                else:
                    self._http_scripts[script] = handler
        log("init_http_scripts(%s)=%s", http_scripts, self._http_scripts)

    def cleanup(self) -> None:
        self._http_scripts = {}

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            HttpServer.PREFIX: {"scripts": tuple(self._http_scripts.keys())},
        }

    def http_menu_request(self, _uri: str, _post_data: bytes) -> HttpResponse:
        menu = self.menu_provider.get_menu_data(remove_icons=True)
        return json_response(menu or "not available")

    def http_desktop_menu_request(self, _uri: str, _post_data: bytes) -> HttpResponse:
        xsessions = self.menu_provider.get_desktop_sessions(remove_icons=True)
        return json_response(xsessions or "not available")

    def http_menu_icon_request(self, uri: str, _post_data: bytes) -> HttpResponse:
        parts = unquote(uri).split("/MenuIcon/", 1)
        # ie: "/menu-icon/a/b" -> ['', 'a/b']
        if len(parts) < 2:
            return invalid_path(uri)
        path = parts[1].split("/")
        # ie: "a/b" -> ['a', 'b']
        category_name = path[0]
        if len(path) < 2:
            # only the category is present
            app_name = ""
        else:
            app_name = path[1]
        log("http_menu_icon_request: category_name=%s, app_name=%s", category_name, app_name)
        icon_type, icon_data = self.menu_provider.get_menu_icon(category_name, app_name)
        return http_icon_response(icon_type, icon_data)

    def http_desktop_menu_icon_request(self, uri: str, _post_data: bytes) -> HttpResponse:
        parts = unquote(uri).split("/DesktopMenuIcon/", 1)
        # ie: "/menu-icon/wmname" -> ['', 'sessionname']
        if len(parts) < 2:
            return invalid_path(uri)
        # in case the sessionname is followed by a slash:
        sessionname = parts[1].split("/")[0]
        log(f"http_desktop_menu_icon_request: {sessionname=}")
        icon_type, icon_data = self.menu_provider.get_desktop_menu_icon(sessionname)
        return http_icon_response(icon_type, icon_data)

    def http_displays_request(self, _uri: str, _post_data: bytes) -> HttpResponse:
        displays = self.get_displays()
        displays_info = _filter_display_dict(displays, "state", "wmname", "xpra-server-mode")
        return json_response(displays_info)

    def get_displays(self) -> dict[str, Any]:
        from xpra.scripts.main import get_displays_info  # pylint: disable=import-outside-toplevel
        return get_displays_info(self.dotxpra)

    def http_sessions_request(self, _uri, _post_data: bytes) -> HttpResponse:
        sessions = self.get_xpra_sessions()
        sessions_info = _filter_display_dict(sessions, "state", "username", "session-type", "session-name", "uuid")
        return json_response(sessions_info)

    def get_xpra_sessions(self) -> dict[str, Any]:
        from xpra.scripts.main import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.dotxpra)

    def http_info_request(self, _uri: str, _post_data: bytes) -> HttpResponse:
        return json_response(self.get_http_info())

    def get_http_info(self) -> dict[str, Any]:
        return {
            "mode": self.session_type,
            "type": "Python",
            "uuid": self.uuid,
        }
