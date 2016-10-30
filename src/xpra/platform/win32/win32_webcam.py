# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
from xpra.log import Logger
log = Logger("webcam", "win32")

from xpra.platform.paths import get_app_dir

#suspend logging during comtypes.client._code_cache and loading of tlb files:
#also set minimum to INFO for all of comtypes
import logging
logging.getLogger("comtypes").setLevel(logging.INFO)
loggers = [logging.getLogger(x) for x in ("comtypes.client._code_cache", "comtypes.client._generate")]
saved_levels = [x.getEffectiveLevel() for x in loggers]
try:
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    import comtypes                                         #@UnresolvedImport
    from comtypes.client import GetModule, CreateObject     #@UnresolvedImport
    from comtypes import CoClass, GUID                      #@UnresolvedImport
    from comtypes.automation import VARIANT                 #@UnresolvedImport
    from comtypes.persist import IPropertyBag, IErrorLog    #@UnresolvedImport
    from ctypes import POINTER
    comtypes.client._generate.__verbose__ = False

    #load directshow:
    module_dir = get_app_dir()
    #so we can run from the source tree:
    if os.path.exists(os.path.join(module_dir, "win32")):
        module_dir = os.path.join(module_dir, "win32")
    directshow_tlb = os.path.join(module_dir, "DirectShow.tlb")
    log("loading module from %s", directshow_tlb)
    directshow = GetModule(directshow_tlb)
    log("directshow=%s", directshow)
finally:
    for i, logger in enumerate(loggers):
        logger.setLevel(saved_levels[i])


CLSID_VideoInputDeviceCategory  = GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
CLSID_SystemDeviceEnum          = GUID('{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}')
class DeviceEnumerator(CoClass):
    _reg_clsid_ = CLSID_SystemDeviceEnum
    _com_interfaces_ = [directshow.ICreateDevEnum]
    _idlflags_ = []
    _typelib_path_ = "E:\\DirectShow.tlb"  #typelib_path
    _reg_typelib_ = ('{24BC6711-3881-420F-8299-34DA1026D31E}', 1, 0)


def get_device_information(moniker):
    log("get_device_information(%s)", moniker)
    storage = moniker.RemoteBindToStorage(None, None, directshow.IPropertyBag._iid_)
    bag = storage.QueryInterface(interface=IPropertyBag)
    info = {}
    for prop,k in {
                   "FriendlyName"   : "card",
                   "DevicePath"     : "device",
                   "Description"    : "description",
                   }.items():
        try:
            error = POINTER(IErrorLog)
            variant = VARIANT("")
            v = bag.Read(pszPropName=prop, pVar=variant, pErrorLog=error())
            log("prop.Read(%s)=%s (%s)", prop, v, type(v))
            info[k] = v
        except:
            log("prop.Read(%s) failed", prop)
    return info

def get_video_devices():
    dev_enum = CreateObject(DeviceEnumerator)
    class_enum = dev_enum.CreateClassEnumerator(CLSID_VideoInputDeviceCategory, 0)
    fetched = True
    devices_info = {}
    index = 0
    while fetched:
        try:
            moniker, fetched = class_enum.RemoteNext(1)
            log("fetched=%s, moniker=%s", fetched, moniker)
            if fetched and moniker:
                info = get_device_information(moniker)
                devices_info[index] = info
                index += 1
        except ValueError:
            log("device %i not found", index)
            break
    return devices_info
