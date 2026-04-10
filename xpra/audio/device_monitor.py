# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Audio output device change monitor for the audio subprocess.
# ABOUTME: Win32 uses IMMNotificationClient via pure ctypes; no-op on other platforms.

from xpra.os_util import WIN32, gi_import
from xpra.log import Logger

log = Logger("audio")

GLib = gi_import("GLib")


def start_device_monitor(on_change) -> None:
    """Start monitoring for audio device changes. Calls on_change() on the
    GLib main loop when the default output endpoint changes.
    No-op on non-Win32 platforms (PulseAudio/CoreAudio handle routing)."""
    if not WIN32:
        return
    try:
        from xpra.platform.win32.audio_device_monitor import start as _start
        _start(on_change)
    except Exception:
        log("start_device_monitor()", exc_info=True)
        log.warn("Warning: audio device change monitoring unavailable")


def stop_device_monitor() -> None:
    if not WIN32:
        return
    try:
        from xpra.platform.win32.audio_device_monitor import stop as _stop
        _stop()
    except Exception:
        log("stop_device_monitor()", exc_info=True)
