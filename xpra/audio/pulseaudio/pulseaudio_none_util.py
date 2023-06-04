#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Dict, Any

from xpra.log import Logger
log = Logger("audio")


def has_pa():
    return False


def set_source_mute(device, mute=False):
    """ none implementation """

def set_sink_mute(device, mute=False):
    """ none implementation """

def get_default_sink():
    return ""

def get_pulse_server():
    return ""

def get_pulse_id():
    return ""

def get_pulse_cookie_hash():
    return ""

def get_pactl_server():
    return ""

def get_pa_device_options(*_args):
    return {}

def get_info() -> Dict[str,Any]:
    return {
            "pulseaudio.wrapper": "none",
            "pulseaudio.found"  : has_pa(),
           }


def main():
    if "-v" in sys.argv:
        log.enable_debug()
    i = get_info()
    for k in sorted(i):
        log.info("%s : %s", k.ljust(64), i[k])

if __name__ == "__main__":
    main()
