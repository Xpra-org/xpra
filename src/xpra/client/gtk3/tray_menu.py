# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_tray_menu_base import GTKTrayMenuBase


class GTK3TrayMenu(GTKTrayMenuBase):

    def show_menu(self, button, time):
        self.close_menu()
        self.menu.popup(None, None, None, None, button, time)
        self.menu_shown = True
