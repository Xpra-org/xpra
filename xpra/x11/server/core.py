# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import threading
from time import monotonic_ns
from typing import Any
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.x11.bindings.core import set_context_check, X11CoreBindings, get_root_xid
from xpra.x11.bindings.randr import RandRBindings
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.info import get_extensions_info
from xpra.x11.error import XError, xswallow, xsync, xlog, verify_sync
from xpra.common import MAX_WINDOW_SIZE, FULL_INFO, NotificationID, noerr
from xpra.util.objects import typedict
from xpra.util.env import envbool, first_time
from xpra.net.compression import Compressed
from xpra.net.common import Packet
from xpra.server.base import ServerBase
from xpra.server import features
from xpra.log import Logger

GLib = gi_import("GLib")

set_context_check(verify_sync)

log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
pointerlog = Logger("x11", "server", "pointer")
grablog = Logger("server", "grab")
cursorlog = Logger("server", "cursor")
screenlog = Logger("server", "screen")

ALWAYS_NOTIFY_MOTION = envbool("XPRA_ALWAYS_NOTIFY_MOTION", False)
FAKE_X11_INIT_ERROR = envbool("XPRA_FAKE_X11_INIT_ERROR", False)
DUMMY_WIDTH_HEIGHT_MM = envbool("XPRA_DUMMY_WIDTH_HEIGHT_MM", True)

window_type_atoms = tuple(f"_NET_WM_WINDOW_TYPE{wtype}" for wtype in (
    "",
    "_NORMAL",
    "_DESKTOP",
    "_DOCK",
    "_TOOLBAR",
    "_MENU",
    "_UTILITY",
    "_SPLASH",
    "_DIALOG",
    "_DROPDOWN_MENU",
    "_POPUP_MENU",
    "_TOOLTIP",
    "_NOTIFICATION",
    "_COMBO",
    "_DND",
    "_NORMAL"
))


def get_root_size() -> tuple[int, int]:
    with xsync:
        return X11WindowBindings().get_root_size()


class X11ServerCore(ServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to ServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def __init__(self) -> None:
        super().__init__()
        self.display = os.environ.get("DISPLAY", "")
        if not envbool("XPRA_GTK", False):
            from xpra.x11.bindings.display_source import get_display_ptr, init_display_source
            if not get_display_ptr():
                init_display_source()
            context = self.main_loop.get_context()
            log("GLib MainContext=%r", context)
            from xpra.x11.bindings.loop import register_glib_source
            register_glib_source(context)
            X11CoreBindings().show_server_info()

    def setup(self) -> None:
        super().setup()
        if FAKE_X11_INIT_ERROR:
            raise RuntimeError("fake x11 init error")
        with xsync:
            # some applications (like openoffice), do not work properly
            # if some x11 atoms aren't defined, so we define them in advance:
            X11CoreBindings().intern_atoms(window_type_atoms)
        with xlog:
            self.init_x11_extensions()

    def init_x11_extensions(self) -> None:
        if features.clipboard or features.cursor:
            try:
                from xpra.x11.bindings.fixes import init_xfixes_events
                init_xfixes_events()
            except ImportError:
                log("init_xfixes_events()", exc_info=True)
                log.warn("Warning: XFixes bindings not available, clipboard and cursor features may not work")
        if features.keyboard:
            try:
                from xpra.x11.bindings.xkb import init_xkb_events
                init_xkb_events()
            except ImportError:
                log("init_xkb_events()", exc_info=True)
                log.warn("Warning: XKB bindings not available, keyboard features may not work")

    def init_uuid(self) -> None:
        super().init_uuid()
        with xlog:
            self.save_server_mode()
            self.save_server_uuid()

    def save_server_mode(self) -> None:
        from xpra.x11.xroot_props import root_set
        root_set("XPRA_SERVER_MODE", "latin1", self.session_type)

    # noinspection PyMethodMayBeStatic
    def get_display_bit_depth(self) -> int:
        with xlog:
            return X11WindowBindings().get_depth(get_root_xid())
        return 0

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("force-ungrab", "wheel-motion", main_thread=True)

    def init_virtual_devices(self, _devices) -> None:
        self.input_devices = "xtest"

    def do_cleanup(self) -> None:
        # prop_del does its own xsync:
        noerr(self.clean_x11_properties)
        super().do_cleanup()
        from xpra.x11.dispatch import cleanup_all_event_receivers
        cleanup_all_event_receivers()

    def clean_x11_properties(self) -> None:
        self.do_clean_x11_properties("XPRA_SERVER_MODE", "_XPRA_RANDR_EXACT_SIZE")

    # noinspection PyMethodMayBeStatic
    def do_clean_x11_properties(self, *properties) -> None:
        from xpra.x11.xroot_props import root_del
        for prop in properties:
            try:
                root_del(prop)
            except Exception as e:
                log.warn(f"Warning: failed to delete property {prop!r} on root window: {e}")

    # noinspection PyMethodMayBeStatic
    def get_server_uuid(self) -> str:
        from xpra.x11.xroot_props import root_get
        return root_get("XPRA_SERVER_UUID", "latin1") or ""

    def save_server_uuid(self) -> None:
        from xpra.x11.xroot_props import root_set
        root_set("XPRA_SERVER_UUID", "latin1", self.uuid)

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "Python/x11"
        if "features" in source.wants:
            capabilities |= {
                "resize_screen": self.randr,
                "resize_exact": self.randr_exact_size,
                "force_ungrab": True,
            }
            if self.randr:
                sizes = self.get_all_screen_sizes()
                if len(sizes) > 1:
                    capabilities["screen-sizes"] = sizes
        return capabilities

    def do_get_info(self, proto, server_sources=()) -> dict[str, Any]:
        start = monotonic_ns()
        info = super().do_get_info(proto, server_sources)
        sinfo = info.setdefault("server", {})
        sinfo["type"] = "Python/x11"
        if FULL_INFO > 1:
            try:
                from xpra.codecs.drm.drm import query  # pylint: disable=import-outside-toplevel
            except ImportError as e:
                log(f"no drm query: {e}")
            else:
                sinfo["drm"] = query()
        log("X11ServerCore.do_get_info took %ims", (monotonic_ns() - start) // 1_000_000)
        return info

    def get_ui_info(self, proto, wids=None, *args) -> dict[str, Any]:
        log("do_get_info thread=%s", threading.current_thread())
        info = super().get_ui_info(proto, wids, *args)
        # this is added here because the server keyboard config doesn't know about "keys_pressed"..
        sinfo = info.setdefault("server", {})
        sinfo.setdefault("x11", {}).update(get_extensions_info(False))
        try:
            from xpra.x11.composite import CompositeHelper
            sinfo["XShm"] = CompositeHelper.XShmEnabled
        except (ImportError, ValueError) as e:
            log("no composite: %s", e)
        # randr:
        if self.randr:
            with xlog:
                sizes = self.get_all_screen_sizes()
                if sizes:
                    sinfo["randr"] = {
                        "": True,
                        "options": tuple(reversed(sorted(sizes))),
                        "exact": self.randr_exact_size,
                    }
        return info

    def get_window_info(self, window) -> dict[str, Any]:
        info = super().get_window_info(window)
        info["XShm"] = window.uses_xshm()
        info["geometry"] = window.get_geometry()
        return info

    # noinspection PyMethodMayBeStatic
    def get_keyboard_config(self, props=None):
        p = typedict(props or {})
        from xpra.x11.server.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        keyboard_config.enabled = p.boolget("keyboard", True)
        keyboard_config.parse_options(p)
        keyboard_config.parse_layout(p)
        keylog("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config

    def set_keymap(self, server_source, force=False) -> None:
        if self.readonly:
            return

        def reenable_keymap_changes(*args) -> bool:
            keylog("reenable_keymap_changes(%s)", args)
            self.keymap_changing_timer = 0
            self._keys_changed()
            return False

        # prevent _keys_changed() from firing:
        # (using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
        if not self.keymap_changing_timer:
            # use idle_add to give all the pending
            # events a chance to run first (and get ignored)
            self.keymap_changing_timer = GLib.timeout_add(100, reenable_keymap_changes)
        # if sharing, don't set the keymap, translate the existing one:
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s != server_source and s.ui_client]
        translate_only = len(other_ui_clients) > 0
        keylog("set_keymap(%s, %s) translate_only=%s", server_source, force, translate_only)
        with xsync:
            # pylint: disable=access-member-before-definition
            server_source.set_keymap(self.keyboard_config, self.keys_pressed, force, translate_only)
            self.keyboard_config = server_source.keyboard_config

    # noinspection PyMethodMayBeStatic
    def get_cursor_image(self):
        # must be called from the UI thread!
        with xlog:
            from xpra.x11.bindings.fixes import XFixesBindings
            return XFixesBindings().get_cursor_image()

    def get_cursor_data(self, skip_default=True) -> tuple[Any, Any]:
        # must be called from the UI thread!
        cursor_image = self.get_cursor_image()
        if cursor_image is None:
            cursorlog("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_cursor_image = list(cursor_image)
        pixels = self.last_cursor_image[7]
        cursorlog("get_cursor_image() cursor=%s", cursor_image[:7] + ["%s bytes" % len(pixels)] + cursor_image[8:])
        is_default = self.default_cursor_image is not None and str(pixels) == str(self.default_cursor_image[7])
        if skip_default and is_default:
            cursorlog("get_cursor_data(): default cursor - clearing it")
            cursor_image = None
        try:
            from xpra.x11.bindings.cursor import X11CursorBindings
            size = X11CursorBindings().get_default_cursor_size()
        except ImportError:
            size = 32
        return cursor_image, (size, (32767, 32767))

    def get_all_screen_sizes(self) -> Sequence[tuple[int, int]]:
        # workaround for #2910: the resolutions we add are not seen by XRRSizes!
        # so we keep track of the ones we have added ourselves:
        sizes = list(RandRBindings().get_xrr_screen_sizes())
        for w, h in self.randr_sizes_added:
            if (w, h) not in sizes:
                sizes.append((w, h))
        return tuple(sizes)

    def get_max_screen_size(self) -> tuple[int, int]:
        max_w, max_h = get_root_size()
        if self.randr:
            sizes = self.get_all_screen_sizes()
            if len(sizes) >= 1:
                for w, h in sizes:
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
            if max_w > MAX_WINDOW_SIZE or max_h > MAX_WINDOW_SIZE:
                screenlog.warn("Warning: maximum screen size is very large: %sx%s", max_w, max_h)
                screenlog.warn(" you may encounter window sizing problems")
            screenlog("get_max_screen_size()=%s", (max_w, max_h))
        return max_w, max_h

    def configure_best_screen_size(self) -> tuple[int, int]:
        # return ServerBase.set_best_screen_size(self)
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = get_root_size()
        if not self.randr:
            return root_w, root_h
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        max_w, max_h = 0, 0
        min_w, min_h = 16384, 16384
        client_sizes = {}
        for ss in sss:
            client_size = ss.desktop_size
            if client_size:
                w, h = client_size
                size = "%ix%i" % (w, h)
                max_w = max(max_w, w)
                max_h = max(max_h, h)
                if w > 0:
                    min_w = min(min_w, w)
                if h > 0:
                    min_h = min(min_h, h)
                client_sizes[ss.uuid] = size
        if len(client_sizes) > 1:
            screenlog.info("screen used by %i clients:", len(client_sizes))
            for uuid, size in client_sizes.items():
                screenlog.info("* %s: %s", uuid, size)
        screenlog("current server resolution is %ix%i", root_w, root_h)
        screenlog("maximum client resolution is %ix%i", max_w, max_h)
        screenlog("minimum client resolution is %ix%i", min_w, min_h)
        w, h = max_w, max_h
        screenlog("using %ix%i", w, h)
        if w <= 0 or h <= 0:
            # invalid - use fallback
            return root_w, root_h
        return self.set_screen_size(w, h)

    def get_best_screen_size(self, desired_w: int, desired_h: int):
        r = self.do_get_best_screen_size(desired_w, desired_h)
        screenlog("get_best_screen_size%s=%s", (desired_w, desired_h), r)
        return r

    def do_get_best_screen_size(self, desired_w: int, desired_h: int):
        if not self.randr:
            return desired_w, desired_h
        screen_sizes = self.get_all_screen_sizes()
        if (desired_w, desired_h) in screen_sizes:
            return desired_w, desired_h
        if self.randr_exact_size:
            try:
                with xsync:
                    if RandRBindings().add_screen_size(desired_w, desired_h):
                        # we have to wait a little bit
                        # to make sure that everything sees the new resolution
                        # (ideally this method would be split in two and this would be a callback)
                        self.randr_sizes_added.append((desired_w, desired_h))
                        import time
                        time.sleep(0.5)
                        return desired_w, desired_h
            except XError as e:
                screenlog("add_screen_size(%s, %s)", desired_w, desired_h, exc_info=True)
                screenlog.warn("Warning: failed to add resolution %ix%i:", desired_w, desired_h)
                screenlog.warn(" %s", e)
            # re-query:
            screen_sizes = self.get_all_screen_sizes()
        # try to find the best screen size to resize to:
        closest = {}
        for w, h in screen_sizes:
            distance = abs(desired_w * desired_h - w * h)
            closest[distance] = (w, h)
        if not closest:
            screenlog.warn("Warning: no matching resolution found for %sx%s", desired_w, desired_h)
            root_w, root_h = get_root_size()
            return root_w, root_h
        min_dist = sorted(closest.keys())[0]
        new_size = closest[min_dist]
        screenlog("best %s resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        w, h = new_size
        return w, h

    def set_screen_size(self, desired_w: int, desired_h: int):
        screenlog("set_screen_size%s", (desired_w, desired_h))
        root_w, root_h = get_root_size()
        if not self.randr:
            return root_w, root_h
        if desired_w == root_w and desired_h == root_h:
            return root_w, root_h  # unlikely: perfect match already!
        # clients may supply "xdpi" and "ydpi" (v0.15 onwards), or just "dpi", or nothing...
        xdpi = self.xdpi or self.dpi
        ydpi = self.ydpi or self.dpi
        screenlog("set_screen_size(%s, %s) xdpi=%s, ydpi=%s",
                  desired_w, desired_h, xdpi, ydpi)
        wmm, hmm = 0, 0
        if xdpi <= 0 or ydpi <= 0:
            # use some sane defaults: either the command line option, or fallback to 96
            # (96 is better than nothing, because we do want to set the dpi
            # to avoid Xdummy setting a crazy dpi from the virtual screen dimensions)
            xdpi = self.default_dpi or 96
            ydpi = self.default_dpi or 96
            # find the "physical" screen dimensions, so we can calculate the required dpi
            # (and do this before changing the resolution)
            client_w, client_h = 0, 0
            sss = self._server_sources.values()
            for ss in sss:
                screen_sizes = getattr(ss, "screen_sizes", ())
                for s in screen_sizes:
                    if len(s) >= 10:
                        # (display_name, width, height, width_mm, height_mm, monitors,
                        # work_x, work_y, work_width, work_height)
                        client_w = max(client_w, s[1])
                        client_h = max(client_h, s[2])
                        wmm = max(wmm, s[3])
                        hmm = max(hmm, s[4])
            if wmm > 0 and hmm > 0 and client_w > 0 and client_h > 0:
                # calculate "real" dpi:
                xdpi = round(client_w * 25.4 / wmm)
                ydpi = round(client_h * 25.4 / hmm)
                screenlog("calculated DPI: %s x %s (from w: %s / %s, h: %s / %s)",
                          xdpi, ydpi, client_w, wmm, client_h, hmm)
        if wmm == 0 or hmm == 0:
            wmm = round(desired_w * 25.4 / xdpi)
            hmm = round(desired_h * 25.4 / ydpi)
        if DUMMY_WIDTH_HEIGHT_MM:
            # FIXME: we assume there is only one output:
            output = 0
            with xsync:
                RandRBindings().set_output_int_property(output, "WIDTH_MM", wmm)
                RandRBindings().set_output_int_property(output, "HEIGHT_MM", hmm)
        screenlog("set_dpi(%i, %i)", xdpi, ydpi)
        self.set_dpi(xdpi, ydpi)

        # try to find the best screen size to resize to:
        w, h = self.get_best_screen_size(desired_w, desired_h)

        if w == root_w and h == root_h:
            screenlog.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return root_w, root_h
        with screenlog.trap_error("Error: failed to set new resolution"):
            with xsync:
                RandRBindings().get_screen_size()
            # Xdummy with randr 1.2:
            screenlog("using XRRSetScreenConfigAndRate with %ix%i", w, h)
            with xsync:
                RandRBindings().set_screen_size(w, h)
            if self.randr_exact_size:
                # Xvfb with randr > 1.2: the resolution has been added
                # we can use XRRSetScreenSize:
                try:
                    with xsync:
                        RandRBindings().xrr_set_screen_size(w, h, wmm, hmm)
                except XError:
                    screenlog("XRRSetScreenSize failed", exc_info=True)
            screenlog("calling RandR.get_screen_size()")
            with xsync:
                root_w, root_h = RandRBindings().get_screen_size()
            screenlog("RandR.get_screen_size()=%s,%s", root_w, root_h)
            screenlog("RandR.get_vrefresh()=%s", RandRBindings().get_vrefresh())
            if root_w != w or root_h != h:
                screenlog.warn("Warning: tried to set resolution to %ix%i", w, h)
                screenlog.warn(" and ended up with %ix%i", root_w, root_h)
            else:
                msg = f"server virtual display now set to {root_w}x{root_h}"
                if desired_w != root_w or desired_h != root_h:
                    msg += f" (best match for {desired_w}x{desired_h})"
                screenlog.info(msg)

            # show dpi via idle_add so server has time to change the screen size (mm)
            GLib.idle_add(self.show_dpi, xdpi, ydpi)
        return root_w, root_h

    def show_dpi(self, xdpi: int, ydpi: int):
        root_w, root_h = get_root_size()
        wmm, hmm = RandRBindings().get_screen_size_mm()  # ie: (1280, 1024)
        screenlog("RandR.get_screen_size_mm=%s,%s", wmm, hmm)
        actual_xdpi = round(root_w * 25.4 / wmm)
        actual_ydpi = round(root_h * 25.4 / hmm)
        if abs(actual_xdpi - xdpi) <= 1 and abs(actual_ydpi - ydpi) <= 1:
            screenlog.info("DPI set to %s x %s", actual_xdpi, actual_ydpi)
            screenlog("wanted: %s x %s", xdpi, ydpi)
        else:
            # should this be a warning:
            log_fn = screenlog.info
            maxdelta = max(abs(actual_xdpi - xdpi), abs(actual_ydpi - ydpi))
            if maxdelta >= 10:
                log_fn = screenlog.warn
            messages = [
                f"DPI set to {actual_xdpi} x {actual_ydpi} (wanted {xdpi} x {ydpi})",
            ]
            if maxdelta >= 10:
                messages.append("you may experience scaling problems, such as huge or small fonts, etc")
                messages.append("to fix this issue, try the dpi switch, or use a patched Xorg dummy driver")
                self.notify_dpi_warning("\n".join(messages))
            for i, message in enumerate(messages):
                log_fn("%s%s", ["", " "][i > 0], message)

    def mirror_client_monitor_layout(self) -> dict[int, Any]:
        with xsync:
            assert RandRBindings().is_dummy16(), "cannot match monitor layout without RandR 1.6"
        # if we have a single UI client,
        # see if we can emulate its monitor geometry exactly
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        screenlog("%i sources=%s", len(sss), sss)
        if len(sss) != 1:
            return {}
        ss = sss[0]
        mdef = ss.get_monitor_definitions()
        if not mdef:
            return {}
        screenlog(f"monitor definition from client {ss}: {mdef}")
        from xpra.common import adjust_monitor_refresh_rate
        mdef = adjust_monitor_refresh_rate(self.refresh_rate, mdef)
        screenlog("refresh-rate adjusted using %s: %s", self.refresh_rate, mdef)
        with xlog:
            RandRBindings().set_crtc_config(mdef)
        return mdef

    def notify_dpi_warning(self, body: str) -> None:
        sources = tuple(self._server_sources.values())
        if len(sources) == 1:
            ss = sources[0]
            if first_time("DPI-warning-%s" % ss.uuid):
                sources[0].may_notify(NotificationID.DPI, "DPI Issue", body, icon_name="font")

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        """ overridden in the seamless server """

    def _process_server_settings(self, _proto, packet: Packet) -> None:
        settings = packet.get_dict(1)
        log("process_server_settings: %s", settings)
        self.update_server_settings(settings)

    def update_server_settings(self, _settings, _reset=False) -> None:
        # implemented in the X11 xpra server only for now
        # (does not make sense to update a shadow server)
        log("ignoring server settings update in %s", self)

    def _process_force_ungrab(self, proto, _packet: Packet) -> None:
        # ignore the window id: wid = packet[1]
        grablog("force ungrab from %s", proto)
        self.X11_ungrab()

    # noinspection PyMethodMayBeStatic
    def X11_ungrab(self) -> None:
        grablog("X11_ungrab")
        with xsync:
            core = X11CoreBindings()
            core.UngrabKeyboard()
            core.UngrabPointer()

    def do_x11_cursor_event(self, event) -> None:
        cursors = getattr(self, "cursors", False)
        if not cursors:
            return
        if self.last_cursor_serial == event.cursor_serial:
            cursorlog("ignoring cursor event %s with the same serial number %s", event, self.last_cursor_serial)
            return
        cursorlog("cursor_event: %s", event)
        self.last_cursor_serial = event.cursor_serial
        for ss in self.window_sources():
            if hasattr(ss, "send_cursor"):
                ss.send_cursor()

    def _motion_signaled(self, model, event) -> None:
        pointerlog("motion_signaled(%s, %s) last mouse user=%s", model, event, self.last_mouse_user)
        # find the window model for this gdk window:
        wid = self._window_to_id.get(model)
        if not wid:
            return
        for ss in self._server_sources.values():
            if ALWAYS_NOTIFY_MOTION or self.last_mouse_user is None or self.last_mouse_user != ss.uuid:
                if hasattr(ss, "update_mouse"):
                    ss.update_mouse(wid, event.x_root, event.y_root, event.x, event.y)

    def do_x11_xkb_event(self, event) -> None:
        # X11: XKBNotify
        log("server do_x11_xkb_event(%r)" % event)
        if event.subtype != "bell":
            log.error(f"Error: unknown event subtype: {event.subtype!r}")
            log.error(f" {event=}")
            return
        # bell events on our windows will come through the bell signal,
        # this method is a catch-all for events on windows we don't manage,
        # so we use wid=0 for that:
        wid = 0
        for ss in self.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def _bell_signaled(self, wm, event) -> None:
        log("bell signaled on window %#x", event.window)
        if not self.bell:
            return
        wid = 0
        rxid = get_root_xid()
        if event.window != rxid and event.window_model is not None:
            wid = self._window_to_id.get(event.window_model, 0)
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        for ss in self.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def _process_wheel_motion(self, proto, packet: Packet) -> None:
        assert self.pointer_device.has_precise_wheel()
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid = packet.get_wid()
        button = packet.get_u8(2)
        distance = packet.get_i64(3)
        pointer = packet.get_ints(4)
        modifiers = packet.get_strs(5)
        # _buttons = packet[6]
        device_id = -1
        props = {}
        self.record_wheel_event(wid, button)
        with xsync:
            if self.do_process_mouse_common(proto, device_id, wid, pointer, props):
                self.last_mouse_user = ss.uuid
                self._update_modifiers(proto, wid, modifiers)
                self.pointer_device.wheel_motion(button, distance / 1000.0)  # pylint: disable=no-member

    def get_pointer_device(self, deviceid: int):
        # pointerlog("get_pointer_device(%i) input_devices_data=%s", deviceid, self.input_devices_data)
        if self.input_devices_data:
            device_data = self.input_devices_data.get(deviceid)
            if device_data:
                pointerlog("get_pointer_device(%i) device=%s", deviceid, device_data.get("name"))
        device = self.pointer_device_map.get(deviceid) or self.pointer_device
        return device

    def _get_pointer_abs_coordinates(self, wid: int, pos) -> tuple[int, int]:
        # simple absolute coordinates
        x, y = pos[:2]
        from xpra.server.subsystem.window import WindowServer
        if len(pos) >= 4 and isinstance(self, WindowServer):
            # relative coordinates
            model = self._id_to_window.get(wid)
            if model:
                rx, ry = pos[2:4]
                geom = model.get_geometry()
                x = geom[0] + rx
                y = geom[1] + ry
                pointerlog("_get_pointer_abs_coordinates(%i, %s)=%s window geometry=%s", wid, pos, (x, y), geom)
        return x, y

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        # (this is called within a `xswallow` context)
        x, y = self._get_pointer_abs_coordinates(wid, pos)
        self.device_move_pointer(device_id, wid, (x, y), props)

    def device_move_pointer(self, device_id: int, wid: int, pos, props: dict):
        device = self.get_pointer_device(device_id)
        x, y = pos
        pointerlog("move_pointer(%s, %s, %s) device=%s, position=%s", wid, pos, device_id, device, (x, y))
        try:
            device.move_pointer(x, y, props)
        except Exception as e:
            pointerlog.error("Error: failed to move the pointer to %sx%s using %s", x, y, device)
            pointerlog.estr(e)

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        pointerlog("do_process_mouse_common%s", (proto, device_id, wid, pointer, props))
        if self.readonly:
            return False
        with xsync:
            pos = X11KeyboardBindings().query_pointer()
        if (pointer and pos != pointer[:2]) or self.input_devices == "xi":
            with xswallow:
                self._move_pointer(device_id, wid, pointer, props)
        return True

    def _update_modifiers(self, proto, wid: int, modifiers) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if ss:
            if self.ui_driver and self.ui_driver != ss.uuid:
                return
            if hasattr(ss, "keyboard_config"):
                ss.make_keymask_match(modifiers)
            if wid == self.get_focus():
                ss.user_event()

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool,
                                 pointer, props: dict) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        props = {}
        if self.process_mouse_common(proto, device_id, wid, pointer, props):
            self.button_action(device_id, wid, pointer, button, pressed, props)

    def button_action(self, device_id: int, wid: int, pointer, button: int, pressed: bool, props: dict) -> None:
        device = self.get_pointer_device(device_id)
        assert device, "pointer device %s not found" % device_id
        if button in (4, 5) and wid:
            self.record_wheel_event(wid, button)
        try:
            pointerlog("%s%s", device.click, (button, pressed, props))
            with xsync:
                device.click(button, pressed, props)
        except XError:
            pointerlog("button_action%s", (device_id, wid, pointer, button, pressed, props), exc_info=True)
            pointerlog.error("Error: failed (un)press mouse button %s", button)

    def record_wheel_event(self, wid: int, button: int) -> None:
        pointerlog("recording scroll event for button %i", button)
        for ss in self.window_sources():
            ss.record_scroll_event(wid)

    @staticmethod
    def make_screenshot_packet_from_regions(regions) -> tuple[str, int, int, str, int, Any]:
        # regions = array of (wid, x, y, PIL.Image)
        if not regions:
            log("screenshot: no regions found, returning empty 0x0 image!")
            return "screenshot", 0, 0, "png", 0, b""
        # in theory, we could run the rest in a non-UI thread since we're done with GTK..
        minx: int = min(x for (_, x, _, _) in regions)
        miny: int = min(y for (_, _, y, _) in regions)
        maxx: int = max((x + img.get_width()) for (_, x, _, img) in regions)
        maxy: int = max((y + img.get_height()) for (_, _, y, img) in regions)
        width = maxx - minx
        height = maxy - miny
        log("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
        from PIL import Image  # pylint: disable=import-outside-toplevel
        screenshot = Image.new("RGBA", (width, height))
        for wid, x, y, img in reversed(regions):
            pixel_format = img.get_pixel_format()
            target_format = {
                "XRGB": "RGB",
                "BGRX": "RGB",
                "BGRA": "RGBA",
            }.get(pixel_format, pixel_format)
            pixels = img.get_pixels()
            w = img.get_width()
            h = img.get_height()
            # PIL cannot use the memoryview directly:
            if isinstance(pixels, memoryview):
                pixels = pixels.tobytes()
            try:
                window_image = Image.frombuffer(target_format, (w, h), pixels, "raw", pixel_format, img.get_rowstride())
            except (ValueError, TypeError):
                log.error("Error parsing window pixels in %s format for window %i", pixel_format, wid, exc_info=True)
                continue
            tx = x - minx
            ty = y - miny
            screenshot.paste(window_image, (tx, ty))
        from io import BytesIO
        buf = BytesIO()
        screenshot.save(buf, "png")
        data = buf.getvalue()
        buf.close()
        compressed = Compressed("png", data)
        packet = ("screenshot", width, height, "png", width * 4, compressed)
        log("screenshot: %sx%s %s", width, height, compressed)
        return packet
