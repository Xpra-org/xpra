#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

# server to client:
WINDOW_CREATE: Final[str] = "window-create"
WINDOW_RAISE = "window-raise"
WINDOW_RESTACK: Final[str] = "window-restack"
WINDOW_INITIATE_MOVERESIZE: Final[str] = "window-initiate-moveresize"
WINDOW_MOVE_RESIZE: Final[str] = "window-move-resize"
WINDOW_RESIZED: Final[str] = "window-resized"
WINDOW_METADATA: Final[str] = "window-metadata"
WINDOW_DESTROY: Final[str] = "window-destroy"
WINDOW_ICON: Final[str] = "window-icon"
WINDOW_DRAW: Final[str] = "window-draw"
WINDOW_EOS: Final[str] = "window-eos"
# a grab belongs to the window holding it: the packets carry a `wid`,
# the server sends them from its `window` source and the client tracks
# the grab as window state (cleared on focus change and on destroy)
WINDOW_GRAB: Final[str] = "window-grab"
WINDOW_UNGRAB: Final[str] = "window-ungrab"

# client to server:
WINDOW_MAP: Final[str] = "window-map"
WINDOW_UNMAP: Final[str] = "window-unmap"
WINDOW_CONFIGURE: Final[str] = "window-configure"
WINDOW_CLOSE: Final[str] = "window-close"
WINDOW_FOCUS: Final[str] = "window-focus"
WINDOW_ACTION: Final[str] = "window-action"
WINDOW_STACKING: Final[str] = "window-stacking"
WINDOW_REFRESH: Final[str] = "window-refresh"
WINDOW_ACK: Final[str] = "window-ack"
WINDOW_BELL: Final[str] = "window-bell"

KEYBOARD_EVENT: Final[str] = "keyboard-event"
KEYBOARD_CONFIG: Final[str] = "keyboard-config"
KEYBOARD_SYNC: Final[str] = "keyboard-sync"
KEYBOARD_RECORD: Final[str] = "keyboard-record"

POINTER_MOTION: Final[str] = "pointer-motion"
POINTER_BUTTON: Final[str] = "pointer-button"
POINTER_WHEEL: Final[str] = "pointer-wheel"
POINTER_DEVICES: Final[str] = "pointer-devices"

LOGGING_EVENT: Final[str] = "logging-event"
LOGGING_CONTROL: Final[str] = "logging-control"

PRINT_DEVICES: Final[str] = "printer-devices"

FILE_SEND: Final[str] = "file-send"
FILE_ACK_CHUNK: Final[str] = "file-ack-chunk"
FILE_SEND_CHUNK: Final[str] = "file-send-chunk"
FILE_DATA_REQUEST: Final[str] = "file-data-request"
FILE_DATA_RESPONSE: Final[str] = "file-data-response"
FILE_REQUEST: Final[str] = "file-request"
FILE_OPEN_URL: Final[str] = "file-open-url"

EVENTS: Final[str] = "events"

# the server's encoding capabilities, sent once the codecs have been initialized
# (see `EncodingsConnection.threaded_init_complete`)
ENCODING_SET: Final[str] = "encoding-set"

CURSOR_SET: Final[str] = "cursor-set"
CURSOR_DATA: Final[str] = "cursor-data"
CURSOR_DEFAULT: Final[str] = "cursor-default"

COMMAND_SIGNAL: Final[str] = "command-signal"
COMMAND_START: Final[str] = "command-start"

DISPLAY_CONFIGURE: Final[str] = "display-configure"
DISPLAY_MONITOR_CONFIGURE: Final[str] = "display-monitor-configure"
DISPLAY_UNGRAB: Final[str] = "display-ungrab"
DISPLAY_RESIZED: Final[str] = "display-resized"
DISPLAY_REQUEST_SCREENSHOT: Final[str] = "display-request-screenshot"
DISPLAY_REQUEST_ICON: Final[str] = "display-request-icon"
DISPLAY_SCREENSHOT: Final[str] = "display-screenshot"
DISPLAY_ICON: Final[str] = "display-icon"
DISPLAY_SHOW_DESKTOP: Final[str] = "display-show-desktop"

NOTIFICATION_SHOW: Final[str] = "notification-show"
NOTIFICATION_CLOSE: Final[str] = "notification-close"
NOTIFICATION_STATUS: Final[str] = "notification-status"

BELL_SET: Final[str] = "bell-set"

SHARING_TOGGLE: Final[str] = "sharing-toggle"
SHARING_LOCK: Final[str] = "sharing-lock"

INFO_REQUEST: Final[str] = "info-request"
INFO_RESPONSE: Final[str] = "info-response"

CHALLENGE: Final[str] = "challenge"

CONNECTION_CLOSE: Final[str] = "connection-close"
CONNECTION_LOST: Final[str] = "connection-lost"
GIBBERISH: Final[str] = "gibberish"
INVALID: Final[str] = "invalid"

PING_ECHO: Final[str] = "ping-echo"

SHUTDOWN_SERVER: Final[str] = "shutdown-server"
