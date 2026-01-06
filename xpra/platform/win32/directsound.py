# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import uuid
from ctypes import WinDLL, WINFUNCTYPE, POINTER, HRESULT, oledll, c_int
from ctypes.wintypes import BOOL, BYTE, LPVOID, LPCWSTR, LPOLESTR

from xpra.platform.win32.common import GUID

dsound = WinDLL("dsound", use_last_error=True)
LPDSENUMCALLBACK = WINFUNCTYPE(BOOL, POINTER(BYTE * 16), LPCWSTR, LPCWSTR, LPVOID)
DirectSoundEnumerateW = dsound.DirectSoundEnumerateW
DirectSoundEnumerateW.restype = HRESULT
DirectSoundEnumerateW.argtypes = [LPDSENUMCALLBACK, LPVOID]
DirectSoundCaptureEnumerateW = dsound.DirectSoundCaptureEnumerateW
DirectSoundCaptureEnumerateW.restype = HRESULT
DirectSoundCaptureEnumerateW.argtypes = [LPDSENUMCALLBACK, LPVOID]
GetDeviceID = dsound.GetDeviceID
GetDeviceID.restype = HRESULT
GetDeviceID.argtypes = [POINTER(GUID), POINTER(GUID)]
# DEFINE_GUID(DSDEVID_DefaultPlayback,     0xDEF00000,0x9C6D,0x47Ed,0xAA,0xF1,0x4D,0xDA,0x8F,0x2B,0x5C,0x03);
# DEFINE_GUID(DSDEVID_DefaultCapture,      0xDEF00001,0x9C6D,0x47Ed,0xAA,0xF1,0x4D,0xDA,0x8F,0x2B,0x5C,0x03);
# DEFINE_GUID(DSDEVID_DefaultVoicePlayback,0xDEF00002,0x9C6D,0x47Ed,0xAA,0xF1,0x4D,0xDA,0x8F,0x2B,0x5C,0x03);
# DEFINE_GUID(DSDEVID_DefaultVoiceCapture, 0xDEF00003,0x9C6D,0x47ED,0xAA,0xF1,0x4D,0xDA,0x8F,0x2B,0x5C,0x03);

StringFromGUID2 = oledll.ole32.StringFromGUID2
StringFromGUID2.restype = c_int
StringFromGUID2.argtypes = [LPVOID, LPOLESTR, c_int]


def _enum_devices(fn) -> list[tuple[int, str, str]]:
    devices = []
    counter = []

    def cb_enum(lp_guid, desc, _module, _context):
        if lp_guid:
            guid_bytes = bytes(lp_guid.contents)
            device_guid = str(uuid.UUID(bytes_le=guid_bytes))
            devices.append((len(counter), device_guid, str(desc)))
        counter.append("")
        return True

    fn(LPDSENUMCALLBACK(cb_enum), None)
    return devices


def get_devices() -> list[tuple[int, str, str]]:
    return _enum_devices(DirectSoundEnumerateW)


def get_capture_devices() -> list[tuple[int, str, str]]:
    return _enum_devices(DirectSoundCaptureEnumerateW)


def main() -> None:
    import sys
    from xpra.platform import program_context
    from xpra.log import Logger, enable_color, consume_verbose_argv
    with program_context("Audio Device Info", "Audio Device Info"):
        enable_color()
        consume_verbose_argv(sys.argv, "audio")
        log = Logger("win32", "audio")
        log.info("")
        log.info("Capture Devices:")
        for i, guid, name in get_capture_devices():
            log.info("* %i %-40s : %s", i, guid, name)
        log.info("")
        log.info("All Devices:")
        for i, guid, name in get_devices():
            log.info("* %i %-40s : %s", i, guid, name)


if __name__ == "__main__":
    main()
