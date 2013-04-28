# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.platform.paths import get_icon_dir
from xpra.log import Logger
log = Logger()
debug = log.debug


class TrayBase(object):

    def __init__(self, popup_cb, activate_cb, delay_tray, tray_icon_filename):
        self.popup_cb = popup_cb
        self.activate_cb = activate_cb
        self.tray_widget = None

    def get_tray_tooltip(self):
        if self.client.session_name:
            return "%s\non %s" % (self.client.session_name, self.connection.target)
        return self.connection.target

    def cleanup(self):
        if self.tray_widget:
            self.hide()
            self.tray_widget = None

    def get_tray_icon_filename(self, cmdlineoverride):
        if cmdlineoverride and os.path.exists(cmdlineoverride):
            debug("get_tray_icon_filename using %s from command line", cmdlineoverride)
            return  cmdlineoverride
        f = os.path.join(get_icon_dir(), "xpra.png")
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

    def set_tooltip(self, text=None):
        raise Exception("override me!")

    def set_blinking(self, on):
        raise Exception("override me!")

    def set_icon(self, basefilename):
        with_ext = "%s.png" % basefilename
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, with_ext)
        self.set_icon_from_file(filename)

    def set_icon_from_file(self, filename):
        if not self.tray_widget:
            return
        if not os.path.exists(filename):
            log.error("could not find icon %s", filename)
            return
        self.do_set_icon_from_file(filename)

    def do_set_icon_from_file(self, filename):
        raise Exception("override me!")
