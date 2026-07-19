# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from typing import Any
from ctypes import create_unicode_buffer, byref, c_ulong
from ctypes.wintypes import RECT

from xpra.util.env import envbool
from xpra.constants import XPRA_APP_ID
from xpra.net.common import Packet
from xpra.scripts.config import InitException
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.server.shadow.root_window_model import CaptureWindowModel
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import get_desktop_name, get_display_size
from xpra.platform.win32.events import get_win32_event_listener
from xpra.platform.win32.shadow.common import get_monitors
from xpra.log import Logger

# user32:
from xpra.platform.win32.common import (
    EnumWindows, EnumWindowsProc, FindWindowA, IsWindowVisible,
    GetWindowTextLengthW, GetWindowTextW,
    GetWindowRect,
    GetWindowThreadProcessId,
    GetSystemMetrics,
)

log = Logger("shadow", "win32")
shapelog = Logger("shape")
keylog = Logger("keyboard")
screenlog = Logger("screen")
vddlog = Logger("vdd")

SEAMLESS = envbool("XPRA_WIN32_SEAMLESS", False)
NVFBC = envbool("XPRA_SHADOW_NVFBC", True)
DXGI = envbool("XPRA_SHADOW_DXGI", True)
GDI = envbool("XPRA_SHADOW_GDI", True)


def _check_nvfbc() -> bool:
    if not NVFBC:
        return False
    from xpra.codecs.nvidia.nvfbc.capture import get_capture_instance
    if not get_capture_instance:
        raise ImportError("get_capture_instance")
    return True


def _check_dxgi() -> bool:
    if not DXGI:
        return False
    from xpra.platform.win32.d3d11.capture import get_capture_for_monitor
    if not get_capture_for_monitor:
        raise ImportError("get_capture_for_monitor")
    return True


def _check_gdi() -> bool:
    return bool(GDI)


def _check_gtk() -> bool:
    from xpra.gtk import signals
    if not signals:
        raise ImportError("xpra.gtk.signals")
    return True


SHADOW_OPTIONS: dict = {
    "auto": lambda: True,
    "dxgi": _check_dxgi,
    "gdi": _check_gdi,
    "nvfbc": _check_nvfbc,
    "gtk": _check_gtk,
}


def _setup_nvfbc_capture(w: int, h: int, pixel_depth: int = 32):
    if not NVFBC:
        return None
    from xpra.codecs.nvidia.nvfbc.capture import get_capture_instance
    capture = get_capture_instance()
    try:
        pixel_format = {24: "RGB", 32: "BGRX", 30: "r210"}[pixel_depth]
        capture.init_context(w, h, pixel_format)
        capture.refresh()
        return capture
    except Exception as e:
        log("NvFBC_Capture", exc_info=True)
        log.warn("Warning: NvFBC screen capture initialization failed:")
        for part in str(e).replace(". ", ":").split(":"):
            if part.strip() and part != "nvfbc":
                log.warn(" %s", part.strip())
        return None


class ShadowServer(ShadowServerBase):

    def __init__(self, display, attrs: dict[str, str]):
        super().__init__(attrs)
        self.session_type = "win32 shadow"
        self.pixel_depth = 32
        self.backend = attrs.get("backend", "auto")
        # Parsec VDD slot index (-1 = not a shadow-device session).
        # This is the stable identity used to re-resolve the \\.\DISPLAYn
        # name after a WM_DISPLAYCHANGE event.
        self._vdd_slot: int = -1
        # Current \\.\DISPLAYn name without the prefix, e.g. "DISPLAY3".
        # Empty string means "capture all monitors" (normal shadow mode).
        self.monitor_device: str = ""
        # Runtime VDD multi-monitor support (regular shadow only): when the
        # Parsec VDD driver is present, clients can add/remove virtual monitors
        # from the tray menu. The shadow server owns the device handle and a
        # keep-alive ping for as long as it has plugged in any virtual display.
        self._vdd_multimonitor: bool = False
        self._vdd_handle = None
        self._vdd_keepalive = None
        # maps DISPLAYn name -> VDD slot, for monitors this server plugged in:
        self._vdd_displays: dict[str, int] = {}
        self._monitors_changed_timer: int = 0
        device = attrs.get("device", "")
        if device:
            self._init_device(device)
        elif GetSystemMetrics(win32con.SM_SAMEDISPLAYFORMAT) == 0:
            raise InitException("all the monitors must use the same display format")
        # TODO: deal with those messages?
        # el.add_event_callback(WM_WTSSESSION_CHANGE,         self.session_change_event)
        # these are bound to callbacks in the client,
        # but on the server we just ignore them:
        el = get_win32_event_listener(True)
        el.ignore_events.update({
            win32con.WM_ACTIVATEAPP: "WM_ACTIVATEAPP",
            win32con.WM_MOVE: "WM_MOVE",
            win32con.WM_INPUTLANGCHANGE: "WM_INPUTLANGCHANGE",
            win32con.WM_WININICHANGE: "WM_WININICHANGE",
        })

    def _init_device(self, device: str) -> None:
        """Parse a device specifier (e.g. 'vdd:3') and resolve to a monitor name."""
        if not device.startswith("vdd:"):
            raise InitException(f"Unknown device specifier {device!r} — expected 'vdd:<slot>'")
        try:
            slot = int(device[4:])
        except ValueError:
            raise InitException(f"Invalid vdd slot in {device!r} — expected integer after 'vdd:'")
        from xpra.platform.win32.parsecvdd import find_monitor_by_slot, DeviceStatus, query_device_status
        status = query_device_status()
        if status != DeviceStatus.OK:
            raise InitException(f"Parsec VDD driver not ready (status: {status.name})")
        monitor = find_monitor_by_slot(slot)
        if not monitor:
            raise InitException(f"Parsec VDD slot {slot} has no active display")
        self._vdd_slot = slot
        self.monitor_device = monitor
        log.info("shadow-device vdd:%i -> monitor %r", slot, monitor)

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.platform.win32.shadow_keyboard import Win32ShadowKeyboardManager
        return Win32ShadowKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.platform.win32.shadow_pointer import Win32ShadowPointerManager
        return Win32ShadowPointerManager

    def get_cursor_subsystem_class(self) -> type:
        from xpra.platform.win32.shadow_cursor import Win32ShadowCursorManager
        return Win32ShadowCursorManager

    def init(self, opts) -> None:
        self.pixel_depth = int(opts.pixel_depth) or 32
        if self.pixel_depth not in (24, 30, 32):
            raise InitException("unsupported pixel depth: %s" % self.pixel_depth)
        super().init(opts)
        if self._vdd_slot >= 0:
            el = get_win32_event_listener(True)
            el.add_event_callback(win32con.WM_DISPLAYCHANGE, self._on_display_change)
        elif not self.monitor_device and self.multi_window:
            self._init_vdd_multimonitor()

    def _init_vdd_multimonitor(self) -> None:
        """
        Enable runtime monitor add/remove for a regular multi-window shadow
        server when the Parsec VDD driver is installed.  Detection is best
        effort: if anything is missing we silently stay in plain shadow mode.
        """
        try:
            from xpra.platform.win32.parsecvdd import query_device_status, DeviceStatus
        except ImportError as e:
            screenlog("parsecvdd is not available: %s", e)
            return
        try:
            status = query_device_status()
        except Exception as e:
            screenlog("query_device_status", exc_info=True)
            screenlog.error("Error: VDD availability probe failed")
            screenlog.estr(e)
            return
        if status == DeviceStatus.NOT_INSTALLED:
            vddlog.info("Parsec VDD is not available", status.name)
            vddlog.info(" you may want to install https://github.com/nomi-san/parsec-vdd to support virtual monitors")
            return
        if status != DeviceStatus.OK:
            vddlog.warn("Warning: Parsec VDD not available (status=%s), monitor add/remove disabled", status.name)
            return
        self._vdd_multimonitor = True
        vddlog.info("Parsec VDD detected: clients can add and remove virtual monitors")
        el = get_win32_event_listener(True)
        el.add_event_callback(win32con.WM_DISPLAYCHANGE, self._on_monitors_changed)

    def setup(self) -> None:
        super().setup()
        if self._vdd_multimonitor:
            # tear down any virtual monitors we created once nobody is watching:
            self.connect("last-client-exited", self._remove_all_virtual_monitors)

    def _remove_all_virtual_monitors(self, *_args) -> None:
        if self._vdd_displays:
            vddlog.info("last client exited, removing all %i virtual monitor(s)", len(self._vdd_displays))
        # remove the displays and release the device handle (a reconnecting
        # client will re-open it on demand). The resulting WM_DISPLAYCHANGE
        # cleans up the capture window models if the server keeps running:
        self._vdd_cleanup()

    def cleanup(self) -> None:
        if self._monitors_changed_timer:
            self.source_remove(self._monitors_changed_timer)
            self._monitors_changed_timer = 0
        if self._vdd_slot >= 0 or self._vdd_multimonitor:
            el = get_win32_event_listener(False)
            if el:
                el.remove_event_callback(win32con.WM_DISPLAYCHANGE, self._on_display_change)
                el.remove_event_callback(win32con.WM_DISPLAYCHANGE, self._on_monitors_changed)
        self._vdd_cleanup()
        super().cleanup()

    def _on_display_change(self, *_args) -> None:
        """
        Windows fires WM_DISPLAYCHANGE whenever a monitor is added, removed,
        or its resolution changes.  Re-resolve our vdd slot to the current
        DISPLAYn name (it may have been renumbered) and refresh the capture
        geometry so the next frame is taken from the right screen region.
        """
        from xpra.platform.win32.parsecvdd import find_monitor_by_slot
        new_device = find_monitor_by_slot(self._vdd_slot)
        if not new_device:
            screenlog.warn("Warning: vdd slot %i has no active display after WM_DISPLAYCHANGE", self._vdd_slot)
            return
        if new_device != self.monitor_device:
            screenlog.info("vdd slot %i renamed: %r -> %r", self._vdd_slot, self.monitor_device, new_device)
            self.monitor_device = new_device
        x, y, w, h = self.get_monitor_geometry()
        screenlog("_on_display_change() vdd:%i %r -> (%i,%i,%ix%i)", self._vdd_slot, self.monitor_device, x, y, w, h)
        window_subsystem = self.get_subsystem("window")
        if window_subsystem:
            for model in window_subsystem.models():
                model.geometry = (x, y, w, h)
        display_subsystem = self.get_subsystem("display")
        if display_subsystem:
            display_subsystem.notify_screen_changed()

    # ------------------------------------------------------------------
    # VDD runtime multi-monitor support
    # ------------------------------------------------------------------

    def get_server_features(self, server_source=None) -> dict[str, Any]:
        features = super().get_server_features(server_source)
        if self._vdd_multimonitor:
            from xpra.platform.win32.parsecvdd import get_vdd_resolutions
            features |= {
                "multi-monitors": True,
                "monitors": self.get_monitor_config(),
                "monitors.min-size": (640, 480),
                "monitors.max-size": (3840, 2160),
                "monitors.add-resolutions": get_vdd_resolutions(),
                # these are virtual displays, so make the client's menu say so:
                "monitors.add-label": "Add a virtual monitor",
            }
        return features

    def get_monitor_config(self) -> dict[int, dict]:
        """
        Describe the currently shadowed monitors for the client's monitor menu.
        Physical monitors are flagged ``dynamic=False`` so they can never be
        removed; parsec-vdd monitors are ``dynamic=True``.
        """
        vdd_set: set[str] = set()
        if self._vdd_multimonitor:
            from xpra.platform.win32.parsecvdd import list_vdd_monitors
            vdd_set = set(list_vdd_monitors())
        config: dict[int, dict] = {}
        for i, monitor in enumerate(self.get_shadow_monitors()):
            plug_name, x, y, width, height = monitor[:5]
            config[i] = {
                "index": i,
                "name": plug_name or f"Monitor-{i}",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "dynamic": plug_name in vdd_set,
            }
        return config

    def _vdd_ensure_open(self) -> None:
        if self._vdd_handle is not None:
            return
        from xpra.platform.win32.parsecvdd import open_device, VddKeepAlive
        self._vdd_handle = open_device()
        self._vdd_keepalive = VddKeepAlive(self._vdd_handle)
        self._vdd_keepalive.start()
        vddlog("VDD device opened by shadow server: handle=%#x", self._vdd_handle.value)

    def _vdd_cleanup(self) -> None:
        if self._vdd_handle is not None:
            from xpra.platform.win32.parsecvdd import remove_display, close_device
            for plug, slot in list(self._vdd_displays.items()):
                try:
                    vddlog.info("removing virtual monitor %r (vdd slot %i)", plug, slot)
                    remove_display(self._vdd_handle, slot)
                except Exception:
                    vddlog("error removing VDD slot %i (%r)", slot, plug, exc_info=True)
            if self._vdd_keepalive:
                self._vdd_keepalive.stop()
                self._vdd_keepalive = None
            close_device(self._vdd_handle)
            self._vdd_handle = None
        self._vdd_displays.clear()

    def add_monitor(self, width: int, height: int) -> None:
        vddlog.info("adding virtual monitor %ix%i", width, height)
        from xpra.platform.win32.parsecvdd import add_display, list_vdd_monitors, VDD_MAX_DISPLAYS
        if len(self._vdd_displays) >= VDD_MAX_DISPLAYS:
            raise RuntimeError(f"too many virtual monitors (maximum is {VDD_MAX_DISPLAYS})")
        self._vdd_ensure_open()
        before = set(list_vdd_monitors())
        slot = add_display(self._vdd_handle)
        if slot < 0:
            raise RuntimeError("VDD add_display() failed")
        vddlog("add_display() returned slot %i, waiting for the monitor to appear", slot)
        # the new monitor appears asynchronously; poll for it without blocking the main loop:
        self.timeout_add(100, self._finish_add_monitor, slot, width, height, before, 0)

    def _finish_add_monitor(self, slot: int, width: int, height: int, before: set, attempt: int) -> bool:
        from xpra.platform.win32.parsecvdd import list_vdd_monitors, set_resolution
        new = set(list_vdd_monitors()) - before
        if not new:
            if attempt < 30:
                self.timeout_add(100, self._finish_add_monitor, slot, width, height, before, attempt + 1)
            else:
                vddlog.warn("Warning: VDD slot %i added but no new monitor appeared", slot)
            return False
        plug = sorted(new)[0]
        self._vdd_displays[plug] = slot
        vddlog.info("virtual monitor %r added (vdd slot %i), setting resolution to %ix%i",
                    plug, slot, width, height)
        try:
            set_resolution(plug, width, height)
        except Exception:
            vddlog("set_resolution(%r, %i, %i) failed", plug, width, height, exc_info=True)
        self._on_monitors_changed()
        return False

    def remove_monitor(self, index: int) -> None:
        from xpra.platform.win32.parsecvdd import remove_display
        config = self.get_monitor_config()
        mdef = config.get(index)
        if not mdef:
            raise ValueError(f"monitor index {index} not found")
        if not mdef.get("dynamic"):
            raise ValueError(f"monitor {mdef.get('name')!r} is not removable")
        plug = mdef["name"]
        slot = self._vdd_displays.pop(plug, None)
        if slot is None:
            raise ValueError(f"no VDD slot tracked for monitor {plug!r}")
        vddlog.info("removing virtual monitor %r (vdd slot %i)", plug, slot)
        remove_display(self._vdd_handle, slot)
        self._on_monitors_changed()

    def _on_monitors_changed(self, *_args) -> None:
        # coalesce bursts of WM_DISPLAYCHANGE / add / remove into a single refresh:
        if self._monitors_changed_timer:
            return
        self._monitors_changed_timer = self.timeout_add(200, self._do_monitors_changed)

    def _do_monitors_changed(self) -> bool:
        self._monitors_changed_timer = 0
        config = self.get_monitor_config()
        vddlog("monitors changed, current config=%s", config)
        # add/remove the capture window models so the client gets new-window
        # and lost-window packets for the monitors that appeared / disappeared:
        self._sync_monitor_windows()
        # push the updated virtual-screen size to clients:
        display = self.get_subsystem("display")
        if display:
            display.notify_screen_changed()
        # update the client's monitor menu:
        self.setting_changed("monitors", config)
        return False

    def _sync_monitor_windows(self) -> None:
        """
        Reconcile the shadow capture window models with the current set of
        monitors. For each monitor we:
          - create a window when it is new (the client gets a new-window packet),
          - remove the window when the monitor is gone (lost-window packet),
          - update the capture geometry (and resize the client window) when an
            existing monitor moved or changed resolution.

        The shared GDI capture covers the whole virtual desktop and adapts to
        its size automatically, so newly added monitors need no separate capture.
        """
        window_sub = self.get_subsystem("window")
        if not window_sub:
            return
        monitors = {m[0]: m for m in self.get_shadow_monitors()}     # plug name -> (plug, x, y, w, h, scale)
        # existing capture windows keyed by monitor name, keeping their wid:
        existing: dict[str, tuple[int, Any]] = {}
        for wid, model in tuple(window_sub._id_to_window.items()):
            existing[getattr(model, "title", "")] = (wid, model)
        vddlog("sync_monitor_windows() monitors=%s, existing windows=%s",
               list(monitors.keys()), list(existing.keys()))
        # remove windows whose monitor no longer exists:
        for title, (wid, model) in existing.items():
            if title not in monitors:
                vddlog.info("removing shadow window for monitor %r", title)
                window_sub._remove_window(model)
        # add new monitors, and update the geometry of existing ones:
        model_class = self.get_root_window_model_class()
        for plug, monitor in monitors.items():
            x, y, width, height = monitor[1:5]
            geometry = (x, y, width, height)
            if plug not in existing:
                vddlog.info("adding shadow window for monitor %r at %ix%i+%i+%i", plug, width, height, x, y)
                capture = self._make_monitor_capture(len(existing), plug, x, y, width, height)
                model = model_class(capture, plug, geometry)
                window_sub._add_new_window(model)
                continue
            wid, model = existing[plug]
            old = tuple(model.geometry)
            if old == geometry:
                continue
            if old[2:4] == (width, height):
                # position-only change: the client shows shadow windows at 0,0,
                # so we only need to move the capture origin (no client update):
                vddlog("monitor %r moved: %s -> %s", plug, old, geometry)
                model.geometry = geometry
            else:
                # resolution change: recreate the window so the new size and its
                # size-constraints reach the client cleanly:
                vddlog.info("monitor %r resolution changed: %s -> %s, recreating window", plug, old, geometry)
                window_sub._remove_window(model)
                capture = self._make_monitor_capture(len(existing), plug, x, y, width, height)
                window_sub._add_new_window(model_class(capture, plug, geometry))

    def _process_configure_monitor(self, _proto, packet: Packet) -> None:
        if not self._vdd_multimonitor:
            raise RuntimeError("this shadow server does not support monitor configuration")
        action = packet.get_str(1)
        if action == "add":
            resolution = packet[2]
            if isinstance(resolution, str):
                from xpra.util.parsing import parse_resolution
                # the refresh-rate may be a string like "auto" or a range;
                # parse_resolution() handles those via get_refresh_rate_for_value():
                display = self.get_subsystem("display")
                default_rr = getattr(display, "refresh_rate", "auto") if display else "auto"
                resolution = parse_resolution(resolution, default_rr)
            if not isinstance(resolution, (tuple, list)) or len(resolution) < 2:
                raise ValueError(f"invalid resolution: {resolution!r}")
            width, height = int(resolution[0]), int(resolution[1])
            self.add_monitor(width, height)
        elif action == "remove":
            identifier = packet.get_str(2)
            if identifier == "index":
                index = packet.get_u32(3)
            else:
                raise ValueError(f"unsupported monitor identifier {identifier!r}")
            self.remove_monitor(index)
        else:
            raise ValueError(f"unsupported 'configure-monitor' action {action!r}")

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("configure-monitor", main_thread=True)

    def guess_session_name(self, _procs=()) -> None:
        desktop_name = get_desktop_name()
        log("get_desktop_name()=%s", desktop_name)
        if desktop_name:
            self.session_name = desktop_name

    def get_display_size(self) -> tuple[int, int]:
        return get_display_size()

    def make_tray_widget(self):
        from xpra.platform.win32.tray import Win32Tray
        tray = self.get_subsystem("tray")
        menu = getattr(tray, "menu", None)
        return Win32Tray(self, XPRA_APP_ID, menu, "Xpra Shadow Server", "server-notconnected",
                         click_cb=self.tray_click_callback, exit_cb=self.tray_exit_callback)

    def get_monitor_geometry(self) -> tuple[int, int, int, int]:
        """
        Return ``(x, y, w, h)`` for the target monitor, or the full virtual
        screen when no specific monitor is selected.
        """
        if self.monitor_device:
            for monitor in get_monitors():
                plug_name = monitor["Device"].lstrip("\\\\.\\")
                if plug_name == self.monitor_device:
                    x1, y1, x2, y2 = monitor["Monitor"]
                    return x1, y1, x2 - x1, y2 - y1
            screenlog.warn("Warning: monitor %r not found, falling back to full screen", self.monitor_device)
        w, h = get_display_size()
        return 0, 0, w, h

    def setup_monitor_capture(self, index: int, title: str, x: int, y: int, w: int, h: int):
        """
        Per-monitor capture dispatch.  DXGI is tried first (by desktop position),
        with a per-monitor GDI fallback.  Full-desktop backends (nvfbc)
        are routed through the base-class shared-capture path.
        """
        backend = self.backend.lower()

        # Full-desktop backends: delegate to shared-capture path (global coords).
        if backend not in ("auto", "dxgi", "gdi"):
            return super().setup_monitor_capture(index, title, x, y, w, h)

        if DXGI and backend in ("auto", "dxgi"):
            try:
                from xpra.platform.win32.d3d11.capture import get_capture_for_monitor
                capture = get_capture_for_monitor(x, y)
                if capture:
                    capture.refresh()
                    log.info("monitor %r at (%i,%i): capture using %s", title, x, y, capture.get_type())
                    return capture
            except Exception:
                log("DXGI capture failed for monitor %r at (%i,%i)", title, x, y, exc_info=True)
            if backend == "dxgi":
                raise RuntimeError(f"DXGI capture unavailable for monitor {title!r} at ({x},{y})")

        if GDI and backend in ("auto", "gdi"):
            from xpra.platform.win32.gdi_screen_capture import GDICapture
            capture = GDICapture(offset_x=x, offset_y=y)
            log.info("monitor %r at (%i,%i): capture using %s", title, x, y, capture.get_type())
            return capture

        raise RuntimeError(f"no capture backend available for monitor {title!r}")

    def setup_capture(self):
        """Full-desktop capture used by the nvfbc explicit-backend mode."""
        w, h = self.get_monitor_geometry()[2:4]
        backend = self.backend.lower()
        if backend in ("nvfbc", "auto") and NVFBC:
            capture = _setup_nvfbc_capture(w, h, self.pixel_depth)
            if capture:
                log.info("capture using NvFBC")
                return capture
        if backend in ("gtk", "auto"):
            try:
                from xpra.gtk.capture import GTKImageCapture
                capture = GTKImageCapture(None)
                log.info("capture using GTK")
                return capture
            except ImportError:
                pass
        raise RuntimeError(f"no full-desktop capture backend available (backend={self.backend!r})")

    def get_root_window_model_class(self) -> type:
        if SEAMLESS:
            from xpra.platform.win32.shadow.model import SeamlessCaptureWindowModel
            return SeamlessCaptureWindowModel
        from xpra.platform.win32.shadow.model import PerMonitorCaptureWindowModel
        return PerMonitorCaptureWindowModel

    def makeDynamicWindowModels(self):
        from xpra.platform.win32.shadow.model import Win32ShadowModel
        assert self.window_matches
        # Ensure a full-virtual-desktop GDI capture exists.
        # Win32ShadowModel.get_image() adds the global window origin before calling
        # capture.get_image(), so offset=0 (full virtual desktop) is correct here.
        if not self.capture:
            from xpra.platform.win32.gdi_screen_capture import GDICapture
            self.capture = GDICapture()
            if self.capture not in self._captures:
                self._captures.append(self.capture)
        ourpid = os.getpid()
        taskbar = FindWindowA("Shell_TrayWnd", None)
        windows: dict[int, tuple[str, tuple[int, int, int, int]]] = {}

        def enum_windows_cb(hwnd, lparam):
            if not IsWindowVisible(hwnd):
                log("window %#x is not visible", hwnd)
                return True
            pid = c_ulong()
            thread_id = GetWindowThreadProcessId(hwnd, byref(pid))
            if pid == ourpid:
                log("skipped our own window %#x, thread id=%#x", hwnd, thread_id)
                return True
            rect = RECT()
            if GetWindowRect(hwnd, byref(rect)) == 0:  # NOSONAR
                log("GetWindowRect failure")
                return True
            if hwnd == taskbar:
                log("skipped taskbar")
                return True
            # skipping IsWindowEnabled check
            length = GetWindowTextLengthW(hwnd)
            buf = create_unicode_buffer(length + 1)
            window_title = ''
            if GetWindowTextW(hwnd, buf, length + 1) > 0:
                window_title = buf.value
            left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            w = right - left
            h = bottom - top
            if left <= -32000 or top <= -32000:
                log("%r is not visible: %s", window_title, (left, top, w, h))
            if w <= 0 and h <= 0:
                log("skipped invalid window size: %ix%i", w, h)
                return True
            windows[hwnd] = (window_title, (left, top, w, h))
            return True

        EnumWindows(EnumWindowsProc(enum_windows_cb), 0)
        log("makeDynamicWindowModels() windows=%s", windows)
        models = []

        def add_model(hwnd: int, title: str, geometry: tuple[int, int, int, int]):
            model = Win32ShadowModel(self.capture, title=title, geometry=geometry)
            model.hwnd = hwnd
            models.append(model)

        for m in self.window_matches:
            window = None
            try:
                if m.startswith("0x"):
                    hwnd = int(m, 16)
                else:
                    hwnd = int(m)
                if hwnd:
                    window = windows.pop(hwnd, None)
                    if window:
                        add_model(hwnd, *window)
            except ValueError:
                namere = re.compile(m, re.IGNORECASE)
                for hwnd, window in tuple(windows.items()):
                    title, geometry = window
                    if namere.match(title):
                        add_model(hwnd, title, geometry)
                        windows.pop(hwnd)
        log("makeDynamicWindowModels()=%s", models)
        return models

    def get_shadow_monitors(self) -> list:
        # Convert to the format expected by ShadowServerBase:
        #   (plug_name, x, y, width, height, scale_factor)
        # When self.monitor_device is set we only expose that one monitor,
        # which is the case for "shadow-device vdd:N" sessions.
        monitors = []
        for i, monitor in enumerate(get_monitors()):
            geom = monitor["Monitor"]
            x1, y1, x2, y2 = geom
            assert x1 < x2 and y1 < y2
            plug_name = monitor["Device"].lstrip("\\\\.\\")
            if self.monitor_device and plug_name != self.monitor_device:
                screenlog("monitor %i: %10s skipped (target is %r)", i, plug_name, self.monitor_device)
                continue
            monitors.append((plug_name, x1, y1, x2 - x1, y2 - y1, 1))
            screenlog("monitor %i: %10s coordinates: %s", i, plug_name, geom)
        log("get_shadow_monitors()=%s", monitors)
        return monitors

    def refresh(self) -> bool:
        v = super().refresh()
        if v and SEAMLESS:
            for rwm in self.subsystems["window"].models():
                rwm.refresh_shape()
        log("refresh()=%s", v)
        return v


def main() -> None:
    from xpra.platform import program_context
    with program_context("Shadow-Test", "Shadow Server Screen Capture Test"):
        rwm = CaptureWindowModel(None)
        pngdata = rwm.take_screenshot()
        filename = "screenshot.png"
        with open(filename, "wb") as f:
            f.write(pngdata[4])
        print(f"saved screenshot as {filename}")


if __name__ == "__main__":
    main()
