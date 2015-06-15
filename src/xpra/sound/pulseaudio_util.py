#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.log import Logger
log = Logger("sound")


def add_audio_tagging_env(icon_path=None):
    """
        This is called audio-tagging in PulseAudio, see:
        http://pulseaudio.org/wiki/ApplicationProperties
        http://0pointer.de/blog/projects/tagging-audio.html
    """
    os.environ["PULSE_PROP_application.name"] = "xpra"
    os.environ["PULSE_PROP_media.role"] = "music"
    if icon_path and os.path.exists(icon_path):
        os.environ["PULSE_PROP_application.icon_name"] = icon_path


#prefer the palib option which does everything in process:
try:
    #use "none" on win32 and osx:
    if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
        from xpra.sound import pulseaudio_none_util as _pulseaudio_util
    else:
        if os.environ.get("XPRA_USE_PACTL", "0")=="1":
            raise ImportError("environment override: not using palib")
        from xpra.sound import pulseaudio_palib_util as _pulseaudio_util
except ImportError as e:
    #fallback forks a process and parses the output:
    log.warn("palib not available, using legacy pactl fallback")
    from xpra.sound import pulseaudio_pactl_util as  _pulseaudio_util       #@Reimport

get_info                = _pulseaudio_util.get_info
has_pa                  = _pulseaudio_util.has_pa
get_pa_device_options   = _pulseaudio_util.get_pa_device_options
get_default_sink        = _pulseaudio_util.get_default_sink
get_pulse_server        = _pulseaudio_util.get_pulse_server
get_pulse_id            = _pulseaudio_util.get_pulse_id
set_source_mute         = _pulseaudio_util.set_source_mute


def main():
    if "-v" in sys.argv:
        log.enable_debug()
    i = get_info()
    for k in sorted(i):
        log.info("%s : %s", k.ljust(64), i[k])

if __name__ == "__main__":
    main()
