# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("client")
workspacelog = Logger("client", "workspace")
screenlog = Logger("client", "screen")
scalinglog = Logger("scaling")


from xpra.exit_codes import EXIT_INTERNAL_ERROR
from xpra.platform.features import REINIT_WINDOWS
from xpra.platform.gui import (get_antialias_info, get_icc_info, get_display_icc_info, show_desktop, get_cursor_size,
                               get_xdpi, get_ydpi, get_number_of_desktops, get_desktop_names, get_wm_name)
from xpra.scripts.config import FALSE_OPTIONS
from xpra.os_util import monotonic_time
from xpra.util import iround, envint, envfloat, log_screen_sizes, engs


MONITOR_CHANGE_REINIT = envint("XPRA_MONITOR_CHANGE_REINIT")


MIN_SCALING = envfloat("XPRA_MIN_SCALING", "0.1")
MAX_SCALING = envfloat("XPRA_MAX_SCALING", "8")
SCALING_OPTIONS = [float(x) for x in os.environ.get("XPRA_TRAY_SCALING_OPTIONS", "0.25,0.5,0.666,1,1.25,1.5,2.0,3.0,4.0,5.0").split(",") if float(x)>=MIN_SCALING and float(x)<=MAX_SCALING]
SCALING_EMBARGO_TIME = int(os.environ.get("XPRA_SCALING_EMBARGO_TIME", "1000"))/1000.0


def r4cmp(v, rounding=1000.0):    #ignore small differences in floats for scale values
    return iround(v*rounding)
def fequ(v1, v2):
    return r4cmp(v1)==r4cmp(v2)


"""
Utility superclass for clients that handle a desktop / display
Adds client-side scaling handling
"""
class DisplayClient(object):
    def __init__(self):
        self.dpi = 0
        self.initial_scaling = 1, 1
        self.xscale, self.yscale = self.initial_scaling
        self.scale_change_embargo = 0
        self.desktop_fullscreen = False
        self.desktop_scaling = False
        self.screen_size_change_pending = False

        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False

        #in WindowClient - should it be?
        #self.server_is_desktop = False

    def init(self, opts):
        self.desktop_fullscreen = opts.desktop_fullscreen
        self.desktop_scaling = opts.desktop_scaling
        self.dpi = int(opts.dpi)
        self.can_scale = opts.desktop_scaling not in FALSE_OPTIONS
        if self.can_scale:
            root_w, root_h = self.get_root_size()
            from xpra.client.scaling_parser import parse_scaling
            self.initial_scaling = parse_scaling(opts.desktop_scaling, root_w, root_h, MIN_SCALING, MAX_SCALING)
            self.xscale, self.yscale = self.initial_scaling


    def cleanup(self):
        pass


    def get_screen_sizes(self, xscale=1, yscale=1):
        raise NotImplementedError()

    def get_root_size(self):
        raise NotImplementedError()


    ######################################################################
    # hello:
    def get_caps(self):
        return {
            "randr_notify"  : True,
            "show-desktop"  : True,
            }


    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_display = c.strget("display")
        self.server_max_desktop_size = c.intpair("max_desktop_size")
        self.server_actual_desktop_size = c.intpair("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.server_randr = c.boolget("resize_screen")
        log("server has randr: %s", self.server_randr)

    def parse_ui_capabilities(self):
        c = self.server_capabilities
        server_desktop_size = c.intlistget("desktop_size")
        log("server desktop size=%s", server_desktop_size)
        self.server_is_desktop = c.boolget("shadow") or c.boolget("desktop")
        skip_vfb_size_check = False           #if we decide not to use scaling, skip warnings
        if not fequ(self.xscale, 1.0) or not fequ(self.yscale, 1.0):
            #scaling is used, make sure that we need it and that the server can support it
            #(without rounding support, size-hints can cause resize loops)
            if self.server_is_desktop and not self.desktop_fullscreen:
                #don't honour auto mode in this case
                if self.desktop_scaling=="auto":
                    log.info(" not scaling a shadow server")
                    skip_vfb_size_check = self.xscale>1 or self.yscale>1
                    self.scalingoff()
            elif self.mmap_enabled:
                if self.desktop_scaling=="auto":
                    log.info(" no need for scaling with mmap")
                    skip_vfb_size_check = self.xscale>1 or self.yscale>1
                    self.scalingoff()
                    self.can_scale = False
        if self.can_scale:
            self.may_adjust_scaling()
        if not self.server_is_desktop and not skip_vfb_size_check:
            avail_w, avail_h = server_desktop_size
            root_w, root_h = self.get_root_size()
            if self.cx(root_w)>(avail_w+1) or self.cy(root_h)>(avail_h+1):
                log.warn("Server's virtual screen is too small")
                log.warn(" server: %sx%s vs client: %sx%s", avail_w, avail_h, self.cx(root_w), self.cy(root_h))
                log.warn(" you may see strange behavior,")
                log.warn(" please see http://xpra.org/trac/wiki/Xdummy#Configuration")
        self.set_max_packet_size()

    def set_max_packet_size(self):
        root_w, root_h = self.cp(*self.get_root_size())
        maxw, maxh = root_w, root_h
        try:
            server_w, server_h = self.server_actual_desktop_size
            maxw = max(root_w, server_w)
            maxh = max(root_h, server_h)
        except:
            pass
        if maxw<=0 or maxh<=0 or maxw>=32768 or maxh>=32768:
            message = "invalid maximum desktop size: %ix%i" % (maxw, maxh)
            log(message)
            self.quit(EXIT_INTERNAL_ERROR)
            raise SystemExit(message)
        if maxw>=16384 or maxh>=16384:
            log.warn("Warning: the desktop size is extremely large: %ix%i", maxw, maxh)
        #max packet size to accomodate:
        # * full screen RGBX (32 bits) uncompressed
        # * file-size-limit
        # both with enough headroom for some metadata (4k)
        p = self._protocol
        if p:
            p.max_packet_size = max(maxw*maxh*4, self.file_size_limit*1024*1024) + 4*1024
            p.abs_max_packet_size = max(maxw*maxh*4 * 4, self.file_size_limit*1024*1024) + 4*1024
            log("maximum packet size set to %i", p.max_packet_size)


    def has_transparency(self):
        return False

    def get_icc_info(self):
        return get_icc_info()

    def get_display_icc_info(self):
        return get_display_icc_info()

    def _process_show_desktop(self, packet):
        show = packet[1]
        log("calling %s(%s)", show_desktop, show)
        show_desktop(show)

    def _process_desktop_size(self, packet):
        root_w, root_h, max_w, max_h = packet[1:5]
        screenlog("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h
        if self.can_scale:
            self.may_adjust_scaling()


    def may_adjust_scaling(self):
        log("may_adjust_scaling() server_is_desktop=%s, desktop_fullscreen=%s", self.server_is_desktop, self.desktop_fullscreen)
        if self.server_is_desktop and not self.desktop_fullscreen:
            #don't try to make it fit
            return
        assert self.can_scale
        max_w, max_h = self.server_max_desktop_size             #ie: server limited to 8192x4096?
        w, h = self.get_root_size()                             #ie: 5760, 2160
        sw, sh = self.cp(w, h)                                  #ie: upscaled to: 11520x4320
        scalinglog("may_adjust_scaling() server desktop size=%s, client root size=%s", self.server_actual_desktop_size, self.get_root_size())
        scalinglog(" scaled client root size using %sx%s: %s", self.xscale, self.yscale, (sw, sh))
        if sw<(max_w+1) and sh<(max_h+1):
            #no change needed
            return
        #server size is too small for the client screen size with the current scaling value,
        #calculate the minimum scaling to fit it:
        def clamp(v):
            return max(MIN_SCALING, min(MAX_SCALING, v))
        x = clamp(float(w)/max_w)
        y = clamp(float(h)/max_h)
        def mint(v):
            #prefer int over float,
            #and even tolerate a 0.1% difference to get it:
            if iround(v)*1000==iround(v*1000):
                return int(v)
            return v
        self.xscale = mint(x)
        self.yscale = mint(y)
        #to use the same scale for both axes:
        #self.xscale = mint(max(x, y))
        #self.yscale = self.xscale
        summary = "Desktop scaling adjusted to accomodate the server"
        xstr = ("%.3f" % self.xscale).rstrip("0")
        ystr = ("%.3f" % self.yscale).rstrip("0")
        messages = [
            "server desktop size is %ix%i" % (max_w, max_h),
            "using scaling factor %s x %s" % (xstr, ystr),
            ]
        try:
            from xpra.notifications.common import XPRA_SCALING_NOTIFICATION_ID
        except:
            pass
        else:
            self.may_notify(XPRA_SCALING_NOTIFICATION_ID, summary, "\n".join(messages), icon_name="scaling")
        scalinglog.warn("Warning: %s", summary)
        for m in messages:
            scalinglog.warn(" %s", m)
        self.emit("scaling-changed")


    ######################################################################
    # screen scaling:
    def sx(self, v):
        """ convert X coordinate from server to client """
        return iround(v*self.xscale)
    def sy(self, v):
        """ convert Y coordinate from server to client """
        return iround(v*self.yscale)
    def srect(self, x, y, w, h):
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)
    def sp(self, x, y):
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    def cx(self, v):
        """ convert X coordinate from client to server """
        return iround(v/self.xscale)
    def cy(self, v):
        """ convert Y coordinate from client to server """
        return iround(v/self.yscale)
    def crect(self, x, y, w, h):
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)
    def cp(self, x, y):
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)


    ######################################################################
    # desktop, screen and scaling:
    def get_desktop_caps(self):
        caps = {}
        wm_name = get_wm_name()
        if wm_name:
            caps["wm_name"] = wm_name

        self._last_screen_settings = self.get_screen_settings()
        root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi = self._last_screen_settings
        caps["desktop_size"] = self.cp(u_root_w, u_root_h)
        caps["desktops"] = ndesktops
        caps["desktop.names"] = desktop_names

        ss = self.get_screen_sizes()
        self._current_screen_sizes = ss

        log.info(" desktop size is %sx%s with %s screen%s:", u_root_w, u_root_h, len(ss), engs(ss))
        log_screen_sizes(u_root_w, u_root_h, ss)
        if self.xscale!=1 or self.yscale!=1:
            caps["screen_sizes.unscaled"] = ss
            caps["desktop_size.unscaled"] = u_root_w, u_root_h
            root_w, root_h = self.cp(u_root_w, u_root_h)
            if fequ(self.xscale, self.yscale):
                sinfo = "%i%%" % iround(self.xscale*100)
            else:
                sinfo = "%i%% x %i%%" % (iround(self.xscale*100), iround(self.yscale*100))
            log.info(" %sscaled by %s, virtual screen size: %ix%i", ["down", "up"][int(u_root_w>root_w or u_root_h>root_h)], sinfo, root_w, root_h)
            log_screen_sizes(root_w, root_h, sss)
        else:
            root_w, root_h = u_root_w, u_root_h
            sss = ss
        caps["screen_sizes"] = sss

        caps["screen-scaling"] = True
        caps["screen-scaling.enabled"] = self.xscale!=1 or self.yscale!=1
        caps["screen-scaling.values"] = (int(1000*self.xscale), int(1000*self.yscale))

        #command line (or config file) override supplied:
        dpi = 0
        if self.dpi>0:
            #scale it:
            xdpi = ydpi = dpi = self.cx(self.cy(self.dpi))
        else:
            #not supplied, use platform detection code:
            #platforms may also provide per-axis dpi (later win32 versions do)
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
            screenlog("xdpi=%i, ydpi=%i", xdpi, ydpi)
            if xdpi>0 and ydpi>0:
                xdpi = self.cx(xdpi)
                ydpi = self.cy(ydpi)
                dpi = iround((xdpi+ydpi)/2.0)
                caps.update({
                    "dpi.x"    : xdpi,
                    "dpi.y"    : ydpi,
                    })
        if dpi:
            caps["dpi"] = dpi
        screenlog("dpi: %i", dpi)
        caps.update({
            "antialias"    : get_antialias_info(),
            "icc"          : self.get_icc_info(),
            "display-icc"  : self.get_display_icc_info(),
            "cursor.size"  : int(2*get_cursor_size()/(self.xscale+self.yscale)),
            })
        return caps
    
    def desktops_changed(self, *args):
        workspacelog("desktops_changed%s", args)
        self.screen_size_changed(*args)

    def workspace_changed(self, *args):
        workspacelog("workspace_changed%s", args)
        for win in self._id_to_window.values():
            win.workspace_changed()

    def screen_size_changed(self, *args):
        screenlog("screen_size_changed(%s) pending=%s", args, self.screen_size_change_pending)
        if self.screen_size_change_pending:
            return
        #update via timer so the data is more likely to be final (up to date) when we query it,
        #some properties (like _NET_WORKAREA for X11 clients via xposix "ClientExtras") may
        #trigger multiple calls to screen_size_changed, delayed by some amount
        #(sometimes up to 1s..)
        self.screen_size_change_pending = True
        delay = 1000
        #if we are suspending, wait longer:
        #(better chance that the suspend-resume cycle will have completed)
        if self._suspended_at>0 and self._suspended_at-monotonic_time()<5*1000:
            delay = 5*1000
        self.timeout_add(delay, self.do_process_screen_size_change)

    def do_process_screen_size_change(self):
        self.update_screen_size()
        screenlog("do_process_screen_size_change() MONITOR_CHANGE_REINIT=%s, REINIT_WINDOWS=%s", MONITOR_CHANGE_REINIT, REINIT_WINDOWS)
        if MONITOR_CHANGE_REINIT and MONITOR_CHANGE_REINIT=="0":
            return
        if MONITOR_CHANGE_REINIT or REINIT_WINDOWS:
            screenlog.info("screen size change: will reinit the windows")
            self.reinit_windows()
            self.reinit_window_icons()


    def get_screen_settings(self):
        u_root_w, u_root_h = self.get_root_size()
        root_w, root_h = self.cp(u_root_w, u_root_h)
        self._current_screen_sizes = self.get_screen_sizes()
        sss = self.get_screen_sizes(self.xscale, self.yscale)
        ndesktops = get_number_of_desktops()
        desktop_names = get_desktop_names()
        screenlog("update_screen_size() sizes=%s, %s desktops: %s", sss, ndesktops, desktop_names)
        if self.dpi>0:
            #use command line value supplied, but scale it:
            xdpi = ydpi = self.dpi
        else:
            #not supplied, use platform detection code:
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
        xdpi = self.cx(xdpi)
        ydpi = self.cy(ydpi)
        screenlog("dpi: %s -> %s", (get_xdpi(), get_ydpi()), (xdpi, ydpi))
        return (root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi)
        
    def update_screen_size(self):
        self.screen_size_change_pending = False
        screen_settings = self.get_screen_settings()
        screenlog("update_screen_size()     new settings=%s", screen_settings)
        screenlog("update_screen_size() current settings=%s", self._last_screen_settings)
        if self._last_screen_settings==screen_settings:
            log("screen size unchanged")
            return
        root_w, root_h, sss = screen_settings[:3]
        screenlog.info("sending updated screen size to server: %sx%s with %s screens", root_w, root_h, len(sss))
        log_screen_sizes(root_w, root_h, sss)
        self.send("desktop_size", *screen_settings)
        self._last_screen_settings = screen_settings
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_xdpi(self):
        return get_xdpi()

    def get_ydpi(self):
        return get_ydpi()


    def scaleup(self):
        scaling = max(self.xscale, self.yscale)
        options = [v for v in SCALING_OPTIONS if r4cmp(v, 10)>r4cmp(scaling, 10)]
        scalinglog("scaleup() options>%s : %s", r4cmp(scaling, 1000)/1000.0, options)
        if options:
            self._scaleto(min(options))

    def scaledown(self):
        scaling = max(self.xscale, self.yscale)
        options = [v for v in SCALING_OPTIONS if r4cmp(v, 10)<r4cmp(scaling, 10)]
        scalinglog("scaledown() options<%s : %s", r4cmp(scaling, 1000)/1000.0, options)
        if options:
            self._scaleto(max(options))

    def _scaleto(self, new_scaling):
        scaling = max(self.xscale, self.yscale)
        scalinglog("_scaleto(%s) current value=%s", r4cmp(new_scaling, 1000)/1000.0, r4cmp(scaling, 1000)/1000.0)
        if new_scaling>0:
            self.scale_change(new_scaling/scaling, new_scaling/scaling)

    def scalingoff(self):
        self.scaleset(1, 1)

    def scalereset(self):
        self.scaleset(*self.initial_scaling)

    def scaleset(self, xscale=1, yscale=1):
        scalinglog("scaleset(%s, %s) current scaling: %s, %s", xscale, yscale, self.xscale, self.yscale)
        self.scale_change(float(xscale)/self.xscale, float(yscale)/self.yscale)

    def scale_change(self, xchange=1, ychange=1):
        scalinglog("scale_change(%s, %s)", xchange, ychange)
        if self.server_is_desktop and self.desktop_fullscreen:
            scalinglog("scale_change(%s, %s) ignored, fullscreen shadow mode is active", xchange, ychange)
            return
        if not self.can_scale:
            scalinglog("scale_change(%s, %s) ignored, scaling is disabled", xchange, ychange)
            return
        if self.screen_size_change_pending:
            scalinglog("scale_change(%s, %s) screen size change is already pending", xchange, ychange)
            return
        if monotonic_time()<self.scale_change_embargo:
            scalinglog("scale_change(%s, %s) screen size change not permitted during embargo time - try again", xchange, ychange)
            return
        def clamp(v):
            return max(MIN_SCALING, min(MAX_SCALING, v))
        xscale = clamp(self.xscale*xchange)
        yscale = clamp(self.yscale*ychange)
        scalinglog("scale_change xscale: clamp(%s*%s)=%s", self.xscale, xchange, xscale)
        scalinglog("scale_change yscale: clamp(%s*%s)=%s", self.yscale, ychange, yscale)
        if fequ(xscale, self.xscale) and fequ(yscale, self.yscale):
            scalinglog("scaling unchanged: %sx%s", self.xscale, self.yscale)
            return
        #re-calculate change values against clamped scale:
        xchange = xscale / self.xscale
        ychange = yscale / self.yscale
        #check against maximum server supported size:
        maxw, maxh = self.server_max_desktop_size
        root_w, root_h = self.get_root_size()
        sw = int(root_w / xscale)
        sh = int(root_h / yscale)
        scalinglog("scale_change root size=%s x %s, scaled to %s x %s", root_w, root_h, sw, sh)
        scalinglog("scale_change max server desktop size=%s x %s", maxw, maxh)
        if not self.server_is_desktop and (sw>(maxw+1) or sh>(maxh+1)):
            #would overflow..
            summary = "Invalid Scale Factor"
            messages = [
                "cannot scale by %i%% x %i%% or lower" % ((100*xscale), (100*yscale)),
                "the scaled client screen %i x %i -> %i x %i" % (root_w, root_h, sw, sh),
                " would overflow the server's screen: %i x %i" % (maxw, maxh),
                ]    
            try:
                from xpra.notifications.common import XPRA_SCALING_NOTIFICATION_ID
            except ImportError:
                pass
            else:
                self.may_notify(XPRA_SCALING_NOTIFICATION_ID, summary, "\n".join(messages), "scaling")
            scalinglog.warn("Warning: %s", summary)
            for m in messages:
                scalinglog.warn(" %s", m)
            return
        self.xscale = xscale
        self.yscale = yscale
        scalinglog("scale_change new scaling: %sx%s, change: %sx%s", self.xscale, self.yscale, xchange, ychange)
        self.scale_reinit(xchange, ychange)

    def scale_reinit(self, xchange=1.0, ychange=1.0):
        #wait at least one second before changing again:
        self.scale_change_embargo = monotonic_time()+SCALING_EMBARGO_TIME
        if fequ(self.xscale, self.yscale):
            scalinglog.info("setting scaling to %i%%:", iround(100*self.xscale))
        else:
            scalinglog.info("setting scaling to %i%% x %i%%:", iround(100*self.xscale), iround(100*self.yscale))
        self.update_screen_size()
        #re-initialize all the windows with their new size
        def new_size_fn(w, h):
            minx, miny = 16384, 16384
            if self.max_window_size!=(0, 0):
                minx, miny = self.max_window_size
            return max(1, min(minx, int(w*xchange))), max(1, min(miny, int(h*ychange)))
        self.reinit_windows(new_size_fn)
        self.reinit_window_icons()
        self.emit("scaling-changed")


    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._ui_packet_handlers, {
            "show-desktop":         self._process_show_desktop,
            "desktop_size":         self._process_desktop_size,
            })
