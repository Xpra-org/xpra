#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2009 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.os_util import gi_import
from xpra.util.version import XPRA_VERSION
from xpra.scripts.config import get_build_info
from xpra.gtk.window import add_close_accel
from xpra.log import Logger

Gtk = gi_import("Gtk")

log = Logger("info")

APPLICATION_NAME = "Xpra"
SITE_DOMAIN = "xpra.org"
SITE_URL = f"https://{SITE_DOMAIN}/"

GPL2 = ""

MAIN_AUTHORS = (
    'Antoine Martin <antoine@xpra.org>',
    'Nathaniel Smith <njs@pobox.com>',
    'Serviware - Arthur Huillet <ahuillet@serviware.com>',
)


def load_license():
    global GPL2
    if not GPL2:
        from xpra.platform.paths import get_resources_dir  # pylint: disable=import-outside-toplevel
        gpl2_file = os.path.join(get_resources_dir(), "COPYING")
        if os.path.exists(gpl2_file):
            with open(gpl2_file, mode="rb") as f:
                GPL2 = f.read().decode("latin1")
    return GPL2 or "Your installation may be corrupted," \
                   " the license text for GPL version 2 could not be found," \
                   "\nplease refer to:\nhttps://www.gnu.org/licenses/gpl-2.0.txt"


about_dialog = None


def close_about(*_args):
    if about_dialog:
        about_dialog.hide()


def about(on_close=close_about, parent: Gtk.Window | None = None):
    global about_dialog
    if about_dialog:
        about_dialog.show()
        about_dialog.present()
        return
    from xpra.platform.paths import get_icon  # pylint: disable=import-outside-toplevel
    xpra_icon = get_icon("xpra.png")
    dialog = Gtk.AboutDialog()
    dialog.set_name("Xpra")
    dialog.set_version(XPRA_VERSION)
    if parent:
        dialog.set_transient_for(parent)
        dialog.set_destroy_with_parent(True)
    dialog.set_authors(MAIN_AUTHORS)
    _license = load_license()
    dialog.set_license(_license)
    dialog.set_comments("\n".join(get_build_info()))
    dialog.set_website(SITE_URL)
    dialog.set_website_label(SITE_DOMAIN)
    if xpra_icon:
        dialog.set_logo(xpra_icon)
    if hasattr(dialog, "set_program_name"):
        dialog.set_program_name(APPLICATION_NAME)
    dialog.connect("response", on_close)
    add_close_accel(dialog, on_close)
    about_dialog = dialog
    dialog.show()


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    with program_context("About"):
        gui_init()
    about(on_close=Gtk.main_quit)
    Gtk.main()
    return 0


if __name__ == "__main__":
    main()
