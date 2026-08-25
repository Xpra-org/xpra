#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.os_util import get_hex_uuid
from xpra.util.env import osexpand, OSEnvContext
from unit.server_test_util import ServerTestUtil, log


class X11ClientTestUtil(ServerTestUtil):

    uq = 0

    def run_client(self, *args):
        client_display = self.find_free_display()
        xvfb = self.start_Xvfb(client_display)
        xvfb.display = client_display
        return xvfb, self.do_run_client(client_display, *args)

    def do_run_client(self, client_display, *args):
        from xpra.x11.vfb_util import xauth_add
        xauth_data = get_hex_uuid()
        xauthority = self.default_env.get("XAUTHORITY", osexpand("~/.Xauthority"))
        xauth_add(xauthority, client_display, xauth_data, os.getuid(), os.getgid())
        env = self.get_run_env()
        env["DISPLAY"] = client_display
        env["XPRA_LOG_PREFIX"] = "client %i: " % X11ClientTestUtil.uq
        X11ClientTestUtil.uq +=1
        log("starting test client on Xvfb %s", client_display)
        return self.run_xpra(["attach"] + list(args) , env=env)

    def find_client_window(self, client_display, title="", min_size=8, timeout=15, interval=0.5):
        """
        Poll the client's own Xvfb until a window matching `title` (substring match
        against _NET_WM_NAME/WM_NAME) shows up, then drill down to the innermost
        mapped descendant of at least `min_size` (the client draws its own chrome
        as an outer window around the actual content window when there is no
        window manager), and return (xid, x, y, w, h) for that content window -
        x, y are root-relative.
        """
        from xpra.x11.prop import prop_get
        start = time.monotonic()
        candidates = []
        while time.monotonic() - start < timeout:
            candidates = []
            with OSEnvContext():
                os.environ["DISPLAY"] = client_display
                from xpra.x11.bindings.display_source import X11DisplayContext
                with X11DisplayContext(client_display):
                    from xpra.x11.bindings.window import X11WindowBindings
                    x11window = X11WindowBindings()

                    def mapped_size(xid):
                        if not x11window.is_mapped(xid):
                            return None
                        geom = x11window.geometry_with_border(xid)
                        if not geom:
                            return None
                        _wx, _wy, w, h, _border = geom
                        if w < min_size or h < min_size:
                            return None
                        return w, h

                    for xid in x11window.get_all_x11_windows():
                        size = mapped_size(xid)
                        if not size:
                            continue
                        w, h = size
                        wtitle = prop_get(xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
                        if not wtitle:
                            wtitle = prop_get(xid, "WM_NAME", "latin1", ignore_errors=True)
                        if title and (not wtitle or title not in wtitle):
                            candidates.append((xid, wtitle, w, h))
                            continue
                        # drill down to the innermost sizeable mapped descendant:
                        # the client draws its own chrome (title bar / border) as an
                        # outer window when there is no window manager, so the actual
                        # painted content lives in a smaller descendant window:
                        content_xid, content_w, content_h = xid, w, h
                        for descendant in x11window.get_all_children(xid):
                            dsize = mapped_size(descendant)
                            if dsize and dsize[0] * dsize[1] < content_w * content_h:
                                content_xid, content_w, content_h = descendant, dsize[0], dsize[1]
                        pos = x11window.get_absolute_position(content_xid)
                        if not pos:
                            continue
                        x, y = pos
                        return content_xid, x, y, content_w, content_h
            time.sleep(interval)
        raise AssertionError(
            "no window found on display %s matching title=%r after %s seconds, candidates seen: %s" % (
                client_display, title, timeout, candidates))

    def read_client_pixel(self, client_display, xid, x, y):
        with OSEnvContext():
            os.environ["DISPLAY"] = client_display
            from xpra.x11.bindings.display_source import X11DisplayContext
            with X11DisplayContext(client_display):
                from xpra.x11.bindings.ximage import XImageBindings
                ximg = XImageBindings().get_ximage(xid, x, y, 1, 1)
                if ximg is None:
                    raise RuntimeError("failed to capture pixel (%i, %i) from window %#x on %s" % (
                        x, y, xid, client_display))
                pixel_format = ximg.get_pixel_format()
                if pixel_format not in ("BGRX", "BGRA"):
                    raise RuntimeError("unexpected pixel format %r reading window %#x on %s" % (
                        pixel_format, xid, client_display))
                pixels = ximg.get_pixels()
                b, g, r = pixels[0], pixels[1], pixels[2]
                return r, g, b

    def wait_for_client_pixel(self, client_display, xid, x, y, expected_rgb, tolerance=0, timeout=15, interval=0.5):
        start = time.monotonic()
        last_rgb = None
        while time.monotonic() - start < timeout:
            last_rgb = self.read_client_pixel(client_display, xid, x, y)
            if all(abs(a - b) <= tolerance for a, b in zip(last_rgb, expected_rgb)):
                return last_rgb
            time.sleep(interval)
        raise AssertionError("pixel (%i, %i) of window %#x on %s: expected %s (tolerance %i) but got %s" % (
            x, y, xid, client_display, expected_rgb, tolerance, last_rgb))
