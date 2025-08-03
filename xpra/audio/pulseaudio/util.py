#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.os_util import WIN32, OSX
from xpra.log import Logger, consume_verbose_argv

log = Logger("audio")

default_icon_path = None


def set_icon_path(v) -> None:
    global default_icon_path
    default_icon_path = v


def add_audio_tagging_env(env_dict: dict = os.environ, icon_path: str = "") -> None:
    """
        This is called audio-tagging in PulseAudio, see:
        https://pulseaudio.org/wiki/ApplicationProperties
        https://0pointer.de/blog/projects/tagging-audio.html
    """
    from xpra.util.version import XPRA_VERSION
    env_dict |= {
        "PULSE_PROP_application.name": "xpra",
        "PULSE_PROP_application.id": "xpra",
        "PULSE_PROP_application.version": XPRA_VERSION,
        "PULSE_PROP_media.role": "music",
    }
    if not icon_path:
        icon_path = default_icon_path
    if icon_path and os.path.exists(icon_path):
        env_dict["PULSE_PROP_application.icon_name"] = str(icon_path)


try:
    # use "none" on win32 and osx:
    if WIN32 or OSX:
        from xpra.audio.pulseaudio import none_impl as _pulseaudio_util
    else:
        from xpra.audio.pulseaudio import pactl_impl as _pulseaudio_util
except ImportError as e:
    # fallback forks a process and parses the output:
    log("cannot import default pulseaudio util: %s", e)
    log("using pulseaudio none fallback")
    del e
    from xpra.audio.pulseaudio import none_impl as _pulseaudio_util

get_info = _pulseaudio_util.get_info
has_pa = _pulseaudio_util.has_pa
get_pa_device_options = _pulseaudio_util.get_pa_device_options
get_default_sink = _pulseaudio_util.get_default_sink
get_pulse_server = _pulseaudio_util.get_pulse_server
get_pulse_id = _pulseaudio_util.get_pulse_id
get_pulse_cookie_hash = _pulseaudio_util.get_pulse_cookie_hash
get_pactl_server = _pulseaudio_util.get_pactl_server
set_source_mute = _pulseaudio_util.set_source_mute
set_sink_mute = _pulseaudio_util.set_sink_mute


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.util.str_fn import print_nested_dict
    with program_context("Pulseaudio-Info"):
        enable_color()
        consume_verbose_argv(sys.argv, "audio")
        i = get_info()
        print_nested_dict(i)


if __name__ == "__main__":
    main()
