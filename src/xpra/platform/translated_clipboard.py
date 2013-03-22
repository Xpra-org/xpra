# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, debug


class TranslatedClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        This implementation of the clipboard helper only has one
        type (aka "selection") of clipboard ("CLIPBOARD" by default)
        and it can convert it to another clipboard name ("PRIMARY")
        when conversing with the other end.
        This is because the server implementation always uses the 3 X11
        clipboards whereas some clients (MS Windows) only have "CLIPBOARD"
        and we generally want to map it to X11's "PRIMARY"...
    """

    def __init__(self, send_packet_cb, progress_cb=None, local_clipboard="CLIPBOARD", remote_clipboard="CLIPBOARD"):
        self.local_clipboard = local_clipboard
        self.remote_clipboard = remote_clipboard
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, progress_cb, [local_clipboard], claim_ownership=True)

    def local_to_remote(self, selection):
        debug("local_to_remote(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.local_clipboard:
            return  self.remote_clipboard
        return  selection

    def remote_to_local(self, selection):
        debug("remote_to_local(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.remote_clipboard:
            return  self.local_clipboard
        return  selection
