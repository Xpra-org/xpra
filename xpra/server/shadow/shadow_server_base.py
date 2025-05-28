# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.server.window import batch_config
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.scripts.config import InitExit
from xpra.platform.gui import get_native_notifier_classes, get_wm_name
from xpra.platform.paths import get_icon_dir
from xpra.server import features
from xpra.exit_codes import ExitCode
from xpra.net.common import PacketType
from xpra.exit_codes import ExitValue
from xpra.util.system import is_Wayland
from xpra.util.env import envint, envbool
from xpra.util.str_fn import csv
from xpra.common import NotificationID, ConnectionMessage
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("shadow")
notifylog = Logger("notify")
mouselog = Logger("mouse")
cursorlog = Logger("cursor")

NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)
POLL_POINTER = envint("XPRA_POLL_POINTER", 20)
CURSORS = envbool("XPRA_CURSORS", True)
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)
NOTIFY_STARTUP = envbool("XPRA_SHADOW_NOTIFY_STARTUP", True)

SHADOWSERVER_BASE_CLASS: type = object
if features.rfb:
    from xpra.server.rfb.server import RFBServer
    SHADOWSERVER_BASE_CLASS = RFBServer


def try_setup_capture(backends: dict[str, Callable], backend: str, *args):
    backend = backend.lower()
    if backend != "auto":
        if backend not in backends:
            raise InitExit(ExitCode.UNSUPPORTED,
                           f"invalid capture backend {backend!r}, should be one of: %s" % csv(backends.keys()))
        backends = {backend: backends[backend]}
    log(f"setup_capture() will try {backends.keys()}")
    for backend, setup_fn in backends.items():
        try:
            log(f"{backend!r}: {setup_fn}{args}")
            capture = setup_fn(*args)
            if not capture:
                log(f"backend {backend!r} is unable to capture")
                continue
            return capture
        except ImportError as e:
            log(f"backend {backend!r} is not installed: {e}")
        except Exception as e:
            log(f"{setup_fn}{args}", exc_info=True)
            log.warn(f"Warning: {backend!r} failed to setup screen capture:")
            log.warn(" %s", e)
    raise InitExit(ExitCode.UNSUPPORTED, f"failed to setup screen capture backend {backend!r}")


class ShadowServerBase(SHADOWSERVER_BASE_CLASS):
    # 20 fps unless the client specifies more:
    DEFAULT_REFRESH_RATE: int = 20

    def __init__(self, root_window, capture=None):
        # noinspection PyArgumentList
        super().__init__()
        self.capture = capture
        self.root = root_window
        self.window_matches: list[str] = []
        self.mapped = []
        self.pulseaudio: bool = False
        self.sharing: bool | None = None
        self.refresh_delay: int = 1000 // self.DEFAULT_REFRESH_RATE
        self.refresh_timer: int = 0
        self.notifications: bool = False
        self.notifier = None
        self.pointer_last_position = None
        self.pointer_poll_timer = 0
        self.last_cursor_data = None
        self.session_name = "shadow"
        self.keyboard_config = None
        batch_config.ALWAYS = True  # always batch

    def init(self, opts) -> None:
        if SHADOWSERVER_BASE_CLASS is not object:
            # RFBServer:
            SHADOWSERVER_BASE_CLASS.init(self, opts)
        self.notifications = bool(opts.notifications)
        if self.notifications:
            self.make_notifier()
        log("init(..) session_name=%s", opts.session_name)
        if opts.session_name:
            self.session_name = opts.session_name
        else:
            self.guess_session_name()

    def run(self) -> ExitValue:
        if NOTIFY_STARTUP:
            GLib.timeout_add(1000, self.notify_startup_complete)
        return super().run()

    def cleanup(self) -> None:
        for wid in self.mapped:
            self.stop_refresh(wid)
        self.cleanup_notifier()
        self.cleanup_capture()

    def cleanup_capture(self) -> None:
        capture = self.capture
        if capture:
            self.capture = None
            capture.clean()

    def guess_session_name(self, procs=None) -> None:
        log("guess_session_name(%s)", procs)
        self.session_name = get_wm_name()  # pylint: disable=assignment-from-none
        log("get_wm_name()=%s", self.session_name)

    def get_server_mode(self) -> str:
        return "shadow"

    def print_screen_info(self) -> None:
        if not features.display or not self.root:
            return
        w, h = self.root.get_geometry()[2:4]
        dinfo = ""
        if is_Wayland():
            wdisplay = os.environ.get("WAYLAND_DISPLAY", "").replace("wayland-", "")
            if wdisplay:
                dinfo = f"Wayland display {wdisplay}"
        else:
            display = os.environ.get("DISPLAY")
            if display:
                dinfo = f"X11 display {display}"
        self.do_print_screen_info(dinfo, w, h)

    def do_print_screen_info(self, display: str, w: int, h: int) -> None:
        if display or w or h:
            if display:
                msg = f" on display {display!r}"
                if w and h:
                    msg += f" of size {w}x{h}"
            else:
                msg = f" on display of size {w}x{h}"
            log.info(msg)
        if self.window_matches:
            return
        try:
            count = len(self._id_to_window)
        except AttributeError as e:
            log(f"no screen info: {e}")
            return
        if count > 1:
            log.info(f" with {count} monitors:")
            for window in self._id_to_window.values():
                title = window.get_property("title")
                x, y, w, h = window.geometry
                log.info("  %-16s %4ix%-4i at %4i,%-4i", title, w, h, x, y)

    def apply_refresh_rate(self, ss) -> None:
        rrate = super().apply_refresh_rate(ss)
        if rrate > 0:
            # adjust refresh delay to try to match:
            self.set_refresh_delay(max(10, 1000 // rrate))

    def make_hello(self, _source) -> dict[str, Any]:
        return {"shadow": True}

    def get_info(self, _proto=None, *args) -> dict[str, Any]:
        info = {
            "sharing": self.sharing is not False,
            "refresh-delay": self.refresh_delay,
        }
        if self.pointer_last_position:
            info["pointer-last-position"] = self.pointer_last_position
        return info

    def get_window_position(self, _window) -> tuple[int, int]:
        # we export the whole desktop as a window:
        return 0, 0

    def _keys_changed(self) -> None:
        from xpra.server.mixins.input import InputServer
        if isinstance(self, InputServer):
            InputServer._keys_changed(self)
            from xpra.platform.keyboard import Keyboard
            log.info("the keymap has been changed: %s", Keyboard().get_layout_spec()[0])

    ############################################################################
    # notifications
    def cleanup_notifier(self) -> None:
        n = self.notifier
        if n:
            self.notifier = None
            n.cleanup()

    def notify_setup_error(self, exception) -> None:
        notifylog("notify_setup_error(%s)", exception)
        notifylog.info("notification forwarding is not available")
        if str(exception).endswith("is already claimed on the session bus"):
            log.info(" the interface is already claimed")

    def make_notifier(self) -> None:
        nc = self.get_notifier_classes()
        notifylog("make_notifier() notifier classes: %s", nc)
        for nclass in nc:
            try:
                self.notifier = nclass()
                notifylog("notifier=%s", self.notifier)
                break
            except Exception:
                notifylog("failed to instantiate %s", nclass, exc_info=True)

    def get_notifier_classes(self) -> list[type]:
        # subclasses will generally add their toolkit specific variants
        # by overriding this method
        # use the native ones first:
        if not NATIVE_NOTIFIER:
            return []
        return get_native_notifier_classes()

    def notify_new_user(self, ss) -> None:
        # overridden here so that we can show the notification
        # directly on the screen we shadow
        notifylog("notify_new_user(%s) notifier=%s", ss, self.notifier)
        if self.notifier:
            tray = self.get_notification_tray()  # pylint: disable=assignment-from-none
            nid = NotificationID.NEW_USER
            title = "User '%s' connected to the session" % (ss.name or ss.username or ss.uuid)
            body = "\n".join(ss.get_connect_info())
            actions: list = []
            hints: dict[str, Any] = {}
            icon_filename = os.path.join(get_icon_dir(), "user.png")
            from xpra.notifications.common import parse_image_path
            icon = parse_image_path(icon_filename)
            self.notifier.show_notify("", tray, nid, "Xpra", 0, "", title, body, actions, hints, 10 * 1000, icon)

    def get_notification_tray(self):
        return None

    def notify_startup_complete(self) -> None:
        self.do_notify_startup("Xpra shadow server is ready", replaces_nid=NotificationID.STARTUP)

    def do_notify_startup(self, title: str, body: str = "", replaces_nid: int | NotificationID = 0) -> None:
        # this is overridden here so that we can show the notification
        # directly on the screen we shadow
        notifylog("do_notify_startup%s", (title, body, replaces_nid))
        if self.notifier:
            tray = self.get_notification_tray()  # pylint: disable=assignment-from-none
            actions = []
            hints = {}
            icon_filename = os.path.join(get_icon_dir(), "server-connected.png")
            from xpra.notifications.common import parse_image_path
            icon = parse_image_path(icon_filename)
            self.notifier.show_notify("", tray, NotificationID.STARTUP, "Xpra", replaces_nid, "",
                                      title, body, actions, hints, 10 * 1000, icon)

    ############################################################################
    # refresh

    def start_refresh(self, wid: int) -> None:
        log("start_refresh(%i) mapped=%s, timer=%s", wid, self.mapped, self.refresh_timer)
        if wid not in self.mapped:
            self.mapped.append(wid)
        self.start_refresh_timer()
        self.start_poll_pointer()

    def start_refresh_timer(self) -> None:
        if not self.refresh_timer:
            self.refresh_timer = GLib.timeout_add(self.refresh_delay, self.refresh)

    def set_refresh_delay(self, v: int) -> None:
        assert 0 < v < 10000
        self.refresh_delay = v
        if self.mapped:
            self.cancel_refresh_timer()
            for wid in self.mapped:
                self.start_refresh(wid)

    def stop_refresh(self, wid: int) -> None:
        log("stop_refresh(%i) mapped=%s", wid, self.mapped)
        try:
            self.mapped.remove(wid)
        except ValueError:
            pass
        if not self.mapped:
            self.no_windows()

    def no_windows(self) -> None:
        self.cancel_refresh_timer()
        self.cancel_poll_pointer()

    def cancel_refresh_timer(self) -> None:
        t = self.refresh_timer
        log("cancel_refresh_timer() timer=%s", t)
        if t:
            self.refresh_timer = 0
            GLib.source_remove(t)

    def refresh(self) -> bool:
        raise NotImplementedError()

    ############################################################################
    # pointer polling

    def get_pointer_position(self):
        raise NotImplementedError()

    def start_poll_pointer(self) -> None:
        log("start_poll_pointer() pointer_poll_timer=%s, input_devices=%s, POLL_POINTER=%s",
            self.pointer_poll_timer, features.input_devices, POLL_POINTER)
        if self.pointer_poll_timer:
            self.cancel_poll_pointer()
        if features.input_devices and POLL_POINTER > 0:
            self.pointer_poll_timer = GLib.timeout_add(POLL_POINTER, self.poll_pointer)

    def cancel_poll_pointer(self) -> None:
        ppt = self.pointer_poll_timer
        log("cancel_poll_pointer() pointer_poll_timer=%s", ppt)
        if ppt:
            self.pointer_poll_timer = 0
            GLib.source_remove(ppt)

    def poll_pointer(self) -> bool:
        self.poll_pointer_position()
        if CURSORS:
            self.poll_cursor()
        return True

    def poll_pointer_position(self) -> None:
        x, y = self.get_pointer_position()
        if self.pointer_last_position == (x, y):
            mouselog("poll_pointer_position() unchanged position=%s", (x, y))
            return
        self.pointer_last_position = (x, y)
        rwm = None
        wid = None
        rx, ry = 0, 0
        # find the window model containing the pointer:
        for wid, window in self._id_to_window.items():
            wx, wy, ww, wh = window.geometry
            if wx <= x < (wx + ww) and wy <= y < (wy + wh):
                rwm = window
                rx = x - wx
                ry = y - wy
                break
        if not rwm:
            mouselog("poll_pointer_position() model not found for position=%s", (x, y))
            return
        mouselog("poll_pointer_position() wid=%i, position=%s, relative=%s", wid, (x, y), (rx, ry))
        for ss in self._server_sources.values():
            um = getattr(ss, "update_mouse", None)
            if um:
                um(wid, x, y, rx, ry)

    def poll_cursor(self) -> None:
        prev = self.last_cursor_data
        curr = self.do_get_cursor_data()  # pylint: disable=assignment-from-none
        self.last_cursor_data = curr

        def cmpv(lcd: Sequence | None) -> tuple[Any, ...]:
            if not lcd:
                return ()
            v = lcd[0]
            if v and len(v) > 2:
                return tuple(v[2:])
            return ()

        if cmpv(prev) != cmpv(curr):
            fields = ("x", "y", "width", "height", "xhot", "yhot", "serial", "pixels", "name")
            if len(prev or []) == len(curr or []) and len(prev or []) == len(fields):
                diff = []
                for i, prev_value in enumerate(prev):
                    if prev_value != curr[i]:
                        diff.append(fields[i])
                cursorlog("poll_cursor() attributes changed: %s", diff)
            if SAVE_CURSORS and curr:
                ci = curr[0]
                if ci:
                    w = ci[2]
                    h = ci[3]
                    serial = ci[6]
                    pixels = ci[7]
                    cursorlog("saving cursor %#x with size %ix%i, %i bytes", serial, w, h, len(pixels))
                    from PIL import Image
                    img = Image.frombuffer("RGBA", (w, h), pixels, "raw", "BGRA", 0, 1)
                    img.save("cursor-%#x.png" % serial, format="PNG")
            for ss in self.window_sources():
                ss.send_cursor()

    def do_get_cursor_data(self):
        # this method is overridden in subclasses with platform specific code
        return None

    def get_cursor_data(self):
        # return cached value we get from polling:
        return self.last_cursor_data

    ############################################################################

    def sanity_checks(self, _proto, c) -> bool:
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid == self.uuid:
                log.warn("Warning: shadowing your own display can be quite confusing")
                clipboard = self._clipboard_helper and c.boolget("clipboard", True)
                if clipboard:
                    log.warn("Warning: clipboard sharing cannot be enabled!")
                    log.warn(" consider using the --no-clipboard option")
                    c["clipboard"] = False
            else:
                log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def parse_screen_info(self, ss):
        try:
            log.info(" client root window size is %sx%s", *ss.desktop_size)
        except Exception:
            log.info(" unknown client desktop size")
        self.apply_refresh_rate(ss)
        return self.get_root_window_size()

    def _process_desktop_size(self, proto, packet: PacketType) -> None:
        # just record the screen size info in the source
        ss = self.get_server_source(proto)
        if ss and len(packet) >= 4:
            ss.set_screen_sizes(packet[3])

    def set_keyboard_repeat(self, key_repeat) -> None:
        """ don't override the existing desktop """
        pass  # pylint: disable=unnecessary-pass

    def set_keymap(self, server_source, force=False) -> None:
        log("set_keymap%s", (server_source, force))
        log.info("shadow server: setting default keymap translation")
        self.keyboard_config = server_source.set_default_keymap()

    def load_existing_windows(self) -> None:
        self.mmap_min_size = 1024 * 1024 * 4 * 2
        for i, model in enumerate(self.makeRootWindowModels()):
            log(f"load_existing_windows() root window model {i} : {model}")
            self._add_new_window(model)
            # at least big enough for 2 frames of BGRX pixel data:
            w, h = model.get_dimensions()
            self.mmap_min_size = max(self.mmap_min_size, w * h * 4 * 2)

    def makeRootWindowModels(self) -> list:
        return [RootWindowModel(self.root)]

    def send_initial_windows(self, ss, sharing: bool = False) -> None:
        log("send_initial_windows(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            w, h = window.get_dimensions()
            client_props = self.client_properties.get(wid, {}).get(ss.uuid, {})
            ss.new_window("new-window", wid, window, 0, 0, w, h, client_props)

    def _add_new_window(self, window) -> None:
        self._add_new_window_common(window)
        if window.get("override-redirect", False):
            self._send_new_or_window_packet(window)
        else:
            self._send_new_window_packet(window)

    def _send_new_window_packet(self, window) -> None:
        geometry = window.get_geometry()
        self._do_send_new_window_packet("new-window", window, geometry)

    def _send_new_or_window_packet(self, window) -> None:
        geometry = window.get_property("geometry")
        self._do_send_new_window_packet("new-override-redirect", window, geometry)

    def process_window_common(self, wid: int):
        return self._id_to_window.get(wid)

    def _process_map_window(self, proto, packet: PacketType) -> None:
        wid, x, y, width, height = packet[1:6]
        window = self.process_window_common(wid)
        if not window:
            # already gone
            return
        self._window_mapped_at(proto, wid, window, (x, y, width, height))
        self.refresh_window_area(window, 0, 0, width, height)
        if len(packet) >= 7:
            self._set_client_properties(proto, wid, window, packet[6])
        self.start_refresh(wid)

    def _process_unmap_window(self, proto, packet: PacketType) -> None:
        wid = packet[1]
        window = self.process_window_common(wid)
        if not window:
            # already gone
            return
        self._window_mapped_at(proto, wid, window)
        # TODO: deal with more than one window / more than one client
        # and stop refresh if all the windows are unmapped everywhere
        if len(self._server_sources) <= 1 and len(self._id_to_window) <= 1:
            self.stop_refresh(wid)

    def _process_configure_window(self, proto, packet: PacketType) -> None:
        wid, x, y, w, h = packet[1:6]
        window = self.process_window_common(wid)
        if not window:
            # already gone
            return
        self._window_mapped_at(proto, wid, window, (x, y, w, h))
        self.refresh_window_area(window, 0, 0, w, h)
        if len(packet) >= 7:
            self._set_client_properties(proto, wid, window, packet[6])

    def _process_close_window(self, proto, packet: PacketType) -> None:
        wid = packet[1]
        window = self.process_window_common(wid)
        if not window:
            # already gone
            return
        # FIXME: with multiple windows / clients,
        # we have to keep track of mappings!
        if len(self._window_to_id) == 1:
            self.disconnect_client(proto, ConnectionMessage.DONE, "closed the only window")

    def do_make_screenshot_packet(self):
        raise NotImplementedError()

    def make_dbus_server(self):
        from xpra.server.dbus.shadow_server import Shadow_DBUS_Server
        return Shadow_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
