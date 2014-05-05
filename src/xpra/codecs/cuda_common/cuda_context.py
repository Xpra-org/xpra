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
assert bytearray
import pycuda
from pycuda import driver
from pycuda import tools
from pycuda.compiler import compile


DEFAULT_CUDA_DEVICE_ID = int(os.environ.get("XPRA_CUDA_DEVICE", "-1"))


#record when we get failures/success:
DEVICE_STATE = {}

def record_device_failure(device_id):
    global DEVICE_STATE
    DEVICE_STATE[device_id] = False

def record_device_success(device_id):
    global DEVICE_STATE
    DEVICE_STATE[device_id] = True


def device_info(d):
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


DEVICES = None
def init_all_devices():
    global DEVICES
    if DEVICES is not None:
        return  DEVICES
    log.info("CUDA initialization (this may take a few seconds)")
    driver.init()
    DEVICES = []
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
        except Exception, e:
            log.error("error on device %s: %s", (device or i), e)
    return DEVICES

def check_devices():
    devices = init_all_devices()
    assert len(devices)>0, "no valid CUDA devices found!"


def reset_state():
    log("cuda_context.reset_state()")
    global DEVICE_STATE
    DEVICES = None


def select_device(preferred_device_id=DEFAULT_CUDA_DEVICE_ID, min_compute=0):
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
                    return device_id, device
                elif tpct>free_pct:
                    selected_device = device
                    selected_device_id = device_id
            finally:
                if context:
                    context.pop()
                    context.detach()
        if selected_device_id>=0 and selected_device:
            log("select device: %s / %s", device_id, device)
            return selected_device_id, selected_device
    return None, None


#cache pre-compiled kernel cubins per device:
KERNEL_cubins = {}
def get_CUDA_function(device_id, function_name, kernel_source):
    """
        Returns the compiled kernel for the given device
        and kernel key.
        Kernels may be pre-compiled with compile_all.
    """
    global KERNEL_cubins
    cubin = KERNEL_cubins.get((device_id, function_name))
    if cubin is None:
        start = time.time()
        log("compiling for device %s: %s=%s", device_id, function_name, kernel_source)
        cubin = compile(kernel_source)
        KERNEL_cubins[(device_id, function_name)] = cubin
        end = time.time()
        log("compilation of %s took %.1fms", function_name, 1000.0*(end-start))
    #now load from cubin:
    start = time.time()
    mod = driver.module_from_buffer(cubin)
    CUDA_function = mod.get_function(function_name)
    end = time.time()
    log("loading function %s from pre-compiled cubin took %.1fms", function_name, 1000.0*(end-start))
    return CUDA_function


def recompile_all(function_name, kernel_src, device_ids=None):
    global KERNEL_cubins
    KERNEL_cubins = {}
    tools.clear_context_caches()
    compile_all(function_name, kernel_src, device_ids)

def compile_all(function_name, kernel_src, device_ids=None):
    """
        Pre-compiles kernel source on the given devices,
        so we can then call get_CUDA_function quickly
        to get the function to call.
    """
    global KERNEL_cubins
    if device_ids is None:
        device_ids = init_all_devices()
    cf = driver.ctx_flags
    for device_id in device_ids:
        device = None
        context = None
        try:
            device = driver.Device(device_id)
            context = device.make_context(flags=cf.SCHED_YIELD | cf.MAP_HOST)
            cubin = KERNEL_cubins.get((device_id, function_name))
            if cubin is None:
                start = time.time()
                log("compiling for device %s: %s=%s", device_id, function_name, kernel_src)
                cubin = compile(kernel_src)
                end = time.time()
                log("compilation of %s took %.1fms", function_name, 1000.0*(end-start))
                KERNEL_cubins[(device_id, function_name)] = cubin
        finally:
            if context:
                context.pop()


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
