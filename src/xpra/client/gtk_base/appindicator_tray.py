# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Ubuntu re-invents the wheel, and it's a broken one

import os
from xpra.client.tray_base import TrayBase
from xpra.platform.paths import get_icon_dir

from xpra.log import Logger
log = Logger()

def _is_ubuntu_11_10_or_later(self):
    lsb = "/etc/lsb-release"
    if not os.path.exists(lsb):
        return  False
    try:
        try:
            f = open(lsb, mode='rb')
            data = f.read()
        finally:
            f.close()
        props = {}
        for l in data.splitlines():
            parts = l.split("=", 1)
            if len(parts)!=2:
                continue
            props[parts[0].strip()] = parts[1].strip()
        log("found lsb properties: %s", props)
        if props.get("DISTRIB_ID")=="Ubuntu":
            version = [int(x) for x in props.get("DISTRIB_RELEASE", "0").split(".")]
            log("detected Ubuntu release %s", version)
            return version>=[11,10]
    except:
        return False

try:
    try:
        import appindicator            #@UnresolvedImport @UnusedImport
    except:
        try:
            from gi.repository import AppIndicator as appindicator  #@UnresolvedImport @Reimport @UnusedImport
        except:
            from gi.repository import AppIndicator3 as appindicator  #@UnresolvedImport @Reimport
except:
    appindicator = None

def can_use_appindicator():
    return appindicator is not None and _is_ubuntu_11_10_or_later()


class AppindicatorTray(TrayBase):

    def __init__(self, menu, delay_tray, tray_icon_filename):
        TrayBase.__init__(self, delay_tray, tray_icon_filename)
        filename = self.get_tray_icon_filename(tray_icon_filename)
        self.tray_widget = appindicator.Indicator("Xpra", filename, appindicator.CATEGORY_APPLICATION_STATUS)
        if delay_tray:
            self.hide()
            self.client.connect("first-ui-received", self.show_appindicator)
        else:
            self.show()
        if hasattr(self.tray_widget, "set_icon_theme_path"):
            self.tray_widget.set_icon_theme_path(get_icon_dir())
        self.tray_widget.set_attention_icon("xpra.png")
        if filename:
            self.tray_widget.set_icon(filename)
        else:
            self.tray_widget.set_label("Xpra")
        self.tray_widget.set_menu(menu)
        return  True

    def hide(self, *args):
        self.tray_widget.set_status(appindicator.STATUS_PASSIVE)

    def show(self, *args):
        self.tray_widget.set_status(appindicator.STATUS_ACTIVE)

    def set_blinking(self, on):
        #"I'm Afraid I Can't Do That"
        pass

    def set_tooltip(self, text=None):
        self.tray_widget.set_label(text or "Xpra")

    def do_set_icon_from_file(self, filename):
        if not hasattr(self.tray_widget, "set_icon_theme_path"):
            self.tray_widget.set_icon(filename)
            return
        head, icon_name = os.path.split(filename)
        if head:
            self.tray_widget.set_icon_theme_path(head)
        #remove extension (wtf?)
        dot = icon_name.rfind(".")
        if dot>0:
            icon_name = icon_name[:dot]
        self.tray_widget.set_icon(icon_name)
