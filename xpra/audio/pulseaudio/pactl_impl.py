#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import hashlib
import os.path
from typing import Any, Optional

from xpra.audio.pulseaudio.common_util import get_pulse_server_x11_property, get_pulse_id_x11_property
from xpra.os_util import WIN32, OSX
from xpra.util.io import which
from xpra.util.str_fn import strtobytes, bytestostr

from xpra.log import Logger

log = Logger("audio")

pactl_bin = None
has_pulseaudio = None


def get_pactl_bin() -> str:
    global pactl_bin
    if pactl_bin is None:
        if WIN32 or OSX:
            pactl_bin = ""
        else:
            pactl_bin = which("pactl")
    return pactl_bin


def pactl_output(log_errors=True, *pactl_args) -> tuple[int, Any, Any]:
    pactl_bin = get_pactl_bin()
    if not pactl_bin:
        return -1, None, None
    # ie: "pactl list"
    cmd = [pactl_bin] + list(pactl_args)
    # force "C" locale so that we can parse the output as expected
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env.pop("DISPLAY", None)
    try:
        import subprocess
        log(f"running {cmd!r} with env={env}")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        from xpra.util.child_reaper import getChildReaper
        procinfo = getChildReaper().add_process(process, "pactl", cmd, True, True)
        log(f"waiting for {cmd!r} output")
        out, err = process.communicate()
        getChildReaper().add_dead_process(procinfo)
        code = process.wait()
        log(f"pactl_output{pactl_args} returned {code}")
        return code, out, err
    except Exception as e:
        if log_errors:
            log.error("failed to execute %s: %s", cmd, e)
        else:
            log("failed to execute %s: %s", cmd, e)
        return -1, None, None


def is_pa_installed() -> bool:
    pactl_bin = get_pactl_bin()
    log("is_pa_installed() pactl_bin=%s", pactl_bin)
    return bool(pactl_bin)


def has_pa() -> bool:
    global has_pulseaudio
    if has_pulseaudio is None:
        has_pulseaudio = get_pulse_server_x11_property() or is_pa_installed()
    return bool(has_pulseaudio)


def set_source_mute(device, mute=False) -> bool:
    code, out, err = pactl_output(True, "set-source-mute", device, str(int(mute)))
    log("set_source_mute: output=%s, err=%s", out, err)
    return code == 0


def set_sink_mute(device, mute=False) -> bool:
    code, out, err = pactl_output(True, "set-sink-mute", device, str(int(mute)))
    log("set_sink_mute: output=%s, err=%s", out, err)
    return code == 0


def get_pactl_info_line(prefix) -> str:
    if not has_pa():
        return ""
    code, out, err = pactl_output(False, "info")
    if code != 0:
        log.warn("Warning: failed to query pulseaudio using 'pactl info'")
        if err:
            for x in err.splitlines():
                log.warn(" %s", bytestostr(x))
        return ""
    stat = ""
    for line in bytestostr(out).splitlines():
        if line.startswith(prefix):
            stat = line[len(prefix):].strip()
            break
    log("get_pactl_info_line(%s)=%s", prefix, stat)
    return stat


def get_default_sink() -> str:
    return get_pactl_info_line("Default Sink:")


def get_pactl_server() -> str:
    return get_pactl_info_line("Server String:")


def get_pulse_cookie_hash() -> bytes:
    v = get_pactl_info_line("Cookie:")
    return strtobytes(hashlib.sha256(strtobytes(v)).hexdigest())


def get_pulse_server(may_start_it=True) -> str:
    xp = get_pulse_server_x11_property()
    if xp or not may_start_it:
        return bytestostr(xp or b"")
    return get_pactl_server()


def get_pulse_id() -> str:
    return get_pulse_id_x11_property()


def get_pa_device_options(monitors=False, input_or_output=None, ignored_devices=("bell-window-system",)):
    """
    Finds the list of devices, monitors=False allows us to filter out monitors
    (which could create audio loops if we use them)
    set input_or_output=True to get inputs only
    set input_or_output=False to get outputs only
    set input_or_output=None to get both
    Same goes for monitors (False|True|None)
    Returns a dict() with the PulseAudio name as key and a description as value
    """
    if WIN32 or OSX:
        return {}
    status, out, _ = pactl_output(False, "list")
    if status != 0 or not out:
        return {}
    return do_get_pa_device_options(out, monitors, input_or_output, ignored_devices)


def do_get_pa_device_options(pactl_list_output, monitors=False, input_or_output=None,
                             ignored_devices=("bell-window-system",)):
    def are_properties_acceptable(name: Optional[str], device_class: Optional[str],
                                  monitor_of_sink: Optional[str]) -> bool:
        if (name is None) or (device_class is None and monitor_of_sink is None):
            return False
        if name in ignored_devices:
            return False
        # Verify against monitor flag if set:
        if monitors is not None:
            if device_class is not None:
                is_monitor = device_class == '"monitor"'
            else:  # monitor_of_sink is not None
                is_monitor = monitor_of_sink != "n/a"
            if is_monitor != monitors:
                return False
        # Verify against input flag (if set):
        if input_or_output is not None:
            is_input = name.lower().find("input") >= 0
            if is_input is True and input_or_output is False:
                return False
            is_output = name.lower().find("output") >= 0
            if is_output is True and input_or_output is True:
                return False
        return True

    name: Optional[str] = None
    device_class: Optional[str] = None
    monitor_of_sink: Optional[str] = None
    device_description: Optional[str] = None
    devices: dict[str, str] = {}
    for line in bytestostr(pactl_list_output).splitlines():
        if not line.startswith(" ") and not line.startswith("\t"):  # clear vars when we encounter a new section
            if are_properties_acceptable(name, device_class, monitor_of_sink):
                assert isinstance(name, str)
                if not device_description:
                    device_description = name
                devices[name] = device_description
            name = None
            device_class = None
            monitor_of_sink = None
            device_description = None
        line = line.strip()
        if line.startswith("Name: "):
            name = line[len("Name: "):]
        if line.startswith("device.class = "):
            device_class = line[len("device-class = "):]
        if line.startswith("Monitor of Sink: "):
            monitor_of_sink = line[len("Monitor of Sink: "):]
        if line.startswith("device.description = "):
            device_description = line[len("device.description = "):].strip('"')
    return devices


def get_info() -> dict[str, Any]:
    i = 0
    dinfo = {}
    status, out, _ = pactl_output(False, "list")
    if status == 0 and out:
        for monitors in (True, False):
            for io in (True, False):
                devices = do_get_pa_device_options(out, monitors, io)
                for d, name in devices.items():
                    dinfo[bytestostr(d)] = bytestostr(name)
                    i += 1
    info = {
        "device": dinfo,
        "devices": i,
        "pulseaudio": {
            "wrapper": "pactl",
            "found": bool(has_pa()),
            "id": get_pulse_id(),
            "server": get_pulse_server(False),
            "cookie-hash": get_pulse_cookie_hash(),
        }
    }
    log("pulseaudio_pactl_util.get_info()=%s", info)
    return info


def main():
    from xpra.util.str_fn import print_nested_dict
    from xpra.util.io import load_binary_file
    if "-v" in sys.argv:
        log.enable_debug()
        sys.argv.remove("-v")
    if len(sys.argv) > 1:
        for filename in sys.argv[1:]:
            if not os.path.exists(filename):
                log.warn("file argument '%s' does not exist, ignoring", filename)
                continue
            data = load_binary_file(filename)
            devices = do_get_pa_device_options(data, True, False)
            log.info("%s devices found in '%s'", len(devices), filename)
            print_nested_dict(devices)
        return

    i = get_info()
    print_nested_dict(i)


if __name__ == "__main__":
    main()
