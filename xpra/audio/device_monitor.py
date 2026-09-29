# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Audio output device change monitor for the audio subprocess.
# ABOUTME: Win32 uses IMMNotificationClient, MacOS uses CoreAudio, both via pure ctypes; no-op on other platforms.

from xpra.os_util import WIN32, OSX
from xpra.log import Logger

log = Logger("audio")


class AudioDeviceMonitor:
    """
    Monitor the default audio output device.
    Calls on_change() on the GLib main loop when it changes.
    No-op on other platforms (PulseAudio / PipeWire handle routing).
    """

    def __init__(self):
        self.monitor = None

    def start(self, on_change) -> bool:
        try:
            if OSX:
                from xpra.platform.darwin.audio_device_monitor import AudioDeviceMonitor as Monitor
                self.monitor = Monitor.reusable()
                self.monitor.start(on_change)
                return True
            if WIN32:
                from xpra.platform.win32 import audio_device_monitor
                audio_device_monitor.start(on_change)
                self.monitor = audio_device_monitor
                return True
        except Exception:
            log("AudioDeviceMonitor.start(%s)", on_change, exc_info=True)
            log.warn("Warning: audio output device monitoring unavailable")
            self.stop()
        return False

    def stop(self) -> bool:
        monitor = self.monitor
        if monitor:
            try:
                result = monitor.stop()
            except Exception:
                log("audio device monitor cleanup failed", exc_info=True)
                return False
            if result is False:
                return False
            self.monitor = None
        return True
