#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2009-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.gtk_common.gobject_compat import import_gtk, is_gtk3
from xpra.version_util import XPRA_VERSION
from xpra.scripts.config import get_build_info
from xpra.gtk_common.gtk_util import add_close_accel
from xpra.log import Logger

log = Logger("info")

gtk = import_gtk()

APPLICATION_NAME = "Xpra"
SITE_DOMAIN = "xpra.org"
SITE_URL = "https://%s/" % SITE_DOMAIN


GPL2 = None
def load_license():
    global GPL2
    if GPL2 is None:
        from xpra.platform.paths import get_resources_dir
        gpl2_file = os.path.join(get_resources_dir(), "COPYING")
        if os.path.exists(gpl2_file):
            with open(gpl2_file, mode='rb') as f:
                GPL2 = f.read().decode('latin1')
    return GPL2


about_dialog = None
def close_about(*_args):
    if about_dialog:
        about_dialog.hide()

def about(on_close=close_about):
    global about_dialog
    if about_dialog:
        about_dialog.show()
        about_dialog.present()
        return
    from xpra.platform.paths import get_icon
    xpra_icon = get_icon("xpra.png")
    dialog = gtk.AboutDialog()
    if not is_gtk3():
        import webbrowser
        def on_website_hook(*_args):
            ''' called when the website item is selected '''
            webbrowser.open(SITE_URL)
        def on_email_hook(*_args):
            webbrowser.open("mailto://shifter-users@lists.devloop.org.uk")
        gtk.about_dialog_set_url_hook(on_website_hook)
        gtk.about_dialog_set_email_hook(on_email_hook)
        if xpra_icon:
            dialog.set_icon(xpra_icon)
    dialog.set_name("Xpra")
    dialog.set_version(XPRA_VERSION)
    dialog.set_authors(('Antoine Martin <antoine@xpra.org>',
                        'Nathaniel Smith <njs@pobox.com>',
                        'Serviware - Arthur Huillet <ahuillet@serviware.com>'))
    _license = load_license()
    dialog.set_license(_license or "Your installation may be corrupted,"
                    + " the license text for GPL version 2 could not be found,"
                    + "\nplease refer to:\nhttp://www.gnu.org/licenses/gpl-2.0.txt")
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


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    with program_context("About"):
        gui_init()
    about(on_close=gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
