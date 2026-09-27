#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import os
import unittest
from contextlib import ExitStack

from xpra.os_util import POSIX
from xpra.util.env import OSEnvContext
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil

W = 64
H = 48


@unittest.skipUnless(POSIX, "X11 only")
class CompositePixmapTest(ServerTestUtil):
    """
    `XCompositeNameWindowPixmap` allocates a new pixmap every time it is called,
    and the caller owns it: see #5051, where one pixmap was leaked per captured
    frame until the X11 resource IDs ran out and new windows rendered blank.

    The window wrappers must *not* free anything: they wrap the window itself,
    and `XFreePixmap` on a window is an X11 error.
    """

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.stack = ExitStack()
        cls.display = cls.find_free_display()
        cls.xvfb = cls.start_Xvfb(cls.display)
        cls.stack.enter_context(OSEnvContext())
        os.environ["DISPLAY"] = cls.display
        from xpra.x11.bindings.display_source import X11DisplayContext
        cls.stack.enter_context(X11DisplayContext(cls.display))
        # this installs the X11 error handlers, so that `xsync` and friends
        # actually trap the errors instead of letting Xlib abort the process:
        from xpra.x11.bindings.loop import EventLoop
        cls.event_loop = EventLoop()

    def setUp(self):
        super().setUp()
        # `ProcessTestUtil.setUp` resets the whole environment:
        os.environ["DISPLAY"] = self.display
        from xpra.x11.bindings.composite import XCompositeBindings
        try:
            XCompositeBindings().ensure_XComposite_support()
        except Exception as e:
            raise unittest.SkipTest(f"no XComposite support: {e}") from None

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.xvfb.terminate()
        pollwait(cls.xvfb, 10)
        ServerTestUtil.tearDownClass()

    def redirected_window(self) -> int:
        """ a mapped, composite-redirected window, unredirected when the test ends """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.bindings.composite import XCompositeBindings
        X11Window = X11WindowBindings()
        X11Composite = XCompositeBindings()
        with xsync:
            xid = X11Window.CreateWindow(get_root_xid(), 0, 0, W, H)
            X11Window.MapWindow(xid)
            X11Composite.XCompositeRedirectWindow(xid)
        self.addCleanup(self.destroy_window, xid)
        return xid

    @staticmethod
    def destroy_window(xid: int) -> None:
        from xpra.x11.error import xswallow
        from xpra.x11.bindings.window import X11WindowBindings
        with xswallow:
            X11WindowBindings().DestroyWindow(xid)

    @staticmethod
    def name_pixmap(xid: int) -> int:
        from xpra.x11.error import xsync
        from xpra.x11.bindings.composite import XCompositeBindings
        with xsync:
            return XCompositeBindings().XCompositeNameWindowPixmap(xid)

    @staticmethod
    def alive(drawable: int) -> bool:
        """ a freed drawable has no geometry: `XGetGeometry` fails with `BadDrawable` """
        from xpra.x11.error import xsync, XError
        from xpra.x11.bindings.window import X11WindowBindings
        try:
            with xsync:
                return bool(X11WindowBindings().getGeometry(drawable))
        except XError:
            return False

    def test_named_pixmap_is_freed(self):
        """ the composite path must not leak: this is #5051 """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.ximage import XImageBindings
        XImage = XImageBindings()
        xid = self.redirected_window()
        pixmaps = []
        for i in range(100):
            pixmap = self.name_pixmap(xid)
            with xsync:
                handle = XImage.wrap_pixmap(pixmap)
            assert handle, f"failed to wrap pixmap {pixmap:#x} on iteration {i}"
            self.assertEqual(handle.get_drawable(), pixmap)
            self.assertTrue(self.alive(pixmap), f"pixmap {pixmap:#x} is not valid before cleanup")
            with xsync:
                handle.cleanup()
            self.assertFalse(self.alive(pixmap), f"pixmap {pixmap:#x} was leaked by cleanup()")
            pixmaps.append(pixmap)
        # every call allocates a new resource id, which is what made this leak fatal:
        self.assertEqual(len(set(pixmaps)), len(pixmaps), "expected a distinct pixmap per call")

    def test_named_pixmap_is_freed_when_garbage_collected(self):
        """ dropping the wrapper without calling `cleanup()` must still free the pixmap """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.ximage import XImageBindings
        xid = self.redirected_window()
        pixmap = self.name_pixmap(xid)
        with xsync:
            handle = XImageBindings().wrap_pixmap(pixmap)
        assert handle
        del handle
        gc.collect()
        self.assertFalse(self.alive(pixmap), f"pixmap {pixmap:#x} was leaked by __dealloc__")

    def test_wrap_pixmap_frees_the_pixmap_if_it_raises(self):
        """ `wrap_pixmap` takes ownership unconditionally, including on failure """
        from xpra.x11.bindings.core import set_context_check, noop
        from xpra.x11.bindings.ximage import XImageBindings
        xid = self.redirected_window()
        pixmap = self.name_pixmap(xid)
        self.assertTrue(self.alive(pixmap))

        class ContextError(Exception):
            pass

        def fail(*_args):
            raise ContextError("simulated context check failure")

        self.addCleanup(set_context_check, noop)
        set_context_check(fail)
        try:
            self.assertRaises(ContextError, XImageBindings().wrap_pixmap, pixmap)
        finally:
            set_context_check(noop)
        gc.collect()
        self.assertFalse(self.alive(pixmap), f"pixmap {pixmap:#x} was leaked when wrapping raised")

    def test_cleanup_is_idempotent(self):
        """ the pixmap must only be freed once, a second cleanup is a no-op """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.ximage import XImageBindings
        xid = self.redirected_window()
        pixmap = self.name_pixmap(xid)
        with xsync:
            handle = XImageBindings().wrap_pixmap(pixmap)
            handle.cleanup()
            handle.cleanup()
        del handle
        gc.collect()
        # any double free would have been reported by the `xsync` blocks above:
        with xsync:
            pass
        self.assertFalse(self.alive(pixmap))

    def test_window_wrapper_does_not_free_the_window(self):
        """ regression guard: `XFreePixmap` on a window is an X11 error """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.ximage import XImageBindings
        xid = self.redirected_window()
        with xsync:
            handle = XImageBindings().get_xwindow_pixmap_wrapper(xid)
        assert handle
        self.assertEqual(handle.get_drawable(), xid)
        with xsync:
            handle.cleanup()
        del handle
        gc.collect()
        self.assertTrue(self.alive(xid), f"window {xid:#x} was freed by the window wrapper")

    def test_image_outlives_the_pixmap(self):
        """
        `XGetImage` copies the pixels to the client,
        so images and their sub-images stay valid once the pixmap is freed:
        the encoding threads hold on to them long after `invalidate_pixmap()`.
        """
        from xpra.x11.error import xsync
        from xpra.x11.bindings.ximage import XImageBindings
        xid = self.redirected_window()
        pixmap = self.name_pixmap(xid)
        with xsync:
            handle = XImageBindings().wrap_pixmap(pixmap)
            image = handle.get_image(0, 0, W, H)
        assert image, "failed to get an image from the named pixmap"
        before = bytes(image.get_pixels())
        with xsync:
            handle.cleanup()
        del handle
        gc.collect()
        self.assertFalse(self.alive(pixmap))
        self.assertEqual(bytes(image.get_pixels()), before, "pixels changed after the pixmap was freed")
        # zero-copy view, and the bottom-row-at-an-offset case which makes a packed copy:
        sub = image.get_sub_image(4, 2, 32, 16)
        sub_bottom = image.get_sub_image(4, H - 8, 32, 8)
        self.assertEqual(len(bytes(sub.get_pixels())), sub.get_size())
        self.assertEqual(len(bytes(sub_bottom.get_pixels())), sub_bottom.get_size())
        sub.free()
        sub_bottom.free()
        image.free()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
