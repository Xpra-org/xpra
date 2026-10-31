#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import socket
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from xpra.util.objects import typedict
from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait, which
from xpra.codecs.image import ImageWrapper
from unit.server_test_util import ServerTestUtil, SERVER_TIMEOUT


class ShadowNotifierTest(unittest.TestCase):

    def test_tray_requires_existing_bus(self):
        from xpra.server import features
        from xpra.server.subsystem import tray
        gtk_module = ModuleType("xpra.gtk.statusicon_tray")
        for enabled, address in ((True, "desktop-bus"), (True, ""), (False, "desktop-bus")):
            widget = Mock()
            gtk_module.GTKStatusIconTray = Mock(return_value=widget)
            native = Mock(return_value=widget)
            with self.subTest(dbus=enabled, address=address), patch.object(tray, "POSIX", True), \
                    patch.object(tray, "OSX", False), patch.object(features, "dbus", enabled), \
                    patch.dict(sys.modules, {gtk_module.__name__: gtk_module}), \
                    patch("xpra.dbus.common.find_session_bus_address", return_value=address), \
                    patch("xpra.platform.systray.get_backends", return_value=[native]) as backends:
                manager = tray.TrayMenu()
                manager.menu = object()
                self.assertIs(manager.make_tray_widget(), widget)
                use_native = bool(enabled and address)
                self.assertEqual(backends.call_count, int(use_native))
                self.assertEqual(native.call_count, int(use_native))
                self.assertEqual(gtk_module.GTKStatusIconTray.call_count, int(not use_native))

    def test_native_notifier_requires_existing_bus(self):
        from xpra.server import features
        from xpra.server.shadow import shadow_server_base as shadow
        server = shadow.ShadowServerBase.__new__(shadow.ShadowServerBase)
        server.subsystems = {}
        for enabled, address in ((True, "desktop-bus"), (True, ""), (False, "desktop-bus")):
            with self.subTest(dbus=enabled, address=address), patch.object(shadow, "POSIX", True), \
                    patch.object(shadow, "OSX", False), patch.object(shadow, "NATIVE_NOTIFIER", True), \
                    patch.object(features, "dbus", enabled), \
                    patch("xpra.dbus.common.find_session_bus_address", return_value=address), \
                    patch("xpra.platform.notification.get_backends", return_value=[object]) as backends:
                self.assertEqual(server.get_notifier_classes(), [object] if enabled and address else [])
                self.assertEqual(backends.call_count, int(bool(enabled and address)))


class ShadowServerTest(ServerTestUtil):

    def start_shadow_server(self, *args):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        assert display in self.find_X11_displays()
        #start server using this display:
        server = self.check_server("shadow", display, *args)
        return display, xvfb, server

    def stop_shadow_server(self, xvfb, server):
        self.check_stop_server(server, "stop", xvfb.display)
        time.sleep(1)
        assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
        xvfb.terminate()

    def test_shadow_start_stop(self):
        _, xvfb, server = self.start_shadow_server()
        self.stop_shadow_server(xvfb, server)

    def test_dbus_interface(self):
        if not POSIX or OSX:
            return
        dbus_send = which("dbus-send")
        if not dbus_send:
            print("Warning: dbus test skipped, 'dbus-send' not found")
            return
        display, xvfb, server = self.start_shadow_server("-d", "dbus")
        info = self.get_server_info(xvfb.display)
        assert info
        tinfo = typedict(info)
        idisplay = tinfo.strget("display.name")
        assert idisplay==display, "expected display '%s' in info, but got '%s'" % (display, idisplay)
        try:
            import dbus
            assert dbus
        except ImportError:
            print("WARNING: python-dbus not found, the dbus interface cannot be tested")
        else:
            dstr = display.lstrip(":")
            # must be within the range accepted by `clamp_refresh_delay`:
            new_delay = 20
            cmd = [
                dbus_send,
                "--session",
                "--type=method_call",
                f"--dest=org.xpra.Server{dstr}",
                "/org/xpra/Server",
                "org.xpra.Server.SetRefreshDelay",
                f"int32:{new_delay}",
            ]
            env = self.get_run_env()
            env["DISPLAY"] = display
            self.run_command(cmd, env=env).wait(20)
            time.sleep(1)
            #check that the value has changed:
            info = self.get_server_info(display)
            assert info
            tinfo = typedict(info)
            assert tinfo.strget("display.name")==display
            rd = tinfo.intget("refresh-delay", 0)
            assert rd==new_delay, f"expected refresh-delay={new_delay}, got {rd}"
        self.stop_shadow_server(xvfb, server)

    @unittest.skipUnless(POSIX and not OSX and which("xterm"), "xterm required for dynamic window match test")
    def test_shadow_dynamic_window_match_no_crash(self):
        # Regression test for a caller/constructor argument-count mismatch:
        # ShadowX11Server.makeDynamicWindowModels()'s `model_class` closure
        # used to call X11ShadowModel(root, capture, title, geometry) -- an
        # extra leading `root` argument the constructor doesn't accept.
        # Every other caller (GTKShadowServerBase.make_capture_window_models)
        # already omits it. This crashed load_existing_windows() with
        # "TypeError: X11ShadowModel.__init__() takes from 1 to 4 positional
        # arguments but 5 were given" for every window matched by a
        # `windows=` (xid=/pid=/command=/class=/title regex) dynamic spec --
        # i.e. any shadow session that doesn't mirror the whole screen.
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        assert display in self.find_X11_displays()
        env = self.get_run_env()
        env["DISPLAY"] = display
        title = "xpra-dynamic-match-test"
        # -e sleep 300, not an interactive shell: an interactive shell's own
        # prompt can overwrite the -T title shortly after startup via an
        # OSC escape sequence, making the window unmatchable by title.
        xterm_proc = self.run_command([xterm, "-T", title, "-e", "sleep", "300"], env=env)
        time.sleep(2)
        try:
            server_proc = self.run_xpra(["shadow", f"{display},windows={title}", "--no-daemon"])
            if pollwait(server_proc, SERVER_TIMEOUT) is not None:
                self.show_proc_error(server_proc, "shadow server failed to start")
            live: list[str] = []
            for _ in range(20):
                live = self.dotxpra.displays()
                if display in live:
                    break
                time.sleep(1)
            assert server_proc.poll() is None, \
                "shadow server terminated unexpectedly -- did makeDynamicWindowModels() crash?"
            assert display in live, f"shadow server display {display!r} not found in {live}"
            info = self.get_server_info(display)
            assert info
            tinfo = typedict(info)
            nwindows = tinfo.intget("state.windows", -1)
            assert nwindows == 1, f"expected exactly 1 matched window, got state.windows={nwindows!r}"
            self.check_stop_server(server_proc, "stop", display)
        finally:
            xterm_proc.terminate()
        time.sleep(1)
        assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
        xvfb.terminate()

    def test_capture_window_model(self):
        from xpra.server.shadow.root_window_model import CaptureWindowModel
        W = 640
        H = 480

        class FakeCapture:
            def take_screenshot(self):
                return self.get_image(0, 0, W, H)

            def get_image(self, x, y, w, h):
                pixels = "0"*w*4*h
                return ImageWrapper(x, y, w, h, pixels, "BGRA", 32, w*4, 4, ImageWrapper.PACKED, True, None)

            def get_info(self):
                return {"type" : "fake"}

        rwm = CaptureWindowModel(FakeCapture(), geometry=(0, 0, W, H))
        assert repr(rwm)
        assert rwm.get_info()
        assert "content-types" in rwm.get_internal_property_names()
        assert "content-type" not in rwm.get_internal_property_names()
        rwm.get_default_window_icon(32)
        for prop in ("title", "class-instance", "size-constraints", "icons"):
            rwm.get_property(prop)
        for prop, value in {
            "client-machine"    : socket.gethostname(),
            "window-type"        : ["NORMAL"],
            "fullscreen"        : False,
            "shadow"            : True,
            "depth"                : 24,
            "scaling"            : None,
            "opacity"            : None,
            "content-types"       : ("desktop",),
        }.items():
            assert rwm.get_property(prop)==value
        rwm.suspend()
        rwm.unmanage(True)
        assert rwm.take_screenshot()
        assert rwm.get_image(10, 10, 20, 20)
        rwm.geometry = (10, 10, W, H)
        img = rwm.get_image(10, 10, 20, 20)
        assert img.get_target_x()==10
        assert img.get_target_y()==10


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
