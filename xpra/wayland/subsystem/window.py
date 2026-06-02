# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from socket import gethostname
from typing import Final
from collections.abc import Sequence

from xpra.codecs.image import ImageWrapper
from xpra.common import noop
from xpra.constants import MoveResize, SOURCE_INDICATION_NORMAL
from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_CREATE
from xpra.server.common import get_sources_by_type
from xpra.server.source.window import WindowsConnection
from xpra.server.subsystem.window import WindowServer
from xpra.util.objects import typedict
from xpra.wayland.models.subsurface_window import SubsurfaceWindow
from xpra.wayland.models.window import Window
from xpra.wayland.popup import Popup
from xpra.wayland.subsurface import Subsurface
from xpra.wayland.surface import Surface
from xpra.log import Logger

log = Logger("server", "wayland")
focuslog = Logger("server", "wayland", "focus")

# Per-surface signals connected on each new Surface in `new_surface`.
PER_SURFACE_EVENTS: Final[Sequence[str]] = (
    "map", "unmap", "commit", "destroy",
    "minimize", "maximize", "fullscreen",
    "move", "resize",
    "surface-image",
    "set-parent",
    "new-subsurface",
)
PER_SUBSURFACE_EVENTS: Final[Sequence[str]] = (
    "commit", "destroy", "subsurface-image",
)


class WaylandWindowServer(WindowServer):

    def __init__(self, server=None):
        super().__init__(server)
        self.focused = 0
        self.pointer_focus = 0
        self.toplevel_wid: dict[int, int] = {}
        self.pending_popups: dict[int, tuple[int, Popup]] = {}
        # subsurface wid -> (parent_wid, offset_x, offset_y, logical_w, logical_h, native_w, native_h)
        self.subsurface_info: dict[int, tuple[int, int, int, int, int, int, int]] = {}
        # subsurface wid -> SubsurfaceWindow facade kept alive across the subsurface lifetime.
        self.subsurface_facades: dict[int, SubsurfaceWindow] = {}

    def connect_compositor(self, compositor) -> None:
        compositor.connect("new-surface", self.new_surface)
        compositor.connect("new-popup", self.new_popup)
        compositor.connect("ssd", self.ssd)
        compositor.connect("activate-request", self.activate_request)

    def get_surface(self, wid: int):
        window = self.get_window(wid)
        if not window:
            return None
        return window._gproperties.get("surface")

    def _register_surface_events(self, surface, events: Sequence[str]) -> None:
        for event in events:
            handler = getattr(self, event.replace("-", "_"))
            surface.connect(event, handler)

    def new_surface(self, surface: Surface, title: str, app_id: str, size: tuple[int, int]) -> None:
        self._register_surface_events(surface, PER_SURFACE_EVENTS)
        geom = (0, 0, size[0], size[1])
        window = Window({
            "client-machine": gethostname(),
            "display": self.server.compositor.get_display(),
            "surface": surface,
            "title": title,
            "app-id": app_id,
            "parent": 0,
            "transient-for": 0,
            "relative-position": (),
            "override-redirect": False,
            "window-type": ("NORMAL",),
            "role": "",
            "iconic": False,
            "geometry": geom,
            "image": None,
            "depth": 32,
            "decorations": False,
        })
        window.setup()
        self.track_toplevel(surface)
        self.do_add_new_window_common(surface.wid, window)
        if size != (0, 0):
            self._do_send_new_window_packet(WINDOW_CREATE, window, geom)

    def new_popup(self, parent_wid: int, popup: Popup,
                  position: tuple[int, int], size: tuple[int, int]) -> None:
        popup.connect("map", self.popup_map)
        popup.connect("unmap", self.unmap)
        popup.connect("commit", self.popup_commit)
        popup.connect("surface-image", self.surface_image)
        popup.connect("reposition", self.popup_reposition)
        popup.connect("destroy", self.popup_destroy)
        self.pending_popups[popup.wid] = (parent_wid, popup)
        self._ensure_popup_window(parent_wid, popup, position, size)

    def _ensure_popup_window(self, parent_wid: int, popup: Popup,
                             position: tuple[int, int], size: tuple[int, int]):
        window = self.get_window(popup.wid)
        if window:
            return window
        x, y = position
        w, h = size
        if w <= 0 or h <= 0:
            log("not creating popup window %i yet: invalid size %ix%i", popup.wid, w, h)
            return None
        parent_wid = self._popup_parent_window_wid(popup, parent_wid)
        geom = (x, y, w, h)
        window = Window({
            "client-machine": gethostname(),
            "display": self.server.compositor.get_display(),
            "surface": popup,
            "title": "",
            "app-id": "",
            "parent": parent_wid,
            "transient-for": parent_wid,
            "relative-position": position,
            "override-redirect": True,
            "window-type": ("DROPDOWN_MENU", "POPUP_MENU"),
            "role": "popup",
            "iconic": False,
            "geometry": geom,
            "image": None,
            "depth": 32,
            "has-alpha": True,
            "decorations": False,
        })
        window.setup()
        self.do_add_new_window_common(popup.wid, window)
        self.pending_popups.pop(popup.wid, None)
        self._do_send_new_window_packet(WINDOW_CREATE, window, geom)
        return window

    def _popup_parent_window_wid(self, popup: Popup, fallback: int) -> int:
        parent = popup.get_parent()
        while parent:
            wid = getattr(parent, "wid", 0)
            if wid and self.get_window(wid):
                return wid
            parent = parent.get_parent() if hasattr(parent, "get_parent") else None
        return fallback if self.get_window(fallback) else 0

    def track_toplevel(self, surface) -> None:
        if not surface:
            return
        log("toplevel(%s)=%#x", surface, surface.toplevel_ptr)
        if toplevel_ptr := surface.toplevel_ptr:
            self.toplevel_wid[toplevel_ptr] = surface.wid

    def ssd(self, toplevel_ptr: int, ssd: bool) -> None:
        wid = self.toplevel_wid.get(toplevel_ptr, 0)
        log.info("ssd(%#x)=%s (wid=%i)", toplevel_ptr, ssd, wid)

    def activate_request(self, surface_ptr: int, token: str) -> None:
        focuslog("activate-request(%#x, %r)", surface_ptr, token)
        from xpra.wayland.wayland_surface import surfaces
        wsurface = surfaces.get(surface_ptr)
        if not wsurface:
            focuslog("activate-request: no surface for %#x", surface_ptr)
            return
        wid = getattr(wsurface, "wid", 0)
        if not wid or not self.get_window(wid):
            focuslog("activate-request: no window for wid=%s", wid)
            return
        self._focus(None, wid, None)
        for ss in get_sources_by_type(self.server, WindowsConnection):
            ss.raise_window(wid)

    def surface_image(self, wid: int, image: ImageWrapper) -> None:
        window = self.get_window(wid)
        if not window:
            if wid in self.pending_popups:
                return
            log.warn("Warning: cannot update window %i: not found!", wid)
            return
        log("new surface image for window %i: %s", wid, image)
        # Do not free the image while window compression threads may still reference it.
        image.free = noop
        window._updateprop("image", image)

    def map(self, wid: int, title: str, app_id: str, size: tuple[int, int]) -> None:
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot map window %i: not found!", wid)
            return
        window._updateprop("title", title)
        window._updateprop("app-id", app_id)
        self.update_size(window, size)

    def unmap(self, wid: int) -> None:
        window = self.get_window(wid)
        if window:
            window.set_property("iconic", True)

    def minimize(self, wid: int) -> None:
        self._toggle_state(wid, "iconic")

    def maximize(self, wid: int) -> None:
        window = self.get_window(wid)
        if not window:
            return
        window._updateprop("iconic", False)
        self._toggle_state(wid, "maximized")

    def fullscreen(self, wid: int) -> None:
        self._toggle_state(wid, "fullscreen")

    def _toggle_state(self, wid, name: str) -> None:
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot toggle %r state, window %i not found", name, wid)
            return
        window._updateprop(name, not window._gproperties.get(name, None))

    def commit(self, wid: int, mapped: bool,
               size: tuple[int, int],
               rects: Sequence[tuple[int, int, int, int]],
               subsurfaces: list[tuple[int, int, int, int, int, int, int]]) -> None:
        log(f"commit wid {wid} {mapped=}, {size=}, {rects=}, {subsurfaces=}")
        window = self.get_window(wid)
        if not window:
            return
        self.track_toplevel(self.get_surface(wid))
        self.update_size(window, size)
        for sub_wid, sx, sy, logical_w, logical_h, native_w, native_h in subsurfaces:
            self.subsurface_info[sub_wid] = (wid, sx, sy, logical_w, logical_h, native_w, native_h)
            facade = self.subsurface_facades.get(sub_wid)
            if facade:
                facade.update_dimensions(logical_w, logical_h)
            for ss in self.window_sources():
                sub_ws = ss.subsurface_sources.get(sub_wid)
                if sub_ws:
                    sub_ws.update_geometry(wid, sx, sy, logical_w, logical_h, native_w, native_h)
        options = {"damage": True}
        last = len(rects) - 1
        for i, (x, y, w, h) in enumerate(rects):
            options["more"] = i != last
            self.refresh_window_area(window, x, y, w, h, options=options)

    def subsurface_image(self, wid: int, image: ImageWrapper,
                         logical_w: int, logical_h: int, native_w: int, native_h: int) -> None:
        info = self.subsurface_info.get(wid)
        if not info:
            log("subsurface-image: no parent info for wid=%i, dropping", wid)
            return
        parent_wid, ox, oy, old_logical_w, old_logical_h, old_native_w, old_native_h = info
        if not self.get_window(parent_wid):
            log("subsurface-image: no parent window for wid=%i (parent=%i)", wid, parent_wid)
            return
        native_w = native_w or old_native_w or image.get_width()
        native_h = native_h or old_native_h or image.get_height()
        logical_w = logical_w or old_logical_w or native_w
        logical_h = logical_h or old_logical_h or native_h
        self.subsurface_info[wid] = (parent_wid, ox, oy, logical_w, logical_h, native_w, native_h)
        facade = self.subsurface_facades.get(wid)
        if facade is None:
            facade = SubsurfaceWindow(logical_w, logical_h, has_alpha=True, depth=32)
            self.subsurface_facades[wid] = facade
        else:
            facade.update_dimensions(logical_w, logical_h)
        facade.set_image(image)
        for ss in self.window_sources():
            sub_ws = ss.make_subsurface_source(wid, parent_wid, ox, oy, facade,
                                               logical_w, logical_h, native_w, native_h)
            sub_ws.damage(0, 0, logical_w, logical_h, {})

    def update_size(self, window, size: tuple[int, int]) -> None:
        old_geom = window.get_property("geometry")
        w, h = size
        if old_geom[2] == w and old_geom[3] == h:
            return
        geom = (old_geom[0], old_geom[1], w, h)
        window._updateprop("geometry", geom)
        if (old_geom[2] == old_geom[3] == 0) and size[0] and size[1]:
            self._do_send_new_window_packet(WINDOW_CREATE, window, geom)

    @staticmethod
    def update_geometry(window, position: tuple[int, int], size: tuple[int, int]) -> None:
        old_geom = window.get_property("geometry")
        x, y = position
        w, h = size
        if w <= 0 or h <= 0:
            return
        geom = (x, y, w, h)
        if old_geom == geom:
            return
        window._updateprop("geometry", geom)
        window._updateprop("relative-position", position)

    def popup_map(self, wid: int, position: tuple[int, int], size: tuple[int, int]) -> None:
        window = self.get_window(wid)
        if not window:
            popup_info = self.pending_popups.get(wid)
            if not popup_info:
                log.warn("Warning: cannot map popup window %i: not found!", wid)
                return
            parent_wid, popup = popup_info
            window = self._ensure_popup_window(parent_wid, popup, position, size)
            if not window:
                return
        window._updateprop("iconic", False)
        self.update_geometry(window, position, size)

    def popup_commit(self, wid: int, mapped: bool,
                     position: tuple[int, int], size: tuple[int, int],
                     has_image: bool) -> None:
        log(f"popup commit wid {wid} {mapped=}, {position=}, {size=}, {has_image=}")
        window = self.get_window(wid)
        if not window:
            popup_info = self.pending_popups.get(wid)
            if not popup_info:
                return
            parent_wid, popup = popup_info
            window = self._ensure_popup_window(parent_wid, popup, position, size)
            if not window:
                return
        self.update_geometry(window, position, size)
        if mapped and has_image:
            w, h = size
            if w > 0 and h > 0:
                self.refresh_window_area(window, 0, 0, w, h, options={"damage": True})

    def popup_reposition(self, wid: int, position: tuple[int, int]) -> None:
        window = self.get_window(wid)
        if window:
            self.update_geometry(window, position, window.get_property("geometry")[2:4])

    def popup_destroy(self, wid: int) -> None:
        self.pending_popups.pop(wid, None)
        self.destroy(wid)

    def destroy(self, wid: int) -> None:
        # The wlroots xdg surface is being freed. Drop every server-side
        # surface reference before delayed focus or encoder callbacks can use it.
        if wid in self.subsurface_info:
            self.subsurface_info.pop(wid, None)
            self.subsurface_facades.pop(wid, None)
            for ss in self.window_sources():
                ss.cleanup_subsurface_source(wid)
        window = self.get_window(wid)
        if window is not None:
            surface = window.get_property("surface")
            if surface:
                self.toplevel_wid.pop(getattr(surface, "toplevel_ptr", 0), 0)
            window._internal_set_property("surface", None)
            window.unmanage()
            if not isinstance(surface, Subsurface):
                self._remove_wid(wid)
        if self.focused == wid:
            self.focused = 0
        if self.pointer_focus == wid:
            self.pointer_focus = 0

    def set_parent(self, wid: int, parent_wid: int) -> None:
        log("set_parent: wid=%i, parent_wid=%i", wid, parent_wid)
        window = self.get_window(wid)
        if not window:
            return
        window._updateprop("parent", parent_wid)
        window._updateprop("transient-for", parent_wid)

    def new_subsurface(self, wid: int, subsurface: Subsurface,
                       width: int, height: int, native_width: int = 0, native_height: int = 0) -> None:
        log.info("new subsurface of %i: %s %ix%i native=%ix%i",
                 wid, subsurface, width, height, native_width, native_height)
        self._register_surface_events(subsurface, PER_SUBSURFACE_EVENTS)

    def move(self, wid: int, serial: int) -> None:
        log(f"move wid {wid}, serial={serial:#x}")
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot move window %i: not found!", wid)
            return
        wsources = self.window_sources()
        if not wsources:
            return
        driversources = [ss for ss in wsources if self.server.ui_driver == ss.uuid]
        source = driversources[0] if driversources else wsources[0]
        x_root, y_root = self.server.subsystems["pointer"].pointer_device.get_position()
        source.initiate_moveresize(wid, window, x_root, y_root, int(MoveResize.MOVE), 1,
                                   SOURCE_INDICATION_NORMAL)

    def resize(self, wid: int, serial: int, moveresize: int) -> None:
        log.info(f"resize wid {wid:#x}, serial={serial:#x}, moveresize={moveresize}")

    def _process_window_map(self, proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        surface = self.get_surface(wid)
        if not (window and surface):
            return
        w = packet.get_i16(4)
        h = packet.get_i16(5)
        cp = packet.get_dict(6) if len(packet) >= 7 else {}
        cp["event"] = "map"
        self._set_client_properties(proto, wid, window, cp)
        surface.resize(w, h)
        self.server.compositor.flush()
        self.refresh_window(window)

    def do_process_window_configure(self, _proto, wid, config: typedict) -> None:
        window = self.get_window(wid)
        surface = self.get_surface(wid)
        if not (window and surface):
            return
        geometry = config.inttupleget("geometry")
        if geometry:
            w, h = geometry[2:4]
            surface.resize(w, h)
            self.server.compositor.flush()
            self.refresh_window(window)

    def _focus(self, _server_source, wid: int, modifiers) -> None:
        server = self.server
        focuslog("_focus(%s, %s) current focus=%i", wid, modifiers, self.focused)
        keyboard = server.subsystems.get("keyboard")
        if modifiers is not None and keyboard:
            keyboard.update_keyboard_modifiers(modifiers)
        if self.focused == wid:
            return
        for window_id, state in {
            self.focused: False,
            wid: True,
        }.items():
            if not window_id:
                if state and keyboard and keyboard.device:
                    keyboard.device.focus(0)
                continue
            window = self.get_window(window_id)
            surface = self.get_surface(window_id)
            focuslog("focus: wid=%#x, state=%s, window=%s, surface=%s", window_id, state, window, surface)
            if window and surface:
                surface.focus(state)
                if state and (ptr := surface.xdg_surface_ptr):
                    if keyboard and keyboard.device:
                        keyboard.device.focus(ptr)
        self.focused = wid
        server.compositor.flush()

    def get_focus(self) -> int:
        return self.focused
