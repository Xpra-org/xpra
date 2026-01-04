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
WINDOW_MOVE_RESIZE = "window-move-resize"
WINDOW_RESIZED = "window-resized"
WINDOW_METADATA = "window-metadata"
WINDOW_DESTROY = "lost-window" if BACKWARDS_COMPATIBLE else "window-destroy"
WINDOW_ICON = "window-icon"
WINDOW_DRAW = "draw" if BACKWARDS_COMPATIBLE else "window-draw"

# client to server:
WINDOW_MAP = "map-window" if BACKWARDS_COMPATIBLE else "window-map"
WINDOW_UNMAP = "unmap-window" if BACKWARDS_COMPATIBLE else "window-unmap"
WINDOW_CONFIGURE = "configure-window" if BACKWARDS_COMPATIBLE else "window-configure"
WINDOW_CLOSE = "close-window" if BACKWARDS_COMPATIBLE else "window-close"
WINDOW_FOCUS = "focus" if BACKWARDS_COMPATIBLE else "window-focus"
WINDOW_ACTION = "window-action"
WINDOW_REFRESH = "buffer-refresh" if BACKWARDS_COMPATIBLE else "window-refresh"
WINDOW_DRAW_ACK = "damage-sequence" if BACKWARDS_COMPATIBLE else "window-draw-ack"

KEYBOARD_EVENT = "keyboard-event"
KEYBOARD_CONFIG = "keyboard-config"
KEYBOARD_SYNC = "set-keyboard-sync-enabled" if BACKWARDS_COMPATIBLE else "keyboard-sync"

POINTER_MOTION = "pointer" if BACKWARDS_COMPATIBLE else "pointer-motion"
POINTER_BUTTON = "pointer-button"
POINTER_WHEEL = "wheel-motion" if BACKWARDS_COMPATIBLE else "pointer-wheel"

LOGGING_EVENT = "logging" if BACKWARDS_COMPATIBLE else "logging-event"
LOGGING_CONTROL = "logging-control"

PRINT_DEVICES = "printers" if BACKWARDS_COMPATIBLE else "print-devices"
PRINT_FILE = "print-file"

FILE_SEND = "file-send"
FILE_ACK_CHUNK = "file-ack-chunk"
FILE_SEND_CHUNK = "file-send-chunk"
FILE_DATA_REQUEST = "file-data-request"
FILE_DATA_RESPONSE = "file-data-response"
FILE_REQUEST = "file-request"

CURSOR_SET = "set-cursors" if BACKWARDS_COMPATIBLE else "cursor-set"

COMMAND_SIGNAL = "command-signal"
COMMAND_START = "start-command" if BACKWARDS_COMPATIBLE else "command-start"
