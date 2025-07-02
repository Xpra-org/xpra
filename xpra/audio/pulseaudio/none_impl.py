#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any


def has_pa() -> bool:
    return False


def set_source_mute(device: str, mute=False) -> None:
    """ none implementation """


def set_sink_mute(device: str, mute=False) -> None:
    """ none implementation """


def get_default_sink() -> str:
    return ""


def get_pulse_server() -> str:
    return ""


def get_pulse_id() -> str:
    return ""


def get_pulse_cookie_hash() -> str:
    return ""


def get_pactl_server() -> str:
    return ""


def get_pa_device_options(*_args) -> dict[str, Any]:
    return {}


def get_info() -> dict[str, Any]:
    return {
        "pulseaudio.wrapper": "none",
        "pulseaudio.found": has_pa(),
    }


def main() -> None:
    from xpra.log import Logger
    log = Logger("audio", "pulseaudio")
    if "-v" in sys.argv:
        log.enable_debug()
    i = get_info()
    for k in sorted(i):
        log.info("%s : %s", k.ljust(64), i[k])


if __name__ == "__main__":
    main()
