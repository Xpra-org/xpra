#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Final
from socket import gethostname
from collections.abc import Sequence

from xpra.codecs.image import ImageWrapper
from xpra.util.gobject import to_gsignals
from xpra.util.objects import typedict
from xpra.wayland.compositor import WaylandCompositor
from xpra.wayland.surface import Surface
from xpra.wayland.subsurface import Subsurface
from xpra.wayland.popup import Popup
from xpra.wayland.output import Output
from xpra.wayland.models.window import Window
from xpra.server.base import ServerBase
from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_CREATE
from xpra.common import noop
from xpra.constants import MoveResize, SOURCE_INDICATION_NORMAL
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("server", "wayland")
focuslog = Logger("server", "wayland", "focus")

GObject = gi_import("GObject")
GLib = gi_import("GLib")

# Per-surface signals connected on each new Surface in _new_surface().
# Each entry is the event name; the handler is `self._<name with dashes -> _>`.
PER_SURFACE_EVENTS: Final[Sequence[str]] = (
    "map", "unmap", "commit", "destroy",
    "minimize", "maximize", "fullscreen",
    "move", "resize",
    "surface-image",
    "set-parent",
    "new-subsurface",
)
PER_SUBSURFACE_EVENTS: Final[Sequence[str]] = (
    "commit", "destroy",
)


class WaylandSeamlessServer(GObject.GObject, ServerBase):
    __gsignals__ = to_gsignals(ServerBase.__signals__)

    def __init__(self):
        GObject.GObject.__init__(self)
        ServerBase.__init__(self)
        self.session_type: str = "wayland"
        self.focused = 0
        self.pointer_focus = 0
        self.toplevel_wid: dict[int, int] = {}
        self.pending_popups: dict[int, tuple[int, Popup]] = {}
        self.outputs: list[Output] = []
        self.compositor = WaylandCompositor()
        # Compositor-wide events; per-surface events are connected per-instance
        # in _new_surface() once we receive the Surface object.
        self.compositor.connect("new-surface", self._new_surface)
        self.compositor.connect("new-popup", self._new_popup)
        self.compositor.connect("new-output", self._new_output)
        self.compositor.connect("ssd", self._ssd)
        self.compositor.connect("activate-request", self._activate_request)
        self.wayland_fd_source = 0
        os.environ.pop("DISPLAY", None)
        os.environ["GDK_BACKEND"] = "wayland"

    def get_child_env(self) -> dict[str, str]:
        env: dict[str, str] = super().get_child_env()
        if os.environ.get("NO_AT_BRIDGE") is None:
            env["NO_AT_BRIDGE"] = "1"
        return env

    def make_keyboard_device(self):
        return self.compositor.get_keyboard_device()

    @staticmethod
    def get_keyboard_config(_props=None):
        # p = typedict(props or {})
        from xpra.wayland.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        log("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config

    def make_pointer_device(self):
        return self.compositor.get_pointer_device()

    def get_clipboard_class(self):
        from xpra.wayland.clipboard import WaylandClipboard

        def make_wayland_clipboard(*args, **kwargs) -> WaylandClipboard:
            return WaylandClipboard(*args, compositor=self.compositor, **kwargs)

        return make_wayland_clipboard

    def get_surface(self, wid: int):
        window = self.get_window(wid)
        if not window:
            return None
        return window._gproperties.get("surface")

    def _focus(self, _server_source, wid: int, modifiers) -> None:
        log("_focus(%s, %s) current focus=%i", wid, modifiers, self.focused)
        if modifiers is not None:
            self.update_keyboard_modifiers(modifiers)
        if self.focused == wid:
            return
        for window_id, state in {
            self.focused: False,        # unfocus
            wid: True,                  # focus
        }.items():
            if not window_id:
                if state:
                    # focus now goes nowhere:
                    self.keyboard_device.focus(0)
                continue
            window = self._id_to_window.get(window_id)
            surface = self.get_surface(window_id)
            log("focus: wid=%#x, state=%s, window=%s, surface=%s", window_id, state, window, surface)
            if window and surface:
                surface.focus(state)
                # Skip the keyboard if the surface has already been destroyed —
                # xdg_surface_ptr returns 0 after Surface.destroy().
                if state and (ptr := surface.xdg_surface_ptr):
                    self.keyboard_device.focus(ptr)
        self.focused = wid
        self.compositor.flush()

    def fake_key(self, keycode: int, press: bool) -> None:
        log("fake_key(%i, %s)", keycode, press)
        if kd := self.keyboard_device:
            kd.reapply_modifiers()
        super().fake_key(keycode, press)
        self.compositor.flush()

    def update_keyboard_modifiers(self, modifiers: Sequence[str], group: int = -1) -> None:
        if group < 0 and (kd := self.keyboard_device):
            group = kd.get_layout_group()
        if kd := self.keyboard_device:
            kd.update_modifiers(modifiers, group)

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, kattrs: dict) -> None:
        attrs = typedict(kattrs)
        if "modifiers" in kattrs:
            self.update_keyboard_modifiers(attrs.strtupleget("modifiers", ()), attrs.intget("group", 0))
        super().do_process_keyboard_event(proto, wid, keyname, pressed, kattrs)

    def _update_modifiers(self, proto, wid: int, modifiers: Sequence[str]) -> None:
        self.update_keyboard_modifiers(modifiers)
        super()._update_modifiers(proto, wid, modifiers)

    def set_keyboard_layout_group(self, grp: int) -> None:
        if kd := self.keyboard_device:
            kd.set_layout_group(grp)

    def set_pointer_focus(self, wid: int, pointer: Sequence) -> None:
        log("set_pointer_focus(%i, %s)", wid, pointer)
        if self.pointer_focus == wid:
            log(" focus unchanged")
            # no change
            return
        log(" current focus=%i", self.pointer_focus)
        if self.pointer_focus and wid == 0:
            # no window has the focus:
            self.pointer_device.leave_surface()
            self.pointer_focus = 0
            return
        surface = self.get_surface(wid)
        log("surface(%i)=%s", wid, surface)
        if surface and len(pointer) >= 4 and (ptr := surface.xdg_surface_ptr):
            x, y = pointer[2:4]
            if self.pointer_device.enter_surface(ptr, x, y):
                self.pointer_focus = wid
        self.compositor.flush()

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        if props and "modifiers" in props:
            self.update_keyboard_modifiers(props.get("modifiers", ()))
        self.set_pointer_focus(wid, pointer)
        log("pointer: %r",pointer)
        try:
            if self.readonly:
                return False
            if pointer:
                if len(pointer) >= 4:
                    x, y = pointer[2:4]
                else:
                    x, y = pointer[:2]
                self.get_pointer_device(device_id).move_pointer(x, y, props or {})
            return True
        finally:
            self.compositor.flush()

    def button_action(self, device_id: int, wid: int, button: int, pressed: bool, props: dict) -> None:
        try:
            super().button_action(device_id, wid, button, pressed, props)
        finally:
            self.compositor.flush()

    def _process_pointer_wheel(self, proto, packet: Packet) -> None:
        try:
            super()._process_pointer_wheel(proto, packet)
        finally:
            self.compositor.flush()

    def _process_window_map(self, _proto, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        surface = self.get_surface(wid)
        if not (window and surface):
            return
        w = packet.get_i16(4)
        h = packet.get_i16(5)
        surface.resize(w, h)
        self.compositor.flush()
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
            self.compositor.flush()
            self.refresh_window(window)

    def _register_surface_events(self, surface, events: Sequence[str]) -> None:
        for event in events:
            handler = getattr(self, "_" + event.replace("-", "_"))
            surface.connect(event, handler)

    def _new_surface(self, surface: Surface, title: str, app_id: str, size: tuple[int, int]) -> None:
        # Subscribe per-surface signals on the Surface instance.
        self._register_surface_events(surface, PER_SURFACE_EVENTS)
        geom = (0, 0, size[0], size[1])
        window = Window({
            "client-machine": gethostname(),
            "display": self.compositor.get_display(),
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

    def _new_popup(self, parent_wid: int, popup: Popup,
                   position: tuple[int, int], size: tuple[int, int]) -> None:
        popup.connect("map", self._popup_map)
        popup.connect("unmap", self._unmap)
        popup.connect("commit", self._popup_commit)
        popup.connect("surface-image", self._surface_image)
        popup.connect("reposition", self._popup_reposition)
        popup.connect("destroy", self._popup_destroy)
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
        x, y = position
        geom = (x, y, w, h)
        window = Window({
            "client-machine": gethostname(),
            "display": self.compositor.get_display(),
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

    def _ssd(self, toplevel_ptr: int, ssd: bool) -> None:
        wid = self.toplevel_wid.get(toplevel_ptr, 0)
        log.info("ssd(%#x)=%s (wid=%i)", toplevel_ptr, ssd, wid)

    def _activate_request(self, surface_ptr: int, token: str) -> None:
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

    def _surface_image(self, wid: int, image: ImageWrapper) -> None:
        window = self.get_window(wid)
        if not window:
            if wid in self.pending_popups:
                return
            log.warn("Warning: cannot update window %i: not found!", wid)
            return
        log("new surface image for window %i: %s", wid, image)
        # don't free this image after use,
        # we will replace it with a new one when needed
        image.free = noop
        window._updateprop("image", image)
        # we can't free the previous image, which may still be referenced by the window compression thread

    def _map(self, wid: int, title: str, app_id: str, size: tuple[int, int]) -> None:
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot map window %i: not found!", wid)
            return
        window._updateprop("title", title)
        window._updateprop("app-id", app_id)
        self.update_size(window, size)

    def _unmap(self, wid: int) -> None:
        window = self.get_window(wid)
        if not window:
            return
        window.set_property("iconic", True)

    def _minimize(self, wid: int) -> None:
        self._toggle_state(wid, "iconic")

    def _maximize(self, wid: int) -> None:
        window = self.get_window(wid)
        if not window:
            return
        window._updateprop("iconic", False)
        self._toggle_state(wid, "maximized")

    def _fullscreen(self, wid: int) -> None:
        self._toggle_state(wid, "fullscreen")

    def _toggle_state(self, wid, name: str) -> None:
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot toggle %r state, window %i not found", name, wid)
            return
        current = window._gproperties.get(name, None)
        window._updateprop(name, not current)

    def _commit(self, wid: int, mapped: bool,
                size: tuple[int, int],
                rects: Sequence[tuple[int, int, int, int]],
                subsurfaces: list[tuple[int, int, int]]) -> None:
        log(f"commit wid {wid} {mapped=}, {size=}, {rects=}, {subsurfaces=}")
        window = self.get_window(wid)
        if not window:
            return
        self.track_toplevel(self.get_surface(wid))
        self.update_size(window, size)
        options = {
            "damage": True,
        }
        last = len(rects) - 1
        for i, (x, y, w, h) in enumerate(rects):
            options["more"] = i != last
            self.refresh_window_area(window, x, y, w, h, options=options)

    def update_size(self, window, size: tuple[int, int]) -> None:
        old_geom = window.get_property("geometry")
        w, h = size
        if old_geom[2] == w and old_geom[3] == h:
            return
        geom = (old_geom[0], old_geom[1], w, h)
        window._updateprop("geometry", geom)
        if (old_geom[2] == old_geom[3] == 0) and size[0] and size[1]:
            self._do_send_new_window_packet(WINDOW_CREATE, window, geom)

    def update_geometry(self, window, position: tuple[int, int], size: tuple[int, int]) -> None:
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

    def _popup_map(self, wid: int, position: tuple[int, int], size: tuple[int, int]) -> None:
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

    def _popup_commit(self, wid: int, mapped: bool,
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

    def _popup_reposition(self, wid: int, position: tuple[int, int]) -> None:
        window = self.get_window(wid)
        if not window:
            return
        old_geom = window.get_property("geometry")
        self.update_geometry(window, position, old_geom[2:4])

    def _popup_destroy(self, wid: int) -> None:
        self.pending_popups.pop(wid, None)
        self._destroy(wid)

    def _destroy(self, wid: int) -> None:
        # The wlroots wlr_xdg_surface is about to be (or has just been) freed.
        # We must drop every server-side reference that could later dereference
        # the dead surface from another thread.
        # encoder pipelines call window.acknowledge_changes() -> surface.frame_done())
        # or from a delayed event (focus packet for the dead wid).
        window = self.get_window(wid)
        if window is not None:
            surface = window.get_property("surface")
            if surface:
                self.toplevel_wid.pop(getattr(surface, "toplevel_ptr", 0), 0)
            window._internal_set_property("surface", None)
            window.unmanage()
            if not isinstance(surface, Subsurface):
                # sub-surfaces have a wid, but not a window!
                self._remove_wid(wid)
        if self.focused == wid:
            self.focused = 0
        if self.pointer_focus == wid:
            self.pointer_focus = 0

    def _set_parent(self, wid: int, parent_wid: int) -> None:
        # The wayland client called xdg_toplevel.set_parent. parent_wid==0 means
        # "no parent" (the relationship was cleared, or the parent is unknown to us).
        log("set_parent: wid=%i, parent_wid=%i", wid, parent_wid)
        window = self.get_window(wid)
        if not window:
            return
        window._updateprop("parent", parent_wid)
        window._updateprop("transient-for", parent_wid)

    def _new_subsurface(self, wid: int, subsurface: Subsurface, width: int, height: int) -> None:
        log.info("new subsurface of %i: %s %ix%i", wid, subsurface, width, height)
        self._register_surface_events(subsurface, PER_SUBSURFACE_EVENTS)

    def _move(self, wid: int, serial: int) -> None:
        log(f"move wid {wid}, serial={serial:#x}")
        window = self.get_window(wid)
        if not window:
            log.warn("Warning: cannot move window %i: not found!", wid)
            return
        # x_root, y_root, direction, button, source_indication = event.data
        # find clients that handle windows:
        wsources = self.window_sources()
        if not wsources:
            return
        # prefer the "UI driver" if we find it:
        driversources = [ss for ss in wsources if self.ui_driver == ss.uuid]
        if driversources:
            source = driversources[0]
        else:
            source = wsources[0]
        # must use relative position!
        x_root, y_root = self.pointer_device.get_position()
        direction = int(MoveResize.MOVE)
        button = 1
        source_indication = SOURCE_INDICATION_NORMAL
        source.initiate_moveresize(wid, window, x_root, y_root, direction, button, source_indication)

    def _resize(self, wid: int, serial: int, moveresize: int) -> None:
        log.info(f"resize wid {wid:#x}, serial={serial:#x}, moveresize={moveresize}")

    def _new_output(self, output: Output) -> None:
        log("new output %r=%r", output.name, output.get_info())
        self.outputs.append(output)

    @staticmethod
    def get_cursor_data() -> None:
        return None

    @staticmethod
    def set_desktop_geometry(w: int, h: int) -> None:
        """ not implemented yet """

    @staticmethod
    def get_display_size():
        return 3840, 2160

    def get_display_description(self) -> str:
        details = ""
        if (outputs := list(self.outputs)) and (len(outputs) == 1):
            details = " " + outputs[0].get_description()
        return f"Wayland Display{details}"

    def get_ui_info(self, proto, **kwargs) -> dict:
        info = super().get_ui_info(proto, **kwargs)
        outputs = {
            i: output.get_info()
            for i, output in enumerate(self.outputs)
        }
        if outputs:
            info.setdefault("wayland", {})["outputs"] = outputs
        return info

    def wayland_io_callback(self, fd: int, condition):
        log("wayland_io_callback%s", (fd, condition))
        if condition & GLib.IO_IN:
            self.compositor.process_events()
        elif condition & GLib.IO_ERR:
            log.error("Error: IO_ERR on wayland compositor fd %i", fd)
        return GLib.SOURCE_CONTINUE

    def setup(self) -> None:
        socket_name = self.compositor.initialize()
        os.environ["WAYLAND_DISPLAY"] = socket_name
        super().setup()

    def do_run(self) -> None:
        log("WaylandSeamlessServer.do_run()")
        fd = self.compositor.get_event_loop_fd()
        conditions = GLib.IO_IN | GLib.IO_ERR
        log("wayland compositor event loop fd=%i", fd)
        self.wayland_fd_source = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, fd, conditions, self.wayland_io_callback)
        super().do_run()

    def cleanup(self):
        super().cleanup()
        if fd := self.wayland_fd_source:
            self.wayland_fd_source = 0
            GLib.source_remove(fd)
        if c := self.compositor:
            self.compositor = None
            c.cleanup()


GObject.type_register(WaylandSeamlessServer)
