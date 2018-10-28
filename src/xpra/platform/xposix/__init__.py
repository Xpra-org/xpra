# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def do_init():
    pass

def do_clean():
    pass

def threaded_server_init():
    from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
    load_xdg_menu_data()
