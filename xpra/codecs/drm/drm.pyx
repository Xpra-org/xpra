# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from typing import Dict, Tuple, Any

from xpra.log import Logger
log = Logger("drm")

cdef extern from "drm.h":
    ctypedef unsigned int __kernel_size_t
    ctypedef struct drm_version:
        int version_major
        int version_minor
        int version_patchlevel
        __kernel_size_t name_len
        char *name
        __kernel_size_t date_len
        char *date
        __kernel_size_t desc_len
        char *desc
    ctypedef drm_version* drmVersionPtr

cdef extern from "xf86drm.h":
    int DRM_NODE_PRIMARY
    int DRM_NODE_CONTROL
    int DRM_NODE_RENDER
    int DRM_NODE_MAX

    ctypedef struct drmDevice:
        char **nodes        #DRM_NODE_MAX sized array
        int available_nodes #DRM_NODE_* bitmask
        int bustype
        #union {
        #drmPciBusInfoPtr pci
        #drmUsbBusInfoPtr usb
        #drmPlatformBusInfoPtr platform
        #drmHost1xBusInfoPtr host1x
        #} businfo;
        #union {
        #drmPciDeviceInfoPtr pci
        #drmUsbDeviceInfoPtr usb
        #drmPlatformDeviceInfoPtr platform
        #drmHost1xDeviceInfoPtr host1x
        #} deviceinfo;
    ctypedef drmDevice* drmDevicePtr

    drmVersionPtr drmGetVersion(int fd)
    void drmFreeVersion(drmVersionPtr ver)

    int drmGetDevices(drmDevicePtr devices[], int max_devices)
    void drmFreeDevices(drmDevicePtr devices[], int count)

#cdef extern from "xf86drmMode.h":
#    int drmIsKMS(int fd)


cdef str s(const char *v):
    pytmp = v[:]
    try:
        return pytmp.decode()
    except:
        return str(v[:])


def get_version() -> Tuple[int, int]:
    return 4, 4


def query() -> Dict[str, Any]:
    info = {}
    cdef int count = drmGetDevices(NULL, 16)
    if count<0:
        log.error(f"Error querying drm devices: {count}")
        return info
    if count==0:
        log.warn("Warning: no drm devices found")
        return info
    cdef drmDevicePtr[16] devices
    count = drmGetDevices(devices, 16)
    assert 0<count<16
    log(f"{count} drm devices found")
    cdef char *path
    cdef int fd
    cdef drmVersionPtr version
    for i in range(count):
        if not devices[i].available_nodes & (1 << DRM_NODE_PRIMARY):
            log(f"{i} is not primary")
            continue
        dev_info = info.setdefault(i, {})
        path = devices[i].nodes[DRM_NODE_PRIMARY]
        log(f"{i} at {s(path)}")
        dev_info["path"] = s(path)
        try:
            with open(path, "rb") as drm_device:
                fd = drm_device.fileno()
                #kms = bool(drmIsKMS(fd))
                #dev_info["kms"] = kms
                version = drmGetVersion(fd)
                if version:
                    dev_info |= {
                        "version"   : (version.version_major, version.version_minor, version.version_patchlevel),
                        "name"      : s(version.name[:version.name_len]),
                        "date"      : s(version.date[:version.date_len]),
                        "desc"      : s(version.desc[:version.desc_len]),
                    }
                    drmFreeVersion(version)
                    #drmModeGetResources
        except OSError as e:
            dev_info["error"] = str(e)
    drmFreeDevices(devices, count)
    return info


def selftest(full=False) -> None:
    info = query()
    log(f"query()={info}")
