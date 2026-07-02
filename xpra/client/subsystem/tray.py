# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#  pylint: disable-msg=E1101

from xpra.platform.systray import get_backends
from xpra.os_util import WIN32, OSX
from xpra.util.objects import make_instance
from xpra.util.env import envint, envbool
from xpra.net.constants import ConnectionMessage
from xpra.constants import XPRA_APP_ID
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("tray")

USE_NATIVE_TRAY = envbool("XPRA_USE_NATIVE_TRAY", True)
TRAY_DELAY = envint("XPRA_TRAY_DELAY", 0)


class TrayClient(StubClientMixin):
    """
    Mixin for supporting our system tray
    (not forwarding other application's trays - that's handled in WindowClient)
    """
    PREFIX = "tray"

    def __init__(self):
        # settings:
        self.icon = None
        # state:
        self.tray = None
        self.delay = False

    def init(self, opts) -> None:
        if not opts.tray:
            return
        self.delay = opts.delay_tray
        self.icon = opts.tray_icon

    def load(self):
        # the menu helper is a toolkit-specific client service (see `get_menu_helper`
        # on the concrete client); the tray is one of its consumers:
        self.client.get_menu_helper()
        if self.delay:
            self.client.connect("first-ui-received", self.setup_xpra_tray)
        else:
            if WIN32 or OSX:
                # show shortly after the main loop starts running:
                self.timeout_add(TRAY_DELAY, self.setup_xpra_tray)
            else:
                # wait for handshake:
                # see appindicator bug #3956
                self.client.after_handshake(self.setup_xpra_tray)

    def setup_xpra_tray(self, *args) -> None:
        log("setup_xpra_tray%s", args)
        tray = self.create_xpra_tray(self.icon or "xpra")
        self.tray = tray
        if not tray:
            return
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

        self.timeout_add(1000, reset_icon)

        def tray_ready(*_args) -> None:
            tray.ready()
        self.client.connect("startup-complete", tray_ready)

    def cleanup(self) -> None:
        if t := self.tray:
            self.tray = None
            with log.trap_error("Error during tray cleanup"):
                t.cleanup()

    def reset_tray_icon(self) -> None:
        tray = self.tray
        if not tray:
            return
        tray.set_icon(None)  # None means back to default icon
        tray.set_tooltip(self.get_tray_title())
        tray.set_blinking(False)

    @staticmethod
    def get_native_tray_classes() -> list[type]:
        # the concrete client's `get_tray_classes` composes these with its
        # toolkit specific variants, if any (e.g. gtk3 adds the StatusIcon tray)
        # use the native ones first:
        if not USE_NATIVE_TRAY:
            return []
        return get_backends()

    def create_xpra_tray(self, tray_icon_filename: str):
        tray = None

        # this is our own tray

        def xpra_tray_click(button, pressed, time=0):
            log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
            mh = self.client.get_menu_helper()
            if button == 1 and pressed:
                self.idle_add(mh.activate, button, time)
            elif button in (2, 3) and not pressed:
                self.idle_add(mh.popup, button, time)

        def xpra_tray_mouseover(*args):
            log("xpra_tray_mouseover%s", args)

        def xpra_tray_exit(*args):
            log("xpra_tray_exit%s", args)
            self.client.disconnect_and_quit(0, ConnectionMessage.CLIENT_EXIT)

        def xpra_tray_geometry(*args):
            if tray:
                log("xpra_tray_geometry%s geometry=%s", args, tray.get_geometry())

        mh = self.client.get_menu_helper()
        menu = mh.build() if mh else None
        tray = self.make_tray(XPRA_APP_ID, menu, self.get_tray_title(), tray_icon_filename,
                              xpra_tray_geometry, xpra_tray_click, xpra_tray_mouseover, xpra_tray_exit)
        log("setup_xpra_tray(%s)=%s (%s)", tray_icon_filename, tray, type(tray))
        if tray:
            def reset_tray_title() -> None:
                tray.set_tooltip(self.get_tray_title())

            self.client.after_handshake(reset_tray_title)
        return tray

    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.client.get_tray_classes()
        log("make_tray%s tray classes=%s", args, tc)
        return make_instance(tc, self.client, *args)

    def get_tray_title(self) -> str:
        t: list[str] = []
        if self.client.session_name or self.client.server_session_name:
            t.append(self.client.session_name or self.client.server_session_name)
        if ce := self.client.get_connection_endpoint():
            t.append(ce)
        if not t:
            t.insert(0, "Xpra")
        v = "\n".join(str(x) for x in t if x)
        log("get_tray_title()=%r (items=%s)", v, t)
        return v
