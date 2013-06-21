# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.clipboard.clipboard_base import ClipboardProtocolHelperBase, ClipboardProxy, debug


class OSXClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        Full of OSX quirks!
    """

    def __init__(self, send_packet_cb, progress_cb=None):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, progress_cb, ["CLIPBOARD"])

    def make_proxy(self, clipboard):
        return OSXClipboardProxy(clipboard)

    def __str__(self):
        return "OSXClipboardProtocolHelper"


class OSXClipboardProxy(ClipboardProxy):

    def got_token(self, targets):
        # We got the anti-token.
        debug("got token, selection=%s, targets=%s", self._selection, targets)
        self._have_token = True
        for target in targets:
            self.selection_add_target(self._selection, target, 0)
        self.selection_owner_set(self._selection)

gobject.type_register(OSXClipboardProxy)
