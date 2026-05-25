# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import signal
import sys
from time import monotonic
from collections import deque
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.server.subsystem.window import WindowServer
from xpra.server.source.window import WindowsConnection
from xpra.util.objects import typedict
from xpra.util.env import envbool, envint
from xpra.common import noop
from xpra.constants import WORKSPACE_NAMES
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import WINDOW_CREATE, WINDOW_METADATA
from xpra.server import features
from xpra.x11.common import Unmanageable, X11Event
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.error import xsync, xswallow, xlog, XError
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "window")
focuslog = Logger("server", "focus")
grablog = Logger("server", "grab")
geomlog = Logger("server", "window", "geometry")
traylog = Logger("server", "tray")
metadatalog = Logger("x11", "metadata")
pointerlog = Logger("x11", "pointer")
windowlog = Logger("server", "window")
workspacelog = Logger("x11", "workspace")
framelog = Logger("x11", "frame")

CONFIGURE_DAMAGE_RATE = envint("XPRA_CONFIGURE_DAMAGE_RATE", 250)
SHARING_SYNC_SIZE = envbool("XPRA_SHARING_SYNC_SIZE", True)
CLAMP_WINDOW_TO_ROOT = envbool("XPRA_CLAMP_WINDOW_TO_ROOT", False)
ALWAYS_RAISE_WINDOW = envbool("XPRA_ALWAYS_RAISE_WINDOW", False)
PRE_MAP = envbool("XPRA_PRE_MAP_WINDOWS", True)

WINDOW_SIGNALS = os.environ.get(
    "XPRA_WINDOW_SIGNALS",
    "SIGINT,SIGTERM,SIGQUIT,SIGCONT,SIGUSR1,SIGUSR2",
).split(",")


def rindex(alist, avalue) -> int:
    return len(alist) - alist[::-1].index(avalue) - 1


def clamp_window(x: int, y: int, w: int, h: int):
    if not CLAMP_WINDOW_TO_ROOT:
        return False, (x, y, w, h)
    with xsync:
        rw, rh = X11WindowBindings().get_root_size()
    # clamp to root window size
    mod = False
    if x + w < 0:
        x = 0
        mod = True
    elif x >= rw:
        x = max(0, min(x, rw - w))
        mod = True
    if y + h < 0:
        y = 0
        mod = True
    elif y >= rh:
        y = max(0, min(y, rh - h))
        mod = True
    return mod, (x, y, w, h)


class SeamlessWindowServer(WindowServer):
    """
    X11 seamless window subsystem.

    Owns the connection to the window manager (`Wm`), all per-window
    state, packet handlers, and the WM signal callbacks. The seamless
    variant server (`xpra.x11.server.seamless.SeamlessServer`) wires up
    the GObject signals and the root overlay rendering, but everything
    that touches actual window models and packet dispatch lives here.
    """

    def __init__(self, server=None):
        WindowServer.__init__(self, server)
        self._wm = None
        self.wm_name = ""
        self._focus_history: deque[int] = deque(maxlen=100)
        self._has_grab = 0
        self._has_focus = 0
        self.last_raised = None
        self._exit_with_windows = False
        self.configure_damage_timers: dict[int, int] = {}
        self.snc_timer = 0

    def init(self, opts) -> None:
        super().init(opts)
        self.wm_name = opts.wm_name
        self._exit_with_windows = opts.exit_with_windows

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("window-signal", main_thread=True)

    def clamp_windows_to_screen(self, screen_w: int, screen_h: int) -> None:
        """
        Clamp every non-tray, non-OR window so its `client-geometry`
        stays within the screen bounds after a resize. Only relevant in
        seamless mode: desktop/monitor/shadow window models don't carry
        a `client-geometry` property.
        """
        for window in self._id_to_window.values():
            if window.is_tray() or window.is_OR():
                continue
            cg = window.get_property("client-geometry")
            if not cg:
                continue
            x, y, w, h = cg
            if x >= screen_w or y >= screen_h:
                x = min(x, screen_w - 64)
                y = min(y, screen_h - 64)
                geomlog("clamped window %s", window)
                window.set_property("client-geometry", (x, y, w, h))

    # --------------------------------------------------------------------
    # WM lifecycle - the seamless server creates the `Wm` instance, calls
    # `init_wm` once it has the X11 connection ready (see SeamlessServer.setup)
    # --------------------------------------------------------------------

    def get_wid(self, model) -> int:
        # reverse lookup: window model -> window id. Returns -1 if the
        # model is not registered.
        return self._window_to_id.get(model, -1)

    def load_existing_windows(self) -> None:
        log(f"load_existing_windows() wm={self._wm}")
        if not self._wm:
            return

        windows = self._wm.get_windows()
        log(f"found {len(windows)} windows: {windows}")
        for window in windows:
            self._add_new_window(window)

        X11Window = X11WindowBindings()
        try:
            with xsync:
                rxid = get_root_xid()
                children = X11Window.get_children(rxid)
        except XError:
            log("load_existing_windows()", exc_info=True)
            log("trying again")
            with xsync:
                children = X11Window.get_children(rxid)
        for xid in children:
            can_add = False
            with xlog:
                can_add = X11Window.is_override_redirect(xid) and X11Window.is_mapped(xid)
            if can_add:
                self._add_new_or_window(xid)
        # from now on, new windows will trigger this callback:
        self._wm.connect("new-window", self._new_window_signaled)

    def update_size_constraints(self, minw: int, minh: int, maxw: int, maxh: int) -> None:
        if wm := self._wm:
            wm.set_size_constraints(minw, minh, maxw, maxh)
        elif features.window:
            # update the static default so the Wm instance will use it
            # when we do instantiate it:
            from xpra.constants import MAX_WINDOW_SIZE
            from xpra.x11 import wm as wm_module
            wm_module.DEFAULT_SIZE_CONSTRAINTS = (0, 0, MAX_WINDOW_SIZE, MAX_WINDOW_SIZE)

    def parse_hello_ui_window_settings(self, ss, _caps) -> None:
        # FIXME: with multiple users, don't set any frame size?
        frame = None
        if ss in self.window_sources():
            window_frame_sizes = ss.window_frame_sizes
            framelog("parse_hello_ui_window_settings: client window_frame_sizes=%s", window_frame_sizes)
            if window_frame_sizes:
                frame = typedict(window_frame_sizes).inttupleget("frame", (0, 0, 0, 0), 4, 4)
        if self._wm:
            self._wm.set_default_frame_extents(frame)

    # --------------------------------------------------------------------
    # window discovery / lifecycle
    # --------------------------------------------------------------------

    def _new_window_signaled(self, _wm, window) -> None:
        self.last_raised = None
        self._add_new_window(window)

    def do_x11_child_map_event(self, event: X11Event) -> None:
        windowlog("do_x11_child_map_event(%s)", event)
        if event.override_redirect:
            self._add_new_or_window(event.window)

    def _add_new_window_common(self, window) -> int:
        windowlog("adding window %s", window)
        wid = super()._add_new_window_common(window)
        window.managed_connect("client-contents-changed", self._contents_changed)
        window.managed_connect("unmanaged", self._lost_window)
        window.managed_connect("grab", self._window_grab)
        window.managed_connect("ungrab", self._window_ungrab)
        bell = self.get_subsystem("bell")
        if bell:
            window.managed_connect("bell", bell._bell_signaled)
        pointer = self.get_subsystem("pointer")
        if pointer:
            window.managed_connect("motion", pointer._motion_signaled)
        window.managed_connect("x11-property-changed", self._x11_property_changed)
        if not window.is_tray():
            window.managed_connect("restack", self._restack_window)
            window.managed_connect("initiate-moveresize", self._initiate_moveresize)
        return wid

    def _x11_property_changed(self, window, event) -> None:
        # name, dtype, dformat, value = event
        metadata = {"x11-property": event}
        wid = self.get_wid(window)
        if wid < 0:
            return
        for ss in self.window_sources():
            ms = getattr(ss, "window_metadata_supported", ())
            if "x11-property" in ms:
                ss.send(WINDOW_METADATA, wid, metadata)

    def allocate_wid(self, window) -> int:
        if "xid" in window.get_property_names():
            return window.get_property("xid")
        return super().allocate_wid(window)

    def _add_new_window(self, window) -> None:
        wid = self._add_new_window_common(window)
        geometry = window.get_property("geometry")
        log("Discovered new ordinary window: %s (geometry=%s)", window, geometry)
        window.managed_connect("notify::geometry", self._window_resized_signaled)
        self._send_new_window_packet(window)
        if PRE_MAP:
            # pre-map the window if any client will be showing it
            window_sources = self.get_sources_by_type(WindowsConnection)
            if window_sources:
                log("pre-mapping window %#x for %s at %s", wid, window_sources, geometry)
                geometry = clamp_window(*geometry)[1]
                self.client_configure_window(window, geometry)
                window.show()
                for s in window_sources:
                    s.map_window(wid, window, geometry)
                self.schedule_configure_damage(wid, 0)

    def _window_resized_signaled(self, window, *args) -> None:
        x, y, nw, nh = window.get_property("geometry")[:4]
        geom = window.get_property("client-geometry")
        geomlog("XpraServer._window_resized_signaled(%s,%s) geometry=%s, desktop manager geometry=%s",
                window, args, (x, y, nw, nh), geom)
        if geom == [x, y, nw, nh]:
            geomlog("XpraServer._window_resized_signaled: unchanged")
            return
        window.set_property("client-geometry", (x, y, nw, nh))
        if not window.get_property("shown"):
            self.size_notify_clients(window)
            return
        if self.snc_timer > 0:
            GLib.source_remove(self.snc_timer)
        # TODO: find a better way to choose the timer delay
        lcce = self.get_window_configure_time_time()
        delay = max(100, min(250, 250 + round(1000 * (lcce - monotonic()))))
        self.snc_timer = GLib.timeout_add(int(delay), self.size_notify_clients, window, lcce)

    def get_window_configure_time_time(self) -> float:
        lcce = 0.0
        for source in self.get_sources_by_type(WindowsConnection):
            lcce = max(lcce, source.window_configure_time)
        return lcce

    def size_notify_clients(self, window, last_lcce=-1) -> None:
        geomlog("size_notify_clients(%s, %s)", window, last_lcce)
        self.snc_timer = 0
        wid = self.get_wid(window)
        if wid < 0:
            geomlog("size_notify_clients: window is gone")
            return
        x, y, nw, nh = window.get_property("client-geometry")
        resize_counter = window.get_property("resize-counter")
        for ss in self.window_sources():
            lcce = getattr(ss, "window_configure_time", 0.0)
            if 0 < last_lcce < lcce:
                geomlog("size_notify_clients: we have received a new client resize since")
                geomlog(" last-configure-events: system=%s, %s=%s", last_lcce, ss, lcce)
                return
            geomlog("size_notify_clients: sending to %s", ss)
            ss.move_resize_window(wid, window, x, y, nw, nh, resize_counter)
            ss.damage(wid, window, 0, 0, nw, nh)

    def _add_new_or_window(self, xid: int) -> None:
        log("_add_new_or_window(%#x)", xid)
        root_overlay = self.get_subsystem("root-overlay")
        if root_overlay and root_overlay.is_overlay_window(xid):
            windowlog("ignoring root overlay window %#x", xid)
            return
        Gdk = sys.modules.get("gi.repository.Gdk")
        if Gdk:
            from xpra.x11.common import get_pywindow
            gdk_window = get_pywindow(xid)
            if not gdk_window or gdk_window.get_window_type() == Gdk.WindowType.TEMP:
                windowlog("ignoring TEMP window %#x", xid)
                return
        if window := self.get_window(xid):
            if window.is_managed():
                windowlog("found existing window model %s for %#x, will refresh it", type(window), xid)
                ww, wh = window.get_dimensions()
                self.refresh_window_area(window, 0, 0, ww, wh, options={"min_delay": 50})
                return
            windowlog("found existing model %s (but no longer managed!) for %#x", type(window), xid)
            self._lost_window(window)
        try:
            with xsync:
                geom = X11WindowBindings().getGeometry(xid)
                if not geom:
                    windowlog(f"Window {xid:x} vanished")
                    return
                windowlog("Discovered new override-redirect window: %#x X11 geometry=%s", xid, geom)
        except Exception as e:
            windowlog("Window error (vanished already?): %s", e)
            return
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.x11.tray import get_tray_window
            tray_xid: int = get_tray_window(xid)
            if tray_xid:
                tray_subsystem = self.get_subsystem("systray")
                assert tray_subsystem
                from xpra.x11.models.systray import SystemTrayWindowModel
                window = SystemTrayWindowModel(tray_xid, xid)
                wid = self._add_new_window_common(window)
                window.call_setup()
                self._send_new_tray_window_packet(wid, window)
            else:
                from xpra.x11.models.or_window import OverrideRedirectWindowModel
                window = OverrideRedirectWindowModel(xid)
                self._add_new_window_common(window)
                window.call_setup()
                window.managed_connect("notify::geometry", self._or_window_geometry_changed)
                packet_type = "new-override-redirect" if BACKWARDS_COMPATIBLE else "window-create"
                self._do_send_new_window_packet(packet_type, window, window.get_property("geometry"))
                self.refresh_window(window)
        except Unmanageable as e:
            if window:
                windowlog("window %s is not manageable: %s", window, e)
                window.setup_failed(e)
                if self.get_wid(window) >= 0:
                    self._lost_window(window, False)
            else:
                windowlog.warn("cannot add window %#x: %s", xid, e)

    def _or_window_geometry_changed(self, window, _pspec=None) -> None:
        geom = window.get_property("geometry")
        x, y, w, h = geom
        if w >= 32768 or h >= 32768:
            geomlog.error("not sending new invalid window dimensions: %ix%i !", w, h)
            return
        geomlog("or_window_geometry_changed: %s (window=%s)", geom, window)
        wid = self.get_wid(window)
        for ss in self.window_sources():
            ss.or_window_geometry(wid, window, x, y, w, h)

    def _show_desktop(self, wm, show) -> None:
        log("show_desktop(%s, %s)", wm, show)
        for ss in self.window_sources():
            ss.show_desktop(show)

    # --------------------------------------------------------------------
    # focus
    # --------------------------------------------------------------------

    def _focus(self, server_source, wid: int, modifiers) -> None:
        focuslog("focus wid=%#x has_focus=%#x", wid, self._has_focus)
        if self.last_raised != wid:
            self.last_raised = None
        if self._has_focus == wid:
            return
        self._focus_history.append(wid)
        hfid = self._has_focus
        had_focus = self.get_window(hfid)

        def reset_focus() -> None:
            focuslog("reset_focus() %#x / %s had focus", hfid, had_focus)
            keyboard = self.get_subsystem("keyboard")
            clear_keys_pressed: Callable[[], None] = getattr(keyboard, "clear_keys_pressed", noop)
            clear_keys_pressed()
            self._has_focus = 0

        if wid == 0:
            reset_focus()
            return
        window = self.get_window(wid)
        if not window:
            reset_focus()
            return
        if window.is_OR():
            focuslog("cannot focus OR window: %s", window)
            return
        if not window.is_managed():
            focuslog.warn("Warning: window %s is no longer managed!", window)
            return
        focuslog("focus: giving focus to %s", window)
        with xswallow:
            self.last_raised = wid
            window.raise_window()
            window.give_client_focus()
        if server_source and modifiers is not None:
            make_keymask_match = getattr(server_source, "make_keymask_match", noop)
            focuslog("focus: will set modifier mask to %s using %s", modifiers, make_keymask_match)
            make_keymask_match(modifiers)
        self._has_focus = wid

    def get_focus(self) -> int:
        return self._has_focus

    def _send_new_window_packet(self, window) -> None:
        self._do_send_new_window_packet(WINDOW_CREATE, window, window.get_property("geometry"))

    def _send_new_tray_window_packet(self, wid: int, window) -> None:
        ww, wh = window.get_dimensions()
        for ss in self.window_sources():
            ss.new_tray(wid, window, ww, wh)
        self.refresh_window(window)

    def _lost_window(self, window, wm_exiting=False) -> None:
        wid = self._remove_window(window)
        self.cancel_configure_damage(wid)
        if self._exit_with_windows and not self.models():
            log.info("no more windows to manage, exiting")
            self.server.clean_quit()
        elif not wm_exiting:
            self.repaint_root_overlay()

    def _contents_changed(self, window, event) -> None:
        if window.is_OR() or window.is_tray() or window.get_property("shown"):
            options = {"damage": True}
            if getattr(event, "more", False):
                options["more"] = True
            self.refresh_window_area(window, event.x, event.y, event.width, event.height, options=options)

    def _window_grab(self, window, event) -> None:
        grab_id = self.get_wid(window)
        grablog("window_grab(%s, %s) has_grab=%#x, has focus=%#x, grab window=%s",
                window, event, self._has_grab, self._has_focus, grab_id)
        if grab_id < 0 or self._has_grab == grab_id:
            return
        self._has_grab = grab_id
        for ss in self.window_sources():
            ss.pointer_grab(self._has_grab)

    def _window_ungrab(self, window, event) -> None:
        grab_id = self.get_wid(window)
        grablog("window_ungrab(%s, %s) has_grab=%#x, has focus=%#x, grab window=%s",
                window, event, self._has_grab, self._has_focus, grab_id)
        if not self._has_grab:
            return
        self._has_grab = 0
        for ss in self.window_sources():
            ss.pointer_ungrab(grab_id)

    def _initiate_moveresize(self, window, event) -> None:
        geomlog("initiate_moveresize(%s, %s)", window, event)
        assert len(event.data) == 5
        wid = self.get_wid(window)
        wsources = self.window_sources()
        if not wsources:
            return
        driversources = [ss for ss in wsources if self.server.ui_driver == ss.uuid]
        source = driversources[0] if driversources else wsources[0]
        source.initiate_moveresize(wid, window, *event.data)

    def _restack_window(self, window, detail, sibling) -> None:
        wid = self.get_wid(window)
        focuslog("restack window(%s) wid=%#x, current focus=%s", (window, detail, sibling), wid, self._has_focus)
        if self.last_raised != wid:
            self.last_raised = None
        if detail == 0 and self._has_focus == wid:
            return
        for ss in self.window_sources():
            ss.restack_window(wid, window, detail, sibling)

    def _set_window_state(self, proto, wid: int, window, new_window_state: dict) -> Sequence[str]:
        if not new_window_state:
            return ()
        nws = typedict(new_window_state)
        metadatalog("set_window_state%s", (wid, window, new_window_state))
        changes: dict[str, Any] = {}
        if "frame" in new_window_state:
            frame = nws.inttupleget("frame", (0, 0, 0, 0))
            window.set_property("frame", frame)
        if "iconified" in new_window_state:
            iconified = nws.boolget("iconified")
            if window.is_OR():
                log("ignoring iconified=%s on OR window %s", iconified, window)
            else:
                if window.get_property("iconic") != bool(iconified):
                    window.set_property("iconic", iconified)
                    changes["iconified"] = bool(iconified)
        for k in (
                "maximized", "above",
                "below", "fullscreen",
                "sticky", "shaded",
                "skip-pager", "skip-taskbar", "focused",
        ):
            if k not in nws:
                continue
            new_state = nws.boolget(k)
            cur_state = bool(window.get_property(k))
            if cur_state != new_state:
                window.update_wm_state(k, new_state)
                changes[k] = new_state
        metadatalog("set_window_state: changes=%s", changes)
        return tuple(changes.keys())

    @staticmethod
    def get_window_position(window) -> tuple[int, int] | None:
        if window is None or window.is_OR() or window.is_tray():
            return None
        pos = window.get_property("client-geometry")
        if not pos:
            pos = window.get_property("geometry")
            if not pos:
                return None
        return pos[0], pos[1]

    @staticmethod
    def client_configure_window(win, geometry, resize_counter: int = 0) -> None:
        log("client_configure_window(%s, %s, %s)", win, geometry, resize_counter)
        old_geom = win.get_property("client-geometry")
        update_geometry = geometry != old_geom
        if update_geometry:
            counter = win.get_property("resize-counter")
            if 0 < resize_counter < counter:
                log("resize ignored: counter %s vs %s", resize_counter, counter)
                update_geometry = False
            else:
                win.set_property("client-geometry", geometry)
        if not win.get_property("shown"):
            win.show()
            return
        if update_geometry:
            win._update_client_geometry()

    def get_info(self, proto) -> dict[str, Any]:
        info = super().get_info(proto)
        info.setdefault("window", {}).update({
            "focused": self._has_focus,
            "grabbed": self._has_grab,
        })
        return info

    def get_window_info(self, window) -> dict[str, Any]:
        info = super().get_window_info(window)
        info |= {
            "focused": bool(self._has_focus and self.get_wid(window) == self._has_focus),
            "grabbed": bool(self._has_grab and self.get_wid(window) == self._has_grab),
        }
        if not (window.is_OR() or window.is_tray()):
            info["shown"] = window.get_property("shown")
        return info

    # --------------------------------------------------------------------
    # packet handlers
    # --------------------------------------------------------------------

    def _process_window_map(self, proto, packet: Packet) -> None:
        if not (ss := self.get_server_source(proto)):
            return  # should not happen
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        window = self.get_window(wid)
        if not window:
            windowlog("cannot map window %#x: not found, already removed?", wid)
            return
        if window.is_OR():
            windowlog.warn("Warning: received map event on OR window %s", wid)
            return
        geomlog("client %s mapped window %#x - %s, at: %s", ss, wid, window, (x, y, w, h))
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        cp = {}
        if len(packet) >= 7:
            cp = packet.get_dict(6)
        cp["event"] = "map"
        self._set_client_properties(proto, wid, window, cp)
        if not self.server.ui_driver:
            self.server.set_ui_driver(ss)
        if self.server.ui_driver == ss.uuid or not window.get_property("shown"):
            if len(packet) >= 8:
                state = packet.get_dict(7)
                self._set_window_state(proto, wid, window, state)
            geometry = self.client_clamp_window(proto, wid, window, x, y, w, h)
            self.client_configure_window(window, geometry)
        self.refresh_window_area(window, 0, 0, w, h)

    def _process_window_unmap(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        if not window:
            log("cannot unmap window %#x: not found, already removed?", wid)
            return
        assert not window.is_OR()
        ss = self.get_server_source(proto)
        if ss is None:
            return
        self._window_mapped_at(proto, wid, window)
        if len(packet) >= 4:
            state = packet.get_dict(3)
            self._set_window_state(proto, wid, window, state)
        if window.get_property("shown"):
            geomlog("client %s unmapped window %#x - %s", ss, wid, window)
            for ss in self.window_sources():
                ss.unmap_window(wid, window)
            window.unmap()
            iconified = len(packet) >= 3 and packet.get_bool(2)
            if iconified and not window.get_property("iconic"):
                window.set_property("iconic", True)
            window.hide()
            self.repaint_root_overlay()

    def client_clamp_window(self, proto, wid: int, window, x: int, y: int, w: int, h: int, resize_counter: int = 0):
        if not CLAMP_WINDOW_TO_ROOT:
            return x, y, w, h
        mod, geom = clamp_window(x, y, w, h)
        if mod:
            if ss := self.get_server_source(proto):
                resize_counter = max(resize_counter, window.get_property("resize-counter"))
                x, y, w, h = geom
                ss.move_resize_window(wid, window, x, y, w, h, resize_counter)
        return geom

    def do_process_window_configure(self, proto, wid, config: typedict) -> None:
        window = self.get_window(wid)
        if not window:
            geomlog("cannot configure window %#x: not found, already removed?", wid)
            return
        ss = self.get_server_source(proto)
        if not ss:
            return

        if not self.server.ui_driver and config.boolget("drive", True):
            self.server.set_ui_driver(ss)
        is_ui_driver = self.server.ui_driver == ss.uuid

        properties = config.dictget("properties")
        if properties:
            metadatalog("window client properties updates: %s", properties)
            self._set_client_properties(proto, wid, window, properties)

        geometry = config.inttupleget("geometry")
        if geometry:
            geomlog("window %i at %s for %s", wid, geometry, proto)
            self._window_mapped_at(proto, wid, window, geometry)

        if "pointer" in config and is_ui_driver and features.pointer and not self.server.readonly:
            pointer_data = typedict(config.dictget("pointer"))
            pointerlog("configure pointer data: %s", pointer_data)
            pwid = pointer_data.intget("wid", 0)
            position = pointer_data.inttupleget("position")
            device_id = pointer_data.intget("device-id")
            if pwid == wid and window.is_OR():
                pwid = 0
            pointer = self.get_subsystem("pointer")
            if pointer and pointer.process_mouse_common(proto, device_id, pwid, position):
                if self._has_focus == pwid and "modifiers" in pointer_data:
                    modifiers = pointer_data.strtupleget("modifiers")
                    pointer._update_modifiers(proto, pwid, modifiers)

        if window.is_tray():
            if geometry and is_ui_driver and not self.server.readonly:
                traylog(f"systray {window} configured to: %s", geometry)
                with xlog:
                    window.move_resize(*geometry)
            self.schedule_configure_damage(wid)
            return

        if "state" in config and is_ui_driver:
            state = config.dictget("state")
            self._set_window_state(proto, wid, window, state)

        if geometry and not window.is_OR() and not self.server.readonly:
            damage = not window.get_property("shown")

            x, y, w, h = geometry
            ocg = window.get_property("client-geometry") or ()
            resize_counter = config.intget("resize-counter", 0)
            geomlog("new geometry: %s", geometry)
            geometry = self.client_clamp_window(proto, wid, window, x, y, w, h, resize_counter)
            self.client_configure_window(window, geometry, resize_counter)
            ncg = window.get_property("client-geometry") or ()
            if ocg != ncg:
                ss.window_configure_time = monotonic()
                self.repaint_root_overlay()
                if ocg[2:4] != ncg[2:4] and SHARING_SYNC_SIZE:
                    counter = max(0, resize_counter - 1)
                    nw, nh = ncg[2:4]
                    for s in self.window_sources():
                        if s != ss:
                            s.resize_window(wid, window, nw, nh, resize_counter=counter)
                damage = True
            if damage:
                self.schedule_configure_damage(wid)

    def schedule_configure_damage(self, wid: int, delay=CONFIGURE_DAMAGE_RATE) -> None:
        if self.configure_damage_timers.get(wid):
            return

        def damage() -> None:
            self.configure_damage_timers.pop(wid, None)
            window = self.get_window(wid)
            if window and window.is_managed():
                self.refresh_window(window)

        self.configure_damage_timers[wid] = GLib.timeout_add(delay, damage)

    def cancel_configure_damage(self, wid: int) -> None:
        if timer := self.configure_damage_timers.pop(wid, None):
            GLib.source_remove(timer)

    def cancel_all_configure_damage(self) -> None:
        timers = tuple(self.configure_damage_timers.values())
        self.configure_damage_timers = {}
        for timer in timers:
            GLib.source_remove(timer)

    def _set_client_properties(self, proto, wid: int, window, new_client_properties: dict) -> None:
        """
        Override so we can update the workspace on the window directly,
        instead of storing it as a client property
        """
        workspace = typedict(new_client_properties).intget("workspace", -1)

        def wn(w) -> str:
            return WORKSPACE_NAMES.get(w) or str(w)

        workspacelog("workspace from client properties %s: %s", new_client_properties, wn(workspace))
        if workspace >= 0:
            window.move_to_workspace(workspace)
            new_client_properties.pop("workspace", None)
        super()._set_client_properties(proto, wid, window, new_client_properties)

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        """
        Override so we can raise the window under the cursor
        (gtk raise does not change window stacking, just focus).
        """
        if wid > 0 and (self.last_raised != wid or ALWAYS_RAISE_WINDOW):
            window = self.get_window(wid)
            if not window:
                pointerlog("_move_pointer(%s, %s) invalid window id", wid, pos)
            else:
                self.last_raised = wid
                pointerlog("raising %s", window)
                with xswallow:
                    window.raise_window()
        pointer = self.get_subsystem("pointer")
        if pointer:
            pointer._move_pointer(device_id, wid, pos, props)

    def _process_window_close(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        windowlog("client closed window %s - %s", wid, window)
        if window:
            window.request_close()
        else:
            windowlog("cannot close window %s: it is already gone!", wid)
        self.repaint_root_overlay()

    def _process_window_signal(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        sig = packet.get_str(2)
        if sig not in WINDOW_SIGNALS:
            log.warn(f"Warning: window signal {sig!r} not handled")
            return
        w = self.get_window(wid)
        if not w:
            log.warn(f"Warning: window {wid:#x} not found")
            return
        pid = w.get_property("pid")
        log("window-signal %s for wid=%#x, pid=%s", sig, wid, pid)
        if not pid:
            log.warn(f"Warning: no pid found for window {wid:#x}, cannot send {sig}")
            return
        try:
            sigval = getattr(signal, sig)
            os.kill(pid, sigval)
            log.info(f"sent signal {sig!r} to pid {pid} for window {wid:#x}")
        except Exception as e:
            log("_process_window_signal(%s, %s)", proto, packet, exc_info=True)
            log.error(f"Error: failed to send signal {sig!r} to pid {pid} for window {wid:#x}")
            log.estr(e)

    def refresh_window_area(self, window, x: int, y: int, width: int, height: int, options=None) -> None:
        super().refresh_window_area(window, x, y, width, height, options)
        root_overlay = self.get_subsystem("root-overlay")
        if root_overlay:
            root_overlay.update_window(window, x, y, width, height)
