#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.log import Logger
log = Logger("sound")
#log.enable_debug()
from xpra.sound.pulseaudio_common_util import get_pulse_server_x11_property, get_pulse_id_x11_property

import palib


class PALibContext(object):
    def __init__(self):
        pass

    def __enter__(self):
        #log("PALibContext.__enter__()")
        self.context = palib.PulseObj("Xpra", None, True)

    def __exit__(self, e_typ, e_val, trcbak):
        #log("PALibContext.__exit__(%s) context=%s", (e_typ, e_val, trcbak), self.context)
        if self.context:
            self.context.pulse_disconnect()
            self.context = None

def has_pa():
    try:
        c = PALibContext()
        with c:
            pac = c.context
            log("has_pa() context=%s", pac)
            log("has_pa() connected=%s", pac.connected)
            log("has_pa()=%s", pac.action_done)
            return pac.action_done
    except Exception as e:
        log("has_pa() %s", e)
        return False

def set_source_mute(device_name, mute=False):
    #a bit ugly, find it by name since that's what we did before with pactl:
    c = PALibContext()
    with c:
        pac = c.context
        for device in pac.pulse_source_list():
            if device.name==device_name:
                log("set_source_mute(%s, %s) found device %s", device_name, mute, device)
                if mute:
                    pac.pulse_mute_sink(device.index)
                else:
                    pac.pulse_unmute_sink(device.index)

def get_default_sink():
    c = PALibContext()
    with c:
        i = c.context.pulse_server_info() or {}
        return i.get("default_sink_name", "")

def get_pulse_server():
    return get_pulse_server_x11_property()

def get_pulse_id():
    return get_pulse_id_x11_property()



def get_pa_device_options(monitors=False, input_or_output=None, ignored_devices=["bell-window-system"], log_errors=True):
    c = PALibContext()
    devices = {}
    with c:
        pac = c.context
        options = []
        if (input_or_output is not False) or monitors:
            #add input devices:
            options.append((pac.pulse_source_list, "monitor_of_sink_name"))
        if input_or_output is not True:
            #add output devices:
            options.append((pac.pulse_sink_list, None))
        log("get_pa_device_options(%s, %s, %s, %s) calling %s", monitors, input_or_output, ignored_devices, log_errors, options)
        for fn, monitor_attribute in options:
            v = fn()
            log("%s()=%s", fn.__name__, tuple(str(x) for x in v))
            for device in v:
                #device.printDebug()
                monitor = None
                if monitor_attribute:
                    monitor = getattr(device, monitor_attribute)
                    log("monitor(%s)=%s", device.name, monitor)
                if monitors is True and not monitor:
                    log("device '%s' skipped: not a monitor device", device.name)
                    continue
                elif monitors is False and monitor:
                    log("device '%s' skipped: this is a monitor device", device.name)
                    continue
                name = device.name or device.description
                devices[name] = device.description or device.name
        assert pac.action_done, "action not done"
    log("get_pa_device_options(%s, %s, %s, %s)=%s", monitors, input_or_output, ignored_devices, log_errors, devices)
    return devices

def get_info():
    info = {}
    from xpra.util import updict
    updict(info, "pulseaudio", {
            "wrapper": "palib",
            "id"     : get_pulse_id(),
            "server" : get_pulse_server(),
           })
    try:
        c = PALibContext()
        with c:
            l = c.context.pulse_server_info()
            for v in l:
                updict(info, "pulseaudio", v)
    except Exception as e:
        log.error("error accessing pulse server: %s", e)
    i = 0
    for monitors in (True, False):
        for io in (True, False):
            devices = get_pa_device_options(monitors, io, log_errors=False)
            for d,name in devices.items():
                info["device.%s" % d] = name
            i += 1
    info["devices"] = i
    return info


def main():
    if "-v" in sys.argv:
        log.enable_debug()
    i = get_info()
    for k in sorted(i):
        log.info("%s : %s", k.ljust(80), i[k])

if __name__ == "__main__":
    main()
