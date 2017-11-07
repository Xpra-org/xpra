#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.log import Logger
log = Logger("encoder", "util")
from xpra.util import pver, print_nested_dict, engs, envbool, csv
from xpra.os_util import bytestostr, strtobytes


MAX_TESTED = 384

nvml_init_warned = False
def wrap_nvml_init(nvmlInit):
    try:
        nvmlInit()
        return True
    except Exception as e:
        log("get_nvml_driver_version() pynvml error", exc_info=True)
        global nvml_init_warned
        if not nvml_init_warned:
            log.warn("Warning: failed to initialize NVML:")
            log.warn(" %s", e)
            nvml_init_warned = True
        return False

def get_nvml_driver_version():
    try:
        from pynvml import nvmlInit, nvmlShutdown, nvmlSystemGetDriverVersion
        try:
            if wrap_nvml_init(nvmlInit):
                v = nvmlSystemGetDriverVersion()
                log("nvmlSystemGetDriverVersion=%s", bytestostr(v))
                return v.split(b".")
        except Exception as e:
            log("get_nvml_driver_version() pynvml error", exc_info=True)
            log.warn("Warning: failed to query the NVidia kernel module version using NVML:")
            log.warn(" %s", e)
        finally:
            nvmlShutdown()
    except ImportError as e:
        log("cannot use nvml to query the kernel module version:")
        log(" %s", e)
    return ""


def get_proc_driver_version():
    from xpra.os_util import load_binary_file
    proc_file = "/proc/driver/nvidia/version"
    v = load_binary_file(proc_file)
    if not v:
        log.warn("Warning: NVidia kernel module not installed?")
        log.warn(" cannot open '%s'", proc_file)
        return ""
    KSTR = b"Kernel Module"
    p = v.find(KSTR)
    if not p:
        log.warn("unknown NVidia kernel module version")
        return ""
    v = v[p+len(KSTR):].strip().split(b" ")[0]
    v = v.split(b".")
    return v


def identify_nvidia_module_version():
    v = get_nvml_driver_version() or get_proc_driver_version()
    #only keep numeric values:
    numver = []
    try:
        for x in v:
            try:
                numver.append(int(x))
            except ValueError:
                if len(numver)==0:
                    raise
        if numver:
            log.info("NVidia driver version %s", pver(numver))
            return numver
    except Exception as e:
        log.warn("failed to parse Nvidia driver version '%s': %s", v, e)
    return []

nvidia_module_version = None
def get_nvidia_module_version(probe=True):
    global nvidia_module_version
    if nvidia_module_version is None and probe:
        nvidia_module_version = identify_nvidia_module_version()
    return nvidia_module_version


def identify_cards():
    devices = {}
    try:
        import pynvml
        from pynvml import nvmlInit, nvmlShutdown, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex
        deviceCount = None
        try:
            if not wrap_nvml_init(nvmlInit):
                return devices
            deviceCount = nvmlDeviceGetCount()
            log("identify_cards() will probe %i cards", deviceCount)
            for i in range(deviceCount):
                handle = nvmlDeviceGetHandleByIndex(i)
                log("identify_cards() handle(%i)=%s", i, handle)
                props = {}
                def meminfo(memory):
                    return {
                            "total"  : int(memory.total),
                            "free"   : int(memory.free),
                            "used"   : int(memory.used),
                            }
                def pciinfo(pci):
                    i = {}
                    for x in ("domain", "bus", "device", "pciDeviceId", "pciSubSystemId"):
                        try:
                            i[x] = int(getattr(pci, x))
                        except:
                            pass
                    try:
                        i["busId"] = bytestostr(pci.busId)
                    except:
                        pass
                    return i
                for prop, fn_name, args, conv in (
                       ("name",                     "nvmlDeviceGetName",                    (),     strtobytes),
                       ("serial",                   "nvmlDeviceGetSerial",                  (),     strtobytes),
                       ("uuid",                     "nvmlDeviceGetUUID",                    (),     strtobytes),
                       ("pci",                      "nvmlDeviceGetPciInfo",                 (),     pciinfo),
                       ("memory",                   "nvmlDeviceGetMemoryInfo",              (),     meminfo),
                       ("pcie-link-generation-max", "nvmlDeviceGetMaxPcieLinkGeneration",   (),     int),
                       ("pcie-link-width-max",      "nvmlDeviceGetMaxPcieLinkWidth",        (),     int),
                       ("pcie-link-generation",     "nvmlDeviceGetCurrPcieLinkGeneration",  (),     int),
                       ("pcie-link-width",          "nvmlDeviceGetCurrPcieLinkWidth",       (),     int),
                       ("clock-info-graphics",      "nvmlDeviceGetClockInfo",               (0,),   int),
                       ("clock-info-sm",            "nvmlDeviceGetClockInfo",               (1,),   int),
                       ("clock-info-mem",           "nvmlDeviceGetClockInfo",               (2,),   int),
                       ("clock-info-graphics-max",  "nvmlDeviceGetMaxClockInfo",            (0,),   int),
                       ("clock-info-sm-max",        "nvmlDeviceGetMaxClockInfo",            (1,),   int),
                       ("clock-info-mem-max",       "nvmlDeviceGetMaxClockInfo",            (2,),   int),
                       ("fan-speed",                "nvmlDeviceGetFanSpeed",                (),     int),
                       ("temperature",              "nvmlDeviceGetTemperature",             (0,),   int),
                       ("power-state",              "nvmlDeviceGetPowerState",              (),     int),
                       ("vbios-version",            "nvmlDeviceGetVbiosVersion",            (),     strtobytes),
                       ):
                    try:
                        fn = getattr(pynvml, fn_name)
                        v = fn(handle, *args)
                        if conv:
                            v = conv(v)
                        props[prop] = v
                    except Exception as e:
                        log("identify_cards() cannot query %s using %s on device %i with handle %s: %s", prop, fn, i, handle, e)
                        continue
                log("identify_cards() [%i]=%s", i, props)
                devices[i] = props
            #unitCount = nvmlUnitGetCount()
            #log.info("unitCount=%s", unitCount)
        except Exception as e:
            log("identify_cards() pynvml error", exc_info=True)
            log.warn("Warning: failed to query the NVidia cards using NVML:")
            log.warn(" %s", e)
        finally:
            if deviceCount is not None:
                nvmlShutdown()
    except ImportError as e:
        log("cannot use nvml to query the kernel module version:")
        log(" %s", e)
    return devices


cards = None
def get_cards(probe=True):
    global cards
    if cards is None and probe:
        cards = identify_cards()
    return cards


def is_blacklisted():
    v = get_nvidia_module_version(True)
    try:
        if v[0]<=MAX_TESTED:
            return False
    except Exception as e:
        log.warn("Warning: error checking driver version:")
        log.warn(" %s", e)
    return None     #we don't know: unreleased / untested


_version_warning = False
def validate_driver_yuv444lossless():
    #this should log the kernel module version
    v = get_nvidia_module_version()
    if not v:
        log.warn("Warning: unknown NVidia driver version")
        bl = None
    else:
        bl = is_blacklisted()
    if bl is True:
        raise Exception("NVidia driver version %s is blacklisted, it does not work with NVENC" % pver(v))
    elif bl is None:
        global _version_warning
        if _version_warning:
            l = log
        else:
            l = log.warn
            _version_warning = True
        if v:
            l("Warning: NVidia driver version %s is untested with NVENC", pver(v))
            l(" (this encoder has been tested with versions up to %s.x only)", MAX_TESTED)
        if not envbool("XPRA_NVENC_YUV444P", False):
            l(" disabling YUV444P and lossless mode")
            l(" use XPRA_NVENC_YUV444P=0 to force enable")
            return False
        l(" force enabling YUV444P and lossless mode")
    return True


def parse_nvfbc_hex_key(s):
    #ie: 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10
    #ie: 0102030405060708090A0B0C0D0E0F10
    #start by removing spaces and 0x:
    hexstr = s.replace("0x", "").replace(",", "").replace(" ", "")
    import binascii
    return binascii.unhexlify(hexstr)


license_keys = {}
def get_license_keys(version=0, basefilename="nvenc"):
    global license_keys
    filename = "%s%s.keys" % (basefilename, version or "")
    keys = license_keys.get(filename)
    if keys is not None:
        return keys
    env_name = "XPRA_%s_CLIENT_KEY" % basefilename.upper()
    env_keys = os.environ.get(env_name, "")
    if env_keys:
        keys = [x.strip() for x in env_keys.split(",")]
        log("using %s keys from environment variable %s: %s", basefilename, env_name, csv(keys))
    else:
        #try to load the license file
        keys = []
        try:
            #see read_xpra_defaults for an explanation of paths
            from xpra.platform.paths import get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs
            dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs()
            for d in dirs:
                if not d:
                    continue
                keys_file = os.path.join(d, filename)
                keys_file = os.path.expanduser(keys_file)
                if not os.path.exists(keys_file):
                    log("get_license_keys(%s, %s) '%s' does not exist", basefilename, version, keys_file)
                    continue
                log("loading %s version %s keys from %s", basefilename, version, keys_file)
                with open(keys_file, "rb") as f:
                    fkeys = []
                    for line in f:
                        sline = bytestostr(line.strip().rstrip(b'\r\n').strip())
                        if len(sline) == 0:
                            log("skipping empty line")
                            continue
                        if sline[0] in ('!', '#'):
                            log("skipping comments")
                            continue
                        fkeys.append(sline)
                        log("added key: %s", sline)
                    log("added %i key%s from %s", len(fkeys), engs(fkeys), keys_file)
                    keys += fkeys
        except Exception:
            log.error("Error loading %s license keys", basefilename, exc_info=True)
    license_keys[filename] = keys
    log("get_nvenc_license_keys(%s)=%s", version, keys)
    return keys


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("Nvidia-Info", "Nvidia Info"):
        #this will log the version number:
        get_nvidia_module_version()
        if is_blacklisted():
            log.warn("Warning: this driver version is blacklisted")
        log.info("NVENC license keys:")
        for v in (0, 8):
            keys = get_license_keys(v)
            log.info("* version %s: %s key(s)", v or "common", len(keys))
            for k in keys:
                log.info("  %s", k)
        cards = get_cards()
        if cards:
            log.info("")
            log.info("%i card%s:", len(cards), engs(cards))
            print_nested_dict(cards, print_fn=log.info)


if __name__ == "__main__":
    main()
