# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from time import monotonic

from xpra.log import Logger
log = Logger("x11", "bindings", "randr")

from xpra.x11.bindings.xlib cimport (
    Display, XID, Bool, Status, Drawable, Window, Time, Atom,
    XDefaultRootWindow,
    XFree, XFlush, XSync,
    AnyPropertyType, PropModeReplace,
    CurrentTime, Success,
    )
from xpra.util import envint, envbool, csv, first_time, decode_str, prettify_plug_name
from xpra.os_util import strtobytes, bytestostr


TIMESTAMPS = envbool("XPRA_RANDR_TIMESTAMPS", False)
GAMMA = envbool("XPRA_RANDR_GAMMA", False)
MAX_NEW_MODES = envint("XPRA_RANDR_MAX_NEW_MODES", 32)
assert MAX_NEW_MODES>=2


from libc.stdint cimport uintptr_t  #pylint: disable=syntax-error
ctypedef unsigned long CARD32


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


MODE_FLAGS_STR = {
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

ROTATIONS = {
    RR_Rotate_0             : 0,
    RR_Rotate_90            : 90,
    RR_Rotate_180           : 180,
    RR_Rotate_270           : 270,
    }

CONNECTION_STR = {
    RR_Connected            : "Connected",
    RR_Disconnected         : "Disconnected",
    RR_UnknownConnection    : "Unknown",
    }

def get_rotation(Rotation v):
    return ROTATIONS.get(v, 0)

def get_rotations(Rotation v):
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

    Bool XRRQueryExtension(Display *, int *, int *)
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

    ctypedef unsigned short SizeID
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
    void XRRChangeOutputProperty (Display *dpy, RROutput output, Atom property, Atom type,
                                  int format, int mode, unsigned char *data, int nelements)
    ctypedef struct XRRPropertyInfo:
        Bool    pending
        Bool    range
        Bool    immutable
        int     num_values
        long    *values
    XRRPropertyInfo *XRRQueryOutputProperty(Display *dpy, RROutput output, Atom property)
    int XRRGetOutputProperty (Display *dpy, RROutput output,
                              Atom property, long offset, long length,
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


from xpra.x11.bindings.core_bindings cimport X11CoreBindingsInstance

cdef RandRBindingsInstance singleton = None
def RandRBindings():
    global singleton
    if singleton is None:
        singleton = RandRBindingsInstance()
    return singleton

cdef class RandRBindingsInstance(X11CoreBindingsInstance):

    cdef int _has_randr
    cdef object _added_modes
    cdef object version

    def __init__(self):
        self.version = self.query_version()
        self._has_randr = self.version>(0, ) and self.check_randr_sizes()
        self._added_modes = {}

    def __repr__(self):
        return "RandRBindings(%s)" % self.display_name

    def get_version(self):
        return self.version

    def query_version(self):
        cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
        cdef int r = XRRQueryExtension(self.display, &event_base, &ignored)
        log("XRRQueryExtension()=%i", r)
        if not r:
            return (0, )
        log("found XRandR extension")
        if not XRRQueryVersion(self.display, &cmajor, &cminor):
            return (0, )
        log("found XRandR extension version %i.%i", cmajor, cminor)
        return (cmajor, cminor)

    def check_randr_sizes(self):
        #check for wayland, which has no sizes:
        #(and we wouldn't be able to set screen resolutions)
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            log("check_randr_sizes: failed to get randr screen info")
            return False
        cdef int num_sizes = 0
        XRRConfigSizes(config, &num_sizes)
        log("found %i config sizes", num_sizes)
        return num_sizes>0

    def has_randr(self):
        return bool(self._has_randr)

    def select_crtc_output_changes(self):
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

    def get_xrr_screen_sizes(self):
        v = self._get_xrr_screen_sizes()
        log("get_xrr_screen_sizes()=%s", v)
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
                    log.warn(" cannot set screen size to match %ix%i", width, height)
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
                    log.error("Error: size not found for %ix%i" % (width, height))
                    log.error(" %i sizes are supported", num_sizes)
                    if num_sizes<=16:
                        log.error(" %s", csv("%ix%i" % (w,h) for w,h in sizes))
                    else:
                        log("sizes found: %s", csv(sizes))
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
                return False
            return True
        finally:
            XRRFreeScreenConfigInfo(config)


    def get_screen_count(self):
        return XScreenCount(self.display)

    def get_screen_size_mm(self):
        sizes = self.get_screen_sizes_mm()
        tw, th = 0, 0
        for w,h in sizes:
            tw += w
            th += h
        return tw, th

    def get_screen_sizes_mm(self):
        cdef unsigned int n = XScreenCount(self.display)
        cdef unsigned int i, w, h
        cdef object sizes = []
        for i in range(n):
            w = XDisplayWidthMM(self.display, i)
            h = XDisplayHeightMM(self.display, i)
            sizes.append((w, h))
        return sizes

    def get_screen_sizes(self):
        cdef unsigned int n = XScreenCount(self.display)
        cdef unsigned int i, w, h
        cdef object sizes = []
        for i in range(n):
            w = XDisplayWidth(self.display, i)
            h = XDisplayHeight(self.display, i)
            sizes.append((w, h))
        return sizes

    def get_screen_size(self):
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
            raise Exception("failed to get screen info")
        try:
            xrrs = XRRConfigSizes(config, &num_sizes)
            if num_sizes==0:
                #on Xwayland, we get no sizes...
                #so fallback to DisplayWidth / DisplayHeight:
                return XDisplayWidth(self.display, 0), XDisplayHeight(self.display, 0)
            if xrrs==NULL:
                raise Exception("failed to get screen sizes")
            size_id = XRRConfigCurrentConfiguration(config, &original_rotation)
            if size_id<0:
                raise Exception("failed to get current configuration")
            if size_id>=num_sizes:
                raise Exception("invalid XRR size ID %i (num sizes=%i)" % (size_id, num_sizes))

            width = xrrs[size_id].width;
            height = xrrs[size_id].height;
            assert width>0 and height>0, "invalid XRR size: %ix%i" % (width, height)
            return int(width), int(height)
        finally:
            XRRFreeScreenConfigInfo(config)

    def get_vrefresh(self):
        voutputs = self.get_vrefresh_outputs()
        if voutputs:
            return min(voutputs.values())
        return self.get_vrefresh_display()

    def get_vrefresh_display(self):
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenConfiguration *config = XRRGetScreenInfo(self.display, window)
        if config==NULL:
            log.error("Error: cannot get refresh rate from screen info")
            return 0
        try:
            return XRRConfigCurrentRate(config)
        finally:
            XRRFreeScreenConfigInfo(config)

    def get_vrefresh_outputs(self):
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
                    log.warn("Warning: no CRTC info for %i", crtc)
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
                                log("%s : %s", csv(output_names), rate)
                                rates[crtc] = rate
                            break
                finally:
                    XRRFreeCrtcInfo(crtc_info)
        finally:
            XRRFreeScreenResources(rsc)
        return rates


    def set_screen_size(self, width, height):
        return self._set_screen_size(width, height)

    def add_screen_size(self, unsigned int w, unsigned int h):
        name = "%sx%s" % (w, h)
        mode = self.do_add_screen_size(name, w, h)
        #now add it to the output:
        cdef RROutput output
        if mode:
            output = self.get_current_output()
            log("adding mode %#x to output %#x", mode, output)
            XRRAddOutputMode(self.display, output, mode)
        return mode

    cdef do_add_screen_size(self, name, unsigned int w, unsigned int h):
        self.context_check()
        log("do_add_screen_size(%s, %i, %i)", name, w, h)
        cdef RRMode mode

        #monitor settings as set in xorg.conf...
        cdef unsigned int maxPixelClock = 230*1000*1000         #230MHz
        cdef unsigned int minHSync = 1*1000                     #1KHz
        cdef unsigned int maxHSync = 300*1000                   #300KHz
        cdef unsigned int minVSync = 1                          #1Hz
        cdef unsigned int maxVSync = 300                        #30Hz
        cdef double idealVSync = 50.0
        cdef double timeHFront = 0.07           #0.074219; 0.075; Width of the black border on right edge of the screen
        cdef double timeHSync = 0.1             #0.107422; 0.1125; Sync pulse duration
        cdef double timeHBack = 0.15            #0.183594; 0.1875; Width of the black border on left edge of the screen
        cdef double timeVBack = 0.06            #0.031901; 0.055664; // Adjust this to move picture up/down
        cdef double yFactor = 1                 #no interlace (0.5) or doublescan (2)

        bname = strtobytes(name)
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRModeInfo *new_mode = XRRAllocModeInfo(bname, len(bname))
        assert new_mode!=NULL

        cdef unsigned long clock
        try:
            xFront = int(w * timeHFront)
            xSync = int(w * timeHSync)
            xBack = int(w * timeHBack)
            xTotal = w + xFront + xSync + xBack
            yFront = 1
            ySync = 3
            yBack = int(h * timeVBack)
            yTotal = h + yFront + ySync + yBack

            modeMaxClock = maxPixelClock
            if (maxHSync * xTotal)<maxPixelClock:
                modeMaxClock = maxHSync * xTotal
            tmp = maxVSync * xTotal * yTotal * yFactor
            if tmp<modeMaxClock:
                modeMaxClock = tmp
            modeMinClock = minHSync * xTotal
            # Monitor minVSync too low? => increase mode minimum pixel clock
            tmp = minVSync * xTotal * yTotal * yFactor
            if tmp > modeMinClock:
                modeMinClock = tmp
            # If minimum clock > maximum clock, the mode is impossible...
            if modeMinClock > modeMaxClock:
                log.warn("Warning: cannot add mode %s", name)
                log.warn(" clock %iHz is above maximum value %iHz", modeMinClock, modeMaxClock)
                log.warn(" no suitable clocks could be found")
                return False

            idealClock = idealVSync * xTotal * yTotal * yFactor
            clock = idealClock;
            if clock < modeMinClock:
                clock = modeMinClock
            elif clock > modeMaxClock:
                clock = modeMaxClock

            log("Modeline %sx%s %s %s %s %s %s %s %s %s %s", w, h, clock/1000/1000,
                            w, w+xFront, w+xFront+xSync, xTotal,
                            h, h+yFront, h+yFront+ySync, yTotal)
            new_mode.width = w
            new_mode.height = h
            new_mode.dotClock = clock
            new_mode.hSyncStart = int(w+xFront)
            new_mode.hSyncEnd = int(w+xFront+xSync)
            new_mode.hTotal = int(xTotal)
            new_mode.hSkew = 0
            new_mode.vSyncStart = int(h+yFront)
            new_mode.vSyncEnd = int(h+yFront+ySync)
            new_mode.vTotal = int(yTotal)
            new_mode.modeFlags = 0
            mode = XRRCreateMode(self.display, window, new_mode)
            log("XRRCreateMode returned %#x" % mode)
            if mode<=0:
                return None
            self._added_modes[name] = int(mode)
        finally:
            XRRFreeModeInfo(new_mode)
        if len(self._added_modes)>MAX_NEW_MODES:
            log("too many new modes (%i), trying to remove the oldest entry", len(self._added_modes))
            log("added modes=%s", csv(self._added_modes.items()))
            try:
                rname, mode = tuple(self._added_modes.items())[0]
                self.remove_mode(mode)
                del self._added_modes[rname]
            except:
                log("failed to remove older mode", exc_info=True)
        return mode

    def remove_screen_size(self, unsigned int w, unsigned int h):
        #TODO: instead of keeping the mode ID,
        #we should query the output and find the mode dynamically...
        name = "%sx%s" % (w, h)
        cdef RRMode mode = self._added_modes.get(name, 0)
        if mode and self.remove_mode(mode):
            del self._added_modes[name]

    def remove_mode(self, RRMode mode):
        self.context_check()
        cdef RROutput output = self.get_current_output()
        log("remove_mode(%i) output=%i", mode, output)
        if mode and output:
            XRRDeleteOutputMode(self.display, output, mode)
            XRRDestroyMode(self.display, mode)

    cdef RROutput get_current_output(self):
        self.context_check()
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        assert rsc!=NULL
        try:
            log("get_current_output() screen_resources: crtcs=%s, outputs=%s, modes=%s", rsc.ncrtc, rsc.noutput, rsc.nmode)
            if rsc.noutput==0:
                log.error("Error: this display has no outputs")
                return 0
            if rsc.noutput>1:
                log("%s outputs", rsc.noutput)
            return rsc.outputs[0]
        finally:
            XRRFreeScreenResources(rsc)

    def xrr_set_screen_size(self, w, h, wmm, hmm):
        self.context_check()
        #and now use it:
        cdef Window window = XDefaultRootWindow(self.display)
        log("XRRSetScreenSize(%#x, %#x, %i, %i, %i, %i)", <uintptr_t> self.display, window, w, h, wmm, hmm)
        XRRSetScreenSize(self.display, window, w, h, wmm, hmm)
        self.XSync()


################################################################
#Below is for handling fully virtualized monitors with
#RandR 1.6 and the dummy version 0.4.0 or later
################################################################

    def is_dummy16(self):
        #figure out if we're dealing with the dummy with randr 1.6 support
        if not self._has_randr:
            log("is_dummy16() no randr!")
            return False
        if self.version<(1, 6):
            log("is_dummy16() randr version too old: %s", self.version)
            return False
        self.context_check()
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        try:
            if rsc.ncrtc<16:
                log("is_dummy16() only %i crtcs", rsc.ncrtc)
                return False
            if rsc.noutput<16:
                log("is_dummy16() only %i outputs", rsc.noutput)
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
                    log("is_dummy16() monitor %i has %i outputs", i, monitors[i].noutput)
                    return False
        finally:
            XRRFreeMonitors(monitors)
        return True

    cdef get_mode_info(self, XRRModeInfo *mi, with_sync=False):
        info = {
            "id"            : mi.id,
            "width"         : mi.width,
            "height"        : mi.height,
            }
        if mi.name and mi.nameLength:
            info["name"] = bytestostr(mi.name[:mi.nameLength])
        if with_sync:
            info.update({
            "dot-clock"     : mi.dotClock,
            "h-sync-start"  : mi.hSyncStart,
            "h-sync-end"    : mi.hSyncEnd,
            "h-total"       : mi.hTotal,
            "h-skew"        : mi.hSkew,
            "v-sync-start"  : mi.vSyncStart,
            "v-sync-end"    : mi.vSyncEnd,
            "v-total"       : mi.vTotal,
            "mode-flags"    : tuple(name for v,name in MODE_FLAGS_STR.items() if mi.modeFlags & v),
            })
        return info

    cdef get_output_properties(self, RROutput output):
        cdef int nprop
        cdef Atom *atoms = XRRListOutputProperties(self.display, output, &nprop)
        cdef Atom prop, actual_type
        cdef int actual_format
        cdef unsigned long nitems
        cdef unsigned long bytes_after
        cdef unsigned char *buf
        cdef int nbytes
        cdef XRRPropertyInfo *prop_info
        log("reading %i properties from output %i", nprop, output)
        properties = {}
        for i in range(nprop):
            prop = atoms[i]
            prop_name = bytestostr(self.XGetAtomName(prop))
            buf = NULL
            r = XRRGetOutputProperty(self.display, output,
                                     prop, 0, 1024,
                                     0, 0, AnyPropertyType,
                                     &actual_type, &actual_format,
                                     &nitems, &bytes_after,
                                     &buf)
            if r or not buf:
                log.warn("Warning: failed to read output property %s", prop_name)
                continue
            if bytes_after:
                log.warn("Warning: failed to read output property %s", prop_name)
                log.warn(" data too large")
                continue
            if not actual_format:
                log.warn("Warning: failed to read output property %s", prop_name)
                log.warn(" invalid format")
                continue
            at = bytestostr(self.XGetAtomName(actual_type))
            if at not in ("INTEGER", "CARDINAL", "ATOM"):
                log("skipped output property %s", at)
                continue
            if actual_format == 8:
                fmt = b"B"
            elif actual_format == 16:
                fmt = b"H"
            elif actual_format == 32:
                fmt = b"L"
            else:
                raise Exception("invalid format %r" % actual_format)
            log("%s : %s / %s", prop_name, at, actual_format)
            try:
                bytes_per_item = struct.calcsize(b"@%s" % fmt)
                nbytes = bytes_per_item * nitems
                data = buf[:nbytes]
                value = struct.unpack(b"@%s" % (fmt*nitems), data)
                if at=="ATOM":
                    value = tuple(bytestostr(self.XGetAtomName(v)) for v in value)
                if at=="INTEGER" and actual_format==8 and prop_name=="EDID" and nitems>=32:
                    #EDID is a binary blob:
                    value = bytes(value)
                    try:
                        from pyedid import parse_edid
                        value = parse_edid(value)._asdict()
                    except ImportError as e:
                        log("cannot parse EDID: %s", e)
                    except ValueError as e:
                        log.warn("Warning: invalid EDID data: %s", e)
                if nitems==1:
                    value = value[0]
                    #convert booleans:
                    prop_info = XRRQueryOutputProperty(self.display, output, prop)
                    if prop_info:
                        if prop_info.num_values==2 and prop_info.values[0] in (0, 1) and prop_info.values[1] in (0, 1):
                            value = bool(value)
                        XFree(prop_info)
            except Exception:
                log.error("Error unpacking %s using format %s from %s",
                          prop_name, fmt, data, exc_info=True)
            else:
                if prop_name=="non-desktop" and value is False:
                    #no value in reporting this, we can assume it is False when missing
                    continue
                properties[prop_name] = value
        XFree(atoms)
        return properties

    cdef get_output_info(self, XRRScreenResources *rsc, RROutput output):
        cdef XRROutputInfo *oi = XRRGetOutputInfo(self.display, rsc, output)
        if oi==NULL:
            return {}
        info = {
            "id"                : output,
            "connection"        : CONNECTION_STR.get(oi.connection, "%i" % oi.connection),
            }
        if oi.connection!=RR_Disconnected:
            info.update({
            "mm-width"          : oi.mm_width,
            "mm-height"         : oi.mm_height,
            "preferred-mode"    : oi.npreferred,
            })
            if TIMESTAMPS:
                info["timestamp"] = oi.timestamp
            so = SUBPIXEL_STR.get(oi.subpixel_order)
            if so and so!="unknown":
                info["subpixel-order"] = so
            if oi.nclone:
                info["clones"] = tuple(int(oi.clones[i] for i in range(oi.nclone)))
            info["properties"] = self.get_output_properties(output)
        if oi.name and oi.nameLen:
            info["name"] = bytestostr(oi.name[:oi.nameLen])
        XRRFreeOutputInfo(oi)
        return info

    cdef get_crtc_info(self, XRRScreenResources *rsc, RRCrtc crtc):
        cdef XRRCrtcInfo *ci = XRRGetCrtcInfo(self.display, rsc, crtc)
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
            info.update({
                "x"         : ci.x,
                "y"         : ci.y,
                "width"     : ci.width,
                "height"    : ci.height,
                "mode"      : ci.mode,
                })
            if GAMMA:
                gamma = XRRGetCrtcGamma(self.display, crtc)
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

    def get_monitor_properties(self):
        cdef int nmonitors
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRMonitorInfo *monitors = XRRGetMonitors(self.display, window, True, &nmonitors)
        cdef XRRMonitorInfo *m
        props = {}
        for i in range(nmonitors):
            m = &monitors[i]
            props[i] = {
                "index"     : i,
                "name"      : bytestostr(self.XGetAtomName(m.name)),
                "primary"   : bool(m.primary),
                "automatic" : bool(m.automatic),
                "x"         : m.x,
                "y"         : m.y,
                "width"     : m.width,
                "height"    : m.height,
                "mm-width"  : m.mwidth,
                "mm-height" : m.mheight,
                #"outputs"   : tuple(rroutput_map.get(m.outputs[j], 0) for j in range(m.noutput)),
                "outputs"   : tuple(m.outputs[j] for j in range(m.noutput)),
                }
        XRRFreeMonitors(monitors)
        return props

    def get_all_screen_properties(self):
        self.context_check()
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        cdef RROutput primary = XRRGetOutputPrimary(self.display, window)
        if rsc==NULL:
            log.error("Error: cannot access screen resources")
            return {}
        props = {}
        if TIMESTAMPS:
            props["timestamp"] = rsc.timestamp
            props["config-timestamp"] = rsc.configTimestamp
        for i in range(rsc.nmode):
            props.setdefault("modes", {})[i] = self.get_mode_info(&rsc.modes[i])
        try:
            for o in range(rsc.noutput):
                if primary and primary==rsc.outputs[o]:
                    props["primary-output"] = o
                output_info = self.get_output_info(rsc, rsc.outputs[o])
                if output_info:
                    oid = output_info["id"]
                    props.setdefault("outputs", {})[oid] = output_info
            for crtc in range(rsc.ncrtc):
                crtc_info = self.get_crtc_info(rsc, rsc.crtcs[crtc])
                if crtc_info:
                    props.setdefault("crtcs", {})[crtc] = crtc_info
        finally:
            XRRFreeScreenResources(rsc)
        props["monitors"] = self.get_monitor_properties()
        return props


    def set_output_int_property(self, int output, prop_name, int value):
        self.context_check()
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        if rsc==NULL:
            log.error("Error: cannot access screen resources")
            return {}
        if output<0 or output>=rsc.noutput:
            raise Exception("invalid output number %r, only %i outputs" % (output, rsc.noutput))
        cdef RROutput rro = rsc.outputs[output]
        cdef Atom prop = self.xatom(prop_name)
        cdef Atom ptype = self.xatom("INTEGER")
        data = struct.pack("@L", value)
        XRRChangeOutputProperty(self.display, rro, prop, ptype,
                                32, PropModeReplace, data, 1)

    def has_mode(self, unsigned int w, unsigned int h):
        self.context_check()
        cdef Window window = XDefaultRootWindow(self.display)
        cdef XRRScreenResources *rsc = XRRGetScreenResourcesCurrent(self.display, window)
        try:
            for i in range(rsc.nmode):
                if rsc.modes[i].width==w and rsc.modes[i].height==h:
                    return True
            return False
        finally:
            XRRFreeScreenResources(rsc)

    def set_crtc_config(self, monitor_defs):
        self.context_check()
        log("set_crtc_config(%s)", monitor_defs)
        def dpi96(v):
            return round(v * 25.4 / 96)
        #first, find the total screen area:
        screen_w, screen_h = 0, 0
        for m in monitor_defs.values():
            width = m.get("width", 0)
            height = m.get("height", 0)
            x = m.get("x", 0)
            y = m.get("y", 0)
            screen_w = max(screen_w, x+width)
            screen_h = max(screen_h, y+height)
        log("total screen area is: %ix%i", screen_w, screen_h)
        if not self.has_mode(screen_w, screen_h):
            self.add_screen_size(screen_w, screen_h)
        self.set_screen_size(screen_w, screen_h)
        self.xrr_set_screen_size(screen_w, screen_h, dpi96(screen_w), dpi96(screen_h))
        root_w, root_h = self.get_screen_size()
        log("root size is now: %ix%i", root_w, root_h)
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
            log.error("Error: only %i crtcs for %i monitors", rsc.ncrtc, count)
            return False
        if rsc.noutput<count:
            log.error("Error: only %i outputs for %i monitors", rsc.noutput, count)
            return False
        cdef RRMode mode
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
        try:
            for i in range(rsc.ncrtc):
                m = monitor_defs.get(i, {})
                crtc = rsc.crtcs[i]
                assert rsc.noutput>i
                output = rsc.outputs[i]
                log("%i: crtc %i and output %i: %s", i, crtc, output, m)
                crtc_info = XRRGetCrtcInfo(self.display, rsc, crtc)
                if not crtc_info:
                    log.error("Error: crtc %i not found (%#x)", i, crtc)
                    continue
                try:
                    if m.get("primary", False):
                        primary = i
                    width = m.get("width", 0)
                    height = m.get("height", 0)
                    output_info = XRRGetOutputInfo(self.display, rsc, output)
                    if not output_info:
                        log.error("Error: output %i not found (%#x)", i, output)
                        continue
                    output_names.append(bytestostr(output_info.name[:output_info.nameLen]))
                    if crtc_info.noutput==0 and output_info.connection==RR_Disconnected and not m:
                        #crtc is not enabled and the corresponding output is not connected,
                        #which is exactly what we want, so just leave it alone
                        log("crtc and output %i are already disabled", i)
                        continue
                    noutput = 1
                    mode = 0
                    if m:
                        #find an existing mode matching this resolution:
                        for j in range(output_info.nmode):
                            #find this RRMode in the screen modes info:
                            for k in range(rsc.nmode):
                                if rsc.modes[k].id==output_info.modes[j] and rsc.modes[k].width==width and rsc.modes[k].height==height:
                                    mode = output_info.modes[j]
                                    mode_name = bytestostr(rsc.modes[j].name)
                                    log("using existing output mode %r (%#x) for %ix%i",
                                        mode_name, mode, width, height)
                                    break
                            if mode:
                                break
                        if not mode:
                            #try to find a screen mode not added to this output yet:
                            mode_name = ""
                            for j in range(rsc.nmode):
                                if rsc.modes[j].width==width and rsc.modes[j].height==height:
                                    mode = rsc.modes[j].id
                                    mode_name = bytestostr(rsc.modes[j].name)
                                    log("using screen mode %s (%#x) for %ix%i",
                                        mode_name, mode, width, height)
                                    break
                            if not mode:
                                mode_name = "%sx%s" % (width, height)
                                mode = self.do_add_screen_size(mode_name, width, height)
                            assert mode!=0, "mode %ix%i not found" % (width, height)
                            XRRAddOutputMode(self.display, output, mode)
                            log("mode %r (%#x) added to output %i (%i)", mode_name, mode, i, output)
                    else:
                        noutput = 0

                    x = m.get("x", 0)
                    y = m.get("y", 0)
                    log("XRRSetCrtcConfig(%#x, %#x, %i, %i, %i, %i, %i, %i, %#x, %i)",
                            <uintptr_t> self.display, <uintptr_t> rsc, crtc,
                            CurrentTime, x, y, mode, RR_Rotate_0, <uintptr_t> &output, noutput)
                    r = XRRSetCrtcConfig(self.display, rsc, crtc,
                          CurrentTime, x, y, mode,
                          RR_Rotate_0, &output, noutput)
                    if r:
                        raise Exception("failed to set crtc config for monitor %i" % i)
                    mmw = m.get("mm-width", dpi96(width))
                    mmh = m.get("mm-height", dpi96(height))
                    self.set_output_int_property(i, "WIDTH_MM", mmw)
                    self.set_output_int_property(i, "HEIGHT_MM", mmh)
                    #this allows us to disconnect the output of this crtc:
                    self.set_output_int_property(i, "SUSPENDED", not bool(m))
                    posinfo = ""
                    if x or y:
                        posinfo = " at %i,%i" % (x, y)
                    log.info("setting dummy crtc and output %i to %ix%i (%ix%i mm)%s",
                             i, width, height, mmw, mmh, posinfo)
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
            log("got %i monitors for %s crtcs", nmonitors, len(monitor_defs))
            #start by removing the ones we don't use:
            try:
                #we only need as many monitors as we have crtcs,
                for mi in range(len(monitor_defs), nmonitors):
                    name_atom = monitors[mi].name
                    log("deleting monitor %i: %s", mi, bytestostr(self.XGetAtomName(name_atom)))
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
                    monitors[mi].name = self.xatom("VFB%i-%s" % (mi, monotonic()))
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
                    names[mi] = bytestostr(self.XGetAtomName(monitors[mi].name))
                log("found %i monitors still active: %s", nmonitors, csv(names.values()))
                active_names = {}
                mi = 0
                for i, m  in monitor_defs.items():
                    log("matching monitor index %i to %i: %s", mi, i, m)
                    name = (prettify_plug_name(m.get("name", "")) or ("VFB-%i" % mi))
                    if name in output_names:
                        name = "VFB-%i" % mi
                    while (name in names.values() or name in active_names.values()) and names.get(mi)!=name and active_names.get(mi)!=name:
                        name += "-%i" % mi
                    active_names[mi] = name
                    monitor.name = self.xatom(name)
                    monitor.primary = m.get("primary", primary==mi)
                    monitor.automatic = m.get("automatic", True)
                    monitor.x = m.get("x", 0)
                    monitor.y = m.get("y", 0)
                    monitor.width = m.get("width", 128)
                    monitor.height = m.get("height", 128)
                    monitor.mwidth = m.get("mm-width", dpi96(monitor.width))
                    monitor.mheight = m.get("mm-height", dpi96(monitor.height))
                    assert rsc.noutput>i, "only %i outputs, cannot set %i" % (rsc.noutput, i)
                    output = rsc.outputs[i]
                    monitor.outputs = &output
                    monitor.noutput = 1
                    log("XRRSetMonitor(%#x, %#x, %#x) output=%i, geometry=%s (%ix%i mm)",
                        <uintptr_t> self.display, <uintptr_t> window, <uintptr_t> &monitor, output,
                        (monitor.x, monitor.y, monitor.width, monitor.height),
                        monitor.mwidth, monitor.mheight)
                    log.info("monitor %i is %r %ix%i", mi, name, monitor.width, monitor.height)
                    XRRSetMonitor(self.display, window, &monitor)
                    mi += 1
            finally:
                XRRFreeMonitors(monitors)
        finally:
            XRRFreeScreenResources(rsc)
