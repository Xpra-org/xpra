# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject               #@UnresolvedImport @UnusedImport

from xpra.client.gtk3.cairo_backing import CairoBacking
from xpra.client.gtk3.gtk3_client_window import GTK3ClientWindow

"""
GTK3 window painted with cairo
"""
class ClientWindow(GTK3ClientWindow):

    __gsignals__ = GTK3ClientWindow.__common_gsignals__

    def get_backing_class(self):
        return CairoBacking

GObject.type_register(ClientWindow)
