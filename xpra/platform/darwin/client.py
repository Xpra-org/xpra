# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import Quartz.CoreGraphics as CG
from Quartz.CoreGraphics import CGDisplayRegisterReconfigurationCallback, CGDisplayRemoveReconfigurationCallback
from Quartz import kCGDisplaySetModeFlag

from xpra.exit_codes import ExitValue
from xpra.client.base.stub import StubClientMixin
from xpra.platform.darwin.gui import (
    enable_focus_workaround, disable_focus_workaround,
    can_access_display,
)
from xpra.common import noop
from xpra.util.env import envint, envbool
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("osx", "events")
GLib = gi_import("GLib")

EVENT_LISTENER = envbool("XPRA_OSX_EVENT_LISTENER", True)
OSX_FOCUS_WORKAROUND = envint("XPRA_OSX_FOCUS_WORKAROUND", 2000)


class PlatformClient(StubClientMixin):
    def __init__(self):
        self.event_loop_started = False
        self.check_display_timer = 0
        self.display_is_asleep = False

    def init_ui(self, opts) -> None:
        swap_keys = opts.swap_keys
        kh = getattr(self, "keyboard_helper", None)
        log("setting swap_keys=%s using %s", swap_keys, kh)
        if kh and kh.keyboard:
            log("%s.swap_keys=%s", kh.keyboard, swap_keys)
            kh.keyboard.swap_keys = swap_keys

    def run(self) -> None:
        if OSX_FOCUS_WORKAROUND:
            def first_ui_received(*_args):
                enable_focus_workaround()
                GLib.timeout_add(OSX_FOCUS_WORKAROUND, disable_focus_workaround)

            self.connect("first-ui-received", first_ui_received)
        self.check_display_timer = GLib.timeout_add(60 * 1000, self.cg_check_display)
        if EVENT_LISTENER:
            with log.trap_error("Error setting up OSX event listener"):
                self.setup_event_listener()

    def cleanup(self) -> None:
        cdt = self.check_display_timer
        if cdt:
            GLib.source_remove(cdt)
            self.check_display_timer = 0
        try:
            r = CGDisplayRemoveReconfigurationCallback(self.cg_display_change, self)
        except ValueError as e:
            log("CGDisplayRemoveReconfigurationCallback: %s", e)
            # if we exit from a signal, this may fail
            r = 1
        if r != 0:
            # don't bother logging this as a warning since we are terminating anyway:
            log("failed to unregister display reconfiguration callback")

    def setup_event_listener(self) -> None:
        log("setup_event_listener()")
        from xpra.platform.darwin.events import get_app_delegate
        delegate = get_app_delegate()
        deiconify_windows = getattr(self, "deiconify_windows", noop)
        log(f"setup_event_listener() {delegate=}, {deiconify_windows=}")
        if deiconify_windows != noop:
            delegate.add_handler("deiconify", deiconify_windows)
        r = CGDisplayRegisterReconfigurationCallback(self.cg_display_change, self)
        if r != 0:
            log.warn("Warning: failed to register display reconfiguration callback")

    def cg_display_change(self, display, flags, userinfo) -> None:
        log("cg_display_change%s", (display, flags, userinfo))
        # The display mode has changed
        # opengl windows may need to be re-created since the GPU may have changed:
        opengl = getattr(self, "opengl_enabled", False)
        reinit_windows = getattr(self, "reinit_windows", noop)
        if (flags & kCGDisplaySetModeFlag) and opengl:
            reinit_windows()

    def cg_check_display(self) -> bool:
        log("cg_check_display()")
        try:
            asleep = None
            if not can_access_display():
                asleep = True
            else:
                did = CG.CGMainDisplayID()
                log("cg_check_display() CGMainDisplayID()=%#x", did)
                if did:
                    asleep = bool(CG.CGDisplayIsAsleep(did))
                    log("cg_check_display() CGDisplayIsAsleep(%#x)=%s", did, asleep)
            if asleep is not None and self.display_is_asleep != asleep:
                self.display_is_asleep = asleep
                if asleep:
                    self.suspend()
                else:
                    self.resume()
            return True
        except Exception:
            log.error("Error checking display sleep status", exc_info=True)
            self.check_display_timer = 0
            return False

    def run_console(self) -> ExitValue:
        # this is for running standalone
        log("starting console event loop")
        self.event_loop_started = True
        import PyObjCTools.AppHelper as AppHelper
        AppHelper.runConsoleEventLoop(installInterrupt=True)
        # when running from the GTK main loop, we rely on another part of the code
        # to run the event loop for us
        return 0

    def stop_console(self) -> None:
        if self.event_loop_started:
            self.event_loop_started = False
            import PyObjCTools.AppHelper as AppHelper
            AppHelper.stopEventLoop()


def main() -> ExitValue:
    from xpra.platform import program_context
    with program_context("OSX Extras"):
        log.enable_debug()
        from xpra.platform.darwin.client import PlatformClient
        ce = PlatformClient()
        ce.run()
        ce.cg_check_display()
        return ce.run_console()


if __name__ == "__main__":
    main()
