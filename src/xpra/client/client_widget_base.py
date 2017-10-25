# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("window")

#pretend to draw the windows, but don't actually do anything
from xpra.util import envbool
USE_FAKE_BACKING = envbool("XPRA_USE_FAKE_BACKING", False)


class ClientWidgetBase(object):

    def __init__(self, client, watcher_pid, wid, has_alpha):
        self._id = wid
        self.watcher_pid = watcher_pid
        #gobject-like scheduler:
        self.source_remove = client.source_remove
        self.idle_add = client.idle_add
        self.timeout_add = client.timeout_add
        #tells us if the server-side window has an alpha channel
        #(whether we are capable of rendering it is down the backing)
        self._has_alpha = has_alpha
        #tells us if this window instance can paint with alpha
        self._window_alpha = False
        self._client = client
        self._current_icon = None

    def make_new_backing(self, backing_class, ww, wh, bw, bh):
        #size of the backing (same as server window source):
        bw = max(1, bw)
        bh = max(1, bh)
        #actual size of window (may be different when scaling):
        ww = max(1, ww)
        wh = max(1, wh)
        backing = self._backing
        if backing is None:
            bc = backing_class
            if USE_FAKE_BACKING:
                from xpra.client.fake_window_backing import FakeBacking
                bc = FakeBacking
            log("make_new_backing%s effective backing class=%s, server alpha=%s, window alpha=%s", (backing_class, ww, wh, ww, wh), bc, self._has_alpha, self._window_alpha)
            backing = bc(self._id, self._window_alpha, self.pixel_depth)
            if self._client.mmap_enabled:
                backing.enable_mmap(self._client.mmap)
        backing.init(ww, wh, bw, bh)
        return backing

    def workspace_changed(self):
        pass

    def set_cursor_data(self, cursor_data):
        pass

    def new_backing(self, w, h):
        raise Exception("override me!")

    def is_OR(self):
        return False

    def is_tray(self):
        return False

    def is_GL(self):
        return False
