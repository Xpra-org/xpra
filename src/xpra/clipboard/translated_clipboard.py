# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.clipboard.clipboard_base import ClipboardProtocolHelperBase, log


DEFAULT_LOCAL_SELECTION     = os.environ.get("XPRA_TRANSLATEDCLIPBOARD_LOCAL_SELECTION")


class TranslatedClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        This implementation of the clipboard helper only has one
        type (aka "selection") of clipboard ("CLIPBOARD" by default)
        and it can convert it to another clipboard name ("PRIMARY")
        when conversing with the other end.
        This is because the X11 server implementation has 3 X11
        selections whereas some clients (MS Windows) only have "CLIPBOARD"
        and we generally want to map it to X11's "PRIMARY"...
    """

    def __init__(self, *args, **kwargs):
        def getselection(name):
            v = kwargs.get("clipboard.%s" % name)           #ie: clipboard.remote
            env_value = os.environ.get("XPRA_TRANSLATEDCLIPBOARD_%s_SELECTION" % name.upper())
            selections = kwargs.get("clipboards.%s" % name) #ie: clipboards.remote
            assert selections, "no %s clipboards!" % name
            for x in (env_value, v):
                if x and x in selections:
                    return x
            return selections[0]
        self.local_clipboard = getselection("local")
        self.remote_clipboard = getselection("remote")
        log("TranslatedClipboardProtocolHelper local=%s, remote=%s", self.local_clipboard, self.remote_clipboard)
        #the local clipboard cannot be changed!
        #we tell the superclass to only initialize this proxy:
        kwargs["clipboards.local"] = [self.local_clipboard]
        #this one can be changed (we send a packet to change the enabled selections)
        kwargs["clipboards.remote"] = [self.remote_clipboard]
        ClipboardProtocolHelperBase.__init__(self, *args, **kwargs)

    def __repr__(self):
        return "TranslatedClipboardProtocolHelper"


    def local_to_remote(self, selection):
        log("local_to_remote(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.local_clipboard:
            return  self.remote_clipboard
        return  selection

    def remote_to_local(self, selection):
        log("remote_to_local(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.remote_clipboard:
            return  self.local_clipboard
        return  selection
