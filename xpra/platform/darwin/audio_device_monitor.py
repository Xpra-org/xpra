# This file is part of Xpra.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Watch the CoreAudio default output using the long-standing AudioObject API."""

import ctypes
from threading import Event

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")
log = Logger("audio")


def fourcc(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), "big")


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = (("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32))


# CoreAudio AudioHardware.h: system object, default output, global scope, main element.
SYSTEM_OBJECT = 1
DEFAULT_OUTPUT = AudioObjectPropertyAddress(fourcc("dOut"), fourcc("glob"), 0)
LISTENER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.POINTER(AudioObjectPropertyAddress), ctypes.c_void_p)


class AudioDeviceMonitor:
    POLL_INTERVAL_MS = 100
    _pending_removal = None

    @classmethod
    def reusable(cls):
        return cls._pending_removal or cls()

    def __init__(self):
        self.coreaudio = None
        self.listener = None
        self.timer = 0
        self.changed = Event()
        self.device_id = None
        self.on_change = noop

    def get_default_output(self) -> int | None:
        device = ctypes.c_uint32()
        size = ctypes.c_uint32(ctypes.sizeof(device))
        status = self.coreaudio.AudioObjectGetPropertyData(
            SYSTEM_OBJECT, ctypes.byref(DEFAULT_OUTPUT), 0, None,
            ctypes.byref(size), ctypes.byref(device))
        if status:
            log("AudioObjectGetPropertyData failed: %s", status)
            return None
        return device.value

    def start(self, on_change) -> None:
        if self.listener:
            # A failed unregister left the listener registered; do not add another one.
            self.changed.clear()
            self.device_id = self.get_default_output()
            self.on_change = on_change
            if not self.timer:
                self.timer = GLib.timeout_add(self.POLL_INTERVAL_MS, self.poll)
            self.changed.set()
            return
        self.coreaudio = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        coreaudio = self.coreaudio
        coreaudio.AudioObjectGetPropertyData.argtypes = (
            ctypes.c_uint32, ctypes.POINTER(AudioObjectPropertyAddress), ctypes.c_uint32,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p)
        coreaudio.AudioObjectGetPropertyData.restype = ctypes.c_int32
        coreaudio.AudioObjectAddPropertyListener.argtypes = (
            ctypes.c_uint32, ctypes.POINTER(AudioObjectPropertyAddress), LISTENER, ctypes.c_void_p)
        coreaudio.AudioObjectAddPropertyListener.restype = ctypes.c_int32
        coreaudio.AudioObjectRemovePropertyListener.argtypes = coreaudio.AudioObjectAddPropertyListener.argtypes
        coreaudio.AudioObjectRemovePropertyListener.restype = ctypes.c_int32
        self.device_id = self.get_default_output()
        self.on_change = on_change

        @LISTENER
        def notify(_object_id, _count, _addresses, _client_data):
            self.changed.set()
            return 0

        status = coreaudio.AudioObjectAddPropertyListener(
            SYSTEM_OBJECT, ctypes.byref(DEFAULT_OUTPUT), notify, None)
        if status:
            self.on_change = noop
            raise OSError("AudioObjectAddPropertyListener failed: %s" % status)
        self.listener = notify
        self.timer = GLib.timeout_add(self.POLL_INTERVAL_MS, self.poll)
        log("CoreAudio default output monitor started: device=%s", self.device_id)
        # Close the race between reading the initial ID and registering the listener.
        self.changed.set()

    def poll(self) -> bool:
        if not self.listener:
            return False
        if self.changed.is_set():
            self.changed.clear()
            device_id = self.get_default_output()
            if device_id is None:
                self.changed.set()
            elif self.device_id is None:
                self.device_id = device_id
            elif device_id != self.device_id:
                log.info("CoreAudio default output changed: %s -> %s", self.device_id, device_id)
                self.device_id = device_id
                self.on_change()
        return True

    def stop(self) -> bool:
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.on_change = noop
        self.changed.clear()
        if self.listener:
            try:
                status = self.coreaudio.AudioObjectRemovePropertyListener(
                    SYSTEM_OBJECT, ctypes.byref(DEFAULT_OUTPUT), self.listener, None)
            except Exception:
                log.warn("Warning: AudioObjectRemovePropertyListener failed; retaining callback", exc_info=True)
                type(self)._pending_removal = self
                return False
            if status:
                log.warn("Warning: AudioObjectRemovePropertyListener failed: %s; retaining callback", status)
                type(self)._pending_removal = self
                return False
            self.listener = None
            log("CoreAudio default output monitor stopped")
        if type(self)._pending_removal is self:
            type(self)._pending_removal = None
        return True
