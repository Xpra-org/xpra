# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk_x11.gdk_display_source import init_display_source #@UnresolvedImport
init_display_source()
from xpra.x11.x11_server_core import X11ServerCore

from xpra.os_util import monotonic_time
from xpra.util import envbool, envint, XPRA_APP_ID
from xpra.gtk_common.gtk_util import get_xwindow, is_gtk3
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.gtk_root_window_model import GTKImageCapture
from xpra.x11.bindings.ximage import XImageBindings     #@UnresolvedImport
from xpra.gtk_common.error import xsync
XImage = XImageBindings()

from xpra.log import Logger
log = Logger("x11", "shadow")
traylog = Logger("tray")
cursorlog = Logger("cursor")
geomlog = Logger("geometry")

USE_XSHM = envbool("XPRA_XSHM", True)
POLL_CURSOR = envint("XPRA_POLL_CURSOR", 20)
MULTI_WINDOW = envbool("XPRA_SHADOW_MULTI_WINDOW", True)
USE_NVFBC = envbool("XPRA_NVFBC", True)
USE_NVFBC_CUDA = envbool("XPRA_NVFBC_CUDA", True)
if USE_NVFBC:
    try:
        from xpra.codecs.nvfbc.fbc_capture_linux import init_module, NvFBC_SysCapture, NvFBC_CUDACapture    #@UnresolvedImport
        init_module()
    except Exception:
        log("NvFBC Capture is not available", exc_info=True)
        USE_NVFBC = False


class XImageCapture(object):
    def __init__(self, xwindow):
        self.xshm = None
        self.xwindow = xwindow
        assert USE_XSHM and XImage.has_XShm(), "no XShm support"

    def __repr__(self):
        return "XImageCapture(%#x)" % self.xwindow

    def clean(self):
        self.close_xshm()

    def close_xshm(self):
        xshm = self.xshm
        if self.xshm:
            self.xshm = None
            with xsync:
                xshm.cleanup()

    def _err(self, e, op="capture pixels"):
        if getattr(e, "msg", None)=="BadMatch":
            log("BadMatch - temporary error in %s of window #%x", op, self.xwindow, exc_info=True)
        else:
            log.warn("Warning: failed to %s of window %#x:", self.xwindow)
            log.warn(" %s", e)
        self.close_xshm()

    def refresh(self):
        if self.xshm:
            #discard to ensure we will call XShmGetImage next time around
            self.xshm.discard()
            return True
        try:
            with xsync:
                log("%s.refresh() xshm=%s", self, self.xshm)
                self.xshm = XImage.get_XShmWrapper(self.xwindow)
                self.xshm.setup()
        except Exception as e:
            self.xshm = None
            self._err(e, "xshm setup")
        return True

    def get_image(self, x, y, width, height):
        if self.xshm is None:
            log("no xshm, cannot get image")
            return None
        try:
            start = monotonic_time()
            with xsync:
                log("X11 shadow get_image, xshm=%s", self.xshm)
                image = self.xshm.get_image(self.xwindow, x, y, width, height)
                return image
        except Exception as e:
            self._err(e)
            return None
        finally:
            end = monotonic_time()
            log("X11 shadow captured %s pixels at %i MPixels/s using %s", width*height, (width*height/(end-start))//1024//1024, ["GTK", "XSHM"][USE_XSHM])


def setup_capture(window):
    ww, wh = window.get_geometry()[2:4]
    capture = None
    if USE_NVFBC:
        try:
            log("setup_capture(%s) USE_NVFBC_CUDA=%s", window, USE_NVFBC_CUDA)
            if USE_NVFBC_CUDA:
                capture = NvFBC_CUDACapture()
            else:
                capture = NvFBC_SysCapture()
            capture.init_context(ww, wh)
            capture.refresh()
            image = capture.get_image(0, 0, ww, wh)
            assert image, "test capture failed"
        except Exception as e:
            log("get_image() NvFBC test failed", exc_info=True)
            log("not using %s: %s", capture, e)
            capture = None
    if not capture and XImage.has_XShm() and USE_XSHM:
        capture = XImageCapture(get_xwindow(window))
    if not capture:
        capture = GTKImageCapture(window)
    log("setup_capture(%s)=%s", window, capture)
    return capture


class GTKX11RootWindowModel(RootWindowModel):

    def __init__(self, root_window, capture):
        RootWindowModel.__init__(self, root_window, capture)
        self.geometry = root_window.get_geometry()[:4]

    def __repr__(self):
        return "GTKX11RootWindowModel(%#x - %s - %s)" % (get_xwindow(self.window), self.geometry, self.capture)

    def get_dimensions(self):
        #used by get_window_info only
        return self.geometry[2:4]

    def get_image(self, x, y, width, height):
        ox, oy = self.geometry[:2]
        image = self.capture.get_image(ox+x, oy+y, width, height)
        if ox>0 or oy>0:
            #adjust x and y of where the image is displayed on the client (target_x and target_y)
            #not where the image lives within the current buffer (x and y)
            image.set_target_x(x)
            image.set_target_y(y)
        return image


#FIXME: warning: this class inherits from ServerBase twice..
#so many calls will happen twice there (__init__ and init)
class ShadowX11Server(GTKShadowServerBase, X11ServerCore):

    def __init__(self):
        GTKShadowServerBase.__init__(self)
        X11ServerCore.__init__(self)
        self.session_type = "shadow"
        self.cursor_poll_timer = None

    def init(self, opts):
        GTKShadowServerBase.init(self, opts)
        X11ServerCore.do_init(self, opts)

    def cleanup(self):
        GTKShadowServerBase.cleanup(self)
        X11ServerCore.cleanup(self)


    def start_refresh(self):
        GTKShadowServerBase.start_refresh(self)
        self.start_poll_cursor()

    def stop_refresh(self):
        GTKShadowServerBase.stop_refresh(self)
        self.stop_poll_cursor()


    def make_tray_widget(self):
        from xpra.platform.xposix.gui import get_native_system_tray_classes
        classes = get_native_system_tray_classes()
        try:
            from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
            classes.append(GTKStatusIconTray)
        except:
            pass
        traylog("tray classes: %s", classes)
        if not classes:
            traylog.error("Error: no system tray implementation available")
            return None
        errs = []
        for c in classes:
            try:
                w = c(self, XPRA_APP_ID, self.tray, "Xpra Shadow Server", None, None, self.tray_click_callback, mouseover_cb=None, exit_cb=self.tray_exit_callback)
                return w
            except Exception as e:
                errs.append((c, e))
        traylog.error("Error: all system tray implementations have failed")
        for c, e in errs:
            traylog.error(" %s: %s", c, e)
        return None


    def makeRootWindowModels(self):
        log("makeRootWindowModels() root=%s", self.root)
        self.capture = setup_capture(self.root)
        if not MULTI_WINDOW:
            models = (GTKX11RootWindowModel(self.root, self.capture),)
        else:
            models = []
            screen = self.root.get_screen()
            n = screen.get_n_monitors()
            for i in range(n):
                geom = screen.get_monitor_geometry(i)
                x, y, width, height = geom.x, geom.y, geom.width, geom.height
                model = GTKX11RootWindowModel(self.root, self.capture)
                if hasattr(screen, "get_monitor_plug_name"):
                    plug_name = screen.get_monitor_plug_name(i)
                    if plug_name or n>1:
                        model.title = plug_name or str(i)
                model.geometry = (x, y, width, height)
                models.append(model)
        log("makeRootWindowModels()=%s", models)
        return models

    def _adjust_pointer(self, proto, wid, pointer):
        pointer = X11ServerCore._adjust_pointer(self, proto, wid, pointer)
        window = self._id_to_window.get(wid)
        if window:
            ox, oy = window.geometry[:2]
            x, y = pointer
            return x+ox, y+oy
        return pointer


    def last_client_exited(self):
        GTKShadowServerBase.last_client_exited(self)
        X11ServerCore.last_client_exited(self)


    def start_poll_cursor(self):
        #the cursor poll timer:
        self.cursor_poll_timer = None
        if POLL_CURSOR>0:
            self.cursor_poll_timer = self.timeout_add(POLL_CURSOR, self.poll_cursor)

    def stop_poll_cursor(self):
        cpt = self.cursor_poll_timer
        if cpt:
            self.cursor_poll_timer = None
            self.source_remove(cpt)

    def poll_cursor(self):
        prev = self.last_cursor_data
        X11ServerCore.get_cursor_data(self)
        def cmpv(v):
            if v and len(v)>2:
                return v[2:]
            return None
        if cmpv(prev)!=cmpv(self.last_cursor_data):
            fields = ("x", "y", "width", "height", "xhot", "yhot", "serial", "pixels", "name")
            if len(prev or [])==len(self.last_cursor_data or []) and len(prev or [])==len(fields):
                diff = []
                for i in range(len(prev)):
                    if prev[i]!=self.last_cursor_data[i]:
                        diff.append(fields[i])
                cursorlog("poll_cursor() attributes changed: %s", diff)
            for ss in self._server_sources.values():
                ss.send_cursor()
        return True

    def get_cursor_data(self):
        return X11ServerCore.get_cursor_data(self)


    def make_hello(self, source):
        capabilities = X11ServerCore.make_hello(self, source)
        capabilities.update(GTKShadowServerBase.make_hello(self, source))
        capabilities["server_type"] = "Python/gtk2/x11-shadow"
        return capabilities

    def get_info(self, proto, *_args):
        info = X11ServerCore.get_info(self, proto)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/gtk%i/x11-shadow" % (2+is_gtk3())
        return info

    def do_make_screenshot_packet(self):
        capture = GTKImageCapture(self.root)
        w, h, encoding, rowstride, data = capture.take_screenshot()
        assert encoding=="png"  #use fixed encoding for now
        from xpra.net.compression import Compressed
        return ["screenshot", w, h, encoding, rowstride, Compressed(encoding, data)]
