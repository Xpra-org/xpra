# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase

class ClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This implementation of the clipboard helper only has one
        type (aka "selection") of clipboard: "CLIPBOARD" and it
        converts it to "PRIMARY" when conversing with the other end.
        This is because the server implementation always uses the 3 X11
        clipboards whereas some clients (win32) only have one.
        This is used by MS Windows clients.
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD"])

    def local_to_remote(self, selection):
        if selection=="CLIPBOARD":
            return  "PRIMARY"
        return  selection

    def remote_to_local(self, selection):
        if selection=="PRIMARY":
            return  "CLIPBOARD"
        return  selection
