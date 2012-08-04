# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase

class TranslatedClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """
        This implementation of the clipboard helper only has one
        type (aka "selection") of clipboard ("CLIPBOARD" by default)
        and it can convert it to another clipboard name ("PRIMARY")
        when conversing with the other end.
        This is because the server implementation always uses the 3 X11
        clipboards whereas some clients (MS Windows) only have "CLIPBOARD"
        and we generally want to map it to X11's "PRIMARY"...
    """

    def __init__(self, send_packet_cb, local_clipboard="CLIPBOARD", remote_clipboard="PRIMARY"):
        self.local_clipboard = local_clipboard
        self.remote_clipboard = remote_clipboard
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, [local_clipboard])

    def local_to_remote(self, selection):
        if selection==self.local_clipboard:
            return  self.remote_clipboard
        return  selection

    def remote_to_local(self, selection):
        if selection==self.remote_clipboard:
            return  self.local_clipboard
        return  selection

class DefaultClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """
        Default clipboard implementation with all 3 selections.
        But without gdk atom support, see gdk_clipboard for a better one!
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])
