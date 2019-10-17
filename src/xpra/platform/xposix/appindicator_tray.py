# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Ubuntu's "tray" is not very useful:
# - we can't know its position
# - we can't get pointer motion events
# - we can't set the icon using a path (not easily anyway)
# - we can only show a menu and nothing else
# - that menu looks bloody awful
# etc

import os
import sys

from xpra.util import envbool
from xpra.os_util import monotonic_time, osexpand, PYTHON2
from xpra.client.tray_base import TrayBase
from xpra.platform.paths import get_icon_dir, get_icon_filename, get_xpra_tmp_dir
from xpra.log import Logger

log = Logger("tray", "posix")

DELETE_TEMP_FILE = envbool("XPRA_APPINDICATOR_DELETE_TEMP_FILE", True)

if PYTHON2:
    import appindicator                     #@UnresolvedImport
    PASSIVE = appindicator.STATUS_PASSIVE
    ACTIVE = appindicator.STATUS_ACTIVE
    APPLICATION_STATUS = appindicator.CATEGORY_APPLICATION_STATUS
    Indicator = appindicator.Indicator
else:
    import gi
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3 #@UnresolvedImport @Reimport
    PASSIVE = AppIndicator3.IndicatorStatus.PASSIVE
    ACTIVE = AppIndicator3.IndicatorStatus.ACTIVE
    APPLICATION_STATUS = AppIndicator3.IndicatorCategory.APPLICATION_STATUS
    def Indicator(tooltip, filename, status):
        return AppIndicator3.Indicator.new(tooltip, filename, status)


class AppindicatorTray(TrayBase):

    def __init__(self, *args, **kwargs):
        TrayBase.__init__(self, *args, **kwargs)
        filename = get_icon_filename(self.default_icon_filename) or "xpra.png"
        self._has_icon = False
        self.tmp_filename = None
        self.tray_widget = Indicator(self.tooltip, filename, APPLICATION_STATUS)
        if hasattr(self.tray_widget, "set_icon_theme_path"):
            self.tray_widget.set_icon_theme_path(get_icon_dir())
        self.tray_widget.set_attention_icon("xpra.png")
        if filename:
            self.set_icon_from_file(filename)
        if not self._has_icon:
            self.tray_widget.set_label("Xpra")
        if self.menu:
            self.tray_widget.set_menu(self.menu)

    def get_geometry(self):
        #no way to tell :(
        return None

    def hide(self):
        self.tray_widget.set_status(PASSIVE)

    def show(self):
        self.tray_widget.set_status(ACTIVE)

    def set_blinking(self, on):
        #"I'm Afraid I Can't Do That"
        pass

    def set_tooltip(self, tooltip=None):
        #we only use this if we haven't got an icon
        #as with appindicator this creates a large text label
        #next to where the icon is/should be
        if not self._has_icon:
            self.tray_widget.set_label(tooltip or "Xpra")

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, _options=None):
        self.clean_last_tmp_icon()
        #use a temporary file (yuk)
        from xpra.gtk_common.gtk_util import COLORSPACE_RGB, pixbuf_new_from_data, pixbuf_save_to_memory
        import tempfile
        tmp_dir = osexpand(get_xpra_tmp_dir())
        if not os.path.exists(tmp_dir):
            os.mkdir(tmp_dir, 0o755)
        fd, self.tmp_filename = tempfile.mkstemp(prefix="tray", suffix=".png", dir=tmp_dir)
        os.close(fd)
        log("set_icon_from_data%s using temporary file %s",
            ("%s pixels" % len(pixels), has_alpha, w, h, rowstride), self.tmp_filename)
        tray_icon = pixbuf_new_from_data(pixels, COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)
        png_data = pixbuf_save_to_memory(tray_icon)
        with open(self.tmp_filename, "wb") as f:
            f.write(png_data)
        self.do_set_icon_from_file(self.tmp_filename)

    def do_set_icon_from_file(self, filename):
        if not hasattr(self.tray_widget, "set_icon_theme_path"):
            self.tray_widget.set_icon(filename)
            self._has_icon = True
            return
        head, icon_name = os.path.split(filename)
        if head:
            log("do_set_icon_from_file(%s) setting icon theme path=%s", filename, head)
            self.tray_widget.set_icon_theme_path(head)
        #remove extension (wtf?)
        noext = os.path.splitext(icon_name)[0]
        log("do_set_icon_from_file(%s) setting icon=%s", filename, noext)
        self.tray_widget.set_icon(noext)
        self._has_icon = True
        self.icon_timestamp = monotonic_time()

    def clean_last_tmp_icon(self):
        if self.tmp_filename and DELETE_TEMP_FILE:
            try:
                os.unlink(self.tmp_filename)
            except (OSError, IOError):
                log("failed to remove tmp icon", exc_info=True)
            self.tmp_filename = None

    def cleanup(self):
        self.clean_last_tmp_icon()
        TrayBase.cleanup(self)


def main():
    from xpra.platform import program_context
    with program_context("AppIndicator-Test", "AppIndicator Test"):
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("tray")

        from xpra.gtk_common.gobject_compat import import_gtk, register_os_signals
        gtk = import_gtk()

        menu = gtk.Menu()
        item = gtk.MenuItem("Some Menu Item Here")
        menu.append(item)
        menu.show_all()
        a = AppindicatorTray(None, None, menu, "test", "xpra.png", None, None, None, gtk.main_quit)
        a.show()
        register_os_signals(gtk.main_quit)
        gtk.main()


if __name__ == "__main__":
    main()
