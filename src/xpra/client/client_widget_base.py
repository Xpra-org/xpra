# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("window")

#pretend to draw the windows, but don't actually do anything
USE_FAKE_BACKING = os.environ.get("XPRA_USE_FAKE_BACKING", "0")=="1"


class ClientWidgetBase(object):

    def __init__(self, client, wid, has_alpha):
        self._id = wid
        #gobject-like scheduler:
        self.source_remove = client.source_remove
        self.idle_add = client.idle_add
        self.timeout_add = client.timeout_add
        self._has_alpha = has_alpha
        self._client = client

    def make_new_backing(self, backing_class, w, h):
        w = max(1, w)
        h = max(1, h)
        backing = self._backing
        if backing is None:
            bc = backing_class
            if USE_FAKE_BACKING:
                from xpra.client.fake_window_backing import FakeBacking
                bc = FakeBacking
            log("make_new_backing(%s, %s, %s) effective backing class=%s, alpha=%s", backing_class, w, h, bc, self._has_alpha)
            backing = bc(self._id, w, h, self._has_alpha)
            if self._client.mmap_enabled:
                backing.enable_mmap(self._client.mmap)
        backing.init(w, h)
        return backing

    def workspace_changed(self):
        pass

    def new_backing(self, w, h):
        raise Exception("override me!")

    def is_OR(self):
        return False

    def is_tray(self):
        return False

    def is_GL(self):
        return False
