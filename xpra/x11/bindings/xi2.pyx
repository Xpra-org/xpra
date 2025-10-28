# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Dict
from collections import deque

from xpra.x11.error import xlog
from xpra.x11.common import X11Event
from xpra.util.str_fn import hexstr
from xpra.x11.bindings.events import add_x_event_type_name

from libc.stdint cimport uintptr_t
from libc.string cimport memset
from xpra.x11.bindings.xlib cimport (
    Display, Bool, Time, Window, Atom, Status, XEvent, CARD32,
    XGenericEventCookie,
    XQueryExtension,
    XGetEventData, XFreeEventData, XDefaultRootWindow, XQueryPointer,
    XGetAtomName,
    XFlush,
    XFree,
    BadRequest, Success, XIAnyPropertyType,
)
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type, atom_str
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.log import Logger

import_check("xi2")

log = Logger("x11", "bindings", "xinput")


######
# Xlib primitives and constants
######

DEF XNone = 0

cdef extern from "X11/extensions/XInput2.h":
    int XI_LASTEVENT
    int XI_DeviceChanged
    int XI_KeyPress
    int XI_KeyRelease
    int XI_ButtonPress
    int XI_ButtonRelease
    int XI_Motion
    int XI_Enter
    int XI_Leave
    int XI_FocusIn
    int XI_FocusOut
    int XI_HierarchyChanged
    int XI_PropertyEvent
    int XI_RawKeyPress
    int XI_RawKeyRelease
    int XI_RawButtonPress
    int XI_RawButtonRelease
    int XI_RawMotion
    int XI_TouchBegin
    int XI_TouchUpdate
    int XI_TouchEnd
    int XI_TouchOwnership
    int XI_RawTouchBegin
    int XI_RawTouchUpdate
    int XI_RawTouchEnd

    int XIMasterPointer
    int XIMasterKeyboard
    int XISlavePointer
    int XISlaveKeyboard
    int XIFloatingSlave

    int XIButtonClass
    int XIKeyClass
    int XIValuatorClass
    int XIScrollClass
    int XITouchClass

    int XIAllDevices
    int XIAllMasterDevices

    ctypedef struct XIValuatorState:
        int           mask_len
        unsigned char *mask
        double        *values

    ctypedef struct XIEvent:
        int           type
        unsigned long serial
        Bool          send_event
        Display       *display
        int           extension
        int           evtype
        Time          time

    ctypedef struct XIRawEvent:
        int           type      #GenericEvent
        unsigned long serial
        Bool          send_event
        Display       *display
        int           extension #XI extension offset
        int           evtype    #XI_RawKeyPress, XI_RawKeyRelease, etc
        Time          time
        int           deviceid
        int           sourceid
        int           detail
        int           flags
        XIValuatorState valuators
        double        *raw_values

    ctypedef struct XIButtonState:
        int           mask_len
        unsigned char *mask

    ctypedef struct XIModifierState:
        int    base
        int    latched
        int    locked
        int    effective

    ctypedef XIModifierState XIGroupState

    ctypedef struct XIDeviceEvent:
        int           type
        unsigned long serial
        Bool          send_event
        Display       *display
        int           extension
        int           evtype
        Time          time
        int           deviceid
        int           sourceid
        int           detail
        Window        root
        Window        event
        Window        child
        double        root_x
        double        root_y
        double        event_x
        double        event_y
        int           flags
        XIButtonState       buttons
        XIValuatorState     valuators
        XIModifierState     mods
        XIGroupState        group

    ctypedef struct XIHierarchyInfo:
        int           deviceid
        int           attachment
        int           use
        Bool          enabled
        int           flags

    ctypedef struct XIHierarchyEvent:
        int           type
        unsigned long serial
        Bool          send_event
        Display       *display
        int           extension
        int           evtype            #XI_HierarchyChanged
        Time          time
        int           flags
        int           num_info
        XIHierarchyInfo *info

    ctypedef struct XIEventMask:
        int                 deviceid
        int                 mask_len
        unsigned char*      mask

    ctypedef struct XIAnyClassInfo:
        int         type
        int         sourceid

    ctypedef struct XIDeviceInfo:
        int                 deviceid
        char                *name
        int                 use
        int                 attachment
        Bool                enabled
        int                 num_classes
        XIAnyClassInfo      **classes

    ctypedef struct XIButtonClassInfo:
        int         type
        int         sourceid
        int         num_buttons
        Atom        *labels
        XIButtonState state

    ctypedef struct XIKeyClassInfo:
        int         type
        int         sourceid
        int         num_keycodes
        int         *keycodes

    ctypedef struct XIValuatorClassInfo:
        int         type
        int         sourceid
        int         number
        Atom        label
        double      min
        double      max
        double      value
        int         resolution
        int         mode

    ctypedef struct XIScrollClassInfo:
        int         type
        int         sourceid
        int         number
        int         scroll_type
        double      increment
        int         flags

    ctypedef struct XITouchClassInfo:
        int         type
        int         sourceid
        int         mode
        int         num_touches

    Status XIQueryVersion(Display *display, int *major_version_inout, int *minor_version_inout)
    Status XISelectEvents(Display *display, Window win, XIEventMask *masks, int num_masks)
    XIDeviceInfo* XIQueryDevice(Display *display, int deviceid, int *ndevices_return)
    void XIFreeDeviceInfo(XIDeviceInfo *info)
    Atom *XIListProperties(Display *display, int deviceid, int *num_props_return)
    Status XIGetProperty(Display *display, int deviceid, Atom property, long offset, long length,
                         Bool delete_property, Atom type, Atom *type_return,
                         int *format_return, unsigned long *num_items_return,
                         unsigned long *bytes_after_return, unsigned char **data)


DEF MAX_XI_EVENTS = 64
DEF XI_EVENT_MASK_SIZE = (MAX_XI_EVENTS+7)//8

XI_EVENT_NAMES: Dict[int, str] = {
    XI_DeviceChanged    : "XI_DeviceChanged",
    XI_KeyPress         : "XI_KeyPress",
    XI_KeyRelease       : "XI_KeyRelease",
    XI_ButtonPress      : "XI_ButtonPress",
    XI_ButtonRelease    : "XI_ButtonRelease",
    XI_Motion           : "XI_Motion",
    XI_Enter            : "XI_Enter",
    XI_Leave            : "XI_Leave",
    XI_FocusIn          : "XI_FocusIn",
    XI_FocusOut         : "XI_FocusOut",
    XI_HierarchyChanged : "XI_HierarchyChanged",
    XI_PropertyEvent    : "XI_PropertyEvent",
    XI_RawKeyPress      : "XI_RawKeyPress",
    XI_RawKeyRelease    : "XI_RawKeyRelease",
    XI_RawButtonPress   : "XI_RawButtonPress",
    XI_RawButtonRelease : "XI_RawButtonRelease",
    XI_RawMotion        : "XI_RawMotion",
    XI_TouchBegin       : "XI_TouchBegin",
    XI_TouchUpdate      : "XI_TouchUpdate",
    XI_TouchEnd         : "XI_TouchEnd",
    XI_TouchOwnership   : "XI_TouchOwnership",
    XI_RawTouchBegin    : "XI_RawTouchBegin",
    XI_RawTouchUpdate   : "XI_RawTouchUpdate",
    XI_RawTouchEnd      : "XI_RawTouchEnd",
}

XI_EVENTS: Dict[intr, str] = {
    XI_DeviceChanged    : "device-changed",
    XI_KeyPress         : "key-press",
    XI_KeyRelease       : "key-release",
    XI_ButtonPress      : "button-press",
    XI_ButtonRelease    : "button-release",
    XI_Motion           : "motion",
    XI_Enter            : "enter",
    XI_Leave            : "leave",
    XI_FocusIn          : "focus-in",
    XI_FocusOut         : "focus-out",
    XI_HierarchyChanged : "focus-changed",
    XI_PropertyEvent    : "property-event",
    XI_RawKeyPress      : "raw-key-press",
    XI_RawKeyRelease    : "raw-key-release",
    XI_RawButtonPress   : "raw-button-press",
    XI_RawButtonRelease : "raw-button-release",
    XI_RawMotion        : "raw-motion",
    XI_TouchBegin       : "touch-begin",
    XI_TouchUpdate      : "touch-update",
    XI_TouchEnd         : "touch-end",
    XI_TouchOwnership   : "touch-ownership",
    XI_RawTouchBegin    : "raw-touch-begin",
    XI_RawTouchUpdate   : "raw-touch-update",
    XI_RawTouchEnd      : "raw-touch-end",
}

XI_USE: Dict[int, str] = {
    XIMasterPointer     : "master pointer",
    XIMasterKeyboard    : "master keyboard",
    XISlavePointer      : "slave pointer",
    XISlaveKeyboard     : "slave keyboard",
    XIFloatingSlave     : "floating slave",
}

CLASS_INFO: Dict[int, str] = {
    XIButtonClass       : "button",
    XIKeyClass          : "key",
    XIValuatorClass     : "valuator",
    XIScrollClass       : "scroll",
    XITouchClass        : "touch",
}


cdef unsigned int xi_opcode = 0


cdef tuple get_xi_version(Display *display, int major=2, int minor=2):
    cdef int rmajor = major, rminor = minor
    cdef int rc = XIQueryVersion(display, &rmajor, &rminor)
    if rc == BadRequest:
        log.warn("Warning: no XI2 %i.%i support,", major, minor)
        log.warn(" server supports version %i.%i only", rmajor, rminor)
        return 0, 0
    log("get_xi_version%s=%s", (major, minor), (rmajor, rminor))
    return rmajor, rminor


cdef int get_xi_opcode(Display *display, int major=2, int minor=2) noexcept:
    cdef int opcode, event, error
    if not XQueryExtension(display, "XInputExtension", &opcode, &event, &error):
        log.warn("Warning: XI2 events are not supported")
        return 0
    cdef int rmajor = major, rminor = minor
    cdef int rc = XIQueryVersion(display, &rmajor, &rminor)
    if rc == BadRequest:
        log.warn("Warning: no XI2 %i.%i support,", major, minor)
        log.warn(" server supports version %i.%i only", rmajor, rminor)
        return 0
    elif rc:
        log.warn("Warning: Xlib bug querying XI2, code %i", rc)
        return 0
    log("get_xi_opcode%s=%i", (major, minor), opcode)
    global xi_opcode
    xi_opcode = opcode
    return opcode



cdef CARD32 last_serial = 0
cdef int last_event_type = 0


cdef dict parse_XIEvent(Display *d, XEvent *e):
    cdef XGenericEventCookie *cookie = <XGenericEventCookie*> e
    cdef XIHierarchyEvent *hierarchy_e
    cdef XIRawEvent *raw
    cdef int i = 0
    if not XGetEventData(d, cookie):
        log("parse_XIEvent(%#x) no event data", <uintptr_t> cookie)
        return {}
    cdef XIEvent *xie = <XIEvent*> cookie.data
    #cdef XIDeviceEvent *device_e = <XIDeviceEvent*> cookie.data
    cdef int xi_type = cookie.evtype
    cdef int etype = xi_opcode + xi_type
    event_name = XI_EVENT_NAMES.get(xi_type)
    if not event_name:
        log("parse_XIEvent(%#x) unknown XI2 event code: %i", <uintptr_t> cookie, xi_type)
        return {}

    # don't parse the same thing again:
    if last_serial == xie.serial and last_event_type == etype:
        log("parse_XIEvent repeated %s event skipped", event_name)
        return {}

    xid = int(XDefaultRootWindow(d))
    event = {
        "name": event_name,
        "window": xid,
        #"xid": pyev.window,
    }

    device_info = None
    if xi_type in (XI_KeyPress, XI_KeyRelease,
                   XI_ButtonPress, XI_ButtonRelease,
                   XI_Motion,
                   XI_TouchBegin, XI_TouchUpdate, XI_TouchEnd):
        device = <XIDeviceEvent*> cookie.data
        #pyev.source = device.sourceid    #always 0
        event.update({
            "device": device.deviceid,
            "detail": device.detail,
            "flags": device.flags,
            "window": int(device.child or device.event or device.root),
            "x_root": device.root_x,
            "y_root": device.root_y,
            "x": device.event_x,
            "y": device.event_y,
        })
        #mask = []
        valuators = {}
        valuator = 0
        for i in range(device.valuators.mask_len*8):
            if device.valuators.mask[i>>3] & (1 << (i & 0x7)):
                valuators[i] = device.valuators.values[valuator]
                valuator += 1
        event["valuators"] = valuators
        buttons = []
        for i in range(device.buttons.mask_len):
            if device.buttons.mask[i>>3] & (1<< (i & 0x7)):
                buttons.append(i)
        event["buttons"] = buttons
        state = []
        event["state"] = state
        event["modifiers"] = {
            "base"      : device.mods.base,
            "latched"   : device.mods.latched,
            "locked"    : device.mods.locked,
            "effective" : device.mods.effective,
        }
        #make it compatible with gdk events:
        event["state"] = device.mods.effective
    elif xi_type in (XI_RawKeyPress, XI_RawKeyRelease,
                     XI_RawButtonPress, XI_RawButtonRelease,
                     XI_RawMotion,
                     XI_RawTouchBegin, XI_RawTouchUpdate, XI_RawTouchEnd):
        raw = <XIRawEvent*> cookie.data
        valuators = {}
        raw_valuators = {}
        valuator = 0
        for i in range(raw.valuators.mask_len*8):
            if raw.valuators.mask[i>>3] & (1 << (i & 0x7)):
                valuators[i] = raw.valuators.values[valuator]
                raw_valuators[i] = raw.raw_values[valuator]
                valuator += 1
        event["valuators"] = valuators
        event["raw_valuators"] = raw_valuators
    elif xi_type == XI_HierarchyChanged:
        hierarchy_e = <XIHierarchyEvent*> cookie.data
        event["window"] = 0
        event["flags"] = hierarchy_e.flags
        #for i in range(hierarchy_e.num_info):
        #XIHierarchyInfo *info
    XFreeEventData(d, cookie)
    return event


cdef dict get_devices(Display *display, show_all=True, show_disabled=False):
    log("get_devices(%s, %s)", show_all, show_disabled)
    global XI_USE
    cdef int ndevices, i, j
    cdef XIDeviceInfo *device
    cdef XIAnyClassInfo *clazz
    if show_all:
        device_types = XIAllDevices
    else:
        device_types = XIAllMasterDevices
    cdef XIDeviceInfo *devices = XIQueryDevice(display, device_types, &ndevices)
    dinfo = {}
    for i in range(ndevices):
        device = &devices[i]
        if not device.enabled and not show_disabled:
            continue
        info = {
            "name"          : device.name,
            "use"           : XI_USE.get(device.use, "unknown use: %i" % device.use),
            "attachment"    : device.attachment,
            "enabled"       : device.enabled,
            }
        classes = {}
        for j in range(device.num_classes):
            clazz = device.classes[j]
            classes[j] = get_class_info(display, clazz)
        info["classes"] = classes
        properties = get_device_properties(display, device.deviceid)
        if properties:
            info["properties"] = properties
        log("[%i] %s: %s", device.deviceid, device.name, info)
        dinfo[device.deviceid] = info
    XIFreeDeviceInfo(devices)
    return dinfo


cdef dict get_device_properties(Display *display, int deviceid):
    cdef int nprops, i
    cdef Atom *atoms = XIListProperties(display, deviceid, &nprops)
    if atoms==NULL or nprops==0:
        return {}
    props = {}
    cdef Atom atom
    for i in range(nprops):
        atom = atoms[i]
        value = get_device_property(display, deviceid, atom)
        if value is not None:
            atom_name = atom_str(display, atom)
            props[atom_name] = value
    return props


cdef object get_device_property(Display *display, int deviceid, Atom property):
    # code mostly duplicated from window bindings XGetWindowProperty:
    cdef int buffer_size = 64 * 1024
    cdef Atom xactual_type = <Atom> 0
    cdef int actual_format = 0
    cdef unsigned long nitems = 0, bytes_after = 0
    cdef unsigned char *prop = NULL
    cdef Atom xreq_type = XIAnyPropertyType

    cdef Status status = XIGetProperty(display,
                           deviceid, property,
                           0,
                           buffer_size // 4,
                           False,
                           xreq_type, &xactual_type,
                           &actual_format, &nitems, &bytes_after, &prop)
    if status != Success:
        raise RuntimeError("failed to retrieve XI property")
    if xactual_type == XNone:
        return None
    if xreq_type and xreq_type != xactual_type:
        raise RuntimeError("expected %s but got %s" % (xreq_type, xactual_type))
    # This should only occur for bad property types:
    assert not (bytes_after and not nitems)
    if bytes_after:
        raise RuntimeError("reserved %i bytes for buffer, but data is bigger by %i bytes!" % (buffer_size, bytes_after))
    assert actual_format > 0
    #unlike XGetProperty, we don't need to special case 64-bit:
    cdef int bytes_per_item = actual_format // 8
    cdef int nbytes = bytes_per_item * nitems
    data = (<char *> prop)[:nbytes]
    XFree(prop)
    prop_type = atom_str(display, xactual_type)

    log("hex=%s (type=%s, nitems=%i, bytes per item=%i, actual format=%i)",
        hexstr(data), prop_type, nitems, bytes_per_item, actual_format)
    fmt = None
    if prop_type=="INTEGER":
        fmt = {
            8   : b"b",
            16  : b"h",
            32  : b"i",
        }.get(actual_format)
    elif prop_type=="CARDINAL":
        fmt = {
            8   : b"B",
            16  : b"H",
            32  : b"I",
        }.get(actual_format)
    elif prop_type=="FLOAT":
        fmt = b"f"
    if fmt:
        value = struct.unpack(fmt*nitems, data)
        if nitems==1:
            return value[0]
        return value
    return data


cdef dict get_class_info(Display *display, XIAnyClassInfo *class_info):
    cdef int i
    cdef XIButtonClassInfo *button
    cdef XIKeyClassInfo *key
    cdef XIValuatorClassInfo *valuator
    cdef XIScrollClassInfo *scroll
    cdef XITouchClassInfo *touch
    info = {
        "type"      : CLASS_INFO.get(class_info.type, "unknown type: %i" % class_info.type),
        "sourceid"  : class_info.sourceid,
    }
    if class_info.type==XIButtonClass:
        button = <XIButtonClassInfo*> class_info
        buttons = []
        for i in range(button.num_buttons):
            if button.labels[i]>0:
                buttons.append(atom_str(display, button.labels[i]))
        info["buttons"] = buttons
        #XIButtonState state
    elif class_info.type==XIKeyClass:
        key = <XIKeyClassInfo*> class_info
        keys = []
        for i in range(key.num_keycodes):
            keys.append(key.keycodes[i])
    elif class_info.type==XIValuatorClass:
        valuator = <XIValuatorClassInfo*> class_info
        info |= {
            "number"    : valuator.number,
            "min"       : valuator.min,
            "max"       : valuator.max,
            "value"     : valuator.value,
            "resolution": valuator.resolution,
            "mode"      : valuator.mode,
        }
        if valuator.label:
            info["label"] = atom_str(display, valuator.label)
    elif class_info.type==XIScrollClass:
        scroll = <XIScrollClassInfo*> class_info
        info |= {
            "number"        : scroll.number,
            "scroll-type"   : scroll.scroll_type,
            "increment"     : scroll.increment,
            "flags"         : scroll.flags,
        }
    elif class_info.type==XITouchClass:
        touch = <XITouchClassInfo*> class_info
        info |= {
            "mode"          : touch.mode,
            "num-touches"   : touch.num_touches,
        }
    return info


def init_xi2_events(parse=True) -> bool:
    cdef Display *display = get_display()
    cdef int event_base = 0, error_base = 0
    if get_xi_version(display) < (2, 2):
        log.warn("Warning: XI2 extension is not available")
        return False
    cdef int opcode = get_xi_opcode(display)
    log("init_xi2_events() opcode=%i", opcode)
    if opcode <= 0:
        log.warn("Warning: XI2 extension returned invalid major opcode: %d", opcode)
        return False

    log("xi2 opcode=%i", opcode)
    cdef int event = 0
    for event_code, name in XI_EVENTS.items():
        event = opcode + event_code
        x11name = XI_EVENT_NAMES.get(event_code, "")
        log("%i=%s", event, x11name)
        if parse:
            add_event_type(event, x11name, f"x11-xi2-{name}", "")
            add_parser(event, parse_XIEvent)
        else:
            add_x_event_type_name(event, x11name)
    return True


cdef void xi_select_events(Display* display):
    cdef Window win = XDefaultRootWindow(display)
    log("xi_select_events() root window=%#x", win)
    assert XI_LASTEVENT < MAX_XI_EVENTS, "bug: source needs to be updated, XI_LASTEVENT=%i" % XI_LASTEVENT
    cdef XIEventMask evmasks[1]
    cdef unsigned char mask1[XI_EVENT_MASK_SIZE]
    memset(mask1, 0, XI_EVENT_MASK_SIZE)
    # define XISetMask(ptr, event)   (((unsigned char*)(ptr))[(event)>>3] |=  (1 << ((event) & 7)))
    # XISetMask(mask1, XI_RawMotion)
    for e in (
        XI_KeyPress, XI_KeyRelease,
        XI_Motion,
        XI_HierarchyChanged,
        XI_ButtonPress, XI_ButtonRelease,
        XI_RawButtonPress, XI_RawButtonRelease,
        XI_TouchBegin, XI_TouchUpdate, XI_TouchEnd,
        XI_RawTouchBegin, XI_RawTouchUpdate, XI_RawTouchEnd,
        XI_RawMotion,
    ):
        mask1[e>>3] |= (1<< (e & 0x7))
    evmasks[0].deviceid = XIAllDevices  #XIAllMasterDevices    #XIAllDevices
    evmasks[0].mask_len = XI_EVENT_MASK_SIZE
    evmasks[0].mask = mask1
    XISelectEvents(display, win, evmasks, 1)


cdef class X11XI2BindingsInstance(X11CoreBindingsInstance):

    cdef int opcode
    cdef object events
    cdef object event_handlers

    def __init__(self):
        self.opcode = -1
        self.event_handlers = {}
        self.reset_events()

    def __repr__(self):
        return "X11XI2Bindings(%s)" % self.display_name

    def connect(self, window, event, handler) -> None:
        self.event_handlers.setdefault(window, {})[event] = handler

    def disconnect(self, window) -> None:
        self.event_handlers.pop(window, None)

    def reset_events(self) -> None:
        self.events = deque(maxlen=100)

    def find_event(self, event_name: str, serial: int) -> int:
        for x in reversed(self.events):
            #log.info("find_event(%s, %#x) checking %s", event_name, serial, x)
            if x.name==event_name and x.serial==serial:
                #log.info("matched")
                return x
            if x.serial<serial:
                #log.info("serial too old")
                return 0
        return 0

    def find_events(self, event_name: str, windows) -> List[int]:
        cdef Window found = 0
        cdef Window window
        matches = []
        for x in reversed(self.events):
            window = x.xid
            if x.name==event_name and ((found>0 and found==window) or (found==0 and window in windows)):
                matches.append(x)
                found = window
            elif found:
                break
        return matches

    def get_xi_version(self, int major=2, int minor=2) -> Tuple[int, int]:
        self.context_check("get_xi_version")
        return get_xi_version(self.display, major, minor)

    cdef int get_xi_opcode(self, int major=2, int minor=2) noexcept:
        if self.opcode > 0:
            return self.opcode
        cdef int opcode = get_xi_opcode(self.display, major, minor)
        self.opcode = opcode
        log("get_xi_opcode%s=%i", (major, minor), opcode)
        return opcode

    cdef void register_parser(self) noexcept:
        log("register_parser()")
        if self.opcode>0:
            from xpra.x11.bindings.events import add_x_event_parser
            add_x_event_parser(self.opcode, self.parse_xi_event)

    cdef void register_gdk_events(self) noexcept:
        log("register_gdk_events()")
        if self.opcode<=0:
            return
        global XI_EVENT_NAMES
        from xpra.x11.bindings.events import add_x_event_signal, add_x_event_type_name
        for e, xi_event_name in XI_EVENTS.items():
            event = self.opcode + e
            add_x_event_signal(event, ("xi-%s" % xi_event_name, None))
            name = XI_EVENT_NAMES[e]
            add_x_event_type_name(event, name)

    def select_xi2_events(self) -> None:
        self.context_check("select_xi2_events")
        xi_select_events(self.display)
        XFlush(self.display)

    def get_devices(self, show_all=True, show_disabled=False) -> Dict[int, Dict[str, Any]]:
        self.context_check("get_devices")
        return get_devices(self.display, show_all, show_disabled)

    def gdk_inject(self) -> None:
        self.get_xi_opcode()
        #log.info("XInput Devices:")
        #from xpra.util.str_fn import print_nested_dict
        #print_nested_dict(self.get_devices(), print_fn=log.info)
        self.register_parser()
        self.register_gdk_events()
        #self.select_xi2_events()


cdef X11CoreBindingsInstance singleton = None


def X11XI2Bindings() -> X11CoreBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11XI2BindingsInstance()
    return singleton
