#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from typing import Any
from collections.abc import Sequence

from xpra.util.str_fn import csv, print_nested_dict, pver, bytestostr
from xpra.util.env import envbool
from xpra.os_util import POSIX
from xpra.util.io import load_binary_file
from xpra.platform.paths import get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs
from xpra.log import Logger, consume_verbose_argv

log = Logger("encoder", "util")

NVIDIA_PROC_FILE = "/proc/driver/nvidia/version"
NVIDIA_HARDWARE = envbool("XPRA_NVIDIA_HARDWARE", False)

nvidia_hardware = 0


def has_nvidia_hardware() -> bool:
    global nvidia_hardware
    if nvidia_hardware == 0:
        nvidia_hardware = _has_nvidia_hardware()
    log(f"has_nvidia_hardware()={nvidia_hardware}")
    return bool(nvidia_hardware)


def _has_nvidia_hardware() -> bool | None:
    if NVIDIA_HARDWARE:
        return True
    # first, check for the kernel module file, this should be very quick:
    try:
        if os.path.exists(NVIDIA_PROC_FILE):
            log(f"has_nvidia_hardware() found kernel module proc file {NVIDIA_PROC_FILE!r}")
            return True
    except OSError:
        log(f"failed to query {NVIDIA_PROC_FILE!r}", exc_info=True)
    # pylint: disable=import-outside-toplevel
    if POSIX:
        # the drm module should also be quick:
        try:
            from xpra.codecs.drm import drm
            info = drm.query()
            for dev_info in info.values():
                dev_name = dev_info.get("name", "").lower()
                if dev_name.find("nouveau") >= 0:
                    continue
                if dev_name.find("nvidia") >= 0:
                    log(f"has_nvidia_hardware() found nvidia drm device: {dev_info}")
                    return True
        except ImportError as e:
            log(f"has_nvidia_hardware() cannot use drm module: {e}")
    try:
        import pynvml
        assert pynvml
        from pynvml import nvmlInit, nvmlShutdown, nvmlDeviceGetCount, NVMLError_DriverNotLoaded
    except ImportError as e:
        log(f"has_nvidia_hardware() cannot use pynvml module: {e}")
    else:
        count = None
        try:
            if nvmlInit():
                count = nvmlDeviceGetCount()
                log(f"has_nvidia_hardware() pynvml found {count} devices")
                return count > 0
        except NVMLError_DriverNotLoaded as e:
            log(f"has_nvidia_hardware() pynvml: {e}")
            return False
        except Exception as e:
            log(f"has_nvidia_hardware() pynvml: {e}")
        finally:
            if count is not None:
                nvmlShutdown()
    # try nvidia-smi for docker contexts
    import subprocess
    try:
        output = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        output = output.decode("utf-8").strip()
        if output:
            log(f"has_nvidia_hardware() found NVIDIA GPU(s) using nvidia-smi: {output}")
            return True
    except (subprocess.CalledProcessError, OSError):
        log("has_nvidia_hardware() nvidia-smi command not found or failed")
    # hope for the best
    log("has_nvidia_hardware() unable to ascertain, returning None")
    return None


nvml_init_warned = False


def wrap_nvml_init(nvmlInit, warn=True) -> bool:
    try:
        nvmlInit()
        return True
    except Exception as e:
        log("get_nvml_driver_version() pynvml error", exc_info=True)
        global nvml_init_warned
        if not nvml_init_warned and warn:
            log(f"{nvmlInit}()", exc_info=True)
            log.warn("Warning: failed to initialize NVML:")
            log.warn(" %s", e)
            nvml_init_warned = True
        return False


def get_nvml_driver_version() -> Sequence[str]:
    version: Sequence[str] = ()
    try:
        # pylint: disable=import-outside-toplevel
        from pynvml import nvmlInit, nvmlShutdown, nvmlSystemGetDriverVersion
    except ImportError as e:
        log("cannot use nvml to query the kernel module version:")
        log(" %s", e)
    else:
        try:
            if wrap_nvml_init(nvmlInit):
                try:
                    v = nvmlSystemGetDriverVersion()
                finally:
                    nvmlShutdown()
                log(f"nvmlSystemGetDriverVersion={bytestostr(v)}")
                version = bytestostr(v).split(".")
        except Exception as e:
            log("get_nvml_driver_version() pynvml error", exc_info=True)
            log.warn("Warning: failed to query the NVidia kernel module version using NVML:")
            log.warn(" %s", e)
    log(f"get_nvml_driver_version()={version}")
    return version


def get_proc_driver_version() -> Sequence[str]:
    if not POSIX:
        return ()
    v = load_binary_file(NVIDIA_PROC_FILE)
    if not v:
        log.warn("Warning: NVidia kernel module not installed?")
        log.warn(f" cannot load {NVIDIA_PROC_FILE!r}")
        return ()
    version = ()
    # ie: "NVRM version: NVIDIA UNIX x86_64 Kernel Module  565.77  Wed Nov 27 23:33:08 UTC 2024"
    # or: "NVIDIA UNIX Open Kernel Module for x86_64  575.57.08  Release Build  (dvs-builder@U22-I3-H04-01-5)  ..."
    KSTR = "Kernel Module"
    for line in bytestostr(v).splitlines():
        if line.find(KSTR) < 0:
            continue
        # try to split on double space:
        parts = line.split("  ")
        if len(parts) >= 3:
            version = parts[1].split(".")
            break
    if version:
        log_fn = log.debug
    else:
        log_fn = log.warn
        log_fn("Warning: unable to parse NVidia kernel module version")
    log_fn(f" {NVIDIA_PROC_FILE!r} contents:")
    for line in v.splitlines():
        log_fn(f"   {bytestostr(line)!r}")
    log(f"get_proc_driver_version()={version}")
    return version


def identify_nvidia_module_version() -> Sequence[int]:
    v = get_nvml_driver_version() or get_proc_driver_version()
    # only keep numeric values:
    numver = []
    try:
        for x in v:
            try:
                numver.append(int(x))
            except ValueError:
                if not numver:
                    raise
        if numver:
            log.info("NVidia driver version %s", pver(numver))
            return tuple(numver)
    except Exception as e:
        log.warn(f"Warning: failed to parse Nvidia driver version {v!r}: {e}")
    return ()


nvidia_module_version = None


def get_nvidia_module_version(probe=True) -> Sequence[int] | None:
    global nvidia_module_version
    if nvidia_module_version is None and probe:
        nvidia_module_version = identify_nvidia_module_version()
    return nvidia_module_version


def identify_cards() -> dict[int, dict[str, Any]]:
    devices: dict[int, dict[str, Any]] = {}
    try:
        # pylint: disable=import-outside-toplevel
        import pynvml
        from pynvml import nvmlInit, nvmlShutdown, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex
        deviceCount = None
        try:
            if not wrap_nvml_init(nvmlInit):
                return devices
            deviceCount = nvmlDeviceGetCount()
            log(f"identify_cards() will probe {deviceCount} cards")
            for i in range(deviceCount):
                handle = nvmlDeviceGetHandleByIndex(i)
                log(f"identify_cards() handle({i})={handle}")
                props: dict[str, Any] = {}

                def meminfo(memory):
                    return {
                        "total": int(memory.total),
                        "free": int(memory.free),
                        "used": int(memory.used),
                    }

                def pciinfo(pci) -> dict[str, int | str]:
                    i = {}
                    for nvname, pubname in {
                        "domain": "domain",
                        "bus": "bus",
                        "device": "device",
                        "pciDeviceId": "pci-device-id",
                        "pciSubSystemId": "pci-subsystem-id",
                    }.items():
                        try:
                            i[pubname] = int(getattr(pci, nvname))
                        except (ValueError, AttributeError):
                            pass
                    try:
                        i["bus-id"] = bytestostr(pci.busId)
                    except AttributeError:
                        pass
                    return i

                for prefix, prop, fn_name, args, conv in (
                        ("", "name", "nvmlDeviceGetName", (), bytestostr),
                        ("", "serial", "nvmlDeviceGetSerial", (), bytestostr),
                        ("", "uuid", "nvmlDeviceGetUUID", (), bytestostr),
                        ("", "pci", "nvmlDeviceGetPciInfo", (), pciinfo),
                        ("", "memory", "nvmlDeviceGetMemoryInfo", (), meminfo),
                        ("pcie-link", "generation-max", "nvmlDeviceGetMaxPcieLinkGeneration", (), int),
                        ("pcie-link", "width-max", "nvmlDeviceGetMaxPcieLinkWidth", (), int),
                        ("pcie-link", "generation", "nvmlDeviceGetCurrPcieLinkGeneration", (), int),
                        ("pcie-link", "width", "nvmlDeviceGetCurrPcieLinkWidth", (), int),
                        ("clock-info", "graphics", "nvmlDeviceGetClockInfo", (0,), int),
                        ("clock-info", "sm", "nvmlDeviceGetClockInfo", (1,), int),
                        ("clock-info", "mem", "nvmlDeviceGetClockInfo", (2,), int),
                        ("clock-info", "graphics-max", "nvmlDeviceGetMaxClockInfo", (0,), int),
                        ("clock-info", "sm-max", "nvmlDeviceGetMaxClockInfo", (1,), int),
                        ("clock-info", "mem-max", "nvmlDeviceGetMaxClockInfo", (2,), int),
                        ("", "fan-speed", "nvmlDeviceGetFanSpeed", (), int),
                        ("", "temperature", "nvmlDeviceGetTemperature", (0,), int),
                        ("", "power-state", "nvmlDeviceGetPowerState", (), int),
                        ("", "vbios-version", "nvmlDeviceGetVbiosVersion", (), bytestostr),
                ):
                    try:
                        fn = getattr(pynvml, fn_name)
                    except AttributeError:
                        log(f"{fn_name} not found in {pynvml}")
                        continue
                    try:
                        v = fn(handle, *args)
                        if conv:
                            v = conv(v)
                        if prefix:
                            d = props.setdefault(prefix, {})
                        else:
                            d = props
                        d[prop] = v
                    except Exception as e:
                        log("identify_cards() cannot query %s using %s on device %i with handle %s: %s",
                            prop, fn, i, handle, e)
                        continue
                log(f"identify_cards() [{i}]={props}")
                devices[i] = props
            # unitCount = nvmlUnitGetCount()
            # log.info("unitCount=%s", unitCount)
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


_cards = None


def get_cards(probe=True) -> dict:
    global _cards
    if _cards is None and probe:
        _cards = identify_cards()
    return _cards


def parse_nvfbc_hex_key(s) -> bytes:
    # ie: 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10
    # ie: 0102030405060708090A0B0C0D0E0F10
    # start by removing spaces and 0x:
    hexstr = s.replace("0x", "").replace(",", "").replace(" ", "")
    import binascii  # pylint: disable=import-outside-toplevel
    return binascii.unhexlify(hexstr)


license_keys: dict[str, tuple] = {}


def get_license_keys(version=0, basefilename="nvenc") -> Sequence[str]:
    filename = f"{basefilename}%s.keys" % (version or "")
    keys = license_keys.get(filename)
    if keys is not None:
        return keys
    env_name = f"XPRA_{basefilename.upper()}_CLIENT_KEY"
    env_keys = os.environ.get(env_name, "")
    if env_keys:
        keys = [x.strip() for x in env_keys.split(",")]
        log(f"using {basefilename} keys from environment variable {env_name} : {csv(keys)}")
    else:
        # try to load the license file
        keys = []
        with log.trap_error(f"Error loading {basefilename!r} license keys"):
            # see read_xpra_defaults for an explanation of paths
            dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs()
            for d in dirs:
                if not d:
                    continue
                keys_file = os.path.join(d, filename)
                keys_file = os.path.expanduser(keys_file)
                if not os.path.exists(keys_file):
                    log(f"get_license_keys({basefilename}, {version}) {keys_file!r} does not exist")
                    continue
                log(f"loading {basefilename} version {version} keys from {keys_file!r}")
                with open(keys_file, "rb") as f:
                    fkeys = []
                    for line in f:
                        sline = line.strip().rstrip(b'\r\n').strip().decode("latin1")
                        if not sline:
                            log("skipping empty line")
                            continue
                        if sline[0] in ('!', '#'):
                            log("skipping comments")
                            continue
                        fkeys.append(sline)
                        log(f"added key: {sline}")
                    log(f"added {len(fkeys)} keys from {keys_file}")
                    keys += fkeys
    license_keys[filename] = keys
    log(f"get_nvenc_license_keys({version})={keys}")
    return keys


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Nvidia-Info", "Nvidia Info"):
        consume_verbose_argv(sys.argv, "encoding")
        # this will log the version number:
        get_nvidia_module_version()
        keys = get_license_keys()
        log.info(f"{len(keys)} NVENC license keys")
        for k in keys:
            log.info(f"  {k}")
        try:
            import pynvml
            assert pynvml
        except ImportError:
            log.warn("Warning: the pynvml library is missing")
            log.warn(" cannot identify the GPUs installed")
        else:
            cards = get_cards()
            if cards:
                log.info("")
                log.info(f"{len(cards)} cards:")
                print_nested_dict(cards, print_fn=log.info)
    return 0


if __name__ == "__main__":
    main()
