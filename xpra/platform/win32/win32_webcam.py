# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
from ctypes import POINTER

#make it possible to run this file without any xpra dependencies:
try:
    from xpra.log import Logger
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    assert app_dir
    log = Logger("webcam", "win32")
except ImportError:
    app_dir = os.getcwd()
    def log(*args):
        print(args[0] % args[1:])

import logging
logging.getLogger("comtypes").setLevel(logging.INFO)

#we need a logger before we import comtypes, so:
#pylint: disable=wrong-import-position
import comtypes                                         #@UnresolvedImport
from comtypes import client                             #@UnresolvedImport
from comtypes.automation import VARIANT                 #@UnresolvedImport
from comtypes.persist import IPropertyBag, IErrorLog    #@UnresolvedImport
from xpra.platform.win32.comtypes_util import QuietenLogging


#try to load directshow tlb from various directories,
#depending on how xpra was packaged, installed locally,
#or even run from the source directory:
dirs = [
    app_dir,
    os.path.join(app_dir, "win32"),
    os.path.join(app_dir, "share", "xpra"),
    os.path.join(os.environ.get("MINGW_PREFIX", ""), "share", "xpra"),
    ]
filenames = [os.environ.get("XPRA_DIRECTSHOW_TLB")] + [os.path.join(d, "DirectShow.tlb") for d in dirs]
directshow_tlb = None
for filename in filenames:
    if filename and os.path.exists(filename):
        directshow_tlb = filename
        break
log("directshow_tlb=%s", directshow_tlb)
if not directshow_tlb:
    raise ImportError("DirectShow.tlb is missing")

with QuietenLogging():
    directshow = client.GetModule(directshow_tlb)
log("directshow: %s", directshow)
log("directshow: %s", dir(directshow))

CLSID_VideoInputDeviceCategory  = comtypes.GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
CLSID_SystemDeviceEnum          = comtypes.GUID('{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}')
class DeviceEnumerator(comtypes.CoClass):
    _reg_clsid_ = CLSID_SystemDeviceEnum
    _com_interfaces_ = [directshow.ICreateDevEnum]
    _idlflags_ = []
    _typelib_path_ = "E:\\DirectShow.tlb"  #typelib_path
    _reg_typelib_ = ('{24BC6711-3881-420F-8299-34DA1026D31E}', 1, 0)


def get_device_information(moniker):
    log("get_device_information(%s)", moniker)
    storage = moniker.RemoteBindToStorage(None, None, directshow.IPropertyBag._iid_)  #pylint: disable=protected-access
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
        except Exception:
            log("prop.Read(%s) failed", prop)
    return info

def get_video_devices():
    from comtypes.client import CreateObject    #@UnresolvedImport
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
