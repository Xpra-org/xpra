# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.platform.paths import get_icon_dir
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_TRAY_DEBUG")


class TrayBase(object):
    """
        Utility superclass for all tray implementations
    """

    def __init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        self.menu = menu
        self.tooltip = tooltip
        self.size_changed_cb = size_changed_cb
        self.click_cb = click_cb
        self.mouseover_cb = mouseover_cb
        self.exit_cb = exit_cb
        self.tray_widget = None
        self.default_icon_filename = icon_filename
        self.default_icon_extension = "png"
        self.default_icon_name = "xpra.png"

    def cleanup(self):
        if self.tray_widget:
            self.hide()
            self.tray_widget = None

    def get_tray_icon_filename(self, cmdlineoverride=None):
        if cmdlineoverride and os.path.exists(cmdlineoverride):
            debug("get_tray_icon_filename using %s from command line", cmdlineoverride)
            return  cmdlineoverride
        f = os.path.join(get_icon_dir(), self.default_icon_name)
        if os.path.exists(f):
            debug("get_tray_icon_filename using default: %s", f)
            return  f
        return  None

    def ready(self):
        pass

    def show(self):
        raise Exception("override me!")

    def hide(self):
        raise Exception("override me!")

    def get_screen(self):
        return -1

    def get_orientation(self):
        return None     #assume "HORIZONTAL"

    def get_geometry(self):
        raise Exception("override me!")

    def get_size(self):
        g = self.get_geometry()
        if g is None:
            return None
        return g[2:4]

    def set_tooltip(self, tooltip=None):
        self.tooltip = tooltip
        raise Exception("override me!")

    def set_blinking(self, on):
        raise Exception("override me!")

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        raise Exception("override me!")

    def set_icon(self, basefilename=None):
        if basefilename is None:
            #use default filename, or find file with default icon name:
            filename = self.default_icon_filename or self.get_tray_icon_filename()
        else:
            #create full path + filename from basefilename:
            with_ext = "%s.%s" % (basefilename, self.default_icon_extension)
            icon_dir = get_icon_dir()
            filename = os.path.join(icon_dir, with_ext)
        if not os.path.exists(filename):
            log.error("could not find icon '%s' for name '%s'", filename, basefilename)
            return
        abspath = os.path.abspath(filename)
        debug("set_icon(%s) using filename=%s", basefilename, abspath)
        self.set_icon_from_file(abspath)

    def set_icon_from_file(self, filename):
        debug("set_icon_from_file(%s) tray_widget=%s", filename, self.tray_widget)
        if not self.tray_widget:
            return
        self.do_set_icon_from_file(filename)

    def do_set_icon_from_file(self, filename):
        raise Exception("override me!")
