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
from xpra.x11.bindings.core import set_context_check, X11CoreBindings
from xpra.x11.bindings.randr import RandRBindings
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.gtk.error import XError, xswallow, xsync, xlog, verify_sync
from xpra.gtk.util import get_default_root_window
from xpra.x11.server.server_uuid import save_uuid, get_uuid, save_mode
from xpra.x11.vfb_util import parse_resolutions
from xpra.x11.gtk.prop import prop_get, prop_set, prop_del
from xpra.x11.gtk.display_source import close_gdk_display_source
from xpra.x11.gtk.bindings import init_x11_filter, cleanup_x11_filter, cleanup_all_event_receivers
from xpra.common import MAX_WINDOW_SIZE, FULL_INFO, NotificationID
from xpra.util.objects import typedict
from xpra.util.env import envbool, first_time
from xpra.net.compression import Compressed
from xpra.net.common import PacketType
from xpra.server.gtk_server import GTKServerBase
from xpra.server import features
from xpra.x11.xkbhelper import clean_keyboard_state
from xpra.scripts.config import FALSE_OPTIONS
from xpra.log import Logger

GLib = gi_import("GLib")

set_context_check(verify_sync)
RandR = RandRBindings()
X11Keyboard = X11KeyboardBindings()
X11Core = X11CoreBindings()
X11Window = X11WindowBindings()

log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
mouselog = Logger("x11", "server", "mouse")
grablog = Logger("server", "grab")
cursorlog = Logger("server", "cursor")
screenlog = Logger("server", "screen")
xinputlog = Logger("xinput")

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


class XTestPointerDevice:
    __slots__ = ()

    def __repr__(self):
        return "XTestPointerDevice"

    @staticmethod
    def move_pointer(x: int, y: int, props=None) -> None:
        mouselog("xtest_fake_motion%s", (x, y, props))
        with xsync:
            X11Keyboard.xtest_fake_motion(x, y)

    @staticmethod
    def click(button: int, pressed: bool, props: dict) -> None:
        mouselog("xtest_fake_button(%i, %s, %s)", button, pressed, props)
        with xsync:
            X11Keyboard.xtest_fake_button(button, pressed)

    @staticmethod
    def has_precise_wheel() -> bool:
        return False


# noinspection PyUnreachableCode
def get_cursor_sizes() -> tuple[int, int]:
    Gdk = gi_import("Gdk")
    display = Gdk.Display.get_default()
    if not display:
        return 0, 0
    return int(display.get_default_cursor_size()), display.get_maximal_cursor_size()


class X11ServerCore(GTKServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to GTKServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def __init__(self) -> None:
        self.root_window = get_default_root_window()
        self.pointer_device = XTestPointerDevice()
        self.touchpad_device = None
        self.pointer_device_map: dict = {}
        self.keys_pressed: dict[int, Any] = {}
        self.x11_filter = False
        self.randr_sizes_added: list[tuple[int, int]] = []
        self.initial_resolutions: Sequence[tuple[int, int, int]] = ()
        self.randr = False
        self.randr_exact_size = False
        self.current_keyboard_group = 0
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        super().__init__()
        log("XShape=%s", X11Window.displayHasXShape())

    def init(self, opts) -> None:
        self.do_init(opts)
        super().init(opts)

    def server_init(self) -> None:
        self.x11_init()
        if features.windows:
            from xpra.x11.window_filters import init_x11_window_filters
            init_x11_window_filters()
        super().server_init()

    def do_init(self, opts) -> None:
        onoff = sizes = opts.resize_display
        if opts.resize_display.find(":") > 0:
            #ie: "off:1080p"
            onoff, sizes = opts.resize_display.split(":", 1)
        try:
            self.initial_resolutions = parse_resolutions(sizes, opts.refresh_rate) or ()
        except ValueError:
            self.initial_resolutions = ()
        self.randr = onoff.lower() not in FALSE_OPTIONS
        self.randr_exact_size = False
        # x11 keyboard bits:
        self.current_keyboard_group = 0

    def x11_init(self) -> None:
        if FAKE_X11_INIT_ERROR:
            raise RuntimeError("fake x11 init error")
        with xlog:
            clean_keyboard_state()
        with xlog:
            if not X11Keyboard.hasXFixes() and self.cursors:
                log.error("Error: cursor forwarding support disabled")
            if not X11Keyboard.hasXTest():
                log.error("Error: keyboard and mouse disabled")
            elif not X11Keyboard.hasXkb():
                log.error("Error: limited keyboard support")
        with xsync:
            self.init_x11_atoms()
        with xlog:
            self.init_randr()
        with xlog:
            self.init_cursor()
        with xlog:
            self.x11_filter = init_x11_filter()
        assert self.x11_filter
        with xlog:
            self.save_mode()

    def save_mode(self) -> None:
        save_mode(self.get_server_mode())

    def init_randr(self) -> None:
        if self.randr and not RandR.has_randr():
            self.randr = False
        screenlog("randr=%s", self.randr)
        if not self.randr:
            return
        # check the property first,
        # because we may be inheriting this display,
        # in which case the screen sizes list may be longer than 1
        xid = self.root_window.get_xid()
        eprop = prop_get(xid, "_XPRA_RANDR_EXACT_SIZE", "u32", ignore_errors=True, raise_xerrors=False)
        screenlog("_XPRA_RANDR_EXACT_SIZE=%s", eprop)
        self.randr_exact_size = eprop == 1 or RandR.get_version() >= (1, 6)
        if not self.randr_exact_size:
            # ugly hackish way of detecting Xvfb with randr,
            # assume that it has only one resolution pre-defined:
            sizes = RandR.get_xrr_screen_sizes()
            if len(sizes) == 1:
                self.randr_exact_size = True
                prop_set(xid, "_XPRA_RANDR_EXACT_SIZE", "u32", 1)
            elif not sizes:
                # xwayland?
                self.randr = False
                self.randr_exact_size = False
        screenlog(f"randr enabled: {self.randr}, exact size={self.randr_exact_size}")
        if not self.randr:
            screenlog.warn("Warning: no X11 RandR support on %s", os.environ.get("DISPLAY"))

    def init_cursor(self) -> None:
        # cursor:
        self.default_cursor_image = None
        self.last_cursor_serial = None
        self.last_cursor_image = None
        self.send_cursor_pending = False

        def get_default_cursor():
            self.default_cursor_image = X11Keyboard.get_cursor_image()
            cursorlog("get_default_cursor=%s", self.default_cursor_image)

        with xlog:
            get_default_cursor()
            X11Keyboard.selectCursorChange(True)

    # noinspection PyMethodMayBeStatic
    def get_display_bit_depth(self) -> int:
        with xlog:
            return X11Window.get_depth(X11Window.get_root_xid())
        return 0

    # noinspection PyMethodMayBeStatic
    def init_x11_atoms(self) -> None:
        # some applications (like openoffice), do not work properly
        # if some x11 atoms aren't defined, so we define them in advance:
        X11Core.intern_atoms(window_type_atoms)

    def set_keyboard_layout_group(self, grp: int) -> None:
        kc = self.keyboard_config
        if not kc:
            keylog(f"set_keyboard_layout_group({grp}) ignored, no config")
            return
        if not kc.layout_groups:
            keylog(f"set_keyboard_layout_group({grp}) ignored, no layout groups support")
            # not supported by the client that owns the current keyboard config,
            # so make sure we stick to the default group:
            grp = 0
        if not X11Keyboard.hasXkb():
            keylog(f"set_keyboard_layout_group({grp}) ignored, no Xkb support")
            return
        if grp < 0:
            grp = 0
        if self.current_keyboard_group == grp:
            keylog(f"set_keyboard_layout_group({grp}) ignored, value unchanged")
            return
        keylog(f"set_keyboard_layout_group({grp}) config={self.keyboard_config}, {self.current_keyboard_group=}")
        try:
            with xsync:
                self.current_keyboard_group = X11Keyboard.set_layout_group(grp)
        except XError as e:
            keylog(f"set_keyboard_layout_group({grp})", exc_info=True)
            keylog.error(f"Error: failed to set keyboard layout group {grp}")
            keylog.estr(e)

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("force-ungrab", "wheel-motion", main_thread=True)

    def init_virtual_devices(self, _devices) -> None:
        self.input_devices = "xtest"

    def do_cleanup(self) -> None:
        log("do_cleanup() x11_filter=%s", self.x11_filter)
        if self.x11_filter:
            self.x11_filter = False
            cleanup_x11_filter()
            # try a few times:
            # errors happen because windows are being destroyed
            # (even more so when we call `cleanup`)
            # and we don't really care too much about this
            for log_fn in (log.debug, log.debug, log.debug, log.debug, log.warn):
                try:
                    with xsync:
                        cleanup_all_event_receivers()
                        # all went well, we're done
                        log("all event receivers have been removed")
                        break
                except Exception as e:
                    log("do_cleanup() cleanup_all_event_receivers()", exc_info=True)
                    log_fn("failed to remove event receivers: %s", e)
        with xlog:
            clean_keyboard_state()
        # prop_del does its own xsync:
        self.clean_x11_properties()
        super().do_cleanup()
        log("close_gdk_display_source()")
        close_gdk_display_source()

    def clean_x11_properties(self) -> None:
        self.do_clean_x11_properties("XPRA_SERVER_MODE", "_XPRA_RANDR_EXACT_SIZE")

    # noinspection PyMethodMayBeStatic
    def do_clean_x11_properties(self, *properties) -> None:
        root_xid = X11Window.get_root_xid()
        for prop in properties:
            try:
                prop_del(root_xid, prop)
            except Exception as e:
                log.warn(f"Warning: failed to delete property {prop!r} on root window {root_xid}: {e}")

    # noinspection PyMethodMayBeStatic
    def get_uuid(self) -> str:
        return get_uuid()

    def save_uuid(self) -> None:
        save_uuid(str(self.uuid))

    def set_keyboard_repeat(self, key_repeat) -> None:
        with xlog:
            if key_repeat:
                self.key_repeat_delay, self.key_repeat_interval = key_repeat
                if self.key_repeat_delay > 0 and self.key_repeat_interval > 0:
                    X11Keyboard.set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                    keylog.info("setting key repeat rate from client: %sms delay / %sms interval",
                                self.key_repeat_delay, self.key_repeat_interval)
            else:
                # dont do any jitter compensation:
                self.key_repeat_delay = -1
                self.key_repeat_interval = -1
                # but do set a default repeat rate:
                X11Keyboard.set_key_repeat_rate(500, 30)
                keylog("keyboard repeat disabled")

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "Python/gtk/x11"
        if "features" in source.wants:
            capabilities |= {
                "resize_screen": self.randr,
                "resize_exact": self.randr_exact_size,
                "force_ungrab": True,
                "keyboard.fast-switching": True,
                "wheel.precise": self.pointer_device.has_precise_wheel(),
                "pointer.optional": True,
                "touchpad-device": bool(self.touchpad_device),
            }
            if self.randr:
                sizes = self.get_all_screen_sizes()
                if len(sizes) > 1:
                    capabilities["screen-sizes"] = sizes
            if self.default_cursor_image and "default_cursor" in source.wants:
                ce = getattr(source, "cursor_encodings", ())
                if "default" not in ce:
                    # we have to send it this way
                    # instead of using send_initial_cursors()
                    capabilities["cursor.default"] = self.default_cursor_image
        return capabilities

    def send_initial_cursors(self, ss, sharing: bool = False) -> None:
        dci = self.default_cursor_image
        encodings = getattr(ss, "cursor_encodings", ())
        enabled = getattr(self, "cursors", False)
        if not (enabled and ("default" in encodings) and dci):
            return
        cursorlog(f"default_cursor_image={dci}, {enabled=}, {encodings=}", )
        with cursorlog.trap_error("Error sending default cursor"):
            ss.do_send_cursor(0, dci, get_cursor_sizes(), encoding_prefix="default:")

    def do_get_info(self, proto, server_sources) -> dict[str, Any]:
        start = monotonic_ns()
        info = super().do_get_info(proto, server_sources)
        sinfo = info.setdefault("server", {})
        sinfo["type"] = "Python/gtk/x11"
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
        if not self.readonly:
            with xlog:
                info.setdefault("keyboard", {}).update(
                    {
                        "state":
                            {
                                "keys_pressed": tuple(self.keys_pressed.keys()),
                                "keycodes-down": X11Keyboard.get_keycodes_down(),
                            },
                        "fast-switching": True,
                        "layout-group": X11Keyboard.get_layout_group(),
                    }
                )
        sinfo = info.setdefault("server", {})
        try:
            from xpra.x11.gtk.composite import CompositeHelper
            sinfo["XShm"] = CompositeHelper.XShmEnabled
        except ImportError:
            pass
        # cursor:
        if self.last_cursor_image:
            info.setdefault("cursor", {}).update({"current": self.get_cursor_info()})
        with xswallow:
            sinfo |= {
                "Xkb": X11Keyboard.hasXkb(),
                "XTest": X11Keyboard.hasXTest(),
            }
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

    def get_cursor_info(self) -> dict[str, Any]:
        # (NOT from UI thread)
        # copy to prevent race:
        cd = self.last_cursor_image
        if cd is None:
            return {}
        dci = self.default_cursor_image
        cinfo = {
            "is-default": bool(dci) and len(dci) >= 8 and len(cd) >= 8 and cd[7] == dci[7],
        }
        # all but pixels:
        for i, x in enumerate(("x", "y", "width", "height", "xhot", "yhot", "serial", None, "name")):
            if x:
                v = cd[i] or ""
                cinfo[x] = v
        return cinfo

    def get_window_info(self, window) -> dict[str, Any]:
        info = super().get_window_info(window)
        info["XShm"] = window.uses_xshm()
        info["geometry"] = window.get_geometry()
        return info

    def get_window_id(self, gdkwindow) -> int:
        if not gdkwindow:
            return 0
        xid = gdkwindow.get_xid()
        if not xid:
            return 0
        for wid, window in self._id_to_window.items():
            if window.get("xid", 0) == xid:
                return wid
        return 0

    # noinspection PyMethodMayBeStatic
    def get_keyboard_config(self, props=None):
        p = props or typedict()
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

    def clear_keys_pressed(self) -> None:
        if self.readonly:
            return
        keylog("clear_keys_pressed()")
        # make sure the timer doesn't fire and interfere:
        self.cancel_key_repeat_timer()
        # clear all the keys we know about:
        if self.keys_pressed:
            keylog("clearing keys pressed: %s", self.keys_pressed)
            with xsync:
                for keycode in self.keys_pressed:
                    self.fake_key(keycode, False)
            self.keys_pressed = {}
        # this will take care of any remaining ones we are not aware of:
        # (there should not be any - but we want to be certain)
        clean_keyboard_state()

    # noinspection PyMethodMayBeStatic
    def get_cursor_image(self):
        # must be called from the UI thread!
        with xlog:
            return X11Keyboard.get_cursor_image()

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
        cursor_sizes = get_cursor_sizes()
        return cursor_image, cursor_sizes

    def get_all_screen_sizes(self) -> Sequence[tuple[int, int]]:
        # workaround for #2910: the resolutions we add are not seen by XRRSizes!
        # so we keep track of the ones we have added ourselves:
        sizes = list(RandR.get_xrr_screen_sizes())
        for w, h in self.randr_sizes_added:
            if (w, h) not in sizes:
                sizes.append((w, h))
        return tuple(sizes)

    def get_max_screen_size(self) -> tuple[int, int]:
        max_w, max_h = self.root_window.get_geometry()[2:4]
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

    def configure_best_screen_size(self):
        # return ServerBase.set_best_screen_size(self)
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = self.root_window.get_geometry()[2:4]
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
                    if RandR.add_screen_size(desired_w, desired_h):
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
            root_w, root_h = self.root_window.get_size()
            return root_w, root_h
        min_dist = sorted(closest.keys())[0]
        new_size = closest[min_dist]
        screenlog("best %s resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        w, h = new_size
        return w, h

    def set_screen_size(self, desired_w: int, desired_h: int):
        screenlog("set_screen_size%s", (desired_w, desired_h))
        root_w, root_h = self.root_window.get_geometry()[2:4]
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
                RandR.set_output_int_property(output, "WIDTH_MM", wmm)
                RandR.set_output_int_property(output, "HEIGHT_MM", hmm)
        screenlog("set_dpi(%i, %i)", xdpi, ydpi)
        self.set_dpi(xdpi, ydpi)

        # try to find the best screen size to resize to:
        w, h = self.get_best_screen_size(desired_w, desired_h)

        if w == root_w and h == root_h:
            screenlog.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return root_w, root_h
        with screenlog.trap_error("Error: failed to set new resolution"):
            with xsync:
                RandR.get_screen_size()
            # Xdummy with randr 1.2:
            screenlog("using XRRSetScreenConfigAndRate with %ix%i", w, h)
            with xsync:
                RandR.set_screen_size(w, h)
            if self.randr_exact_size:
                # Xvfb with randr > 1.2: the resolution has been added
                # we can use XRRSetScreenSize:
                try:
                    with xsync:
                        RandR.xrr_set_screen_size(w, h, wmm, hmm)
                except XError:
                    screenlog("XRRSetScreenSize failed", exc_info=True)
            screenlog("calling RandR.get_screen_size()")
            with xsync:
                root_w, root_h = RandR.get_screen_size()
            screenlog("RandR.get_screen_size()=%s,%s", root_w, root_h)
            screenlog("RandR.get_vrefresh()=%s", RandR.get_vrefresh())
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
        root_w, root_h = self.root_window.get_geometry()[2:4]
        wmm, hmm = RandR.get_screen_size_mm()  # ie: (1280, 1024)
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
            assert RandR.is_dummy16(), "cannot match monitor layout without RandR 1.6"
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
            RandR.set_crtc_config(mdef)
        return mdef

    def notify_dpi_warning(self, body: str) -> None:
        sources = tuple(self._server_sources.values())
        if len(sources) == 1:
            ss = sources[0]
            if first_time("DPI-warning-%s" % ss.uuid):
                sources[0].may_notify(NotificationID.DPI, "DPI Issue", body, icon_name="font")

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        """ overridden in the seamless server """

    def _process_server_settings(self, _proto, packet: PacketType) -> None:
        settings = packet[1]
        log("process_server_settings: %s", settings)
        self.update_server_settings(settings)

    def update_server_settings(self, _settings, _reset=False) -> None:
        # implemented in the X11 xpra server only for now
        # (does not make sense to update a shadow server)
        log("ignoring server settings update in %s", self)

    def _process_force_ungrab(self, proto, _packet: PacketType) -> None:
        # ignore the window id: wid = packet[1]
        grablog("force ungrab from %s", proto)
        self.X11_ungrab()

    # noinspection PyMethodMayBeStatic
    def X11_ungrab(self) -> None:
        grablog("X11_ungrab")
        with xsync:
            X11Core.UngrabKeyboard()
            X11Core.UngrabPointer()

    # noinspection PyMethodMayBeStatic
    def fake_key(self, keycode, press) -> None:
        keylog("fake_key(%s, %s)", keycode, press)
        mink, maxk = X11Keyboard.get_minmax_keycodes()
        if keycode < mink or keycode > maxk:
            return
        with xsync:
            X11Keyboard.xtest_fake_key(keycode, press)

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
            ss.send_cursor()

    def _motion_signaled(self, model, event) -> None:
        mouselog("motion_signaled(%s, %s) last mouse user=%s", model, event, self.last_mouse_user)
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
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name)

    def _bell_signaled(self, wm, event) -> None:
        log("bell signaled on window %#x", event.window)
        if not self.bell:
            return
        wid = 0
        rxid = X11Window.get_root_xid()
        if event.window != rxid and event.window_model is not None:
            wid = self._window_to_id.get(event.window_model, 0)
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        for ss in self.window_sources():
            ss.bell(wid, event.device, event.percent,
                    event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name)

    def setup_input_devices(self) -> None:
        xinputlog("setup_input_devices() input_devices feature=%s", features.input_devices)
        if not features.input_devices:
            return
        xinputlog("setup_input_devices() format=%s, input_devices=%s", self.input_devices_format, self.input_devices)
        xinputlog("setup_input_devices() input_devices_data=%s", self.input_devices_data)
        # xinputlog("setup_input_devices() input_devices_data=%s", self.input_devices_data)
        xinputlog("setup_input_devices() pointer device=%s", self.pointer_device)
        xinputlog("setup_input_devices() touchpad device=%s", self.touchpad_device)
        self.pointer_device_map = {}
        if not self.touchpad_device:
            # no need to assign anything, we only have one device anyway
            return
        # if we find any absolute pointer devices,
        # map them to the "touchpad_device"
        XIModeAbsolute = 1
        for deviceid, device_data in self.input_devices_data.items():
            name = device_data.get("name")
            # xinputlog("[%i]=%s", deviceid, device_data)
            xinputlog("[%i]=%s", deviceid, name)
            if device_data.get("use") != "slave pointer":
                continue
            classes = device_data.get("classes")
            if not classes:
                continue
            # look for absolute pointer devices:
            touchpad_axes = []
            for i, defs in classes.items():
                xinputlog(" [%i]=%s", i, defs)
                mode = defs.get("mode")
                label = defs.get("label")
                if not mode or mode != XIModeAbsolute:
                    continue
                if defs.get("min", -1) == 0 and defs.get("max", -1) == (2 ** 24 - 1):
                    touchpad_axes.append((i, label))
            if len(touchpad_axes) == 2:
                xinputlog.info("found touchpad device: %s", name)
                xinputlog("axes: %s", touchpad_axes)
                self.pointer_device_map[deviceid] = self.touchpad_device

    def _process_wheel_motion(self, proto, packet: PacketType) -> None:
        assert self.pointer_device.has_precise_wheel()
        ss = self.get_server_source(proto)
        if not ss:
            return
        wid, button, distance, pointer, modifiers, _buttons = packet[1:7]
        device_id = -1
        props = {}
        self.record_wheel_event(wid, button)
        with xsync:
            if self.do_process_mouse_common(proto, device_id, wid, pointer, props):
                self.last_mouse_user = ss.uuid
                self._update_modifiers(proto, wid, modifiers)
                self.pointer_device.wheel_motion(button, distance / 1000.0)  # pylint: disable=no-member

    def get_pointer_device(self, deviceid: int):
        # mouselog("get_pointer_device(%i) input_devices_data=%s", deviceid, self.input_devices_data)
        if self.input_devices_data:
            device_data = self.input_devices_data.get(deviceid)
            if device_data:
                mouselog("get_pointer_device(%i) device=%s", deviceid, device_data.get("name"))
        device = self.pointer_device_map.get(deviceid) or self.pointer_device
        return device

    def _get_pointer_abs_coordinates(self, wid: int, pos) -> tuple[int, int]:
        # simple absolute coordinates
        x, y = pos[:2]
        from xpra.server.mixins.window import WindowServer
        if len(pos) >= 4 and isinstance(self, WindowServer):
            # relative coordinates
            model = self._id_to_window.get(wid)
            if model:
                rx, ry = pos[2:4]
                geom = model.get_geometry()
                x = geom[0] + rx
                y = geom[1] + ry
                mouselog("_get_pointer_abs_coordinates(%i, %s)=%s window geometry=%s", wid, pos, (x, y), geom)
        return x, y

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        # (this is called within a `xswallow` context)
        x, y = self._get_pointer_abs_coordinates(wid, pos)
        self.device_move_pointer(device_id, wid, (x, y), props)

    def device_move_pointer(self, device_id: int, wid: int, pos, props):
        device = self.get_pointer_device(device_id)
        x, y = pos
        mouselog("move_pointer(%s, %s, %s) device=%s, position=%s",
                 wid, pos, device_id, device, (x, y))
        try:
            device.move_pointer(x, y, props)
        except Exception as e:
            mouselog.error("Error: failed to move the pointer to %sx%s using %s", x, y, device)
            mouselog.estr(e)

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        mouselog("do_process_mouse_common%s", (proto, device_id, wid, pointer, props))
        if self.readonly:
            return False
        with xsync:
            pos = X11Keyboard.query_pointer()
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
            mouselog("%s%s", device.click, (button, pressed, props))
            with xsync:
                device.click(button, pressed, props)
        except XError:
            mouselog("button_action%s", (device_id, wid, pointer, button, pressed, props), exc_info=True)
            mouselog.error("Error: failed (un)press mouse button %s", button)

    def record_wheel_event(self, wid: int, button: int) -> None:
        mouselog("recording scroll event for button %i", button)
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
        packet = ("screenshot", width, height, "png", width * 4, Compressed("png", data))
        log("screenshot: %sx%s %s", packet[1], packet[2], packet[-1])
        return packet
