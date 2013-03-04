# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, ClipboardProxy, debug


class MergedClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        This implementation uses a single shared ClipboardProxy instance
        to interact with the 3 remote clipboards instances.
    """

    def __init__(self, send_packet_cb, progress_cb=None, local_clipboard="CLIPBOARD", remote_clipboard="PRIMARY"):
        self.clipboards = ["CLIPBOARD", "PRIMARY", "SECONDARY"]
        self.current_remote_clipboard = None
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, progress_cb, clipboards=self.clipboards)

    def init_proxies(self, clipboards):
        assert self.clipboards==clipboards
        self.proxy = ClipboardProxy("CLIPBOARD")
        self.proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        self.proxy.connect("get-clipboard-from-remote", self._get_clipboard_from_remote_handler)
        self.proxy.show()
        self._clipboard_proxies = {}
        for clipboard in clipboards:
            self._clipboard_proxies[clipboard] = self.proxy

    def _send_clipboard_token_handler(self, proxy, selection):
        """ claim all remote clipboards """
        debug("send clipboard token for all: %s", selection)
        for clipboard in self.clipboards:
            self.send("clipboard-token", clipboard)

    def _process_clipboard_token(self, packet):
        selection = packet[1]
        self.current_remote_clipboard = selection
        self.proxy.got_token()
        debug("got clipboard token: %s", packet)

    def local_to_remote(self, selection):
        debug("local_to_remote(%s) current_remote_clipboard=%s", selection, self.current_remote_clipboard)
        return  self.current_remote_clipboard or selection
