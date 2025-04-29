# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("window")
# pretend to draw the windows, but don't actually do anything:
USE_FAKE_BACKING = envbool("XPRA_USE_FAKE_BACKING", False)


class ClientWidgetBase:

    def __init__(self, client, wid: int, has_alpha: bool):
        self.wid = wid
        # tells us if the server-side window has an alpha channel
        # (whether we are capable of rendering it is down the backing)
        self._has_alpha = has_alpha
        # tells us if this window instance can paint with alpha
        self._window_alpha = False
        self._client = client
        self._current_icon = None
        self._backing = None
        self.pixel_depth = 24

    def get_info(self) -> dict[str, Any]:
        info = {
            "has-alpha": self._has_alpha,
            "window-alpha": self._window_alpha,
            "pixel-depth": self.pixel_depth,
        }
        b = self._backing
        if b:
            info["backing"] = b.get_info()
        return info

    def make_new_backing(self, backing_class: Callable, ww: int, wh: int, bw: int, bh: int):
        # size of the backing, which should be the same as the server's window source:
        bw = max(1, bw)
        bh = max(1, bh)
        # actual size of window, which may be different when scaling:
        ww = max(1, ww)
        wh = max(1, wh)
        if ww >= 32768 or wh >= 32768:
            log.warn("Warning: invalid window dimensions %ix%i", ww, wh)
        backing = self._backing
        if backing is None:
            bc = backing_class
            if USE_FAKE_BACKING:
                from xpra.client.gui.fake_window_backing import FakeBacking  # pylint: disable=import-outside-toplevel
                bc = FakeBacking
            log("make_new_backing%s effective backing class=%s, server alpha=%s, window alpha=%s",
                (backing_class, ww, wh, ww, wh), bc, self._has_alpha, self._window_alpha)
            backing = bc(self.wid, self._window_alpha, self.pixel_depth)
            mmap = getattr(self._client, "mmap_read_area", None)
            if mmap:
                backing.enable_mmap(mmap)
        backing.init(ww, wh, bw, bh)
        return backing

    def freeze(self) -> None:
        """
        Subclasses can suspend screen updates and free some resources
        """

    def unfreeze(self) -> None:
        """
        Subclasses may resume normal operation that were suspended by freeze()
        """

    def set_cursor_data(self, cursor_data) -> None:  # pragma: no cover
        pass

    def new_backing(self, w: int, h: int):  # pragma: no cover
        raise NotImplementedError

    def is_OR(self) -> bool:  # pragma: no cover
        return False

    def is_tray(self) -> bool:  # pragma: no cover
        return False

    def is_GL(self) -> bool:  # pragma: no cover
        return False
