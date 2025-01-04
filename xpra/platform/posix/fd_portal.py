#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from enum import IntEnum
from collections.abc import Callable

from xpra.dbus.common import loop_init, init_session_bus
from xpra.log import Logger

log = Logger("shadow")

BASE_REQUEST_PATH = "/org/freedesktop/portal/desktop/request"
PORTAL_REQUEST = "org.freedesktop.portal.Request"
PORTAL_SESSION_INTERFACE = "org.freedesktop.portal.Session"
PORTAL_DESKTOP_INTERFACE = "org.freedesktop.portal.Desktop"
PORTAL_DESKTOP_PATH = "/org/freedesktop/portal/desktop"
REMOTEDESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"

loop_init()
bus = init_session_bus()


class AvailableDeviceTypes(IntEnum):
    KEYBOARD = 1
    POINTER = 2
    TOUCHSCREEN = 4


class AvailableSourceTypes(IntEnum):
    MONITOR = 1
    WINDOW = 2
    VIRTUAL = 4


dbus_sender_name: str = (bus.get_unique_name()[1:]).replace(".", "_")
request_counter: int = 0


def screenscast_dbus_call(method, callback: Callable, *args, options=None) -> None:
    dbus_desktop_call(SCREENCAST_IFACE, method, callback, *args, options=options)


def remotedesktop_dbus_call(method, callback: Callable, *args, options=None) -> None:
    dbus_desktop_call(REMOTEDESKTOP_IFACE, method, callback, *args, options=options)


def dbus_desktop_call(interface: str, method, callback: Callable, *args, options=None) -> None:
    # generate a new token and path:
    options = options or {}
    global request_counter
    request_counter += 1
    request_token = f"u{request_counter}"
    request_path = f"{BASE_REQUEST_PATH}/{dbus_sender_name}/{request_token}"
    log(f"adding dbus signal receiver {callback}")
    bus.add_signal_receiver(callback,
                            "Response",
                            PORTAL_REQUEST,
                            PORTAL_DESKTOP_INTERFACE,
                            request_path)
    options["handle_token"] = request_token
    log(f"calling {method} with args={args}, options={options}")
    method(*(args + (options,)), dbus_interface=interface)


def get_portal_interface():
    return bus.get_object(PORTAL_DESKTOP_INTERFACE, PORTAL_DESKTOP_PATH)


def get_session_interface(session_path: str):
    return bus.get_object(PORTAL_DESKTOP_INTERFACE, session_path)
