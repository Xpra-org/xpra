# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# load xpra's custom css overrides

import os.path

from gi.repository import Gtk, Gdk

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
    style_provider = get_style_provider()
    if style_provider:
        screen = Gdk.Screen.get_default()
        if not screen:
            log.warn("Warning: cannot inject GTK CSS overrides")
            log.warn(" no default screen")
            return
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

_style_provider = None
def get_style_provider():
    global _style_provider
    if _style_provider:
        return _style_provider
    _style_provider = Gtk.CssProvider()
    load_css(_style_provider)
    return _style_provider

def load_css(provider):
    css_dir = os.path.join(get_resources_dir(), "css")
    if not os.path.exists(css_dir) or not os.path.isdir(css_dir):
        log.error("Error: cannot find directory '%s'", css_dir)
        return None
    filename = None
    def parsing_error(_css_provider, _section, error):
        log.error("Error: CSS parsing error on")
        log.error(" '%s'", filename)
        log.error(" %s", error)
    provider.connect("parsing-error", parsing_error)
    for f in sorted(os.listdir(css_dir)):
        filename = os.path.join(css_dir, f)
        try:
            provider.load_from_path(filename)
            log(" - loaded '%s'", filename)
        except Exception as e:
            log("load_from_path(%s)", filename, exc_info=True)
            log.error("Error: CSS loading error on")
            log.error(" '%s'", filename)
            log.error(" %s", e)
