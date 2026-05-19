# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.server.common import get_sources_by_type
from xpra.server.window import batch_config
from xpra.server.base import ServerBase
from xpra.scripts.config import InitExit
from xpra.platform.gui import get_wm_name
from xpra.platform.paths import get_icon_dir
from xpra.server import features
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.exit_codes import ExitValue
from xpra.util.env import envint, envbool
from xpra.util.str_fn import csv
from xpra.util.parsing import DEFAULT_REFRESH_RATE, str_to_bool
from xpra.constants import NotificationID
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("shadow")
notifylog = Logger("notify")
pointerlog = Logger("pointer")
cursorlog = Logger("cursor")

NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)
POLL_POINTER = envint("XPRA_POLL_POINTER", 20)
CURSORS = envbool("XPRA_CURSORS", True)
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)
NOTIFY_STARTUP = envbool("XPRA_SHADOW_NOTIFY_STARTUP", True)


def try_setup_capture(backends: dict[str, Callable], backend: str, *args):
    backend = backend.lower()
    if backend != "auto":
        if backend not in backends:
            raise InitExit(ExitCode.UNSUPPORTED,
                           f"invalid capture backend {backend!r}, should be one of: %s" % csv(backends.keys()))
        backends = {backend: backends[backend]}
    log(f"setup_capture() will try {csv(backends.keys())}")
    for backend, setup_fn in backends.items():
        try:
            log(f"{backend!r}: {setup_fn}{args}")
            capture = setup_fn(*args)
            if not capture:
                log(f"backend {backend!r} is unable to capture using {setup_fn!r}({csv(args)})")
                continue
            return capture
        except ImportError as e:
            log.info(f"shadow backend {backend!r} is not installed: {e}")
        except Exception as e:
            log(f"{setup_fn}{args}", exc_info=True)
            log.warn(f"Warning: {backend!r} failed to setup screen capture:")
            log.warn(" %s", e)
    raise InitExit(ExitCode.UNSUPPORTED, f"failed to setup screen capture backends: {csv(backends)}")


class ShadowServerBase(ServerBase):
    SIGNALS = ServerBase.__signals__
    # 20 fps unless the client specifies more:
    DEFAULT_REFRESH_RATE = DEFAULT_REFRESH_RATE

    def __init__(self, attrs: dict[str, str], capture=None):
        # noinspection PyArgumentList
        ServerBase.__init__(self, mode="shadow")
        self.capture = capture
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
        self.session_type = "shadow"
        self.keyboard_config = None
        self.multi_window = str_to_bool(attrs.get("multi-window", True))
        batch_config.ALWAYS = True  # always batch

    def init(self, opts) -> None:
        super().init(opts)
        self.notifications = bool(opts.notifications)
        if self.notifications:
            self.make_notifier()
        log("init(..) session_name=%s", opts.session_name)
        if opts.session_name:
            self.session_name = opts.session_name

    def run(self) -> ExitValue:
        if NOTIFY_STARTUP:
            GLib.timeout_add(1000, self.notify_startup_complete)
        return super().run()

    def setup(self) -> None:
        if not self.session_name:
            GLib.idle_add(self.guess_session_name)
        super().setup()

    def cleanup(self) -> None:
        for wid in self.mapped:
            self.stop_refresh(wid)
        self.cleanup_notifier()
        self.cleanup_capture()

    def cleanup_capture(self) -> None:
        if capture := self.capture:
            self.capture = None
            capture.clean()

    def guess_session_name(self, procs=()) -> None:
        log("guess_session_name(%s)", procs)
        self.session_name = get_wm_name()  # pylint: disable=assignment-from-none
        log("get_wm_name()=%s", self.session_name)

    def get_display_description(self) -> None:
        descr = super().get_display_description()
        if self.window_matches:
            return descr
        try:
            models = self.subsystems["window"].models()
        except (AttributeError, KeyError) as e:
            log(f"no screen info: {e}")
            return descr
        if len(models) > 1:
            descr += f"\n with {len(models)} monitors:"
            for window in models:
                title = window.get_property("title")
                x, y, w, h = window.geometry
                descr += "\n  %-16s %4ix%-4i at %4i,%-4i" % (title, w, h, x, y)
        return descr

    @staticmethod
    def set_desktop_geometry(w: int, h: int) -> None:
        """ shadow servers don't modify the existing resolution """

    def make_hello(self, source) -> dict[str, Any]:
        hello = super().make_hello(source)
        hello["shadow"] = True
        return hello

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        info.update({
            "sharing": self.sharing is not False,
            "refresh-delay": self.refresh_delay,
        })
        if self.pointer_last_position:
            info["pointer-last-position"] = self.pointer_last_position
        return info

    def _keys_changed(self) -> None:
        from xpra.server.subsystem.keyboard import KeyboardServer
        if isinstance(self, KeyboardServer):
            KeyboardServer._keys_changed(self)
            from xpra.platform.keyboard import Keyboard
            log.info("the keymap has been changed: %s", Keyboard().get_layout_spec()[0])

    ############################################################################
    # notification
    def cleanup_notifier(self) -> None:
        if n := self.notifier:
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

    def get_notifier_classes(self) -> list[Callable]:
        # subclasses will generally add their toolkit specific variants
        # by overriding this method
        # use the native ones first:
        if not NATIVE_NOTIFIER:
            return []
        from xpra.platform.notification import get_backends
        return get_backends()

    def notify_new_user(self, ss) -> None:
        # overridden here so that we can show the notification
        # directly on the screen we shadow
        notifylog("notify_new_user(%s) notifier=%s", ss, self.notifier)
        if self.notifier:
            tray = self.get_notification_tray()  # pylint: disable=assignment-from-none
            nid = NotificationID.NEW_USER
            title = "User '%s' connected to the session" % (ss.name or ss.username or ss.uuid)
            body = "\n".join(ss.get_connect_info())
            actions: Sequence[str] = ()
            hints: dict[str, Any] = {}
            icon_filename = os.path.join(get_icon_dir(), "user.png")
            from xpra.notification.common import parse_image_path
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
            actions: Sequence[str] = ()
            hints = {}
            icon_filename = os.path.join(get_icon_dir(), "server-connected.png")
            from xpra.notification.common import parse_image_path
            icon = parse_image_path(icon_filename)
            self.notifier.show_notify("", tray, NotificationID.STARTUP, "Xpra", replaces_nid, "",
                                      title, body, actions, hints, 10 * 1000, icon)

    ############################################################################
    # refresh

    def start_refresh(self, wid: int) -> None:
        log("start_refresh(%#x) mapped=%s, timer=%s", wid, self.mapped, self.refresh_timer)
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
        log("stop_refresh(%#x) mapped=%s", wid, self.mapped)
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

    @staticmethod
    def get_pointer_position() -> tuple[int, int]:
        from xpra.platform.pointer import get_position
        return get_position()

    def start_poll_pointer(self) -> None:
        log("start_poll_pointer() pointer_poll_timer=%s, pointer=%s, POLL_POINTER=%s",
            self.pointer_poll_timer, features.pointer, POLL_POINTER)
        if self.pointer_poll_timer:
            self.cancel_poll_pointer()
        if features.pointer and POLL_POINTER > 0:
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
            pointerlog("poll_pointer_position() unchanged position=%s", (x, y))
            return
        self.pointer_last_position = (x, y)
        rwm = None
        wid = None
        rx, ry = 0, 0
        # find the window model containing the pointer:
        window_sub = self.subsystems["window"]
        for wid, window in window_sub._id_to_window.items():
            wx, wy, ww, wh = window.geometry
            if wx <= x < (wx + ww) and wy <= y < (wy + wh):
                rwm = window
                rx = x - wx
                ry = y - wy
                break
        if not rwm:
            pointerlog("poll_pointer_position() model not found for position=%s", (x, y))
            return
        pointerlog("poll_pointer_position() wid=%#x, position=%s, relative=%s", wid, (x, y), (rx, ry))
        try:
            from xpra.server.source.pointer import PointerConnection
        except ImportError:
            return
        pointer_sources = get_sources_by_type(self, PointerConnection)
        for ss in pointer_sources:
            ss.update_mouse(wid, x, y, rx, ry)

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
            try:
                from xpra.server.source.cursor import CursorsConnection
            except ImportError:
                pass
            else:
                for ss in get_sources_by_type(self, CursorsConnection):
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
            if server_uuid == self.subsystems["id"].uuid:
                log.warn("Warning: shadowing your own display can be quite confusing")
                clipboard = self.get_subsystem("clipboard")
                if clipboard and clipboard.helper and c.boolget("clipboard", True):
                    log.warn("Warning: clipboard sharing cannot be enabled!")
                    log.warn(" consider using the --no-clipboard option")
                    c["clipboard"] = False
            else:
                log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def _process_desktop_size(self, proto, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        # just record the screen size info in the source
        ss = self.get_server_source(proto)
        if ss and len(packet) >= 4:
            ss.set_screen_sizes(packet[3])

    def set_keyboard_repeat(self, *_args) -> None:
        """ don't override the existing desktop """

    def set_keymap(self, server_source, force=False) -> None:
        log("set_keymap%s", (server_source, force))
        log.info("shadow server: setting default keymap translation")
        self.keyboard_config = server_source.set_default_keymap()

    def make_capture_window_models(self) -> list:
        from xpra.server.shadow.root_window_model import CaptureWindowModel
        return [CaptureWindowModel()]

    def make_dbus_server(self):
        from xpra.server.dbus.shadow_server import Shadow_DBUS_Server
        return Shadow_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
