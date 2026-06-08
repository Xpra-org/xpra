# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.server.common import get_sources_by_type
from xpra.server.shadow.common import parse_geometries
from xpra.server.window import batch_config
from xpra.server.base import ServerBase
from xpra.scripts.config import InitExit
from xpra.platform.paths import get_icon_dir
from xpra.server import features
from xpra.exit_codes import ExitCode
from xpra.codecs.constants import TransientCodecException, CodecStateException
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
screenlog = Logger("screen")

NATIVE_NOTIFIER = envbool("XPRA_NATIVE_NOTIFIER", True)
POLL_POINTER = envint("XPRA_POLL_POINTER", 20)
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
        ServerBase.__init__(self)
        self.capture = capture
        self._captures: list = []
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
        self.session_name = "shadow"
        self.session_type = "shadow"
        self.keyboard_config = None
        self.multi_window = str_to_bool(attrs.get("multi-window", True))
        batch_config.ALWAYS = True  # always batch

    def get_display_subsystem_class(self) -> type:
        from xpra.server.shadow.display import ShadowDisplayManager
        return ShadowDisplayManager

    def get_window_subsystem_class(self) -> type:
        from xpra.server.shadow.window import ShadowWindowServer
        return ShadowWindowServer

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.server.shadow.keyboard import ShadowKeyboardManager
        return ShadowKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.server.shadow.pointer import ShadowPointerManager
        return ShadowPointerManager

    def get_cursor_subsystem_class(self) -> type:
        from xpra.server.shadow.cursor import ShadowCursorManager
        return ShadowCursorManager

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
        self.connect("last-client-exited", self.stop_all_refresh)

    def stop_all_refresh(self, *args) -> None:
        log("stop_all_refresh%s mapped=%s", args, self.mapped)
        for wid in tuple(self.mapped):
            self.stop_refresh(wid)

    def accept_client_ssh_agent(self, uuid: str, ssh_auth_sock: str) -> None:
        log(f"accept_client_ssh_agent({uuid}, {ssh_auth_sock}) not setting up ssh agent forwarding for shadow servers")

    def cleanup(self) -> None:
        for wid in self.mapped:
            self.stop_refresh(wid)
        self.cleanup_notifier()
        self.cleanup_capture()

    def cleanup_capture(self) -> None:
        captures, self._captures = self._captures, []
        self.capture = None
        for c in captures:
            c.clean()

    def guess_session_name(self, procs=()) -> None:
        log("guess_session_name(%s)", procs)
        display = self.subsystems.get("display")
        self.session_name = display.get_wm_name() if display else ""
        log("get_wm_name()=%s", self.session_name)

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
        ncs: list[Callable] = list(get_backends())
        if self.get_subsystem("gtk"):
            # if the gtk subsystem is already loaded, we can load GTKNotifier safely:
            try:
                from xpra.gtk.notifier import GTKNotifier  # pylint: disable=import-outside-toplevel
                ncs.append(GTKNotifier)
            except Exception as e:
                notifylog = Logger("notify")
                notifylog("get_notifier_classes()", exc_info=True)
                notifylog.warn("Warning: cannot load GTK notifier:")
                notifylog.warn(" %s", e)
        return ncs

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
        tray = self.get_subsystem("tray")
        return getattr(tray, "widget", None)

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
        log("refresh() mapped=%s, captures=%s", self.mapped, self._captures)
        if not self.mapped:
            self.refresh_timer = 0
            return False
        self.refresh_window_models()
        if self._captures:
            try:
                # Refresh all captures; if none report new content skip damage.
                updates = [c.refresh() for c in self._captures]
                if not any(updates):
                    return True
            except TransientCodecException as tce:
                log("refresh()", exc_info=True)
                log.warn("Warning: transient codec exception:")
                log.warn(" %s", tce)
                self.recreate_window_models()
                return False
            except CodecStateException as cse:
                log("refresh()", exc_info=True)
                log.warn("Warning: codec state exception:")
                log.warn(" %s", cse)
                self.recreate_window_models()
                return False
        self.refresh_windows()
        return True

    def refresh_windows(self) -> None:
        window_sub = self.get_subsystem("window")
        if not window_sub:
            return
        for window in window_sub.models():
            window_sub.refresh_window(window)

    def refresh_window_models(self) -> None:
        if not self.window_matches or not features.window:
            return
        # update the window models which may have changed,
        # some may have disappeared, new ones created,
        # or they may just have changed their geometry:
        try:
            windows = self.makeDynamicWindowModels()
        except Exception as e:
            log("refresh_window_models()", exc_info=True)
            log.error("Error refreshing window models")
            log.estr(e)
            return
        # build a map of window identifier -> window model:
        xid_to_window = {window.get_id(): window for window in windows}
        log("xid_to_window(%s)=%s", windows, xid_to_window)
        sources = self.window_sources()
        window_sub = self.subsystems["window"]
        for wid, window in tuple(window_sub._id_to_window.items()):
            xid = window.get_id()
            new_model = xid_to_window.pop(xid, None)
            if new_model is None:
                # window no longer exists:
                self._remove_window(window)
                continue
            resized = window.geometry[2:] != new_model.geometry[2:]
            window.geometry = new_model.geometry
            if resized:
                # it has been resized:
                window.geometry = new_model.geometry
                window.notify("size-constraints")
                for ss in sources:
                    ss.resize_window(wid, window, window.geometry[2], window.geometry[3])
        # any models left are new windows:
        window_sub = self.get_subsystem("window")
        for window in xid_to_window.values():
            self._add_new_window(window)
            if window_sub:
                window_sub.refresh_window(window)

    def recreate_window_models(self) -> None:
        # remove all existing models and re-create them:
        for model in self.subsystems["window"].models():
            self._remove_window(model)
        self.cleanup_capture()
        for model in self.make_capture_window_models():
            self._add_new_window(model)

    def send_updated_screen_size(self) -> None:
        log("send_updated_screen_size")
        super().send_updated_screen_size()
        if features.window:
            self.recreate_window_models()

    def setup_capture(self):
        raise NotImplementedError()

    def setup_monitor_capture(self, index: int, title: str, x: int, y: int, w: int, h: int):
        """
        Return a capture instance for one monitor.  Captures work in local
        (monitor-relative) coordinates: (0, 0) is always the monitor's top-left.

        Default implementation creates a single shared capture via setup_capture()
        (backward-compatible for platforms that capture the whole virtual desktop).
        Subclasses override this to return a per-monitor capture instance.
        """
        if not self.capture:
            self.capture = self.setup_capture()
            if not self.capture:
                raise RuntimeError("failed to instantiate a capture backend")
            log.info(f"capture using {self.capture.get_type()}")
        return self.capture

    def get_root_window_model_class(self) -> type:
        from xpra.server.shadow.root_window_model import CaptureWindowModel
        return CaptureWindowModel

    def makeDynamicWindowModels(self):
        assert self.window_matches
        raise NotImplementedError("dynamic window shadow is not implemented on this platform")

    ############################################################################
    # pointer polling

    def get_pointer_position(self) -> tuple[int, int]:
        pointer = self.subsystems.get("pointer")
        return pointer.get_pointer_position() if pointer else (0, 0)

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
        cursor = self.get_subsystem("cursor")
        poll_cursor = getattr(cursor, "poll_cursor", None)
        if poll_cursor:
            poll_cursor()
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
        from xpra.server.source.stub import PointerSource
        for ss in get_sources_by_type(self, PointerSource):
            ss.update_mouse(wid, x, y, rx, ry)

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

    def make_capture_window_models(self) -> list:
        screenlog("make_capture_window_models() display_options=%s", self.display_options)
        model_class = self.get_root_window_model_class()
        models = []
        display_name = self.get_display_name()
        match_str = None
        geometries = ()
        if "=" in self.display_options:
            # parse the display options as a dictionary:
            from xpra.util.parsing import parse_simple_dict
            opt_dict = parse_simple_dict(self.display_options)
            windows = opt_dict.get("windows")
            if windows:
                self.window_matches = windows.split("/")
                return self.makeDynamicWindowModels()
            match_str = opt_dict.get("plug")
            geometries_str = opt_dict.get("geometry", "")
            if geometries_str:
                geometries = parse_geometries(geometries_str)
        else:
            try:
                geometries = parse_geometries(self.display_options)
            except ValueError:
                match_str = self.display_options
        log(f"make_capture_window_models() multi_window={self.multi_window}")
        if not self.multi_window or geometries:
            if not geometries:
                rw, rh = self.get_display_size()
                geometries = ((0, 0, rw, rh), )
            for i, geometry in enumerate(geometries):
                x, y, w, h = geometry
                capture = self._make_monitor_capture(i, display_name, x, y, w, h)
                model = model_class(capture, display_name, geometry)
                models.append(model)
            return models
        found = []
        screenlog("capture inputs matching %r", match_str or "all")
        monitors = self.get_shadow_monitors()
        for i, monitor in enumerate(monitors):
            plug_name, x, y, width, height, scale_factor = monitor
            title = display_name
            if plug_name or i > 1:
                title = plug_name or str(i)
            found.append(plug_name or title)
            if match_str and not (title in match_str or plug_name in match_str):
                screenlog.info(" skipped monitor %s", plug_name or title)
                continue
            geometry = (x, y, width, height)
            capture = self._make_monitor_capture(i, title, x, y, width, height)
            model = model_class(capture, title, geometry)
            models.append(model)
            screenlog("monitor %i: %10s geometry=%s, scale factor=%s", i, title, geometry, scale_factor)
        screenlog("make_capture_window_models()=%s", models)
        if not models and match_str:
            screenlog.warn("Warning: no monitors found matching %r", match_str)
            screenlog.warn(" only found: %s", csv(found))
        return models

    def _make_monitor_capture(self, index: int, title: str, x: int, y: int, w: int, h: int):
        """Call setup_monitor_capture() and register the result in self._captures."""
        capture = self.setup_monitor_capture(index, title, x, y, w, h)
        if capture not in self._captures:
            self._captures.append(capture)
        return capture

    def get_shadow_monitors(self) -> list[tuple[str, int, int, int, int, int]]:
        gtk = self.get_subsystem("gtk")
        return gtk.get_monitors() if gtk else []

    def get_display_size(self) -> tuple[int, int]:
        display = self.get_subsystem("display")
        return display.get_display_size() if display else (0, 0)

    def make_dbus_server(self):
        from xpra.server.dbus.shadow_server import Shadow_DBUS_Server
        return Shadow_DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))
