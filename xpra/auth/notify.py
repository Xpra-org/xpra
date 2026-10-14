# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Asks the current user(s) of the session to allow or deny the connection.
The request is shown using a platform specific backend:
* MS Windows: a balloon notification on the system tray icon, which opens a confirmation dialog when clicked
* other platforms: a dbus notification with "Allow" and "Deny" actions
"""

import threading
from collections.abc import Callable

from xpra.os_util import gi_import, WIN32
from xpra.util.objects import typedict
from xpra.util.str_fn import std
from xpra.util.thread import is_main_thread
from xpra.auth.sys_auth_base import SysAuthenticator, log

GLib = gi_import("GLib")

TIMEOUT = 30


def make_request(summary: str, body: str, timeout: int, callback: Callable[[bool], None]):
    if WIN32:
        from xpra.platform.win32.auth_request import TrayRequest
        return TrayRequest(summary, body, timeout, callback)
    from xpra.dbus.auth_request import DBusRequest
    return DBusRequest(summary, body, timeout, callback)


class Authenticator(SysAuthenticator):

    __slots__ = ("connection_str", "event", "request", "result", "timeout")

    def __init__(self, **kwargs):
        log(f"notify.Authenticator({kwargs})")
        self.timeout = int(kwargs.pop("timeout", TIMEOUT))
        connection = kwargs.get("connection")
        if not connection:
            raise ValueError("connection object is missing")
        self.connection_str = str(connection)
        super().__init__(**kwargs)
        self.event = threading.Event()
        self.result = False
        self.request = None

    def requires_challenge(self) -> bool:
        return False

    def validate_caps(self, caps: typedict) -> bool:
        return True

    def default_authenticate_check(self, caps: typedict) -> bool:
        if is_main_thread():
            log.error("Error: notify authentication cannot run from the main thread")
            return False
        self.event.clear()
        self.result = False
        GLib.idle_add(self.show_request)
        if not self.event.wait(self.timeout):
            log.info("notify authentication request timed out after %i seconds", self.timeout)
            GLib.idle_add(self.close_request)
            return False
        log("notify authentication result=%s", self.result)
        return self.result

    def show_request(self) -> None:
        summary = "Connection request"
        body = f"from {self.connection_str}"
        if self.username:
            body += f"\nas user {std(self.username)!r}"
        try:
            self.request = make_request(summary, body, self.timeout, self.answer)
        except Exception as e:
            log("make_request%s", (summary, body, self.timeout, self.answer), exc_info=True)
            log.error("Error: notify authentication cannot request access")
            log.estr(e)
            self.event.set()
            return
        log("show_request() request=%s", self.request)

    def answer(self, result: bool) -> None:
        log("answer(%s) request=%s", result, self.request)
        if not self.request:
            # closed already
            return
        self.result = result
        self.event.set()
        GLib.idle_add(self.close_request)

    def close_request(self) -> None:
        request = self.request
        log("close_request() request=%s", request)
        if request:
            self.request = None
            request.close()

    def cleanup(self) -> None:
        if is_main_thread():
            self.close_request()
        else:
            GLib.idle_add(self.close_request)

    def __repr__(self):
        return "notify"
