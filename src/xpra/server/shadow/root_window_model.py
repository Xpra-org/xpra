# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket

from xpra.log import Logger
log = Logger("shadow")

from xpra.util import prettify_plug_name


class RootWindowModel(object):

    def __init__(self, root_window):
        self.window = root_window
        self.property_names = ["title", "class-instance", "client-machine", "window-type", "size-hints", "icon", "shadow"]
        self.dynamic_property_names = []
        self.internal_property_names = []

    def suspend(self):
        pass

    def is_managed(self):
        return True

    def is_tray(self):
        return False

    def is_OR(self):
        return False

    def has_alpha(self):
        return False

    def uses_XShm(self):
        return False

    def is_shadow(self):
        return True

    def get_default_window_icon(self):
        return None

    def acknowledge_changes(self):
        pass

    def get_dimensions(self):
        return self.window.get_size()

    def get_image(self, x, y, width, height):
        raise NotImplementedError()

    def get_property_names(self):
        return self.property_names

    def get_dynamic_property_names(self):
        return self.dynamic_property_names

    def get_internal_property_names(self):
        return self.internal_property_names

    def get_generic_os_name(self):
        for k,v in {"linux"     : "linux",
                    "darwin"    : "osx",
                    "win"       : "win32",
                    "freebsd"   : "freebsd"}.items():
            if sys.platform.startswith(k):
                return v
        return sys.platform

    def get_property(self, prop):
        if prop=="title":
            return prettify_plug_name(self.window.get_screen().get_display().get_name())
        elif prop=="client-machine":
            return socket.gethostname()
        elif prop=="window-type":
            return ["NORMAL"]
        elif prop=="fullscreen":
            return False
        elif prop=="shadow":
            return True
        elif prop=="scaling":
            return None
        elif prop=="opacity":
            return None
        elif prop=="size-hints":
            size = self.window.get_size()
            return {"maximum-size"  : size,
                    "minimum-size"  : size,
                    "base-size" : size}
        elif prop=="class-instance":
            osn = self.get_generic_os_name()
            return ("xpra-%s" % osn, "Xpra-%s" % osn.upper())
        elif prop=="icon":
            #convert it to a cairo surface..
            #because that's what the property is expected to be
            try:
                import gtk.gdk
                from xpra.platform.paths import get_icon
                icon_name = self.get_generic_os_name()+".png"
                icon = get_icon(icon_name)
                log("icon(%s)=%s", icon_name, icon)
                if not icon:
                    return None
                import cairo
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, icon.get_width(), icon.get_height())
                gc = gtk.gdk.CairoContext(cairo.Context(surf))
                gc.set_source_pixbuf(icon, 0, 0)
                gc.paint()
                log("icon=%s", surf)
                return surf
            except:
                log("failed to return window icon")
                return None
        else:
            raise ValueError("invalid property: %s" % prop)
        return None

    def get(self, name, default_value=None):
        try:
            return self.get_property(name)
        except ValueError as e:
            log("get(%s, %s) %s on %s", name, default_value, e, self)
            return default_value


    def managed_connect(self, *args):
        log.warn("ignoring managed signal connect request: %s", args)

    def connect(self, *args):
        log.warn("ignoring signal connect request: %s", args)

    def disconnect(self, *args):
        log.warn("ignoring signal disconnect request: %s", args)
