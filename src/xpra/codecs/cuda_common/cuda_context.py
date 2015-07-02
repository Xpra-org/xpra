#@PydevCodeAnalysisIgnore
#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#Not sure why force builtins fails on PyCUDA but not on PyOpenCL...

from xpra.log import Logger
log = Logger("csc", "cuda")

import os
import time
import pycuda
from pycuda import driver
from pycuda import tools
from pycuda.compiler import compile


CUDA_DEVICE_ID = int(os.environ.get("XPRA_CUDA_DEVICE", "-1"))
CUDA_DEVICE_NAME = os.environ.get("XPRA_CUDA_DEVICE_NAME", "")


#record when we get failures/success:
DEVICE_STATE = {}

def record_device_failure(device_id):
    global DEVICE_STATE
    DEVICE_STATE[device_id] = False

def record_device_success(device_id):
    global DEVICE_STATE
    DEVICE_STATE[device_id] = True


def device_info(d):
    if not d:
        return "None"
    return "%s @ %s" % (d.name(), d.pci_bus_id())

def get_pycuda_version():
    return pycuda.VERSION


def get_pycuda_info():
    init_all_devices()
    return {"version"               : pycuda.VERSION,
            "version.text"          : pycuda.VERSION_TEXT,
            "version.status"        : pycuda.VERSION_STATUS,
            "driver.version"        : driver.get_version(),
            "driver.driver_version" : driver.get_driver_version()}


DEVICE_INFO = {}
def get_device_info(i):
    global DEVICE_INFO
    return DEVICE_INFO.get(i, None)

DEVICES = None
def init_all_devices():
    global DEVICES, DEVICE_INFO
    if DEVICES is not None:
        return  DEVICES
    log.info("CUDA initialization (this may take a few seconds)")
    driver.init()
    DEVICES = []
    DEVICE_INFO = {}
    log("CUDA driver version=%s", driver.get_driver_version())
    ngpus = driver.Device.count()
    log.info("CUDA %s / PyCUDA %s, found %s device(s):", ".".join([str(x) for x in driver.get_version()]), pycuda.VERSION_TEXT, ngpus)
    da = driver.device_attribute
    cf = driver.ctx_flags
    for i in range(ngpus):
        device = None
        context = None
        try:
            device = driver.Device(i)
            log(" + testing device %s: %s", i, device_info(device))
            DEVICE_INFO[i] = device_info(device)
            host_mem = device.get_attribute(da.CAN_MAP_HOST_MEMORY)
            if not host_mem:
                log.warn("skipping device %s (cannot map host memory)", device_info(device))
                continue
            context = device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
            log("   created context=%s", context)
            log("   api version=%s", context.get_api_version())
            free, total = driver.mem_get_info()
            log("   memory: free=%sMB, total=%sMB",  int(free/1024/1024), int(total/1024/1024))
            log("   multi-processors: %s, clock rate: %s", device.get_attribute(da.MULTIPROCESSOR_COUNT), device.get_attribute(da.CLOCK_RATE))
            log("   max block sizes: (%s, %s, %s)", device.get_attribute(da.MAX_BLOCK_DIM_X), device.get_attribute(da.MAX_BLOCK_DIM_Y), device.get_attribute(da.MAX_BLOCK_DIM_Z))
            log("   max grid sizes: (%s, %s, %s)", device.get_attribute(da.MAX_GRID_DIM_X), device.get_attribute(da.MAX_GRID_DIM_Y), device.get_attribute(da.MAX_GRID_DIM_Z))
            max_width = device.get_attribute(da.MAXIMUM_TEXTURE2D_WIDTH)
            max_height = device.get_attribute(da.MAXIMUM_TEXTURE2D_HEIGHT)
            log("   maximum texture size: %sx%s", max_width, max_height)
            log("   max pitch: %s", device.get_attribute(da.MAX_PITCH))
            SMmajor, SMminor = device.compute_capability()
            compute = (SMmajor<<4) + SMminor
            log("   compute capability: %#x (%s.%s)", compute, SMmajor, SMminor)
            try:
                DEVICES.append(i)
                log.info("  + %s (memory: %s%% free, compute: %s.%s)", device_info(device), 100*free/total, SMmajor, SMminor)
            finally:
                context.pop()
        except Exception as e:
            log.error("error on device %s: %s", (device or i), e)
    return DEVICES

def get_devices():
    global DEVICES
    return DEVICES

def check_devices():
    devices = init_all_devices()
    assert len(devices)>0, "no valid CUDA devices found!"


def reset_state():
    log("cuda_context.reset_state()")
    global DEVICE_STATE
    DEVICES = None


def select_device(preferred_device_id=-1, preferred_device_name=CUDA_DEVICE_NAME, min_compute=0):
    if preferred_device_id<0 and CUDA_DEVICE_ID>=0:
        preferred_device_id = CUDA_DEVICE_ID
    devices = init_all_devices()
    global DEVICE_STATE
    free_pct = 0
    cf = driver.ctx_flags
    #split device list according to device state:
    ok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is True]
    nok_devices = [device_id for device_id in devices if DEVICE_STATE.get(device_id, True) is not True]
    for list_name, device_list in {"OK" : ok_devices, "failing" : nok_devices}.items():
        selected_device_id = None
        selected_device = None
        log("will test %s devices from %s list: %s", len(device_list), list_name, device_list)
        for device_id in device_list:
            context = None
            try:
                device = driver.Device(device_id)
                log("select_device: testing device %s: %s", device_id, device_info(device))
                context = device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
                log("created context=%s", context)
                free, total = driver.mem_get_info()
                log("memory: free=%sMB, total=%sMB",  int(free/1024/1024), int(total/1024/1024))
                tpct = 100*free/total
                SMmajor, SMminor = device.compute_capability()
                compute = (SMmajor<<4) + SMminor
                if compute<min_compute:
                    log("ignoring device %s: compute capability %#x (minimum %#x required)", device_info(device), compute, min_compute)
                elif device_id==preferred_device_id:
                    l = log
                    if len(device_list)>1:
                        l = log.info
                    l("device matches preferred device id %s: %s", preferred_device_id, device_info(device))
                    return device_id, device
                elif preferred_device_name and device_info(device).find(preferred_device_name)>=0:
                    log("device matches preferred device name: %s", preferred_device_name)
                    return device_id, device
                elif tpct>free_pct:
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
            l("selected device %s: %s", device_id, device_info(device))
            return selected_device_id, selected_device
    return -1, None


#cache kernel fatbin files:
KERNELS = {}
def get_CUDA_function(device_id, function_name):
    """
        Returns the compiled kernel for the given device
        and kernel key.
    """
    global KERNELS
    data = KERNELS.get(function_name)
    if data is None:
        from xpra.platform.paths import default_get_app_dir
        from xpra.os_util import load_binary_file
        cubin_file = os.path.join(default_get_app_dir(), "cuda", "%s.fatbin" % function_name)
        log("get_CUDA_function(%s, %s) cubin file=%s", device_id, function_name, cubin_file)
        data = load_binary_file(cubin_file)
        if not data:
            log.error("failed to load CUDA bin file %s", cubin_file)
            return None
        log(" loaded %s bytes", len(data))
        KERNELS[function_name] = data
    #now load from cubin:
    start = time.time()
    mod = driver.module_from_buffer(data)
    log("get_CUDA_function(%s, %s) module=%s", device_id, function_name, mod)
    try:
        CUDA_function = mod.get_function(function_name)
    except driver.LogicError as e:
        raise Exception("failed to load '%s' from %s: %s" % (function_name, mod, e))
    end = time.time()
    log("loading function %s from pre-compiled cubin took %.1fms", function_name, 1000.0*(end-start))
    return CUDA_function


def main():
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    log.info("pycuda_info: %s" % get_pycuda_info())

    if sys.platform.startswith("win"):
        print("\nPress Enter to close")
        sys.stdin.readline()


if __name__ == "__main__":
    main()
