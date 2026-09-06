#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.os_util import get_hex_uuid
from xpra.util.env import osexpand, OSEnvContext
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil, log


class X11ClientTestUtil(ServerTestUtil):

    uq = 0

    def terminate_and_wait(self, proc, timeout=5) -> None:
        # a bare `proc.terminate()` only sends the signal and returns immediately:
        # the next test's `find_free_display()` can then race this process's own
        # display/socket cleanup and end up reusing a display it hasn't released yet:
        if proc.poll() is None:
            proc.terminate()
            if pollwait(proc, timeout) is None:
                proc.kill()
                pollwait(proc, timeout)

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

    def find_client_window(self, client_display, title="", size=(), min_size=8, timeout=30, interval=0.5):
        """
        Poll the client's own Xvfb until a window matching `title` (substring match
        against _NET_WM_NAME/WM_NAME) shows up, then drill down to the window its
        contents are painted into, and return (xid, x, y, w, h) for that content
        window - x, y are root-relative.

        Where the contents end up depends on the backing: the cairo backing paints
        straight into the toplevel (its drawing area is a windowless widget), whereas
        the OpenGL backing gets an X11 window of its own as a child of the toplevel.
        Both are handled here by picking the innermost window of the toplevel's tree
        that still covers most of it.
        Beware of the client's headerbar: it turns the window into a CSD one, so the
        toplevel then also covers the titlebar and the shadow border and its top-left
        corner is no longer the top-left corner of the contents
        (use `--headerbar=no` to paint into the whole toplevel).
        `size`, when given, is the exact content size to match - use it whenever the
        test knows how big the window should be, so that any such mismatch fails here
        with a clear message rather than as a bogus pixel value later on.
        """
        from xpra.x11.prop import prop_get
        start = time.monotonic()
        candidates = []
        # keep a single X11 connection open for the whole polling loop instead of
        # opening and closing one on every iteration: besides the overhead, the X11
        # bindings singletons (`X11WindowBindings()`, etc) cache the `Display*` they
        # were created for, so churning through connections makes them "stale" on
        # almost every call and forces them to be recreated constantly:
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

                def matches(w, h, maxw, maxh) -> bool:
                    if w > maxw or h > maxh:
                        return False
                    if size:
                        return (w, h) == tuple(size)
                    # the contents cover the whole window minus the CSD chrome,
                    # any other window of the tree (input-only helpers, etc) is much smaller:
                    return w * h * 2 >= maxw * maxh

                def find_content(xid, w, h):
                    # `get_all_children` returns the whole subtree, parents first,
                    # so this also finds windows nested deeper than the direct children:
                    best = (xid, w, h) if matches(w, h, w, h) else ()
                    for descendant in x11window.get_all_children(xid):
                        dsize = mapped_size(descendant)
                        if not dsize or not matches(dsize[0], dsize[1], w, h):
                            continue
                        # prefer the innermost match: the OpenGL drawing area covers its
                        # parent window, which then only ever shows us unpainted pixels
                        if not best or dsize[0] * dsize[1] <= best[1] * best[2]:
                            best = (descendant, dsize[0], dsize[1])
                    return best

                while time.monotonic() - start < timeout:
                    candidates = []
                    for xid in x11window.get_all_x11_windows():
                        wsize = mapped_size(xid)
                        if not wsize:
                            continue
                        w, h = wsize
                        wtitle = prop_get(xid, "_NET_WM_NAME", "utf8", ignore_errors=True)
                        if not wtitle:
                            wtitle = prop_get(xid, "WM_NAME", "latin1", ignore_errors=True)
                        if title and (not wtitle or title not in wtitle):
                            candidates.append((xid, wtitle, w, h))
                            continue
                        content = find_content(xid, w, h)
                        if not content:
                            # ie: the window is up but its contents don't have the expected size yet
                            candidates.append((xid, wtitle, w, h))
                            continue
                        content_xid, content_w, content_h = content
                        pos = x11window.get_absolute_position(content_xid)
                        if not pos:
                            continue
                        x, y = pos
                        return content_xid, x, y, content_w, content_h
                    time.sleep(interval)
        raise AssertionError(
            "no window found on display %s matching title=%r size=%s after %s seconds, candidates seen: %s" % (
                client_display, title, size or "any", timeout, candidates))

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

    def wait_for_client_pixel(self, client_display, xid, x, y, expected_rgb, tolerance=0, timeout=30, interval=0.5):
        start = time.monotonic()
        last_rgb = None
        # see `find_client_window`: hold the X11 connection open for the whole
        # polling loop instead of reopening it (and re-creating the X11 bindings
        # singletons) on every single pixel read:
        with OSEnvContext():
            os.environ["DISPLAY"] = client_display
            from xpra.x11.bindings.display_source import X11DisplayContext
            with X11DisplayContext(client_display):
                geom = ()
                while time.monotonic() - start < timeout:
                    last_rgb = self.read_client_pixel(client_display, xid, x, y)
                    if all(abs(a - b) <= tolerance for a, b in zip(last_rgb, expected_rgb)):
                        return last_rgb
                    time.sleep(interval)
                # the window geometry tells us if we ended up sampling the wrong window
                # (ie: the client's CSD chrome rather than the window contents):
                from xpra.x11.bindings.window import X11WindowBindings
                geom = X11WindowBindings().geometry_with_border(xid)
        raise AssertionError("pixel (%i, %i) of window %#x (geometry=%s) on %s: expected %s (tolerance %i) but got %s" % (
            x, y, xid, geom, client_display, expected_rgb, tolerance, last_rgb))
