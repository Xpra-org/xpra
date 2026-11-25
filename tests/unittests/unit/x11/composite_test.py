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
        from xpra.common import noop
        from xpra.x11.bindings.core import set_context_check
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
        before = bytes(image.get_plane(0))
        with xsync:
            handle.cleanup()
        del handle
        gc.collect()
        self.assertFalse(self.alive(pixmap))
        self.assertEqual(bytes(image.get_plane(0)), before, "pixels changed after the pixmap was freed")
        # zero-copy view, and the bottom-row-at-an-offset case which makes a packed copy:
        sub = image.get_sub_image(4, 2, 32, 16)
        sub_bottom = image.get_sub_image(4, H - 8, 32, 8)
        self.assertEqual(len(bytes(sub.get_plane(0))), sub.get_size())
        self.assertEqual(len(bytes(sub_bottom.get_plane(0))), sub_bottom.get_size())
        sub.free()
        sub_bottom.free()
        image.free()

    # pre-redirection of override-redirect windows, before they are mapped:

    def or_window(self, mapped=False, parent=0) -> int:
        from xpra.x11.error import xsync
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        with xsync:
            xid = X11Window.CreateWindow(parent or get_root_xid(), 0, 0, W, H, OR=True)
            if mapped:
                X11Window.MapWindow(xid)
        self.addCleanup(self.destroy_window, xid)
        return xid

    @staticmethod
    def can_redirect(xid: int) -> bool:
        """ only one manual redirection is allowed: this fails if the window is still redirected """
        from xpra.x11.error import xsync, XError
        from xpra.x11.bindings.composite import XCompositeBindings
        X11Composite = XCompositeBindings()
        try:
            with xsync:
                X11Composite.XCompositeRedirectWindow(xid)
        except XError:
            return False
        with xsync:
            X11Composite.XCompositeUnredirectWindow(xid)
        return True

    def tearDown(self):
        from xpra.x11.composite import pre_redirected
        leftover = tuple(pre_redirected)
        pre_redirected.clear()
        super().tearDown()
        self.assertEqual(leftover, (), "pre-redirected windows were not claimed or cancelled")

    def test_pre_redirect_is_claimed(self):
        from xpra.x11.error import xsync
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.composite import CompositeHelper, pre_redirect, pre_redirected
        xid = self.or_window()
        self.assertTrue(pre_redirect(xid))
        self.assertTrue(pre_redirect(xid), "pre-redirecting twice must be harmless")
        self.assertIn(xid, pre_redirected)
        self.assertFalse(self.can_redirect(xid), "the window should be redirected already")
        with xsync:
            X11WindowBindings().MapWindow(xid)
        helper = CompositeHelper(xid)
        # this would fail with `BadAccess` if the helper tried to redirect it again:
        with xsync:
            helper.setup()
        self.assertNotIn(xid, pre_redirected)
        with xsync:
            self.assertIsNotNone(helper.get_contents_handle())
            helper.destroy()
        self.assertTrue(self.can_redirect(xid), "the helper did not un-redirect the window")

    def test_cancel_pre_redirect(self):
        from xpra.x11.composite import pre_redirect, cancel_pre_redirect, pre_redirected
        xid = self.or_window()
        self.assertTrue(pre_redirect(xid))
        cancel_pre_redirect(xid)
        self.assertNotIn(xid, pre_redirected)
        self.assertTrue(self.can_redirect(xid))
        # not pre-redirected: must not touch the window
        self.assertTrue(self.can_redirect(xid))
        cancel_pre_redirect(xid)

    def test_pre_redirect_vanished_window(self):
        from xpra.x11.composite import pre_redirect, pre_redirected
        xid = self.or_window()
        self.destroy_window(xid)
        self.assertFalse(pre_redirect(xid))
        self.assertNotIn(xid, pre_redirected)

    def test_root_events(self):
        """ `CreateNotify`, `MapNotify`, `DestroyNotify` and `ReparentNotify` on the root window """
        from unittest.mock import patch
        from xpra.x11.error import xsync
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.composite import pre_redirected, cancel_pre_redirect
        from xpra.x11.subsystem import window as window_module
        X11Window = X11WindowBindings()
        if not window_module.PRE_REDIRECT_OR:
            self.skipTest("XPRA_PRE_REDIRECT_OR is disabled")
        subsystem = window_module.SeamlessWindowServer(None)
        subsystem.receive_root_events()
        self.addCleanup(subsystem.cleanup)
        self.assertTrue(subsystem.pre_redirect_or)

        def process_events():
            with xsync:
                pass
            self.event_loop.process_events()

        added = []
        # the subsystem has `__slots__`, so patch the class:
        with patch.object(window_module.SeamlessWindowServer, "_add_new_or_window", lambda _self, xid: added.append(xid)):
            # an override-redirect window is redirected as soon as it is created:
            xid = self.or_window()
            process_events()
            self.assertIn(xid, pre_redirected)
            # mapped, but nothing claimed it (ie: the window was ignored): un-redirected
            with xsync:
                X11Window.MapWindow(xid)
            process_events()
            self.assertEqual(added, [xid])
            self.assertNotIn(xid, pre_redirected)
            self.assertTrue(self.can_redirect(xid))

            # destroyed before it is mapped:
            xid = self.or_window()
            process_events()
            self.assertIn(xid, pre_redirected)
            self.destroy_window(xid)
            process_events()
            self.assertNotIn(xid, pre_redirected)

            # reparented away from the root before it is mapped:
            xid = self.or_window()
            parent = self.or_window()
            process_events()
            self.assertIn(xid, pre_redirected)
            with xsync:
                X11Window.Reparent(xid, parent, 0, 0)
            process_events()
            self.assertNotIn(xid, pre_redirected)
            self.assertTrue(self.can_redirect(xid))
            cancel_pre_redirect(parent)

            # ordinary windows are left alone:
            with xsync:
                xid = X11Window.CreateWindow(subsystem.root_event_xid, 0, 0, W, H)
            self.addCleanup(self.destroy_window, xid)
            process_events()
            self.assertNotIn(xid, pre_redirected)
            self.assertTrue(self.can_redirect(xid))

            # still pending when the subsystem is cleaned up:
            xid = self.or_window()
            process_events()
            self.assertIn(xid, pre_redirected)
            subsystem.cleanup()
            self.assertNotIn(xid, pre_redirected)
            self.assertTrue(self.can_redirect(xid))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
