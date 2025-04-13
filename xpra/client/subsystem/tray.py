# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#  pylint: disable-msg=E1101

from xpra.platform.gui import get_native_tray_classes, get_native_tray_menu_helper_class
from xpra.os_util import gi_import, WIN32, OSX
from xpra.util.objects import make_instance
from xpra.util.env import envint
from xpra.common import XPRA_APP_ID, ConnectionMessage
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("tray")

TRAY_DELAY = envint("XPRA_TRAY_DELAY", 0)


class TrayClient(StubClientMixin):
    """
    Mixin for supporting our system tray
    (not forwarding other application's trays - that's handled in WindowClient)
    """
    PREFIX = "tray"

    def __init__(self):
        # settings:
        self.tray_icon = None
        # state:
        self.tray = None
        self.menu_helper = None

    def init(self, opts) -> None:
        if not opts.tray:
            return
        self.tray_icon = opts.tray_icon
        self.get_menu_helper()
        if opts.delay_tray:
            self.connect("first-ui-received", self.setup_xpra_tray)
        else:
            if WIN32 or OSX:
                # show shortly after the main loop starts running:
                GLib.timeout_add(TRAY_DELAY, self.setup_xpra_tray)
            else:
                # wait for handshake:
                # see appindicator bug #3956
                self.after_handshake(self.setup_xpra_tray)

    def setup_xpra_tray(self, *args) -> None:
        log("setup_xpra_tray%s", args)
        tray = self.create_xpra_tray(self.tray_icon or "xpra")
        self.tray = tray
        if tray:
            tray.show()
            icon_timestamp = tray.icon_timestamp

            def reset_icon() -> None:
                if not self.tray:
                    return
                # re-set the icon after a short delay,
                # seems to help with buggy tray geometries,
                # but don't do it if we have already changed the icon
                # (ie: the dynamic window icon code may have set a new one)
                if icon_timestamp == tray.icon_timestamp:
                    tray.set_icon()

            GLib.timeout_add(1000, reset_icon)

    def cleanup(self) -> None:
        t = self.tray
        if t:
            self.tray = None
            with log.trap_error("Error during tray cleanup"):
                t.cleanup()

    def get_tray_classes(self) -> list[type]:
        # subclasses may add their toolkit specific variants, if any
        # by overriding this method
        # use the native ones first:
        return get_native_tray_classes()

    def get_menu_helper(self):
        """
        menu helper used by our tray (make_tray / setup_xpra_tray)
        and for showing the menu on windows via a shortcut,
        this method is overriden in the gtk3.client
        """
        mhc = (get_native_tray_menu_helper_class(), )
        self.menu_helper = make_instance(mhc, self)
        return self.menu_helper

    def show_menu(self, *_args) -> None:
        if self.menu_helper:
            self.menu_helper.activate()

    def create_xpra_tray(self, tray_icon_filename: str):
        tray = None

        # this is our own tray

        def xpra_tray_click(button, pressed, time=0):
            log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
            if button == 1 and pressed:
                GLib.idle_add(self.menu_helper.activate, button, time)
            elif button in (2, 3) and not pressed:
                GLib.idle_add(self.menu_helper.popup, button, time)

        def xpra_tray_mouseover(*args):
            log("xpra_tray_mouseover%s", args)

        def xpra_tray_exit(*args):
            log("xpra_tray_exit%s", args)
            self.disconnect_and_quit(0, ConnectionMessage.CLIENT_EXIT)

        def xpra_tray_geometry(*args):
            if tray:
                log("xpra_tray_geometry%s geometry=%s", args, tray.get_geometry())

        menu = None
        if self.menu_helper:
            menu = self.menu_helper.build()
        tray = self.make_tray(XPRA_APP_ID, menu, self.get_tray_title(), tray_icon_filename,
                              xpra_tray_geometry, xpra_tray_click, xpra_tray_mouseover, xpra_tray_exit)
        log("setup_xpra_tray(%s)=%s (%s)", tray_icon_filename, tray, type(tray))
        if tray:
            def reset_tray_title() -> None:
                tray.set_tooltip(self.get_tray_title())

            self.after_handshake(reset_tray_title)
        return tray

    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.get_tray_classes()
        log("make_tray%s tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    def get_tray_title(self) -> str:
        t: list[str] = []
        if self.session_name or self.server_session_name:
            t.append(self.session_name or self.server_session_name)
        ce = self.get_connection_endpoint()
        if ce:
            t.append(ce)
        if not t:
            t.insert(0, "Xpra")
        v = "\n".join(str(x) for x in t if x)
        log("get_tray_title()=%r (items=%s)", v, t)
        return v
