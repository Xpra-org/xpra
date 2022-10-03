#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore
#pylint: disable=no-member

import os
from time import monotonic
from threading import RLock
import threading

from xpra.codecs.nv_util import numpy_import_lock
from xpra.codecs.codec_constants import TransientCodecException
from xpra.util import engs, print_nested_dict, envint, csv, first_time
from xpra.platform.paths import (
    get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs,
    get_resources_dir,
    )
from xpra.os_util import load_binary_file
from xpra.log import Logger

with numpy_import_lock:
    import pycuda               #@UnresolvedImport
    from pycuda import driver   #@UnresolvedImport

log = Logger("cuda")

MIN_FREE_MEMORY = envint("XPRA_CUDA_MIN_FREE_MEMORY", 10)

#record when we get failures/success:
DEVICE_STATE = {}

def record_device_failure(device_id):
    DEVICE_STATE[device_id] = False

def record_device_success(device_id):
    DEVICE_STATE[device_id] = True


def device_info(d):
    if not d:
        return "None"
    return f"{d.name()} @ {d.pci_bus_id()}"

def pci_bus_id(d):
    if not d:
        return "None"
    return d.pci_bus_id()

def device_name(d):
    if not d:
        return "None"
    return d.name()

def compute_capability(d):
    SMmajor, SMminor = d.compute_capability()
    return (SMmajor<<4) + SMminor


def get_pycuda_version():
    return pycuda.VERSION


def get_pycuda_info():
    init_all_devices()
    i = {
        "version" : {
            ""        : pycuda.VERSION,
            "text"    : pycuda.VERSION_TEXT,
            }
        }
    if pycuda.VERSION_STATUS:
        i["version.status"] = pycuda.VERSION_STATUS
    return i

def get_cuda_info():
    init_all_devices()
    return {
        "driver"    : {
            "version"        : driver.get_version(),
            "driver_version" : driver.get_driver_version(),
            }
        }


DEVICE_INFO = {}
def get_device_info(i):
    return DEVICE_INFO.get(i, None)
DEVICE_NAME = {}
def get_device_name(i):
    return DEVICE_NAME.get(i, None)


PREFS = None
def get_prefs():
    global PREFS
    if PREFS is None:
        PREFS = {}
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
            try:
                c_prefs = {}
                with open(conf_file, "rb") as f:
                    for line in f:
                        sline = line.strip().rstrip(b'\r\n').strip().decode("latin1")
                        props = sline.split("=", 1)
                        if len(props)!=2:
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
            PREFS.update(c_prefs)
    return PREFS

def get_pref(name):
    assert name in ("device-id", "device-name", "enabled-devices", "disabled-devices", "load-balancing")
    #ie: env_name("device-id")="XPRA_CUDA_DEVICE_ID"
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
def driver_init():
    global driver_init_done
    if driver_init_done is None:
        log.info("CUDA initialization (this may take a few seconds)")
        try:
            driver.init()
            driver_init_done = True
            log(f"CUDA driver version={driver.get_driver_version()}")
            ngpus = driver.Device.count()
            if ngpus==0:
                cuda_v = ".".join(str(x) for x in driver.get_version())
                log.info(f"CUDA {cuda_v} / PyCUDA {pycuda.VERSION_TEXT}, no devices found")
            driver_init_done = True
        except Exception as e:
            log("driver_init()", exc_info=True)
            log.warn("Warning: cannot initialize CUDA")
            log.warn(f" {e}")
            driver_init_done = False
    return driver_init_done


DEVICES = None
def init_all_devices():
    global DEVICES, DEVICE_INFO
    if DEVICES is not None:
        return DEVICES
    DEVICES = []
    DEVICE_INFO = {}
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if disabled_gpus is True or enabled_gpus==[]:
        log("all devices are disabled!")
        return DEVICES
    log(f"init_all_devices() enabled: {csv(enabled_gpus)}, disabled: %s", csv(disabled_gpus) or "none")
    if not driver_init():
        return DEVICES
    ngpus = driver.Device.count()
    log(f"init_all_devices() ngpus={ngpus}")
    if ngpus==0:
        return DEVICES
    for i in range(ngpus):
        #shortcut if this GPU number is disabled:
        if disabled_gpus is not None and i in disabled_gpus:
            log(f"device {i} is in the list of disabled gpus, skipped")
            continue
        device = None
        devinfo = f"gpu {i}"
        try:
            device = driver.Device(i)
            devinfo = device_info(device)
            log(" + testing device %s: %s", i, devinfo)
            DEVICE_NAME[i] = device_name(device)
            DEVICE_INFO[i] = devinfo
            if check_device(i, device):
                DEVICES.append(i)
        except Exception as e:
            log.error("error on device %s: %s", devinfo, e)
    return DEVICES

def check_device(i, device, min_compute=0):
    ngpus = driver.Device.count()
    da = driver.device_attribute
    devinfo = device_info(device)
    devname = device_name(device)
    pci = pci_bus_id(device)
    host_mem = device.get_attribute(da.CAN_MAP_HOST_MEMORY)
    if not host_mem:
        log.warn("skipping device %s (cannot map host memory)", devinfo)
        return False
    compute = compute_capability(device)
    if compute<min_compute:
        log("ignoring device %s: compute capability %#x (minimum %#x required)",
            device_info(device), compute, min_compute)
        return False
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if enabled_gpus not in (None, True) and \
        i not in enabled_gpus and devname not in enabled_gpus and pci not in enabled_gpus:
        log("device %i '%s' / '%s' is not in the list of enabled gpus, skipped", i, devname, pci)
        return False
    if disabled_gpus is not None and (devname in disabled_gpus or pci in disabled_gpus):
        log("device '%s' / '%s' is in the list of disabled gpus, skipped", i, devname, pci)
        return False
    cf = driver.ctx_flags
    context = device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
    try:
        log("   created context=%s", context)
        log("   api version=%s", context.get_api_version())
        free, total = driver.mem_get_info()
        log("   memory: free=%sMB, total=%sMB",  int(free//1024//1024), int(total//1024//1024))
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
        compute = (SMmajor<<4) + SMminor
        log("   compute capability: %#x (%s.%s)", compute, SMmajor, SMminor)
        if i==0:
            #we print the list info "header" from inside the loop
            #so that the log output is bunched up together
            log.info("CUDA %s / PyCUDA %s, found %s device%s:",
                     ".".join([str(x) for x in driver.get_version()]), pycuda.VERSION_TEXT, ngpus, engs(ngpus))
        log.info("  + %s (memory: %s%% free, compute: %s.%s)",
                 device_info(device), 100*free//total, SMmajor, SMminor)
        if SMmajor<2:
            log.info("  this device is too old!")
            return False
        return True
    finally:
        context.pop()


def get_devices():
    return DEVICES

def check_devices():
    devices = init_all_devices()
    assert devices, "no valid CUDA devices found!"


def reset_state():
    log("cuda_context.reset_state()")
    global DEVICE_STATE
    DEVICE_STATE = {}


def select_device(preferred_device_id=-1, min_compute=0):
    log("select_device(%s, %s)", preferred_device_id, min_compute)
    for device_id in (preferred_device_id, get_pref("device-id")):
        if device_id is not None and device_id>=0:
            dct = make_device_context(device_id)
            if dct:
                device, context, tpct = dct
                context.pop()
                context.detach()
                if min_compute>0:
                    compute = compute_capability(device)
                    if compute<min_compute:
                        log.warn("Warning: GPU device %i only supports compute %#x", device_id, compute)
                if tpct<MIN_FREE_MEMORY:
                    log.warn("Warning: GPU device %i is low on memory: %i%%", device_id, tpct)
                return device_id, device
    load_balancing = get_pref("load-balancing")
    log("load-balancing=%s", load_balancing)
    if load_balancing=="round-robin":
        return select_round_robin(min_compute)
    if load_balancing!="memory" and first_time("cuda-load-balancing"):
        log.warn("Warning: invalid load balancing value '%s'", load_balancing)
    return select_best_free_memory(min_compute)

rr = 0
def select_round_robin(min_compute):
    if not driver_init():
        return -1, None
    enabled_gpus = get_gpu_list("enabled-devices")
    disabled_gpus = get_gpu_list("disabled-devices")
    if disabled_gpus is True or enabled_gpus==[]:
        log("all devices are disabled!")
        return -1, None
    ngpus = driver.Device.count()
    if ngpus==0:
        return -1, None
    devices = list(range(ngpus))
    global rr
    i = rr
    while devices:
        n = len(devices)
        i = (rr+1) % n
        device_id = devices[i]
        device = driver.Device(device_id)
        if check_device(device_id, device, min_compute):
            break
        devices.remove(device_id)
    rr = i
    return device_id, device


def select_best_free_memory(min_compute=0):
    #load preferences:
    preferred_device_name = get_pref("device-name")
    devices = init_all_devices()
    free_pct = 0
    #split device list according to device state:
    ok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is True]
    nok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is not True]
    for list_name, device_list in {"OK" : ok_devices, "failing" : nok_devices}.items():
        selected_device_id = -1
        selected_device = None
        log("will test %s device%s from %s list: %s", len(device_list), engs(device_list), list_name, device_list)
        for device_id in device_list:
            context = None
            dct = make_device_context(device_id)
            if not dct:
                continue
            try:
                device, context, tpct = dct
                compute = compute_capability(device)
                if compute<min_compute:
                    log("ignoring device %s: compute capability %#x (minimum %#x required)",
                        device_info(device), compute, min_compute)
                elif preferred_device_name and device_info(device).find(preferred_device_name)>=0:
                    log("device matches preferred device name: %s", preferred_device_name)
                    return device_id, device
                elif tpct>=MIN_FREE_MEMORY and tpct>free_pct:
                    log("device has enough free memory: %i (min=%i, current best device=%i)",
                        tpct, MIN_FREE_MEMORY, free_pct)
                    selected_device = device
                    selected_device_id = device_id
                    free_pct = tpct
            finally:
                if context:
                    context.pop()
                    context.detach()
        if selected_device_id>=0 and selected_device:
            l = log
            if len(devices)>1:
                l = log.info
            l("selected device %s: %s", selected_device_id, device_info(selected_device))
            return selected_device_id, selected_device
    return -1, None

def load_device(device_id):
    log("load_device(%i)", device_id)
    try:
        return driver.Device(device_id)
    except Exception as e:
        log("load_device(%s)", device_id, exc_info=True)
        log.error("Error: allocating CUDA device %s", device_id)
        log.error(" %s", e)
    return None

def make_device_context(device_id):
    log(f"make_device_context({device_id}")
    device = load_device(device_id)
    if not device:
        return None
    log(f"make_device_context({device_id}) device_info={device_info(device)}")
    cf = driver.ctx_flags
    flags = cf.SCHED_YIELD | cf.MAP_HOST
    try:
        context = device.make_context(flags=flags)
    except Exception as e:
        log(f"{device}.make_context({flags:x})", exc_info=True)
        log.error(f"Error: cannot create CUDA context for device {device_id}")
        log.estr(e)
        return None
    log(f"created context={context}")
    free, total = driver.mem_get_info()
    log("memory: free=%sMB, total=%sMB",  int(free/1024/1024), int(total/1024/1024))
    tpct = 100*free//total
    return device, context, tpct


def get_device_context(options):
    MIN_COMPUTE = 0x30
    device_id, device = select_device(options.intget("cuda_device", -1), min_compute=MIN_COMPUTE)
    if device_id<0 or not device:
        return None
    return cuda_device_context(device_id, device)


class cuda_device_context:
    __slots__ = ("device_id", "device", "context", "lock", "opengl", "instances_to_cleanup", "owning_thread_id", "queue_destruction")
    def __init__(self, device_id, device, opengl=False):
        assert device, "no cuda device"
        self.device_id = device_id
        self.device = device
        self.opengl = opengl
        self.context = None
        self.lock = RLock()
        self.instances_to_cleanup = []
        self.owning_thread_id = 0
        self.queue_destruction = False
        log("%r", self)

    def __bool__(self):
        return self.device is not None

    def __enter__(self):
        if not self.lock.acquire(False):
            raise TransientCodecException("failed to acquire cuda device lock")
        if not self.context:
            self.make_context()
        return self.push_context()

    def make_context(self):
        start = monotonic()
        cf = driver.ctx_flags
        if self.opengl:
            with numpy_import_lock:
                from pycuda import gl  # @UnresolvedImport pylint: disable=import-outside-toplevel
                self.context = gl.make_context(self.device)
        else:
            self.context = self.device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
        end = monotonic()
        self.context.pop()
        self.owning_thread_id = threading.current_thread().ident
        log("cuda context allocation took %ims", 1000*(end-start))

    def push_context(self):
        self.context.push()
        return self.context

    def __exit__(self, exc_type, exc_val, exc_tb):
        log("cuda context deallocation start")
        self.pop_context()
        self.lock.release()
        log("cuda context deallocation end")
        if self.queue_destruction:
            self.destroy_cuda_context()

    def pop_context(self):
        c = self.context
        if c:
            log("cuda context exists, popping")
            c.pop()
        #except driver.LogicError as e:
        #log.warn("Warning: PyCUDA %s", e)
        #self.clean()
        #self.init_cuda()


    def __repr__(self):
        return f"cuda_device_context({self.device_id} - {self.lock._is_owned()}, has_context:{bool(self.context)}, instances_to_cleanup:{len(self.instances_to_cleanup)})"

    def get_info(self):
        info = {
            "id" : self.device_id,
            "device" : {
                "name"         : self.device.name(),
                "pci_bus_id"   : self.device.pci_bus_id(),
                "memory"       : int(self.device.total_memory()//1024//1024),
                },
            "opengl"    : self.opengl,
            }
        if self.context:
            info["api_version"] = self.context.get_api_version()
        return info

    def add_cleanup_instance(self, inst):
        self.instances_to_cleanup.append(inst)

    def remove_cleanup_instance(self, inst):
        if inst in self.instances_to_cleanup:
            self.instances_to_cleanup.remove(inst)

    def __del__(self):
        log("cuda_context() del called")
        self.free()

    def free(self):
        log("free() context=%s", self.context)
        
        log("Freeing cleanup instances: %s", self.instances_to_cleanup)
        instances_to_cleanup = self.instances_to_cleanup[:]
        for i in range(len(instances_to_cleanup)):
            log(" - instance num: %i", i)
            instances_to_cleanup[i].clean_instance()
        instances_to_cleanup = []
        self.instances_to_cleanup = []

        if self.owning_thread_id == threading.current_thread().ident:
            log("cuda_context owning thread is this thread, immediately destroying")
            self.destroy_cuda_context()
        else:
            log("need to queue cuda destruction for later by encoding thread")
            self.queue_destruction = True


        c = self.context
        if c:
            log("cuda free(): found context")
            try:
                c.synchronize()
            except pycuda.driver.LogicError:
                log("got excpetion at synchronize, continuing")
        log("cuda free() done")

    def destroy_cuda_context(self):
        log("destroy_cuda_context()")
        assert self.owning_thread_id == threading.current_thread().ident, "attempting to cleanup cuda_device_context from wrong thread"

        self.device_id = 0
        self.device = None
        self.context = None
        self.owning_thread_id = 0

        c = self.context
        if c:
            with self.lock:
                c.detach()
        log("destroy_cuda_context() done")

CUDA_ERRORS_INFO = {
    #this list is taken from the CUDA 7.0 SDK header file,
    #so we don't have to build against CUDA (lacks pkgconfig anyway)
    #and so we don't have to worry about which version of the SDK we link against either
    0   : "SUCCESS",
    1   : "INVALID_VALUE",
    2   : "OUT_OF_MEMORY",
    3   : "NOT_INITIALIZED",
    4   : "DEINITIALIZED",
    5   : "PROFILER_DISABLED",
    6   : "PROFILER_NOT_INITIALIZED",
    7   : "PROFILER_ALREADY_STARTED",
    8   : "PROFILER_ALREADY_STOPPED",
    100 : "NO_DEVICE",
    101 : "INVALID_DEVICE",
    200 : "INVALID_IMAGE",
    201 : "INVALID_CONTEXT",
    202 : "CONTEXT_ALREADY_CURRENT",
    205 : "MAP_FAILED",
    206 : "UNMAP_FAILED",
    207 : "ARRAY_IS_MAPPED",
    208 : "ALREADY_MAPPED",
    209 : "NO_BINARY_FOR_GPU",
    210 : "ALREADY_ACQUIRED",
    211 : "NOT_MAPPED",
    212 : "NOT_MAPPED_AS_ARRAY",
    213 : "NOT_MAPPED_AS_POINTER",
    214 : "ECC_UNCORRECTABLE",
    215 : "UNSUPPORTED_LIMIT",
    216 : "CONTEXT_ALREADY_IN_USE",
    217 : "PEER_ACCESS_UNSUPPORTED",
    218 : "INVALID_PTX",
    219 : "INVALID_GRAPHICS_CONTEXT",
    300 : "INVALID_SOURCE",
    301 : "FILE_NOT_FOUND",
    302 : "SHARED_OBJECT_SYMBOL_NOT_FOUND",
    303 : "SHARED_OBJECT_INIT_FAILED",
    304 : "OPERATING_SYSTEM",
    400 : "INVALID_HANDLE",
    500 : "NOT_FOUND",
    600 : "NOT_READY",
    700 : "ILLEGAL_ADDRESS",
    701 : "LAUNCH_OUT_OF_RESOURCES",
    702 : "LAUNCH_TIMEOUT",
    703 : "LAUNCH_INCOMPATIBLE_TEXTURING",
    704 : "PEER_ACCESS_ALREADY_ENABLED",
    705 : "PEER_ACCESS_NOT_ENABLED",
    708 : "PRIMARY_CONTEXT_ACTIVE",
    709 : "CONTEXT_IS_DESTROYED",
    710 : "ASSERT",
    711 : "TOO_MANY_PEERS",
    712 : "HOST_MEMORY_ALREADY_REGISTERED",
    713 : "HOST_MEMORY_NOT_REGISTERED",
    714 : "HARDWARE_STACK_ERROR",
    715 : "ILLEGAL_INSTRUCTION",
    716 : "MISALIGNED_ADDRESS",
    717 : "INVALID_ADDRESS_SPACE",
    718 : "INVALID_PC",
    719 : "LAUNCH_FAILED",
    800 : "NOT_PERMITTED",
    801 : "NOT_SUPPORTED",
    999 : "UNKNOWN",
     }


#cache kernel fatbin files:
KERNELS = {}
def get_CUDA_function(function_name):
    """
        Returns the compiled kernel for the given device
        and kernel key.
    """
    data = KERNELS.get(function_name)
    if data is None:
        cubin_file = os.path.join(get_resources_dir(), "cuda", f"{function_name}.fatbin")
        log(f"get_CUDA_function({function_name}) cubin file={cubin_file!r}")
        data = load_binary_file(cubin_file)
        if not data:
            log.error(f"Error: failed to load CUDA bin file {cubin_file!r}")
            return None
        log(f" loaded {len(data)} bytes")
        KERNELS[function_name] = data
    #now load from cubin:
    start = monotonic()
    try:
        mod = driver.module_from_buffer(data)
    except Exception as e:
        log(f"module_from_buffer({data})", exc_info=True)
        log.error(f"Error: failed to load module from buffer for {function_name!r}")
        log.estr(e)
        return None
    log(f"get_CUDA_function({function_name}) module={mod}")
    try:
        fn = function_name
        CUDA_function = mod.get_function(fn)
    except driver.LogicError as e:
        raise Exception(f"failed to load {function_name!r} from {mod}: {e}") from None
    end = monotonic()
    log(f"loading function {function_name!r} from pre-compiled cubin took %.1fms", 1000.0*(end-start))
    return CUDA_function


def main():
    # pylint: disable=import-outside-toplevel
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("CUDA-Info", "CUDA Info"):
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
