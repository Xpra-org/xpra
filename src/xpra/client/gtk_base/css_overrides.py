# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# load xpra's custom css overrides

import os.path

from xpra.util import envbool
from xpra.platform.paths import get_resources_dir
from xpra.log import Logger

log = Logger("gtk", "util")

CSS_OVERRIDES = envbool("XPRA_CSS_OVERRIDES", True)


_done = False
def inject_css_overrides():
    global _done
    if _done or not CSS_OVERRIDES:
        return
    _done = True

    css_dir = os.path.join(get_resources_dir(), "css")
    log("inject_css_overrides() css_dir=%s", css_dir)
    from gi.repository import Gtk, Gdk
    style_provider = Gtk.CssProvider()
    filename = None
    def parsing_error(_css_provider, _section, error):
        log.error("Error: CSS parsing error on")
        log.error(" '%s'", filename)
        log.error(" %s", error)
    style_provider.connect("parsing-error", parsing_error)
    for f in sorted(os.listdir(css_dir)):
        filename = os.path.join(css_dir, f)
        try:
            style_provider.load_from_path(filename)
            log(" - loaded '%s'", filename)
        except Exception as e:
            log("load_from_path(%s)", filename, exc_info=True)
            log.error("Error: CSS loading error on")
            log.error(" '%s'", filename)
            log.error(" %s", e)

    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        style_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
