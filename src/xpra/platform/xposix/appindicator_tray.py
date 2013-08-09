# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Ubuntu re-invents the wheel, and it's a broken one

import os
from xpra.client.tray_base import TrayBase, debug
from xpra.platform.paths import get_icon_dir


def is_unity():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "unity"


_appindicator = False
def get_appindicator():
    global _appindicator
    if _appindicator is False:
        try:
            try:
                import appindicator            #@UnresolvedImport @UnusedImport
            except:
                try:
                    from gi.repository import AppIndicator as appindicator  #@UnresolvedImport @Reimport @UnusedImport
                    _appindicator = appindicator
                except:
                    from gi.repository import AppIndicator3 as appindicator  #@UnresolvedImport @Reimport
                    _appindicator = appindicator
        except:
            _appindicator = None
    return _appindicator

def can_use_appindicator():
    return get_appindicator() is not None and is_unity()


class AppindicatorTray(TrayBase):

    def __init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        TrayBase.__init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb)
        filename = self.get_tray_icon_filename(icon_filename)
        self.appindicator = get_appindicator()
        assert self.appindicator, "appindicator is not available!"
        self.tray_widget = self.appindicator.Indicator(tooltip, filename, self.appindicator.CATEGORY_APPLICATION_STATUS)
        if hasattr(self.tray_widget, "set_icon_theme_path"):
            self.tray_widget.set_icon_theme_path(get_icon_dir())
        self.tray_widget.set_attention_icon("xpra.png")
        if filename:
            self.tray_widget.set_icon(filename)
        else:
            self.tray_widget.set_label("Xpra")
        if menu:
            self.tray_widget.set_menu(menu)

    def hide(self, *args):
        self.tray_widget.set_status(self.appindicator.STATUS_PASSIVE)

    def show(self, *args):
        self.tray_widget.set_status(self.appindicator.STATUS_ACTIVE)

    def set_blinking(self, on):
        #"I'm Afraid I Can't Do That"
        pass

    def set_tooltip(self, text=None):
        self.tray_widget.set_label(text or "Xpra")

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        #can't do that either..
        pass

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


def main():
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.DEBUG)

    appindicator = get_appindicator()
    if not appindicator:
        debug("appindicator not available")
        return

    if not can_use_appindicator():
        debug("appindicator may not be shown...")

    from xpra.gtk_common.gobject_compat import import_gobject, import_gtk
    gobject = import_gobject()
    gtk = import_gtk()

    menu = gtk.Menu()
    item = gtk.MenuItem("Some Menu Item Here")
    menu.append(item)
    menu.show_all()
    a = AppindicatorTray(menu, "test", "xpra.png", None, None, None, gtk.main_quit)
    a.show()
    gobject.timeout_add(1000*10, gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
