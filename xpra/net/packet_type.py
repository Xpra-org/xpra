#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.net.common import BACKWARDS_COMPATIBLE

# every packet type that was renamed, as `(legacy, modern, sender)`,
# the `sender` is only specified when the legacy name is ambiguous:
LEGACY_PACKET_TYPES: list[tuple[str, str, str]] = []


def compat(legacy: str, modern: str, sender="") -> str:
    """
    Records the renamed packet type and returns the name to use:
    the `legacy` one when we are backwards compatible,
    the protocol layer upgrades it for the peers that use the modern names
    (see `get_packet_type_upgrades`).
    """
    LEGACY_PACKET_TYPES.append((legacy, modern, sender))
    return legacy if BACKWARDS_COMPATIBLE else modern


# server to client:
WINDOW_CREATE: Final[str] = compat("new-window", "window-create")
WINDOW_RAISE = compat("raise-window", "window-raise")
WINDOW_RESTACK: Final[str] = compat("restack-window", "window-restack")
WINDOW_INITIATE_MOVERESIZE: Final[str] = compat("initiate-moveresize", "window-initiate-moveresize")
WINDOW_MOVE_RESIZE: Final[str] = "window-move-resize"
WINDOW_RESIZED: Final[str] = "window-resized"
WINDOW_METADATA: Final[str] = "window-metadata"
WINDOW_DESTROY: Final[str] = compat("lost-window", "window-destroy")
WINDOW_ICON: Final[str] = "window-icon"
WINDOW_DRAW: Final[str] = compat("draw", "window-draw")
WINDOW_EOS: Final[str] = compat("eos", "window-eos")
# a grab belongs to the window holding it: the packets carry a `wid`,
# the server sends them from its `window` source and the client tracks
# the grab as window state (cleared on focus change and on destroy)
WINDOW_GRAB: Final[str] = compat("pointer-grab", "window-grab")
WINDOW_UNGRAB: Final[str] = compat("pointer-ungrab", "window-ungrab")

# client to server:
WINDOW_MAP: Final[str] = compat("map-window", "window-map")
WINDOW_UNMAP: Final[str] = compat("unmap-window", "window-unmap")
WINDOW_CONFIGURE: Final[str] = "window-configure"
WINDOW_CLOSE: Final[str] = compat("close-window", "window-close")
WINDOW_DISMISS: Final[str] = "window-dismiss"
WINDOW_FOCUS: Final[str] = compat("focus", "window-focus")
WINDOW_ACTION: Final[str] = "window-action"
WINDOW_STACKING: Final[str] = "window-stacking"
WINDOW_REFRESH: Final[str] = compat("buffer-refresh", "window-refresh")
# the legacy ack packet: `packet_sequence` first and an optional `message`,
# the modern equivalent is `window-ack`, which starts with the `wid`:
WINDOW_DRAW_ACK: Final[str] = compat("damage-sequence", "window-draw-ack")
WINDOW_ACK: Final[str] = "window-ack"
WINDOW_BELL: Final[str] = compat("bell", "window-bell")

KEYBOARD_EVENT: Final[str] = "keyboard-event"
KEYBOARD_CONFIG: Final[str] = "keyboard-config"
KEYBOARD_SYNC: Final[str] = compat("set-keyboard-sync-enabled", "keyboard-sync")
KEYBOARD_RECORD: Final[str] = "keyboard-record"

POINTER_MOTION: Final[str] = compat("pointer", "pointer-motion")
POINTER_BUTTON: Final[str] = "pointer-button"
POINTER_WHEEL: Final[str] = compat("wheel-motion", "pointer-wheel")
POINTER_DEVICES: Final[str] = compat("input-devices", "pointer-devices")

LOGGING_EVENT: Final[str] = compat("logging", "logging-event")
LOGGING_CONTROL: Final[str] = "logging-control"

PRINT_DEVICES: Final[str] = compat("printers", "printer-devices")
PRINT_FILE: Final[str] = compat("print-file", "printer-file")

FILE_SEND: Final[str] = compat("send-file", "file-send")
FILE_ACK_CHUNK: Final[str] = compat("ack-file-chunk", "file-ack-chunk")
FILE_SEND_CHUNK: Final[str] = compat("send-file-chunk", "file-send-chunk")
FILE_DATA_REQUEST: Final[str] = compat("send-data-request", "file-data-request")
FILE_DATA_RESPONSE: Final[str] = compat("send-data-response", "file-data-response")
FILE_REQUEST: Final[str] = compat("request-file", "file-request")
FILE_OPEN_URL: Final[str] = compat("open-url", "file-open-url")

EVENTS: Final[str] = compat("server-event", "events")

# the server's encoding capabilities, sent once the codecs have been initialized
# (see `EncodingsConnection.threaded_init_complete`)
ENCODING_SET: Final[str] = compat("encodings", "encoding-set")

CURSOR_SET: Final[str] = compat("set-cursors", "cursor-set")
CURSOR_DATA: Final[str] = "cursor-data"
CURSOR_DEFAULT: Final[str] = "cursor-default"

COMMAND_SIGNAL: Final[str] = "command-signal"
COMMAND_START: Final[str] = compat("start-command", "command-start")

DISPLAY_CONFIGURE: Final[str] = compat("configure-display", "display-configure")
DISPLAY_MONITOR_CONFIGURE: Final[str] = compat("configure-monitor", "display-monitor-configure")
DISPLAY_UNGRAB: Final[str] = compat("force-ungrab", "display-ungrab")
DISPLAY_RESIZED: Final[str] = compat("desktop_size", "display-resized")
DISPLAY_REQUEST_SCREENSHOT: Final[str] = compat("screenshot", "display-request-screenshot", "client")
DISPLAY_REQUEST_ICON: Final[str] = "display-request-icon"
DISPLAY_SCREENSHOT: Final[str] = compat("screenshot", "display-screenshot", "server")
DISPLAY_ICON: Final[str] = "display-icon"
DISPLAY_SHOW_DESKTOP: Final[str] = compat("show-desktop", "display-show-desktop")

NOTIFICATION_SHOW: Final[str] = compat("notify_show", "notification-show")
NOTIFICATION_CLOSE: Final[str] = compat("notify_close", "notification-close")
NOTIFICATION_STATUS: Final[str] = compat("set-notify", "notification-status")

BELL_SET: Final[str] = compat("set-bell", "bell-set")

SHARING_TOGGLE: Final[str] = "sharing-toggle"
SHARING_LOCK: Final[str] = compat("lock-toggle", "sharing-lock")

INFO_REQUEST: Final[str] = "info-request"
INFO_RESPONSE: Final[str] = "info-response"

CHALLENGE: Final[str] = "challenge"

CONNECTION_CLOSE: Final[str] = compat("disconnect", "connection-close")
CONNECTION_LOST: Final[str] = "connection-lost"
GIBBERISH: Final[str] = "gibberish"
INVALID: Final[str] = "invalid"

PING_ECHO: Final[str] = compat("ping_echo", "ping-echo")

SHUTDOWN_SERVER: Final[str] = "shutdown-server"
EXIT_SERVER: Final[str] = "exit-server"


# legacy names which are not exposed as constants,
# but which are still sent when we are backwards compatible:
LEGACY_PACKET_TYPES += [
    ("command_request", "control-request", ""),
    ("set-clipboard-enabled", "clipboard-status", ""),
    ("encoding", "encoding-set", "client"),
    ("configure-override-redirect", "window-move-resize", "server"),
    ("new-override-redirect", "window-create", "server"),
    ("sound-data", "audio-data", ""),
    ("sound-control", "audio-control", ""),
]


def get_packet_type_upgrades(server: bool) -> dict[str, str]:
    """
    The renames to apply to the packets we send to a peer that uses the modern names.
    """
    sender = "server" if server else "client"
    return {legacy: modern for legacy, modern, s in LEGACY_PACKET_TYPES if s in ("", sender)}


def get_legacy_packet_types(modern: str) -> tuple[str, ...]:
    """
    The legacy names that a modern packet type replaces,
    used for looking up the handlers we have registered using a legacy name.
    """
    return tuple(legacy for legacy, m, _ in LEGACY_PACKET_TYPES if m == modern)
