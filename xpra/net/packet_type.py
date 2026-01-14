#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.common import BACKWARDS_COMPATIBLE

# server to client:
WINDOW_CREATE: Final[str] = "new-window" if BACKWARDS_COMPATIBLE else "window-create"
WINDOW_RAISE = "raise-window" if BACKWARDS_COMPATIBLE else "window-raise"
WINDOW_RESTACK: Final[str] = "restack-window" if BACKWARDS_COMPATIBLE else "window-restack"
WINDOW_INITIATE_MOVERESIZE: Final[str] = "initiate-moveresize" if BACKWARDS_COMPATIBLE else "window-initiate-moveresize"
WINDOW_MOVE_RESIZE: Final[str] = "window-move-resize"
WINDOW_RESIZED: Final[str] = "window-resized"
WINDOW_METADATA: Final[str] = "window-metadata"
WINDOW_DESTROY: Final[str] = "lost-window" if BACKWARDS_COMPATIBLE else "window-destroy"
WINDOW_ICON: Final[str] = "window-icon"
WINDOW_DRAW: Final[str] = "draw" if BACKWARDS_COMPATIBLE else "window-draw"

# client to server:
WINDOW_MAP: Final[str] = "map-window" if BACKWARDS_COMPATIBLE else "window-map"
WINDOW_UNMAP: Final[str] = "unmap-window" if BACKWARDS_COMPATIBLE else "window-unmap"
WINDOW_CONFIGURE: Final[str] = "window-configure"
WINDOW_CLOSE: Final[str] = "close-window" if BACKWARDS_COMPATIBLE else "window-close"
WINDOW_FOCUS: Final[str] = "focus" if BACKWARDS_COMPATIBLE else "window-focus"
WINDOW_ACTION: Final[str] = "window-action"
WINDOW_REFRESH: Final[str] = "buffer-refresh" if BACKWARDS_COMPATIBLE else "window-refresh"
WINDOW_DRAW_ACK: Final[str] = "damage-sequence" if BACKWARDS_COMPATIBLE else "window-draw-ack"

KEYBOARD_EVENT: Final[str] = "keyboard-event"
KEYBOARD_CONFIG: Final[str] = "keyboard-config"
KEYBOARD_SYNC: Final[str] = "set-keyboard-sync-enabled" if BACKWARDS_COMPATIBLE else "keyboard-sync"

POINTER_MOTION: Final[str] = "pointer" if BACKWARDS_COMPATIBLE else "pointer-motion"
POINTER_BUTTON: Final[str] = "pointer-button"
POINTER_WHEEL: Final[str] = "wheel-motion" if BACKWARDS_COMPATIBLE else "pointer-wheel"

LOGGING_EVENT: Final[str] = "logging" if BACKWARDS_COMPATIBLE else "logging-event"
LOGGING_CONTROL: Final[str] = "logging-control"

PRINT_DEVICES: Final[str] = "printers" if BACKWARDS_COMPATIBLE else "print-devices"
PRINT_FILE: Final[str] = "print-file"

FILE_SEND: Final[str] = "file-send"
FILE_ACK_CHUNK: Final[str] = "file-ack-chunk"
FILE_SEND_CHUNK: Final[str] = "file-send-chunk"
FILE_DATA_REQUEST: Final[str] = "file-data-request"
FILE_DATA_RESPONSE: Final[str] = "file-data-response"
FILE_REQUEST: Final[str] = "file-request"

CURSOR_SET: Final[str] = "set-cursors" if BACKWARDS_COMPATIBLE else "cursor-set"
CURSOR_DATA: Final[str] = "cursor-data"
CURSOR_DEFAULT: Final[str] = "cursor-default"

COMMAND_SIGNAL: Final[str] = "command-signal"
COMMAND_START: Final[str] = "start-command" if BACKWARDS_COMPATIBLE else "command-start"

DISPLAY_CONFIGURE: Final[str] = "configure-display" if BACKWARDS_COMPATIBLE else "display-configure"
DISPLAY_REQUEST_SCREENSHOT: Final[str] = "screenshot" if BACKWARDS_COMPATIBLE else "display-request-screenshot"
DISPLAY_SCREENSHOT: Final[str] = "screenshot" if BACKWARDS_COMPATIBLE else "display-screenshot"

INFO_REQUEST: Final[str] = "info-request"
INFO_RESPONSE: Final[str] = "info-response"

CHALLENGE: Final[str] = "challenge"

CONNECTION_CLOSE: Final[str] = "disconnect" if BACKWARDS_COMPATIBLE else "connection-close"
CONNECTION_LOST: Final[str] = "connection-lost"
GIBBERISH: Final[str] = "gibberish"
INVALID: Final[str] = "invalid"
