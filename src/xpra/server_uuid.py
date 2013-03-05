# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk

from wimpiggy.prop import prop_set, prop_get


def save_uuid(uuid):
    prop_set(gtk.gdk.get_default_root_window(),
                           "_XPRA_SERVER_UUID", "latin1", uuid)
def get_uuid():
    return prop_get(gtk.gdk.get_default_root_window(),
                                  "_XPRA_SERVER_UUID", "latin1", ignore_errors=True)
