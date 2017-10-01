# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk_x11.prop import prop_set, prop_get
from xpra.gtk_common.gtk_util import get_default_root_window


def save_uuid(uuid):
    prop_set(get_default_root_window(), "_XPRA_SERVER_UUID", "latin1", uuid)

def get_uuid():
    return prop_get(get_default_root_window(), "_XPRA_SERVER_UUID", "latin1", ignore_errors=True)
