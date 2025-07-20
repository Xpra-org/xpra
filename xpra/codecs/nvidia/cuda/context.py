#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# @PydevCodeAnalysisIgnore
# pylint: disable=no-member

import os
import sys
from typing import Any
from time import monotonic
from threading import RLock
from collections.abc import Sequence

from xpra.codecs.constants import TransientCodecException
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, print_nested_dict
from xpra.util.env import envint, envbool, first_time, numpy_import_context
from xpra.platform.paths import (
    get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs,
    get_resources_dir, get_app_dir,
)
from xpra.os_util import WIN32
from xpra.util.system import is_WSL
from xpra.util.io import load_binary_file
from xpra.log import Logger, consume_verbose_argv

log = Logger("cuda")

if WIN32 and not os.environ.get("CUDA_PATH") and getattr(sys, "frozen", None) in ("windows_exe", "console_exe", True):
    os.environ["CUDA_PATH"] = get_app_dir()

if is_WSL() and not envbool("XPRA_PYCUDA_WSL", False):
    raise ImportError("refusing to import pycuda on WSL, use `XPRA_PYCUDA_WSL=1` to override")

with numpy_import_context("CUDA context import"):
    import pycuda
    log(f"loaded pycuda successfully: {pycuda}")
    from pycuda import driver
    from pycuda.driver import (
        get_version, get_driver_version, mem_get_info,
        init,
        Device, device_attribute, ctx_flags,
        module_from_buffer, LogicError,
    )

MIN_FREE_MEMORY = envint("XPRA_CUDA_MIN_FREE_MEMORY", 10)

# record when we get failures/success:
DEVICE_STATE: dict[int, bool] = {}


def record_device_failure(device_id: int) -> None:
    DEVICE_STATE[device_id] = False


def record_device_success(device_id: int) -> None:
    DEVICE_STATE[device_id] = True


def device_info(d) -> str:
    if not d:
        return "None"
    return f"{d.name()} @ {d.pci_bus_id()}"


def pci_bus_id(d) -> str:
    if not d:
        return "None"
    return d.pci_bus_id()


def device_name(d) -> str:
    if not d:
        return "None"
    return d.name()


def compute_capability(d) -> int:
    smmajor, smminor = d.compute_capability()
    return (smmajor << 4) + smminor


def get_pycuda_version() -> Sequence[int]:
    return pycuda.VERSION


def get_pycuda_info() -> dict[str, Any]:
    init_all_devices()
    i = {
        "version": {
            "": pycuda.VERSION,
            "text": pycuda.VERSION_TEXT,
        }
    }
    if pycuda.VERSION_STATUS:
        i["version.status"] = pycuda.VERSION_STATUS
    return i


def get_cuda_info() -> dict[str, Any]:
    init_all_devices()
    return {
        "driver": {
            "version": get_version(),
            "driver_version": get_driver_version(),
        }
    }


DEVICE_INFO: dict[int, str] = {}


def get_device_info(i: int) -> str:
    return DEVICE_INFO.get(i, "")


DEVICE_NAME: dict[int, str] = {}


def get_device_name(i: int) -> str:
    return DEVICE_NAME.get(i, "")


PREFS = None


def get_prefs() -> dict[str, Any]:
    global PREFS
    if PREFS is None:
        PREFS = do_get_prefs()
    return PREFS or {}


def do_get_prefs() -> dict[str, Any]:
    prefs: dict[str, Any] = {}
    dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs()
    log(f"get_prefs() will try to load cuda.conf from: {dirs}")
    for d in dirs:
        conf_file = os.path.join(os.path.expanduser(d), "cuda.conf")
        if not os.path.exists(conf_file):
            log(f"get_prefs() {conf_file!r} does not exist!")
            continue
        if not os.path.isfile(conf_file):
            log(f"get_prefs() {conf_file!r} is not a file!")
            continue
        c_prefs: dict[str, Any] = {}
        try:
            with open(conf_file, "rb") as f:
                for line in f:
                    sline = line.strip().rstrip(b'\r\n').strip().decode("latin1")
                    props = sline.split("=", 1)
                    if len(props) != 2:
                        continue
                    name = props[0].strip()
                    value = props[1].strip()
                    if name in ("enabled-devices", "disabled-devices"):
                        for v in value.split(","):
                            c_prefs.setdefault(name, []).append(v.strip())
                    elif name in ("device-id", "device-name", "load-balancing"):
                        c_prefs[name] = value
        except Exception as e:
            log.error(f"Error: cannot read cuda configuration file {conf_file!r}")
            log.estr(e)
        log(f"get_prefs() {conf_file!r} : {c_prefs}")
        prefs.update(c_prefs)
    return prefs


def get_pref(name: str):
    assert name in ("device-id", "device-name", "enabled-devices", "disabled-devices", "load-balancing")
    # ie: env_name("device-id")="XPRA_CUDA_DEVICE_ID"
    env_name = "XPRA_CUDA_" + str(name).upper().replace("-", "_")
    env_value = os.environ.get(env_name)
    if env_value is not None:
        if name in ("enabled-devices", "disabled-devices"):
            return env_value.split(",")
        return env_value
    return get_prefs().get(name)


def get_gpu_list(list_type):
    v = get_pref(list_type)
    log(f"get_gpu_list({list_type}) pref={v}")
    if not v:
        return None
    if "all" in v:
        return True
    if "none" in v:
        return []

    def dev(x):
        try:
            return int(x)
        except ValueError:
            return x.strip()

    try:
        return [dev(x) for x in v]
    except ValueError:
        log(f"get_gpu_list({list_type})", exc_info=True)
        log.error(f"Error: invalid value for {list_type!r} CUDA preference")
        return None


driver_init_done = None


def driver_init() -> bool:
    global driver_init_done
    if driver_init_done is None:
        log.info("CUDA initialization (this may take a few seconds)")
        try:
            init()
            driver_init_done = True
            log(f"CUDA driver version={get_driver_version()}")
            ngpus = Device.count()
            if ngpus == 0:
                cuda_v = ".".join(str(x) for x in get_version())
                log.info(f"CUDA {cuda_v} / PyCUDA {pycuda.VERSION_TEXT}, no devices found")
            driver_init_done = True
        except driver.LogicError as e:
            log("driver_init()", exc_info=True)
            log.warn("Warning: cannot initialize CUDA")
            log.warn(f" {e}")
            driver_init_done = False
        except Exception as e:
            log("driver_init()", exc_info=True)
            log.error("Error: cannot initialize CUDA")
            log.estr(e)
            driver_init_done = False
    return driver_init_done


DEVICES: list[int] | None = None


def init_all_devices() -> list[int]:
    global DEVICES, DEVICE_INFO
    if DEVICES is not None:
        return DEVICES
    DEVICES = []
    DEVICE_INFO = {}
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if disabled_gpus is True or enabled_gpus == []:
        log("all devices are disabled!")
        return DEVICES
    log(f"init_all_devices() enabled: {csv(enabled_gpus)}, disabled: %s", csv(disabled_gpus) or "none")
    if not driver_init():
        return DEVICES
    ngpus = Device.count()
    log(f"init_all_devices() ngpus={ngpus}")
    if ngpus == 0:
        return DEVICES
    for i in range(ngpus):
        # shortcut if this GPU number is disabled:
        if disabled_gpus is not None and i in disabled_gpus:
            log(f"device {i} is in the list of disabled gpus, skipped")
            continue
        devinfo = f"gpu {i}"
        try:
            device = Device(i)
            devinfo = device_info(device)
            log(" + testing device %s: %s", i, devinfo)
            DEVICE_NAME[i] = device_name(device)
            DEVICE_INFO[i] = devinfo
            if check_device(i, device):
                DEVICES.append(i)
        except Exception as e:
            log.error("error on device %s: %s", devinfo, e)
    return DEVICES


def check_device(i: int, device, min_compute: int = 0) -> bool:
    ngpus = Device.count()
    da = device_attribute
    devinfo = device_info(device)
    devname = device_name(device)
    pci = pci_bus_id(device)
    host_mem = device.get_attribute(da.CAN_MAP_HOST_MEMORY)
    if not host_mem:
        log.warn("skipping device %s (cannot map host memory)", devinfo)
        return False
    compute = compute_capability(device)
    if compute < min_compute:
        log("ignoring device %s: compute capability %#x (minimum %#x required)",
            device_info(device), compute, min_compute)
        return False
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if enabled_gpus not in (None, True):
        # check the enabled gpu list:
        if not any(x in enabled_gpus for x in (i, devname, pci)):
            log("device %i '%s' / '%s' is not in the list of enabled gpus, skipped", i, devname, pci)
            return False
    if disabled_gpus is not None and (devname in disabled_gpus or pci in disabled_gpus):
        log("device '%s' / '%s' is in the list of disabled gpus, skipped", i, devname, pci)
        return False
    cf = ctx_flags
    context = device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
    try:
        log("   created context=%s", context)
        log("   api version=%s", context.get_api_version())
        free, total = mem_get_info()
        log("   memory: free=%sMB, total=%sMB", int(free // 1024 // 1024), int(total // 1024 // 1024))
        log("   multi-processors: %s, clock rate: %s",
            device.get_attribute(da.MULTIPROCESSOR_COUNT), device.get_attribute(da.CLOCK_RATE))
        log("   max block sizes: (%s, %s, %s)",
            device.get_attribute(da.MAX_BLOCK_DIM_X),
            device.get_attribute(da.MAX_BLOCK_DIM_Y),
            device.get_attribute(da.MAX_BLOCK_DIM_Z),
            )
        log("   max grid sizes: (%s, %s, %s)",
            device.get_attribute(da.MAX_GRID_DIM_X),
            device.get_attribute(da.MAX_GRID_DIM_Y),
            device.get_attribute(da.MAX_GRID_DIM_Z),
            )
        max_width = device.get_attribute(da.MAXIMUM_TEXTURE2D_WIDTH)
        max_height = device.get_attribute(da.MAXIMUM_TEXTURE2D_HEIGHT)
        log("   maximum texture size: %sx%s", max_width, max_height)
        log("   max pitch: %s", device.get_attribute(da.MAX_PITCH))
        SMmajor, SMminor = device.compute_capability()
        compute = (SMmajor << 4) + SMminor
        log("   compute capability: %#x (%s.%s)", compute, SMmajor, SMminor)
        if i == 0:
            # we print the list info "header" from inside the loop
            # so that the log output is bunched up together
            log.info("CUDA %s / PyCUDA %s, found %s devices:",
                     ".".join([str(x) for x in get_version()]), pycuda.VERSION_TEXT, ngpus)
        mfree = round(100 * free / total)
        log.info(f"  + {device_info(device)} (memory: {mfree}% free, compute: {SMmajor}.{SMminor})")
        if SMmajor < 2:
            log.info("  this device is too old!")
            return False
        return True
    finally:
        context.pop()


def get_devices() -> list[int] | None:
    return DEVICES


def check_devices() -> None:
    devices = init_all_devices()
    assert devices, "no valid CUDA devices found!"


def reset_state() -> None:
    log("cuda_context.reset_state()")
    global DEVICE_STATE
    DEVICE_STATE = {}


def select_device(preferred_device_id=-1, min_compute=0) -> tuple[int, Any]:
    log("select_device(%s, %s)", preferred_device_id, min_compute)
    for device_id in (preferred_device_id, get_pref("device-id")):
        if device_id is not None and device_id >= 0:
            dct = make_device_context(device_id)
            if dct:
                device, context, tpct = dct
                context.pop()
                context.detach()
                if min_compute > 0:
                    compute = compute_capability(device)
                    if compute < min_compute:
                        log.warn("Warning: GPU device %i only supports compute %#x", device_id, compute)
                if tpct < MIN_FREE_MEMORY:
                    log.warn(f"Warning: GPU device {device_id} is low on memory: {tpct}%")
                return device_id, device
    load_balancing = get_pref("load-balancing")
    log("load-balancing=%s", load_balancing)
    if load_balancing == "round-robin":
        return select_round_robin(min_compute)
    if load_balancing and load_balancing != "memory" and first_time("cuda-load-balancing"):
        log.warn("Warning: invalid load balancing value '%s'", load_balancing)
    return select_best_free_memory(min_compute)


rr = 0


def select_round_robin(min_compute: int) -> tuple[int, Any]:
    if not driver_init():
        return -1, None
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if disabled_gpus is True or enabled_gpus == []:
        log("all devices are disabled!")
        return -1, None
    ngpus = Device.count()
    if ngpus == 0:
        return -1, None
    devices = list(range(ngpus))
    global rr
    i = rr
    device_id = 0
    device = None
    while devices:
        n = len(devices)
        i = (rr + 1) % n
        device_id = devices[i]
        device = Device(device_id)
        if check_device(device_id, device, min_compute):
            break
        devices.remove(device_id)
    rr = i
    return device_id, device


def select_best_free_memory(min_compute: int = 0) -> tuple[int, Any]:
    # load preferences:
    preferred_device_name = get_pref("device-name")
    devices = init_all_devices()
    free_pct = 0
    # split device list according to device state:
    ok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is True]
    nok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is not True]
    for list_name, device_list in {"OK": ok_devices, "failing": nok_devices}.items():
        selected_device_id = -1
        selected_device = None
        log("will test %s devices from %s list: %s", len(device_list), list_name, device_list)
        for device_id in device_list:
            context = None
            dct = make_device_context(device_id)
            if not dct:
                continue
            try:
                device, context, tpct = dct
                compute = compute_capability(device)
                if compute < min_compute:
                    log("ignoring device %s: compute capability %#x (minimum %#x required)",
                        device_info(device), compute, min_compute)
                elif preferred_device_name and device_info(device).find(preferred_device_name) >= 0:
                    log("device matches preferred device name: %s", preferred_device_name)
                    return device_id, device
                elif tpct >= MIN_FREE_MEMORY and tpct > free_pct:
                    log("device has enough free memory: %i (min=%i, current best device=%i)",
                        tpct, MIN_FREE_MEMORY, free_pct)
                    selected_device = device
                    selected_device_id = device_id
                    free_pct = tpct
            finally:
                if context:
                    context.pop()
                    context.detach()
        if selected_device_id >= 0 and selected_device:
            log_fn = log.info if len(devices) > 1 else log.debug
            log_fn("selected device %s: %s", selected_device_id, device_info(selected_device))
            return selected_device_id, selected_device
    return -1, None


def load_device(device_id: int):
    log("load_device(%i)", device_id)
    try:
        return Device(device_id)
    except Exception as e:
        log("load_device(%s)", device_id, exc_info=True)
        log.error("Error: allocating CUDA device %s", device_id)
        log.estr(e)
    return None


def make_device_context(device_id: int) -> tuple:
    log(f"make_device_context({device_id}")
    device = load_device(device_id)
    if not device:
        return ()
    log(f"make_device_context({device_id}) device_info={device_info(device)}")
    cf = ctx_flags
    flags = cf.SCHED_YIELD | cf.MAP_HOST
    try:
        context = device.make_context(flags=flags)
    except Exception as e:
        log(f"{device}.make_context({flags:x})", exc_info=True)
        log.error(f"Error: cannot create CUDA context for device {device_id}")
        log.estr(e)
        return ()
    log(f"created context={context}")
    free, total = mem_get_info()
    log("memory: free=%sMB, total=%sMB", int(free / 1024 / 1024), int(total / 1024 / 1024))
    tpct = 100 * free // total
    return device, context, tpct


def get_device_context(options: typedict):
    MIN_COMPUTE = 0x30
    device_id, device = select_device(options.intget("cuda_device", -1), min_compute=MIN_COMPUTE)
    if device_id < 0 or not device:
        return None
    return cuda_device_context(device_id, device)


default_device_context: object | None = None


def get_default_device_context():
    global default_device_context
    if default_device_context is None:
        start = monotonic()
        cuda_device_id, cuda_device = select_device()
        if cuda_device_id < 0 or not cuda_device:
            raise RuntimeError("failed to select a cuda device")
        log("using device %s", cuda_device)
        default_device_context = cuda_device_context(cuda_device_id, cuda_device)
        end = monotonic()
        log("default device context init took %.1fms", 1000 * (end - start))
    return default_device_context


def free_default_device_context() -> None:
    global default_device_context
    ddc = default_device_context
    default_device_context = None
    if ddc:
        ddc.free()


class cuda_device_context:
    __slots__ = ("device_id", "device", "context", "lock", "opengl")

    def __init__(self, device_id: int, device, opengl=False):
        assert device, "no cuda device"
        self.device_id = device_id
        self.device = device
        self.opengl = opengl
        self.context = None
        self.lock = RLock()
        log("%r", self)

    def __bool__(self):
        return self.device is not None

    def __enter__(self):
        if not self.lock.acquire(False):
            raise TransientCodecException("failed to acquire cuda device lock")
        if not self.context:
            self.make_context()
        return self.push_context()

    def make_context(self) -> None:
        start = monotonic()
        if self.opengl:
            with numpy_import_context("CUDA make context"):
                from pycuda import gl  # @UnresolvedImport pylint: disable=import-outside-toplevel
                self.context = gl.make_context(self.device)
        else:
            self.context = self.device.make_context(flags=ctx_flags.SCHED_YIELD | ctx_flags.MAP_HOST)
        end = monotonic()
        self.context.pop()
        log("cuda context allocation took %ims", 1000 * (end - start))

    def push_context(self):
        self.context.push()
        return self.context

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.pop_context()
        self.lock.release()

    def pop_context(self) -> None:
        c = self.context
        if c:
            c.pop()
        # except driver.LogicError as e:
        # log.warn("Warning: PyCUDA %s", e)
        # self.clean()
        # self.init_cuda()

    def __repr__(self):
        extra = " - locked" if self.lock._is_owned() else ""
        return f"cuda_device_context({self.device_id}{extra})"

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "id": self.device_id,
            "device": {
                "name": self.device.name(),
                "pci_bus_id": self.device.pci_bus_id(),
                "memory": int(self.device.total_memory() // 1024 // 1024),
            },
            "opengl": self.opengl,
        }
        if self.context:
            info["api_version"] = self.context.get_api_version()
        return info

    def __del__(self):
        self.free()

    def free(self) -> None:
        c = self.context
        if log:
            log("free() context=%s", c)
        if c:
            self.device_id = 0
            self.device = None
            self.context = None
            with self.lock:
                c.detach()


# cache kernel fatbin files:
KERNELS: dict[str, bytes] = {}


def get_CUDA_function(function_name: str):
    """
        Returns the compiled kernel for the given device
        and kernel key.
    """
    data = KERNELS.get(function_name)
    if data is None:
        cubin_file = os.path.join(get_resources_dir(), "cuda", f"{function_name}.fatbin")
        log(f"get_CUDA_function({function_name}) cubin file={cubin_file!r}")
        if not os.path.exists(cubin_file):
            log.error(f"Error: failed to load CUDA bin file {cubin_file!r}")
            log.error(" this file does not exist")
            return None
        data = load_binary_file(cubin_file)
        if not data:
            log.error(f"Error: failed to load CUDA bin file {cubin_file!r}")
            return None
        log(f" loaded {len(data)} bytes")
        KERNELS[function_name] = data
    # now load from cubin:
    start = monotonic()
    try:
        mod = module_from_buffer(data)
    except Exception as e:
        log(f"module_from_buffer({data})", exc_info=True)
        log.error(f"Error: failed to load module from buffer for {function_name!r}")
        log.estr(e)
        return None
    log(f"get_CUDA_function({function_name}) module={mod}")
    try:
        fn = function_name
        CUDA_function = mod.get_function(fn)
    except LogicError as e:
        raise ValueError(f"failed to load {function_name!r} from {mod}: {e}") from None
    end = monotonic()
    log(f"loading function {function_name!r} from pre-compiled cubin took %.1fms", 1000.0 * (end - start))
    return CUDA_function


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("CUDA-Info", "CUDA Info"):
        consume_verbose_argv(sys.argv, "cuda")
        pycuda_info = get_pycuda_info()
        log.info("pycuda_info")
        print_nested_dict(pycuda_info, print_fn=log.info)
        log.info("cuda_info")
        print_nested_dict(get_cuda_info(), print_fn=log.info)
        log.info("preferences:")
        print_nested_dict(get_prefs(), print_fn=log.info)
        log.info("device automatically selected:")
        log.info(" %s", device_info(select_device()[1]))


if __name__ == "__main__":
    main()
