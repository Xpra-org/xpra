# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Dict
from time import monotonic

from xpra.log import Logger
log = Logger("x11", "bindings", "randr")

from xpra.x11.bindings.xlib cimport (
    Display, XID, Bool, Status, Drawable, Window, Time, Atom, XEvent,
    XDefaultRootWindow,
    XGetAtomName,
    XFree, XFlush, XSync,
    AnyPropertyType, PropModeReplace,
    CurrentTime, Success,
)
from xpra.common import DEFAULT_REFRESH_RATE
from xpra.util.env import envint, envbool, first_time
from xpra.util.str_fn import csv, decode_str, strtobytes
from xpra.util.screen import prettify_plug_name


TIMESTAMPS = envbool("XPRA_RANDR_TIMESTAMPS", False)
GAMMA = envbool("XPRA_RANDR_GAMMA", False)
MAX_NEW_MODES = envint("XPRA_RANDR_MAX_NEW_MODES", 32)
assert MAX_NEW_MODES>=2


from libc.stdint cimport uintptr_t   # pylint: disable=syntax-error
ctypedef unsigned long CARD32
ctypedef unsigned short SizeID


###################################
# Randr
###################################
cdef extern from "X11/extensions/randr.h":
    ctypedef unsigned long XRRModeFlags
    ctypedef unsigned short Connection
    ctypedef unsigned short SubpixelOrder
    ctypedef unsigned short Rotation
    Rotation RR_Rotate_0
    Rotation RR_Rotate_90
    Rotation RR_Rotate_180
    Rotation RR_Rotate_270
    Connection RR_Connected
    Connection RR_Disconnected
    Connection RR_UnknownConnection
    int RR_HSyncPositive
    int RR_HSyncNegative
    int RR_VSyncPositive
    int RR_VSyncNegative
    int RR_Interlace
    int RR_DoubleScan
    int RR_CSync
    int RR_CSyncPositive
    int RR_CSyncNegative
    int RR_HSkewPresent
    int RR_BCast
    int RR_PixelMultiplex
    int RR_DoubleClock
    int RR_ClockDivideBy2

    int RRScreenChangeNotifyMask
    int RRCrtcChangeNotifyMask
    int RROutputChangeNotifyMask
    int RROutputPropertyNotifyMask

    int RRScreenChangeNotify


MODE_FLAGS_STR: Dict[int, str] = {
    RR_HSyncPositive    : "HSyncPositive",
    RR_HSyncNegative    : "HSyncNegative",
    RR_VSyncPositive    : "VSyncPositive",
    RR_VSyncNegative    : "VSyncNegative",
    RR_Interlace        : "Interlace",
    RR_DoubleScan       : "DoubleScan",
    RR_CSync            : "CSync",
    RR_CSyncPositive    : "CSyncPositive",
    RR_CSyncNegative    : "CSyncNegative",
    RR_HSkewPresent     : "HSkewPresent",
    RR_BCast            : "BCast",
    RR_PixelMultiplex   : "PixelMultiplex",
    RR_DoubleClock      : "DoubleClock",
    RR_ClockDivideBy2   : "ClockDivideBy2",
}

ROTATIONS: Dict[int, str] = {
    RR_Rotate_0             : 0,
    RR_Rotate_90            : 90,
    RR_Rotate_180           : 180,
    RR_Rotate_270           : 270,
}

CONNECTION_STR: Dict[int, str] = {
    RR_Connected            : "Connected",
    RR_Disconnected         : "Disconnected",
    RR_UnknownConnection    : "Unknown",
}


def get_rotation(Rotation v) -> int:
    return ROTATIONS.get(v, 0)


def get_rotations(Rotation v) -> List[int]:
    rotations = []
    for renum, rval in ROTATIONS.items():
        if renum & v:
            rotations.append(rval)
    return rotations


cdef extern from "X11/extensions/render.h":
    int SubPixelUnknown
    int SubPixelHorizontalRGB
    int SubPixelHorizontalBGR
    int SubPixelVerticalRGB
    int SubPixelVerticalBGR
    int SubPixelNone

SUBPIXEL_STR = {
    SubPixelUnknown : "unknown",
    SubPixelHorizontalRGB : "RGB",
    SubPixelHorizontalBGR : "BGR",
    SubPixelVerticalRGB : "VRGB",
    SubPixelVerticalBGR : "VBGR",
    SubPixelNone        : "none",
    }


cdef extern from "X11/extensions/Xrandr.h":
    ctypedef XID RRMode
    ctypedef XID RROutput
    ctypedef XID RRCrtc

    int XRRUpdateConfiguration(XEvent *event)

    ctypedef struct XRRScreenChangeNotifyEvent:
        int type;                   # event base
        unsigned long serial
        Bool send_event             # true if this came from a SendEvent request
        Display *display            # Display the event was read from
        Window window               # window which selected for this event
        Window root                 # Root window for changed screen
        Time timestamp              # when the screen change occurred
        Time config_timestamp       # when the last configuration change
        SizeID size_index
        SubpixelOrder subpixel_order
        Rotation rotation
        int width
        int height
        int mwidth
        int mheight

    Bool XRRQueryExtension(Display *, int * major, int * minor)
    Status XRRQueryVersion(Display *, int * major, int * minor)

    void XRRSelectInput(Display *dpy, Window window, int mask)
    ctypedef struct XRRScreenSize:
        int width, height
        int mwidth, mheight
    XRRScreenSize *XRRSizes(Display *dpy, int screen, int *nsizes)
    void XRRSetScreenSize(Display *dpy, Window w, int width, int height, int mmWidth, int mmHeight)
    ctypedef struct XRRModeInfo:
        RRMode              id
        unsigned int        width
        unsigned int        height
        unsigned long       dotClock
        unsigned int        hSyncStart
        unsigned int        hSyncEnd
        unsigned int        hTotal
        unsigned int        hSkew
        unsigned int        vSyncStart
        unsigned int        vSyncEnd
        unsigned int        vTotal
        char                *name
        unsigned int        nameLength
        XRRModeFlags        modeFlags
    ctypedef struct XRRScreenResources:
        Time        timestamp
        Time        configTimestamp
        int         ncrtc
        RRCrtc      *crtcs
        int         noutput
        RROutput    *outputs
        int         nmode
        XRRModeInfo *modes

    ctypedef struct XRROutputInfo:
        Time            timestamp
        RRCrtc          crtc
        char            *name
        int             nameLen
        unsigned long   mm_width
        unsigned long   mm_height
        Connection      connection
        SubpixelOrder   subpixel_order
        int             ncrtc
        RRCrtc          *crtcs
        int             nclone
        RROutput        *clones
        int             nmode
        int             npreferred
        RRMode          *modes

    ctypedef struct XRRCrtcInfo:
        Time            timestamp
        int             x, y
        unsigned int    width, height
        RRMode          mode
        Rotation        rotation
        int             noutput
        RROutput        *outputs
        Rotation        rotations
        int             npossible
        RROutput        *possible

    ctypedef struct XRRScreenConfiguration:
        pass
    Status XRRSetScreenConfigAndRate(Display *dpy, XRRScreenConfiguration *config,
                                  Drawable draw, int size_index, Rotation rotation,
                                  short rate, Time timestamp)
    XRRScreenConfiguration *XRRGetScreenInfo(Display *, Window w)
    XRRScreenSize *XRRConfigSizes(XRRScreenConfiguration *config, int *nsizes)
    short *XRRConfigRates(XRRScreenConfiguration *config, int sizeID, int *nrates)
    SizeID XRRConfigCurrentConfiguration(XRRScreenConfiguration *config, Rotation *rotation)

    void XRRFreeScreenConfigInfo(XRRScreenConfiguration *)
    XRRScreenResources *XRRGetScreenResourcesCurrent(Display *dpy, Window window)
    void XRRFreeScreenResources(XRRScreenResources *resources)

    XRROutputInfo *XRRGetOutputInfo(Display *dpy, XRRScreenResources *resources, RROutput output)
    void XRRFreeOutputInfo (XRROutputInfo *outputInfo)
    Atom *XRRListOutputProperties (Display *dpy, RROutput output, int *nprop)
    void XRRChangeOutputProperty (Display *dpy, RROutput output, Atom prop, Atom ptype,
                                  int pformat, int mode, unsigned char *data, int nelements)
    ctypedef struct XRRPropertyInfo:
        Bool    pending
        Bool    range
        Bool    immutable
        int     num_values
        long    *values
    XRRPropertyInfo *XRRQueryOutputProperty(Display *dpy, RROutput output, Atom prop)
    int XRRGetOutputProperty (Display *dpy, RROutput output,
                              Atom prop, long offset, long length,
                              Bool _delete, Bool pending, Atom req_type,
                              Atom *actual_type, int *actual_format,
                              unsigned long *nitems, unsigned long *bytes_after,
                              unsigned char **prop)

    XRRCrtcInfo *XRRGetCrtcInfo(Display *dpy, XRRScreenResources *resources, RRCrtc crtc)
    void XRRFreeCrtcInfo(XRRCrtcInfo *crtcInfo)
    Status XRRSetCrtcConfig(Display *dpy, XRRScreenResources *resources, RRCrtc crtc,
                            Time timestamp, int x, int y,
                            RRMode mode, Rotation rotation,
                            RROutput *outputs, int noutputs)

    void XRRSetOutputPrimary(Display *dpy, Window window, RROutput output)
    RROutput XRRGetOutputPrimary(Display *dpy, Window window)

    int XRRGetCrtcGammaSize(Display *dpy, RRCrtc crtc)
    ctypedef struct XRRCrtcGamma:
        int             size
        unsigned short  *red
        unsigned short  *green
        unsigned short  *blue
    XRRCrtcGamma *XRRGetCrtcGamma(Display *dpy, RRCrtc crtc)
    XRRCrtcGamma *XRRAllocGamma (int size)
    void XRRSetCrtcGamma(Display *dpy, RRCrtc crtc, XRRCrtcGamma *gamma)
    void XRRFreeGamma(XRRCrtcGamma *gamma)

    XRRModeInfo *XRRAllocModeInfo(char *name, int nameLength)
    RRMode XRRCreateMode(Display *dpy, Window window, XRRModeInfo *modeInfo)
    void XRRDestroyMode (Display *dpy, RRMode mode)
    void XRRAddOutputMode(Display *dpy, RROutput output, RRMode mode)
    void XRRDeleteOutputMode(Display *dpy, RROutput output, RRMode mode)
    void XRRFreeModeInfo(XRRModeInfo *modeInfo)

    int XScreenCount(Display *display)
    int XDisplayWidthMM(Display *display, int screen_number)
    int XDisplayHeightMM(Display *display, int screen_number)
    int XDisplayWidth(Display *display, int screen_number)
    int XDisplayHeight(Display *display, int screen_number)

    short XRRConfigCurrentRate(XRRScreenConfiguration *config)

    ctypedef struct XRRMonitorInfo:
        Atom name
        Bool primary
        Bool automatic
        int noutput
        int x
        int y
        int width
        int height
        int mwidth
        int mheight
        RROutput *outputs
    XRRMonitorInfo *XRRAllocateMonitor(Display *dpy, int noutput)
    XRRMonitorInfo *XRRGetMonitors(Display *dpy, Window window, Bool get_active, int *nmonitors)
    void XRRSetMonitor(Display *dpy, Window window, XRRMonitorInfo *monitor)
    void XRRDeleteMonitor(Display *dpy, Window window, Atom name)
    void XRRFreeMonitors(XRRMonitorInfo *monitors)


from xpra.x11.bindings.core cimport X11CoreBindingsInstance


cdef dict get_mode_info(XRRModeInfo *mi, with_sync: bool):
    info = {
        "id"            : mi.id,
        "width"         : mi.width,
        "height"        : mi.height,
    }
    if mi.name and mi.nameLength:
        info["name"] = s(mi.name[:mi.nameLength])
    if with_sync:
        info |= {
            "dot-clock"     : mi.dotClock,
            "h-sync-start"  : mi.hSyncStart,
            "h-sync-end"    : mi.hSyncEnd,
            "h-total"       : mi.hTotal,
            "h-skew"        : mi.hSkew,
            "v-sync-start"  : mi.vSyncStart,
            "v-sync-end"    : mi.vSyncEnd,
            "v-total"       : mi.vTotal,
            "mode-flags"    : tuple(name for v,name in MODE_FLAGS_STR.items() if mi.modeFlags & v),
        }
    return info


cdef dict get_output_info(Display *display, XRRScreenResources *rsc, RROutput output):
    cdef XRROutputInfo *oi = XRRGetOutputInfo(display, rsc, output)
    if oi==NULL:
        return {}
    info = {
        "id"                : output,
        "connection"        : CONNECTION_STR.get(oi.connection, "%i" % oi.connection),
        }
    if oi.connection!=RR_Disconnected:
        info |= {
            "width-mm"          : oi.mm_width,
            "height-mm"         : oi.mm_height,
            "preferred-mode"    : oi.npreferred,
        }
        if TIMESTAMPS:
            info["timestamp"] = oi.timestamp
        so = SUBPIXEL_STR.get(oi.subpixel_order)
        if so and so!="unknown":
            info["subpixel-order"] = so
        if oi.nclone:
            info["clones"] = tuple(int(oi.clones[i] for i in range(oi.nclone)))
        info["properties"] = get_output_properties(display, output)
    if oi.name and oi.nameLen:
        info["name"] = s(oi.name[:oi.nameLen])
    XRRFreeOutputInfo(oi)
    return info


cdef str get_XAtom(Display *display, Atom atom):
    cdef char *v = XGetAtomName(display, atom)
    if v == NULL:
        return ""
    r = v[:]
    XFree(v)
    return r.decode()


cdef str s(const char *v):
    pytmp = v[:]
    try:
        return pytmp.decode()
    except:
        return str(v[:])


cdef dict get_output_properties(Display *display, RROutput output):
    cdef int nprop
    cdef Atom *atoms = XRRListOutputProperties(display, output, &nprop)
    cdef Atom prop, actual_type
    cdef int actual_format
    cdef unsigned long nitems
    cdef unsigned long bytes_after
    cdef unsigned char *buf
    cdef int nbytes
    cdef XRRPropertyInfo *prop_info
    log(f"reading {nprop} properties from output {output}")
    properties = {}
    for i in range(nprop):
        prop = atoms[i]
        prop_name = get_XAtom(display, prop)
        buf = NULL
        r = XRRGetOutputProperty(display, output,
                                 prop, 0, 1024,
                                 0, 0, AnyPropertyType,
                                 &actual_type, &actual_format,
                                 &nitems, &bytes_after,
                                 &buf)
        if r or not buf:
            log.warn(f"Warning: failed to read output property {prop_name!r}")
            continue
        if bytes_after:
            log.warn(f"Warning: failed to read output property {prop_name!r}")
            log.warn(" data too large")
            continue
        if not actual_format:
            log.warn(f"Warning: failed to read output property {prop_name!r}")
            log.warn(" invalid format")
            continue
        at = get_XAtom(display, actual_type)
        if at not in ("INTEGER", "CARDINAL", "ATOM"):
            log(f"skipped output property {at}")
            continue
        if actual_format == 8:
            fmt = b"B"
        elif actual_format == 16:
            fmt = b"H"
        elif actual_format == 32:
            fmt = b"L"
        else:
            raise ValueError(f"invalid format {actual_format}")
        log(f"{prop_name!r} : {at} / {actual_format}")
        try:
            bytes_per_item = struct.calcsize(b"@%s" % fmt)
            nbytes = bytes_per_item * nitems
            data = buf[:nbytes]
            value = struct.unpack(b"@%s" % (fmt*nitems), data)
            if at=="ATOM":
                value = tuple(get_XAtom(display, v) for v in value)
            if at=="INTEGER" and actual_format==8 and prop_name=="EDID" and nitems>=32:
                #EDID is a binary blob:
                value = bytes(value)
                try:
                    from pyedid import parse_edid
                    value = parse_edid(value)._asdict()
                except ImportError as e:
                    log(f"cannot parse EDID: {e}")
                except ValueError as e:
                    log.warn(f"Warning: invalid EDID data: {e}")
            if nitems==1:
                value = value[0]
                #convert booleans:
                prop_info = XRRQueryOutputProperty(display, output, prop)
                if prop_info:
                    if prop_info.num_values==2 and prop_info.values[0] in (0, 1) and prop_info.values[1] in (0, 1):
                        value = bool(value)
                    XFree(prop_info)
        except Exception:
            log.error(f"Error unpacking {prop_name!r} using format {fmt} from {data!r}", exc_info=True)
        else:
            if prop_name=="non-desktop" and value is False:
                #no value in reporting this, we can assume it is False when missing
                continue
            properties[prop_name] = value
    XFree(atoms)
    return properties


cdef dict get_all_screen_properties(Display *display):
    cdef Window window = XDefaultRootWindow(display)
    cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(display, window)
    cdef RROutput primary = XRRGetOutputPrimary(display, window)
    if rsc==NULL:
        log.error("Error: cannot access screen resources")
        return {}
    props = {}
    if TIMESTAMPS:
        props["timestamp"] = rsc.timestamp
        props["config-timestamp"] = rsc.configTimestamp
    for i in range(rsc.nmode):
        props.setdefault("modes", {})[i] = get_mode_info(&rsc.modes[i], False)
    try:
        for o in range(rsc.noutput):
            if primary and primary==rsc.outputs[o]:
                props["primary-output"] = o
            output_info = get_output_info(display, rsc, rsc.outputs[o])
            if output_info:
                oid = output_info["id"]
                props.setdefault("outputs", {})[oid] = output_info
        for crtc in range(rsc.ncrtc):
            crtc_info = get_crtc_info(display, rsc, rsc.crtcs[crtc])
            if crtc_info:
                props.setdefault("crtcs", {})[crtc] = crtc_info
    finally:
        XRRFreeScreenResources(rsc)
    props["monitors"] = get_monitor_properties(display)
    return props


cdef dict get_crtc_info(Display *display, XRRScreenResources *rsc, RRCrtc crtc):
    cdef XRRCrtcInfo *ci = XRRGetCrtcInfo(display, rsc, crtc)
    if ci==NULL:
        return {}
    info = {
        "noutput"   : ci.noutput,
        "npossible" : ci.npossible,
    }
    if ci.noutput:
        info["outputs"] = tuple(int(ci.outputs[i]) for i in range(ci.noutput))
    if TIMESTAMPS:
        info["timestamp"] = int(ci.timestamp)
    cdef XRRCrtcGamma *gamma
    if ci.mode or ci.width or ci.height or ci.noutput:
        info |= {
            "x"         : ci.x,
            "y"         : ci.y,
            "width"     : ci.width,
            "height"    : ci.height,
            "mode"      : ci.mode,
        }
        if GAMMA:
            gamma = XRRGetCrtcGamma(display, crtc)
            if gamma and gamma.size:
                info["gamma"] = {
                    "red"   : tuple(gamma.red[i] for i in range(gamma.size)),
                    "green" : tuple(gamma.green[i] for i in range(gamma.size)),
                    "blue"  : tuple(gamma.blue[i] for i in range(gamma.size)),
                }
                XRRFreeGamma(gamma)
    if ci.rotation!=RR_Rotate_0:
        info["rotation"] = get_rotation(ci.rotation)
    if ci.rotations!=RR_Rotate_0:
        info["rotations"] = get_rotations(ci.rotations)
    XRRFreeCrtcInfo(ci)
    return info


cdef dict get_monitor_properties(Display *display):
    cdef int nmonitors
    cdef Window window = XDefaultRootWindow(display)
    cdef XRRMonitorInfo *monitors = XRRGetMonitors(display, window, True, &nmonitors)
    cdef XRRMonitorInfo *m
    props = {}
    for i in range(nmonitors):
        m = &monitors[i]
        props[i] = {
            "index"     : i,
            "name"      : get_XAtom(display, m.name),
            "primary"   : bool(m.primary),
            "automatic" : bool(m.automatic),
            "x"         : m.x,
            "y"         : m.y,
            "width"     : m.width,
            "height"    : m.height,
            "width-mm"  : m.mwidth,
            "height-mm" : m.mheight,
            #"outputs"   : tuple(rroutput_map.get(m.outputs[j], 0) for j in range(m.noutput)),
            "outputs"   : tuple(m.outputs[j] for j in range(m.noutput)),
        }
    XRRFreeMonitors(monitors)
    return props


cdef class RandRBindingsInstance(X11CoreBindingsInstance):

    cdef int _has_randr
    cdef int _randr_event_base
    cdef object _added_modes
    cdef object version

    def __init__(self):
        self.version = self.query_version()
        self._added_modes = {}
        self._has_randr = self.version>(0, ) and self.check_randr_sizes()
        self._randr_event_base = 0

    def __repr__(self):
        return f"RandRBindings({self.display_name})"

    def get_version(self) -> Tuple[int, int]:
        return self.version

    def query_version(self) -> Tuple[int, int]:
        cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
        cdef int r = XRRQueryExtension(self.display, &event_base, &ignored)
        log(f"XRRQueryExtension()={r}")
        if not r:
            return (0, )
        log("found XRandR extension")
        if not XRRQueryVersion(self.display, &cmajor, &cminor):
            return (0, )
        log(f"found XRandR extension version {cmajor}.{cminor}")
        self._randr_event_base = event_base
        return cmajor, cminor

    def check_randr_sizes(self) -> bool:
        #check for wayland, which has no sizes:
        #(and we wouldn't be able to set screen resolutions)
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            log("check_randr_sizes: failed to get randr screen info")
            return False
        cdef int num_sizes = 0
        XRRConfigSizes(config, &num_sizes)
        log(f"found {num_sizes} config sizes")
        return num_sizes>0

    def has_randr(self) -> bool:
        return bool(self._has_randr)

    def select_screen_changes(self) -> None:
        cdef int mask = RRScreenChangeNotifyMask
        cdef Window root = XDefaultRootWindow(self.display)
        XRRSelectInput(self.display, root, mask)

    def select_crtc_output_changes(self) -> None:
        cdef int mask = RRScreenChangeNotifyMask | RRCrtcChangeNotifyMask | RROutputChangeNotifyMask | RROutputPropertyNotifyMask
        cdef Window root = XDefaultRootWindow(self.display)
        XRRSelectInput(self.display, root, mask)

    cdef _get_xrr_screen_sizes(self):
        cdef int num_sizes = 0
        cdef XRRScreenSize xrr
        cdef XRRScreenSize *xrrs = XRRSizes(self.display, 0, &num_sizes)
        sizes = []
        if xrrs==NULL:
            return sizes
        for i in range(num_sizes):
            xrr = xrrs[i]
            sizes.append((xrr.width, xrr.height))
        return sizes

    def get_xrr_screen_sizes(self) -> List[Tuple[int, int]]:
        v = self._get_xrr_screen_sizes()
        log(f"get_xrr_screen_sizes()={v}")
        return v

    cdef _set_screen_size(self, width, height):
        self.context_check()
        cdef int num_sizes = 0
        cdef int num_rates = 0
        cdef short* rates = <short*> 0
        cdef short rate = 0
        cdef Rotation rotation = 0
        cdef Time time = 0
        cdef int sizeID = 0
        cdef XRRScreenSize *xrrs
        cdef XRRScreenSize xrr

        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            log.error("Error: failed to get randr screen info")
            return False
        try:
            xrrs = XRRConfigSizes(config, &num_sizes)
            if xrrs==NULL:
                log.error("Error: failed to get randr screen sizes")
                return False
            if num_sizes==0:
                if first_time("no-randr-sizes"):
                    log.warn("Warning: no randr sizes found")
                    log.warn(f" cannot set screen size to match {width}x{height}")
                else:
                    log("no randr sizes")
                return False
            sizes = []
            sizeID = -1
            oversize = {}
            for i in range(num_sizes):
                xrr = xrrs[i]
                sizes.append((int(xrr.width), int(xrr.height)))
                if xrr.width==width and xrr.height==height:
                    sizeID = i
                elif xrr.width>=width and xrr.height>=height:
                    extra = xrr.width*xrr.height - width*height
                    oversize[extra] = i
            if sizeID<0:
                if oversize:
                    #choose the next highest:
                    extra = sorted(oversize.keys())[0]
                    sizeID = oversize[extra]
                else:
                    log.error(f"Error: size not found for {width}x{height}")
                    log.error(f" {num_sizes} sizes are supported")
                    if num_sizes<=16:
                        log.error(" %s", csv(f"{w}x{h}" for w, h in sizes))
                    else:
                        log(f"sizes found: {csv(sizes)}")
                    return False
            rates = XRRConfigRates(config, sizeID, &num_rates)
            if rates==NULL:
                log.error("Error: failed to get randr config rates")
                return False
            rate = rates[0]
            rotation = RR_Rotate_0
            time = CurrentTime
            status = XRRSetScreenConfigAndRate(self.display, config, window, sizeID, rotation, rate, time)
            log("XRRSetScreenConfigAndRate%s=%s", (<uintptr_t> self.display, <uintptr_t> config, window, sizeID, rotation, rate, time), status)
            if status != Success:
                log.error("Error: failed to set new screen size")
                log.error(f" XRRSetScreenConfigAndRate returned {status}")
                return False
            return True
        finally:
            XRRFreeScreenConfigInfo(config)

    def get_screen_count(self) -> int:
        return XScreenCount(self.display)

    def get_screen_size_mm(self) -> Tuple[int, int]:
        sizes = self.get_screen_sizes_mm()
        tw, th = 0, 0
        for w,h in sizes:
            tw += w
            th += h
        return tw, th

    def get_screen_sizes_mm(self) -> List[Tuple[int, int]]:
        cdef unsigned int n = XScreenCount(self.display)
        cdef unsigned int i, w, h
        cdef object sizes = []
        for i in range(n):
            w = XDisplayWidthMM(self.display, i)
            h = XDisplayHeightMM(self.display, i)
            sizes.append((w, h))
        return sizes

    def get_screen_sizes(self) -> List[Tuple[int, int]]:
        cdef unsigned int n = XScreenCount(self.display)
        cdef unsigned int i, w, h
        cdef object sizes = []
        for i in range(n):
            w = XDisplayWidth(self.display, i)
            h = XDisplayHeight(self.display, i)
            sizes.append((w, h))
        return sizes

    def get_screen_size(self) -> Tuple[int, int]:
        return self._get_screen_size()

    def _get_screen_size(self):
        self.context_check()
        cdef XRRScreenSize *xrrs
        cdef Rotation original_rotation
        cdef int num_sizes = 0
        cdef SizeID size_id
        cdef int width, height
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            raise RuntimeError("failed to get screen info")
        try:
            xrrs = XRRConfigSizes(config, &num_sizes)
            if num_sizes==0:
                #on Xwayland, we get no sizes...
                #so fallback to DisplayWidth / DisplayHeight:
                return XDisplayWidth(self.display, 0), XDisplayHeight(self.display, 0)
            if xrrs==NULL:
                raise RuntimeError("failed to get screen sizes")
            size_id = XRRConfigCurrentConfiguration(config, &original_rotation)
            if size_id<0:
                raise RuntimeError("failed to get current configuration")
            if size_id>=num_sizes:
                raise RuntimeError(f"invalid XRR size ID {size_id} (num sizes={num_sizes})")

            width = xrrs[size_id].width
            height = xrrs[size_id].height
            assert width>0 and height>0, f"invalid XRR size: {width}x{height}"
            return int(width), int(height)
        finally:
            XRRFreeScreenConfigInfo(config)

    def get_vrefresh(self) -> int:
        voutputs = self.get_vrefresh_outputs()
        if voutputs:
            return min(voutputs.values())
        return self.get_vrefresh_display()

    def get_vrefresh_display(self) -> int:
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            log.error("Error: cannot get refresh rate from screen info")
            return 0
        try:
            return XRRConfigCurrentRate(config)
        finally:
            XRRFreeScreenConfigInfo(config)

    def get_vrefresh_outputs(self) -> Dict[int, int]:
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRROutputInfo *output_info = NULL
        cdef XRRCrtcInfo *crtc_info = NULL
        cdef XRRModeInfo *mode_info = NULL
        rates = {}
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        if rsc==NULL:
            log.error("Error: cannot access screen resources")
            return 0
        try:
            for crtc in range(rsc.ncrtc):
                crtc_info = XRRGetCrtcInfo(self.display, rsc, rsc.crtcs[crtc])
                if crtc_info==NULL:
                    log.warn(f"Warning: no CRTC info for {crtc}")
                    continue
                try:
                    #find the mode info:
                    for i in range(rsc.nmode):
                        mode_info = &rsc.modes[i]
                        if mode_info.id==crtc_info.mode:
                            if mode_info.hTotal and mode_info.vTotal:
                                rate = round(mode_info.dotClock / (mode_info.hTotal * mode_info.vTotal))
                                #outputs affected:
                                output_names = []
                                for o in range(crtc_info.noutput):
                                    output_info = XRRGetOutputInfo(self.display, rsc, crtc_info.outputs[o])
                                    if output_info!=NULL:
                                        output_names.append(decode_str(output_info.name))
                                        XRRFreeOutputInfo(output_info)
                                log(f"{csv(output_names)} : {rate}")
                                rates[crtc] = rate
                            break
                finally:
                    XRRFreeCrtcInfo(crtc_info)
        finally:
            XRRFreeScreenResources(rsc)
        return rates

    def set_screen_size(self, int width, int height) -> bool:
        return self._set_screen_size(width, height)

    def add_screen_size(self, unsigned int w, unsigned int h, unsigned int vrefresh=DEFAULT_REFRESH_RATE) -> RRMode:
        hz = round(vrefresh/1000)
        name = f"{w}x{h}@{hz}"
        mode = self.do_add_screen_size(name, w, h, vrefresh)
        #now add it to the output:
        cdef RROutput output
        if mode:
            output = self.get_current_output()
            log(f"adding mode {mode:#x} to output {output:#x}")
            XRRAddOutputMode(self.display, output, mode)
        return mode

    cdef RRMode do_add_screen_size(self, name, unsigned int w, unsigned int h, unsigned int vrefresh):
        self.context_check("do_add_screen_size")
        log("do_add_screen_size(%s, %i, %i, %i)", name, w, h, vrefresh)
        cdef XRRModeInfo *new_mode = self.calculate_mode(name, w, h, vrefresh)
        assert new_mode!=NULL
        cdef RRMode mode = self._added_modes.get(name, 0)
        if mode:
            return mode
        cdef Window window = XDefaultRootWindow(self.display)
        try:
            mode_info = get_mode_info(new_mode, True)
            mode = XRRCreateMode(self.display, window, new_mode)
            log(f"XRRCreateMode returned {mode:#x} for mode %s", mode_info)
            if mode<=0:
                return 0
            self._added_modes[name] = int(mode)
        finally:
            XRRFreeModeInfo(new_mode)
        if len(self._added_modes)>MAX_NEW_MODES:
            log("too many new modes (%i), trying to remove the oldest entry", len(self._added_modes))
            log("added modes=%s", csv(self._added_modes.items()))
            try:
                rname, rmode = tuple(self._added_modes.items())[0]
                self.remove_mode(rmode)
                del self._added_modes[rname]
            except:
                log("failed to remove older mode", exc_info=True)
        return mode

    cdef XRRModeInfo *calculate_mode(self, name, unsigned int w, unsigned int h, unsigned int vrefresh):
        log("calculate_mode(%s, %i, %i, %i)", name, w, h, vrefresh)
        #monitor settings as set in xorg.conf...
        cdef unsigned int minHSync = 1*1000                     #1KHz
        cdef unsigned int maxHSync = 300*1000                   #300KHz
        cdef unsigned int minVSync = 1                          #1Hz
        cdef unsigned int maxVSync = 300                        #240Hz
        cdef double idealVSync = vrefresh/1000
        cdef double timeHFront = 0.07           #0.074219; 0.075; Width of the black border on right edge of the screen
        cdef double timeHSync = 0.1             #0.107422; 0.1125; Sync pulse duration
        cdef double timeHBack = 0.15            #0.183594; 0.1875; Width of the black border on left edge of the screen
        cdef double timeVBack = 0.06            #0.031901; 0.055664; // Adjust this to move picture up/down
        cdef double yFactor = 1                 #no interlace (0.5) or doublescan (2)

        bname = name.encode("latin1")
        cdef XRRModeInfo *mode = XRRAllocModeInfo(bname, len(bname))
        assert mode!=NULL

        xFront = round(w * timeHFront)
        xSync = round(w * timeHSync)
        xBack = round(w * timeHBack)
        xTotal = w + xFront + xSync + xBack
        yFront = 1
        ySync = 3
        yBack = round(h * timeVBack)
        yTotal = h + yFront + ySync + yBack

        if sizeof(long)<=4:
            maxPixelClock = 0xffffffff
        else:
            maxPixelClock = 30*1000*1000*1000    #30,000 MHz
        modeMaxClock = min(maxPixelClock, maxHSync * xTotal, maxVSync * xTotal * yTotal * yFactor)
        modeMinClock = max(minHSync * xTotal, minVSync * xTotal * yTotal * yFactor)
        # If minimum clock > maximum clock, the mode is impossible...
        if modeMinClock > modeMaxClock:
            log.warn(f"Warning: cannot add mode {name}")
            log.warn(f" clock {modeMinClock}Hz is above maximum value {modeMaxClock}Hz")
            log.warn(" no suitable clocks could be found")
            return NULL

        idealClock = idealVSync * xTotal * yTotal * yFactor
        cdef unsigned long clock = min(modeMaxClock, max(modeMinClock, idealClock))
        log("Modeline %ix%i@%i %s %s %s %s %s %s %s %s %s", w, h, round(vrefresh/1000),
                        clock/1000/1000,
                        w, w+xFront, w+xFront+xSync, xTotal,
                        h, h+yFront, h+yFront+ySync, yTotal)
        mode.width = w
        mode.height = h
        mode.dotClock = clock
        mode.hSyncStart = round(w+xFront)
        mode.hSyncEnd = round(w+xFront+xSync)
        mode.hTotal = round(xTotal)
        mode.hSkew = 0
        mode.vSyncStart = round(h+yFront)
        mode.vSyncEnd = round(h+yFront+ySync)
        mode.vTotal = round(yTotal)
        mode.modeFlags = 0
        return mode

    def remove_screen_size(self, unsigned int w, unsigned int h) -> None:
        #TODO: instead of keeping the mode ID,
        #we should query the output and find the mode dynamically...
        name = "%sx%s" % (w, h)
        cdef RRMode mode = self._added_modes.get(name, 0)
        if mode and self.remove_mode(mode):
            del self._added_modes[name]

    def remove_mode(self, RRMode mode) -> None:
        self.context_check("remove_mode")
        cdef RROutput output = self.get_current_output()
        log(f"remove_mode({mode}) output={output}")
        if mode and output:
            XRRDeleteOutputMode(self.display, output, mode)
            XRRDestroyMode(self.display, mode)

    cdef RROutput get_current_output(self):
        self.context_check("get_current_output")
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        assert rsc!=NULL
        try:
            log("get_current_output() screen_resources: crtcs=%s, outputs=%s, modes=%s", rsc.ncrtc, rsc.noutput, rsc.nmode)
            if rsc.noutput==0:
                log.error("Error: this display has no outputs")
                return 0
            if rsc.noutput>1:
                log(f"{rsc.noutput} outputs")
            return rsc.outputs[0]
        finally:
            XRRFreeScreenResources(rsc)

    def xrr_set_screen_size(self, int w, int h, int wmm, int hmm) -> None:
        self.context_check("xrr_set_screen_size")
        #and now use it:
        cdef Window window = XDefaultRootWindow(self.display)
        log("XRRSetScreenSize(%#x, %#x, %i, %i, %i, %i)", <uintptr_t> self.display, window, w, h, wmm, hmm)
        XRRSetScreenSize(self.display, window, w, h, wmm, hmm)
        self.XSync()

################################################################
#Below is for handling fully virtualized monitors with
#RandR 1.6 and the dummy version 0.4.0 or later
################################################################

    def is_dummy16(self) -> bool:
        self.context_check("is_dummy16")
        #figure out if we're dealing with the dummy with randr 1.6 support
        if not self._has_randr:
            log("is_dummy16() no randr!")
            return False
        if self.version<(1, 6):
            log(f"is_dummy16() randr version too old: {self.version}")
            return False
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        try:
            if rsc.ncrtc<16:
                log(f"is_dummy16() only {rsc.ncrtc} crtcs")
                return False
            if rsc.noutput<16:
                log(f"is_dummy16() only {rsc.noutput} outputs")
                return False
            if rsc.nmode==0:
                log("is_dummy16() no modes!")
                return False
        finally:
            XRRFreeScreenResources(rsc)
        cdef int nmonitors
        cdef XRRMonitorInfo *monitors = XRRGetMonitors(self.display, window, True, &nmonitors)
        try:
            if not nmonitors:
                log("is_dummy16() no monitors!")
                return False
            for i in range(nmonitors):
                if monitors[i].noutput!=1:
                    n = monitors[i].noutput
                    log(f"is_dummy16() monitor {i} has {n} outputs")
                    return False
        finally:
            XRRFreeMonitors(monitors)
        return True

    def get_monitor_properties(self) -> Dict[str, Any]:
        self.context_check("get_monitor_properties")
        return get_monitor_properties(self.display)

    def get_all_screen_properties(self) -> Dict[str, Any]:
        self.context_check("get_all_screen_properties")
        return get_all_screen_properties(self.display)

    def set_output_int_property(self, int output, prop_name: str, int value) -> None:
        self.context_check("set_output_int_property")
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        if rsc==NULL:
            log.error("Error: cannot access screen resources")
            return {}
        if output<0 or output>=rsc.noutput:
            raise ValueError(f"invalid output number {output}, only {rsc.noutput} outputs")
        cdef RROutput rro = rsc.outputs[output]
        cdef Atom prop = self.str_to_atom(prop_name)
        cdef Atom ptype = self.str_to_atom("INTEGER")
        data = struct.pack("@L", value)
        XRRChangeOutputProperty(self.display, rro, prop, ptype,
                                32, PropModeReplace, data, 1)

    def has_mode(self, unsigned int w, unsigned int h) -> bool:
        self.context_check("has_mode")
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        try:
            for i in range(rsc.nmode):
                if rsc.modes[i].width==w and rsc.modes[i].height==h:
                    return True
            return False
        finally:
            XRRFreeScreenResources(rsc)

    def set_crtc_config(self, monitor_defs: Dict) -> None:
        self.context_check("set_crtc_config")
        log(f"set_crtc_config({monitor_defs})")
        def dpi96(v):
            return round(v * 25.4 / 96)
        #first, find the total screen area:
        screen_w, screen_h = 0, 0
        for m in monitor_defs.values():
            x, y, width, height = m["geometry"]
            screen_w = max(screen_w, x+width)
            screen_h = max(screen_h, y+height)
        log(f"total screen area is: {screen_w}x{screen_h}")
        if not self.has_mode(screen_w, screen_h):
            self.add_screen_size(screen_w, screen_h, DEFAULT_REFRESH_RATE)
        self.set_screen_size(screen_w, screen_h)
        self.xrr_set_screen_size(screen_w, screen_h, dpi96(screen_w), dpi96(screen_h))
        root_w, root_h = self.get_screen_size()
        log(f"root size is now: {root_w}x{root_h}")
        count = len(monitor_defs)
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        cdef Status r
        if rsc==NULL:
            log.error("Error: cannot access screen resources")
            return False
        if max(monitor_defs.keys())>=rsc.ncrtc or min(monitor_defs.keys())<0:
            log.error("Error: invalid monitor indexes in %s", csv(monitor_defs.keys()))
            return False
        if rsc.ncrtc<count:
            log.error(f"Error: only {rsc.ncrtc} crtcs for {count} monitors")
            return False
        if rsc.noutput<count:
            log.error(f"Error: only {rsc.noutput} outputs for {count} monitors")
            return False
        cdef RRMode mode
        cdef XRRModeInfo *match_mode = NULL
        cdef int nmonitors
        cdef RRCrtc crtc
        cdef XRRCrtcInfo *crtc_info = NULL
        cdef RROutput output
        cdef XRROutputInfo *output_info = NULL
        cdef XRRMonitorInfo *monitors
        cdef XRRMonitorInfo monitor
        primary = 0
        #we can't have monitor names the same as output names!?
        output_names = []
        new_modes = {}
        try:
            for i in range(rsc.ncrtc):
                m = monitor_defs.get(i, {})
                crtc = rsc.crtcs[i]
                assert rsc.noutput>i
                output = rsc.outputs[i]
                log(f"{i}: crtc {crtc} and output {output}: {m}")
                crtc_info = XRRGetCrtcInfo(self.display, rsc, crtc)
                if not crtc_info:
                    log.error(f"Error: crtc {i} not found ({crtc:#x})")
                    continue
                try:
                    output_info = XRRGetOutputInfo(self.display, rsc, output)
                    if not output_info:
                        log.error(f"Error: output {i} not found ({output:#x})")
                        continue
                    output_names.append(s(output_info.name[:output_info.nameLen]))
                    if crtc_info.noutput==0 and output_info.connection==RR_Disconnected and not m:
                        #crtc is not enabled and the corresponding output is not connected,
                        #which is exactly what we want, so just leave it alone
                        log(f"crtc and output {i} are already disabled")
                        continue
                    noutput = 1
                    mode = 0
                    vrefresh = 0
                    hz = 60
                    x, y, width, height = 0, 0, 1024, 768
                    if m:
                        if m.get("primary", False):
                            primary = i
                        x, y, width, height = m["geometry"]
                        vrefresh = m.get("refresh-rate", DEFAULT_REFRESH_RATE)
                        hz = round(vrefresh/1000)
                        mode_name = f"{width}x{height}@{hz}"
                        match_mode = self.calculate_mode(mode_name, width, height, vrefresh)
                        assert match_mode, "no mode to match"
                        #find an existing mode matching this resolution + vrefresh:
                        for j in range(output_info.nmode):
                            #find this exact RRMode in the screen modes info:
                            for k in range(rsc.nmode):
                                if (
                                    rsc.modes[k].id==output_info.modes[j] and
                                    rsc.modes[k].width==match_mode.width and
                                    rsc.modes[k].height==match_mode.height and
                                    rsc.modes[k].dotClock==match_mode.dotClock
                                    ):
                                    mode = output_info.modes[j]
                                    mode_name = s(rsc.modes[j].name)
                                    log("using existing output mode %r (%#x) for %ix%i",
                                        mode_name, mode, width, height)
                                    break
                            if mode:
                                break
                        if not mode:
                            #try to find a screen mode not added to this output yet:
                            for j in range(rsc.nmode):
                                if (
                                    rsc.modes[j].width==match_mode.width and
                                    rsc.modes[j].height==match_mode.height and
                                    rsc.modes[j].dotClock==match_mode.dotClock
                                    ):
                                    mode = rsc.modes[j].id
                                    mode_name = s(rsc.modes[j].name)
                                    log(f"using screen mode {mode_name!r} ({mode:#x}) for {width}x{height}")
                                    break
                            if not mode:
                                #may have already been added:
                                mode = new_modes.get(mode_name, 0)
                                if not mode:
                                    mode = self.do_add_screen_size(mode_name, width, height, vrefresh)
                                    new_modes[mode_name] = mode
                            assert mode!=0, f"mode {width}x{height}@{hz} not found"
                            XRRAddOutputMode(self.display, output, mode)
                            log(f"mode {mode_name!r} ({mode:#x}) added to output {i} ({output})")
                        XRRFreeModeInfo(match_mode)
                    else:
                        noutput = 0

                    log("XRRSetCrtcConfig(%#x, %#x, %i, %i, %i, %i, %i, %i, %#x, %i)",
                            <uintptr_t> self.display, <uintptr_t> rsc, crtc,
                            CurrentTime, x, y, mode, RR_Rotate_0, <uintptr_t> &output, noutput)
                    r = XRRSetCrtcConfig(self.display, rsc, crtc,
                          CurrentTime, x, y, mode,
                          RR_Rotate_0, &output, noutput)
                    if r:
                        raise RuntimeError(f"failed to set crtc config for monitor {i}")
                    mmw = m.get("width-mm", 0) or dpi96(width)
                    mmh = m.get("height-mm", 0) or dpi96(height)
                    self.set_output_int_property(i, "WIDTH_MM", mmw)
                    self.set_output_int_property(i, "HEIGHT_MM", mmh)
                    #this allows us to disconnect the output of this crtc:
                    self.set_output_int_property(i, "SUSPENDED", not bool(m))
                    if width==0 or height==0:
                        log.info(f"disabling dummy crtc and output {i}")
                    else:
                        posinfo = ""
                        if x or y:
                            posinfo = " at %i,%i" % (x, y)
                        dpiinfo = ""
                        dpix = round(width * 25.4 / mmw)
                        dpiy = round(height * 25.4 / mmh)
                        if abs(dpix-dpiy)<2:
                            dpi = round((dpix+dpiy)/2)
                            dpiinfo = f"dpi={dpi}"
                        else:
                            dpiinfo = f"dpi={dpix}x{dpiy}"
                        log.info(f"setting dummy crtc and output {i} to:")
                        log.info(f" {width}x{height} {hz}Hz ({mmw}x{mmh} mm, {dpiinfo}){posinfo}")
                finally:
                    if output_info:
                        XRRFreeOutputInfo(output_info)
                        output_info = NULL
                    if crtc_info:
                        XRRFreeCrtcInfo(crtc_info)
                        crtc_info = NULL
            self.XSync()
            #now configure the monitors
            monitors = XRRGetMonitors(self.display, window, True, &nmonitors)
            if not monitors:
                log.error("Error: failed to retrieve the list of monitors")
                return False
            log(f"got {nmonitors} monitors for {len(monitor_defs)} crtcs")
            #start by removing the ones we don't use:
            try:
                #we only need as many monitors as we have crtcs,
                for mi in range(len(monitor_defs), nmonitors):
                    name_atom = monitors[mi].name
                    log(f"deleting monitor {mi}: %s", self.get_atom_name(name_atom))
                    XRRDeleteMonitor(self.display, window, name_atom)
            finally:
                XRRFreeMonitors(monitors)
            self.XSync()
            #rename the ones we do use
            #which makes it easier to prevent name Atom conflicts:
            #we use a temporary name that is guaranteed to never conflict
            #when we finally modify the monitors to use the unique name we actually want:
            monitors = XRRGetMonitors(self.display, window, True, &nmonitors)
            try:
                for mi in range(nmonitors):
                    monitors[mi].name = self.str_to_atom(f"VFBTEMP{mi}")
                    XRRSetMonitor(self.display, window, &monitors[mi])
            finally:
                XRRFreeMonitors(monitors)
            self.XSync()
            monitors = XRRGetMonitors(self.display, window, True, &nmonitors)
            if not monitors:
                log.error("Error: failed to retrieve the list of monitors")
                return False
            try:
                names = {}
                for mi in range(nmonitors):
                    names[mi] = self.get_atom_name(monitors[mi].name)
                log(f"found {nmonitors} monitors still active: %s", csv(names.values()))
                active_names = {}
                mi = 0
                for i, m  in monitor_defs.items():
                    log(f"matching monitor index {mi} to {i}: {m}")
                    name = (prettify_plug_name(m.get("name", "")) or ("VFB-%i" % mi))
                    if name in output_names:
                        name = "VFB-%i" % mi
                    while (name in names.values() or name in active_names.values()) and names.get(mi)!=name and active_names.get(mi)!=name:
                        name += "-%i" % mi
                    x, y, width, height = m["geometry"]
                    active_names[mi] = name
                    monitor.name = self.str_to_atom(name)
                    monitor.primary = m.get("primary", primary==mi)
                    monitor.automatic = m.get("automatic", True)
                    monitor.x = x
                    monitor.y = y
                    monitor.width = width
                    monitor.height = height
                    monitor.mwidth = m.get("width-mm", dpi96(monitor.width))
                    monitor.mheight = m.get("height-mm", dpi96(monitor.height))
                    assert rsc.noutput>i, f"only {rsc.noutput} outputs, cannot set {i}"
                    output = rsc.outputs[i]
                    monitor.outputs = &output
                    monitor.noutput = 1
                    log("XRRSetMonitor(%#x, %#x, %#x) output=%i, geometry=%s (%ix%i mm)",
                        <uintptr_t> self.display, <uintptr_t> window, <uintptr_t> &monitor, output,
                        (monitor.x, monitor.y, monitor.width, monitor.height),
                        monitor.mwidth, monitor.mheight)
                    log.info(f"monitor {mi} is {name!r} {monitor.width}x{monitor.height}")
                    XRRSetMonitor(self.display, window, &monitor)
                    mi += 1
            finally:
                XRRFreeMonitors(monitors)
        finally:
            XRRFreeScreenResources(rsc)


cdef RandRBindingsInstance singleton = None


def RandRBindings() -> RandRBindingsInstance:
    global singleton
    if singleton is None:
        singleton = RandRBindingsInstance()
    return singleton
