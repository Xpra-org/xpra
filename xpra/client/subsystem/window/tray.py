# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.os_util import OSX
from xpra.util.system import is_Ubuntu
from xpra.util.objects import typedict, make_instance
from xpra.util.env import envint, envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "tray")

DYNAMIC_TRAY_ICON: bool = envbool("XPRA_DYNAMIC_TRAY_ICON", not OSX and not is_Ubuntu())
ICON_OVERLAY: int = envint("XPRA_ICON_OVERLAY", 50)
ICON_SHRINKAGE: int = envint("XPRA_ICON_SHRINKAGE", 75)


class WindowTray(StubClientMixin):

    def __init__(self):
        self.client_supports_system_tray: bool = False

    def init(self, opts) -> None:
        if opts.system_tray:
            try:
                from xpra.client.gui import client_tray
                assert client_tray
            except ImportError:
                log.warn("Warning: the tray forwarding module is missing")
            else:
                self.client_supports_system_tray = True

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        return {
            "system_tray": self.client_supports_system_tray,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        return True

    ######################################################################
    # system tray
    def _process_new_tray(self, packet: Packet) -> None:
        assert self.client_supports_system_tray
        self._ui_event()
        wid = packet.get_wid()
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        w = max(1, self.sx(w))
        h = max(1, self.sy(h))
        metadata = typedict()
        if len(packet) >= 5:
            metadata = typedict(packet.get_dict(4))
        log("tray %#x metadata=%s", wid, metadata)
        if wid in self._id_to_window:
            raise ValueError("we already have a window %#x: %s" % (wid, self.get_window(wid)))
        app_id = wid
        tray = self.setup_system_tray(self, app_id, wid, w, h, metadata)
        log("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid

    def make_system_tray(self, *args):
        """ tray used for application systray forwarding """
        tc = self.get_system_tray_classes()
        log("make_system_tray%s system tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    # noinspection PyMethodMayBeStatic
    def get_system_tray_classes(self) -> list[type]:
        # subclasses may add their toolkit specific variants, if any
        # by overriding this method
        # use the native ones first:
        from xpra.platform.systray import get_forwarding_backends
        return get_forwarding_backends()

    def setup_system_tray(self, client, app_id, wid: int, w: int, h: int, metadata: typedict):
        tray_widget = None

        # this is a tray forwarded for a remote application

        def tray_click(button, pressed, event_time=0):
            tray = self.get_window(wid)
            log("tray_click(%s, %s, %s) tray=%s", button, pressed, event_time, tray)
            if tray:
                x, y = self.get_mouse_position()
                modifiers = self.get_current_modifiers()
                button_packet = ["button-action", wid, button, pressed, (x, y), modifiers]
                log("button_packet=%s", button_packet)
                self.send_positional(*button_packet)
                tray.reconfigure()

        def tray_mouseover(x, y):
            tray = self.get_window(wid)
            log("tray_mouseover(%s, %s) tray=%s", x, y, tray)
            if tray:
                modifiers = self.get_current_modifiers()
                device_id = -1
                self.send_mouse_position(device_id, wid, self.cp(x, y), modifiers)

        def do_tray_geometry(*args):
            # tell the "ClientTray" where it now lives
            # which should also update the location on the server if it has changed
            tray = self.get_window(wid)
            if tray_widget:
                geom = tray_widget.get_geometry()
            else:
                geom = ()
            log("tray_geometry(%s) widget=%s, geometry=%s tray=%s", args, tray_widget, geom, tray)
            if tray and geom:
                tray.move_resize(*geom)

        def tray_geometry(*args):
            # the tray widget may still be None if we haven't returned from make_system_tray yet,
            # in which case we will check the geometry a little bit later:
            if tray_widget:
                do_tray_geometry(*args)
            else:
                self.idle_add(do_tray_geometry, *args)

        def tray_exit(*args):
            log("tray_exit(%s)", args)

        title = metadata.strget("title")
        tray_widget = self.make_system_tray(app_id, None, title, "",
                                            tray_geometry, tray_click, tray_mouseover, tray_exit)
        log("setup_system_tray%s tray_widget=%s", (client, app_id, wid, w, h, title), tray_widget)
        assert tray_widget, "could not instantiate a system tray for tray id %s" % wid
        tray_widget.show()
        from xpra.client.gui.client_tray import ClientTray
        mmap = getattr(self, "mmap_read_area", None)
        return ClientTray(client, wid, w, h, metadata, tray_widget, mmap)

    def get_tray_window(self, app_name: str, hints):
        # try to identify the application tray that generated this notification,
        # so we can show it as coming from the correct systray icon
        # on platforms that support it (ie: win32)
        trays = tuple(w for w in self._id_to_window.values() if w.is_tray())
        if trays:
            try:
                pid = int(hints.get("pid") or 0)
            except (TypeError, ValueError):
                pass
            else:
                if pid:
                    for tray in trays:
                        metadata: typedict = typedict(getattr(tray, "_metadata", {}))
                        if metadata.intget("pid") == pid:
                            log("tray window: matched pid=%i", pid)
                            return tray.tray_widget
            if app_name and app_name.lower() != "xpra":
                # exact match:
                for tray in trays:
                    # log("window %s: is_tray=%s, title=%s", window,
                    #    window.is_tray(), getattr(window, "title", None))
                    if tray.title == app_name:
                        return tray.tray_widget
                for tray in trays:
                    if tray.title.find(app_name) >= 0:
                        return tray.tray_widget
        return self.tray

    def set_tray_icon(self) -> None:
        # find all the window icons,
        # and if they are all using the same one, then use it as tray icon
        # otherwise use the default icon
        log("set_tray_icon() DYNAMIC_TRAY_ICON=%s, tray=%s", DYNAMIC_TRAY_ICON, self.tray)
        if not self.tray:
            return
        if not DYNAMIC_TRAY_ICON:
            # the icon ends up looking garbled on win32,
            # and we somehow also lose the settings that can keep us in the visible systray list
            # so don't bother
            return
        windows = tuple(w for w in self._window_to_id if not w.is_tray())
        # get all the icons:
        icons = tuple(getattr(w, "_current_icon", None) for w in windows)
        missing = sum(1 for icon in icons if icon is None)
        log("set_tray_icon() %i windows, %i icons, %i missing", len(windows), len(icons), missing)
        if icons and not missing:
            icon = icons[0]
            for i in icons[1:]:
                if i != icon:
                    # found a different icon
                    icon = None
                    break
            if icon:
                has_alpha = icon.mode == "RGBA"
                width, height = icon.size
                log("set_tray_icon() using unique %s icon: %ix%i (has-alpha=%s)",
                    icon.mode, width, height, has_alpha)
                rowstride = width * (3 + int(has_alpha))
                rgb_data = icon.tobytes("raw", icon.mode)
                self.tray.set_icon_from_data(rgb_data, has_alpha, width, height, rowstride)
                return
        # this sets the default icon (badly named function!)
        log("set_tray_icon() using default icon")
        self.tray.set_icon()

    def init_authenticated_packet_handlers(self) -> None:
        # still need to be prefixed:
        self.add_packets("new-tray", main_thread=True)
