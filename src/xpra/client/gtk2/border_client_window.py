# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from xpra.client.gtk2.client_window import ClientWindow


class BorderClientWindow(ClientWindow):
    """
    Adds support for painting the border around the window contents,
    the colour and size can be configured with the "--border=" command line option
    this can be toggled at runtime using the "magic_key" shortcut.
    """

    __gsignals__ = ClientWindow.__common_gsignals__

    def toggle_debug(self, *args):
        pass

gobject.type_register(BorderClientWindow)
