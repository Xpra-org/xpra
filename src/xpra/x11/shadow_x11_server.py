# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os, time

from xpra.gtk_common.gtk_util import get_xwindow, get_default_root_window
from xpra.x11.x11_server_base import X11ServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.server.shadow.gtk_root_window_model import GTKRootWindowModel
from xpra.x11.bindings.ximage import XImageBindings     #@UnresolvedImport
from xpra.gtk_common.error import xsync
XImage = XImageBindings()

from xpra.log import Logger
log = Logger("x11", "shadow")

USE_XSHM = os.environ.get("XPRA_XSHM", "1")=="1"


class GTKX11RootWindowModel(GTKRootWindowModel):

    def __init__(self, root_window):
        GTKRootWindowModel.__init__(self, root_window)
        self.xshm = None

    def __repr__(self):
        return "GTKX11RootWindowModel(%#x)" % get_xwindow(self.window)

    def suspend(self):
        #we can cleanup the current xshm area and we'll create a new one later
        self.cleanup()

    def cleanup(self):
        if self.xshm:
            with xsync:
                self.xshm.cleanup()
            self.xshm = None


    def get_image(self, x, y, width, height, logger=None):
        try:
            start = time.time()
            with xsync:
                if USE_XSHM:
                    log("X11 shadow get_image, xshm=%s", self.xshm)
                    if self.xshm is None:
                        self.xshm = XImage.get_XShmWrapper(get_xwindow(self.window))
                        self.xshm.setup()
                    if self.xshm:
                        image = self.xshm.get_image(get_xwindow(self.window), x, y, width, height)
                        #discard to ensure we will call XShmGetImage next time around
                        self.xshm.discard()
                        return image
                #fallback to gtk capture:
                return GTKRootWindowModel.get_image(self, x, y, width, height, logger)
        except Exception as e:
            log.warn("Warning: failed to capture root window pixels:")
            log.warn(" %s", e)
            #cleanup and hope for the best!
            self.cleanup()
        finally:
            end = time.time()
            log("X11 shadow captured %s pixels at %i MPixels/s using %s", width*height, (width*height/(end-start))//1024//1024, ["GTK", "XSHM"][USE_XSHM])


class ShadowX11Server(ShadowServerBase, X11ServerBase):

    def __init__(self):
        ShadowServerBase.__init__(self, get_default_root_window())
        X11ServerBase.__init__(self, False)


    def makeRootWindowModel(self):
        return GTKX11RootWindowModel(self.root)

    def last_client_exited(self):
        self.stop_refresh()
        X11ServerBase.last_client_exited(self)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #adjust pointer position for offset in client:
        x, y = pointer
        wx, wy = self.mapped_at[:2]
        pointer = x-wx, y-wy
        X11ServerBase._process_mouse_common(self, proto, wid, pointer, modifiers)

    def make_hello(self, source):
        capabilities = X11ServerBase.make_hello(self, source)
        capabilities.update(ShadowServerBase.make_hello(self, source))
        capabilities["server_type"] = "Python/gtk2/x11-shadow"
        return capabilities

    def get_info(self, proto):
        info = X11ServerBase.get_info(self, proto)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/gtk2/x11-shadow"
        return info
