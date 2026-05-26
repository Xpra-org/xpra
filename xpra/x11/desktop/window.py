# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.subsystem.window import WindowServer
from xpra.util.objects import typedict
from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_CREATE
from xpra.log import Logger

log = Logger("server")
windowlog = Logger("server", "window")
geomlog = Logger("server", "window", "geometry")
metadatalog = Logger("x11", "metadata")


class DesktopWindowServer(WindowServer):
    """
    Window subsystem for the X11 `desktop` / `monitor` servers.

    Desktop servers expose a fixed virtual monitor (or a set of them) as
    the windows seen by clients. There is no X11 window manager involved
    and no compositing - the variant feeds in capture-style window models
    via `load_existing_windows`. This subsystem owns the packet handlers
    and the variant-specific window lifecycle.
    """

    def load_existing_windows(self) -> None:
        # the variant (xpra.x11.desktop.desktop_server / monitor_server)
        # populates window models via its own `load_existing_windows`
        # override on the SERVER class. This stub stays here for safety.
        raise NotImplementedError

    def send_initial_windows(self, ss, sharing: bool = False) -> None:
        models = self.models()
        windowlog("send_initial_windows(%s, %s) will send: %s", ss, sharing, models)
        for model in models:
            self.send_new_desktop_model(model, ss, sharing)

    def send_new_desktop_model(self, model, ss, _sharing: bool = False) -> None:
        x, y, w, h = model.get_geometry()
        wid = self._window_to_id[model]
        wprops = self.client_properties.get(wid, {}).get(ss.uuid, {})
        ss.new_window(WINDOW_CREATE, wid, model, x, y, w, h, wprops)
        ss.damage(wid, model, 0, 0, w, h)

    def rfb_sources(self, exclude=None) -> tuple:
        try:
            from xpra.server.rfb.source import RFBSource
        except ImportError:
            return ()
        return self.get_sources_by_type(RFBSource, exclude=exclude)

    def refresh_window_area(self, window, x, y, width, height, options=None) -> None:
        super().refresh_window_area(window, x, y, width, height, options)
        wid = self._window_to_id[window]
        for ss in self.rfb_sources():
            ss.damage(wid, window, x, y, width, height, options)

    def _lost_window(self, window, wm_exiting=False) -> None:
        """ could be used to slow down the refresh rate? """

    def _contents_changed(self, window, event) -> None:
        log("contents changed on %s: %s", window, event)
        self.refresh_window_area(window, event.x, event.y, event.width, event.height)

    def _set_window_state(self, proto, wid: int, window, new_window_state: dict) -> list[str]:
        if not new_window_state:
            return []
        metadatalog("set_window_state%s", (proto, wid, window, new_window_state))
        changes = []
        # boolean: but not a wm_state and renamed in the model (iconic vs iconified)
        iconified = new_window_state.get("iconified")
        if iconified is not None and window._updateprop("iconic", iconified):
            changes.append("iconified")
        focused = new_window_state.get("focused")
        if focused is not None and window._updateprop("focused", focused):
            changes.append("focused")
        return changes

    @staticmethod
    def get_window_position(_window) -> tuple[int, int]:
        # the desktop window is exported as a whole-screen window
        return 0, 0

    def _process_window_map(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        window = self.get_window(wid)
        if not window:
            windowlog("cannot map window %s: already removed!", wid)
            return
        geomlog("client mapped window %s - %s, at: %s", wid, window, (x, y, w, h))
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        if len(packet) >= 8:
            state = packet.get_dict(7)
            self._set_window_state(proto, wid, window, state)
        if len(packet) >= 7:
            props = packet.get_dict(6)
            self._set_client_properties(proto, wid, window, props)
        self.refresh_window_area(window, 0, 0, w, h)

    def _process_window_unmap(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        if len(packet) >= 4:
            # optional window_state added in 0.15 to update flags
            # during iconification events:
            state = packet.get_dict(3)
            self._set_window_state(proto, wid, window, state)
        assert not window.is_OR()
        self._window_mapped_at(proto, wid, window)
        # TODO: handle iconification?

    def do_process_window_configure(self, proto, wid, config: typedict) -> None:
        window = self.get_window(wid)
        if not window:
            geomlog("cannot configure window %s: already removed!", wid)
            return

        pointer = self.get_subsystem("pointer")
        if pointer and "pointer" in config and not self.server.readonly:
            pointer_data = typedict(config.dictget("pointer"))
            pwid = pointer_data.intget("wid", 0)
            position = pointer_data.inttupleget("position")
            device_id = pointer_data.intget("device-id")
            if pointer.process_mouse_common(proto, device_id, pwid, position):
                if "modifiers" in pointer_data:
                    modifiers = pointer_data.strtupleget("modifiers")
                    pointer._update_modifiers(proto, pwid, modifiers)

        if "state" in config:
            state = config.dictget("state")
            self._set_window_state(proto, wid, window, state)

        geometry = config.inttupleget("geometry")
        if geometry:
            self._window_mapped_at(proto, wid, window, geometry)
            if not self.server.readonly:
                w, h = geometry[2:4]
                oww, owh = window.get_geometry()[2:4]
                geomlog("do_process_window_configure size was: %s, now %s", (oww, owh), (w, h))
                if oww != w or owh != h:
                    window.resize(w, h)

        properties = config.dictget("properties")
        if properties:
            metadatalog("window client properties updates: %s", properties)
            self._set_client_properties(proto, wid, window, properties)

        if "state" in config:
            w, h = window.get_geometry()[2:4]
            self.refresh_window_area(window, 0, 0, w, h)

    def _process_window_close(self, proto, packet: Packet) -> None:
        # disconnect?
        pass

    def calculate_workarea(self, w: int, h: int):
        """
        The workarea is managed server-side by the window manager,
        so we don't need to apply any changes here.
        """


class XpraDesktopWindowServer(DesktopWindowServer):
    """
    Window subsystem for the `desktop` server: a single full-screen
    monitor model backed by the X11 root window.
    """

    def load_existing_windows(self) -> None:
        from xpra.x11.error import xsync
        from xpra.x11.desktop.desktop_model import ScreenDesktopModel
        display = self.get_subsystem("display")
        randr = getattr(display, "randr", False)
        randr_exact_size = getattr(display, "randr_exact_size", False)
        with xsync:
            model = ScreenDesktopModel(randr, randr_exact_size)
            model.setup()
            log("adding root window model %s", model)
            self.do_add_new_window_common(1, model)
            model.managed_connect("client-contents-changed", self._contents_changed)
            model.managed_connect("resized", self.send_updated_screen_size)
            pointer = self.get_subsystem("pointer")
            if pointer:
                model.managed_connect("motion", pointer._motion_signaled)

    def send_updated_screen_size(self, model) -> None:
        # the vfb has been resized
        wid = self._window_to_id[model]
        x, y, w, h = model.get_geometry()
        geomlog("send_updated_screen_size(%s) geometry=%s", model, (x, y, w, h))
        for ss in self.window_sources():
            ss.resize_window(wid, model, w, h)
            ss.damage(wid, model, 0, 0, w, h)
        if display := self.get_subsystem("display"):
            display.emit("display-geometry-changed")


class MonitorWindowServer(DesktopWindowServer):
    """
    Window subsystem for the `monitor` server: each X11 RandR monitor is
    a separate window model. The variant server (`XpraMonitorServer`)
    still owns the RandR event listening and reconfiguration code; this
    subsystem owns the model lifecycle and the related callbacks.
    """

    def load_existing_windows(self) -> None:
        from xpra.x11.error import xlog
        from xpra.x11.bindings.randr import RandRBindings
        with xlog:
            monitors = RandRBindings().get_monitor_properties()
            log("load_existing_windows() found monitors=%r", monitors)
            for i, monitor in monitors.items():
                self.add_monitor_model(i + 1, monitor)

    def add_monitor_model(self, wid: int, monitor: dict[str, Any]):
        from xpra.x11.desktop.monitor_model import MonitorDesktopModel
        log("add_monitor_model(%i, %r)", wid, monitor)
        model = MonitorDesktopModel(monitor)
        model.setup()
        log("adding monitor model %s", model)
        self.do_add_new_window_common(wid, model)
        model.managed_connect("client-contents-changed", self._contents_changed)
        model.managed_connect("resized", self.monitor_resized)
        pointer = self.get_subsystem("pointer")
        if pointer:
            model.managed_connect("motion", pointer._motion_signaled)
        return model

    def monitor_resized(self, model) -> None:
        # delegated to the variant server, which owns the reconfigure
        # state machine and the RandR adjustments.
        self.server.monitor_resized(model)
