# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

import os
import errno
import signal
import datetime
import math
from collections import deque
from time import sleep, time, monotonic
from queue import SimpleQueue
from threading import Thread
from typing import Any
from subprocess import Popen, PIPE, STDOUT, TimeoutExpired
from collections.abc import Callable, Sequence

from xpra.platform.gui import (
    get_window_min_size, get_window_max_size,
    get_double_click_time, get_double_click_distance, get_native_system_tray_classes,
)
from xpra.net.common import PacketType
from xpra.exit_codes import ExitCode, ExitValue
from xpra.common import WINDOW_NOT_FOUND, WINDOW_DECODE_SKIPPED, WINDOW_DECODE_ERROR, noerr
from xpra.platform.paths import get_icon_filename, get_resources_dir, get_python_execfile_command
from xpra.scripts.config import FALSE_OPTIONS
from xpra.client.gui.window_border import WindowBorder
from xpra.util.thread import start_thread
from xpra.util.str_fn import std, bytestostr, strtobytes, memoryview_to_bytes
from xpra.os_util import OSX, POSIX, gi_import
from xpra.util.system import is_Ubuntu, is_Wayland
from xpra.util.objects import typedict, make_instance
from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envint, envbool, first_time
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("window")
geomlog = Logger("geometry")
paintlog = Logger("paint")
drawlog = Logger("draw")
focuslog = Logger("focus")
grablog = Logger("grab")
iconlog = Logger("icon")
mouselog = Logger("mouse")
metalog = Logger("metadata")
traylog = Logger("client", "tray")
execlog = Logger("client", "exec")

GLib = gi_import("GLib")

SMOOTH_SCROLL: bool = envbool("XPRA_SMOOTH_SCROLL", True)

PAINT_FAULT_RATE: int = envint("XPRA_PAINT_FAULT_INJECTION_RATE")
PAINT_FAULT_TELL: bool = envbool("XPRA_PAINT_FAULT_INJECTION_TELL", True)
PAINT_DELAY: int = envint("XPRA_PAINT_DELAY", -1)

WM_CLASS_CLOSEEXIT: list[str] = os.environ.get("XPRA_WM_CLASS_CLOSEEXIT", "Xephyr").split(",")
TITLE_CLOSEEXIT: list[str] = os.environ.get("XPRA_TITLE_CLOSEEXIT", "Xnest").split(",")

OR_FORCE_GRAB_STR: str = os.environ.get("XPRA_OR_FORCE_GRAB", "DIALOG:sun-awt-X11")
OR_FORCE_GRAB: dict[str, list[str]] = {}
for s in OR_FORCE_GRAB_STR.split(","):
    if not s:
        continue
    parts = s.split(":")
    if len(parts) == 1:
        OR_FORCE_GRAB.setdefault("*", []).append(s)
    else:
        OR_FORCE_GRAB.setdefault(parts[0], []).append(parts[1])

SKIP_DUPLICATE_BUTTON_EVENTS: bool = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)

DYNAMIC_TRAY_ICON: bool = envbool("XPRA_DYNAMIC_TRAY_ICON", not OSX and not is_Ubuntu())
ICON_OVERLAY: int = envint("XPRA_ICON_OVERLAY", 50)
ICON_SHRINKAGE: int = envint("XPRA_ICON_SHRINKAGE", 75)
SAVE_WINDOW_ICONS: bool = envbool("XPRA_SAVE_WINDOW_ICONS", False)
SAVE_CURSORS: bool = envbool("XPRA_SAVE_CURSORS", False)
POLL_POINTER = envint("XPRA_POLL_POINTER", 0)

DRAW_LOG_FMT = "process_draw: %7i %8s for window %3i, sequence %8i, %4ix%-4i at %4i,%-4i" \
               " using %6s encoding with options=%s"


def find_signal_watcher_command() -> str:
    if not envbool("XPRA_SIGNAL_WATCHER", POSIX and not OSX):
        return ""
    cmd = os.environ.get("XPRA_SIGNAL_WATCHER_COMMAND", "xpra_signal_listener")
    if cmd and os.path.isabs(cmd):
        return cmd
    if cmd:
        for prefix in ("/usr", get_resources_dir()):
            pcmd = prefix + "/libexec/xpra/" + cmd
            if os.path.exists(pcmd):
                return pcmd
    log.warn("Warning: %r not found", cmd)
    return ""


SIGNAL_WATCHER_COMMAND = find_signal_watcher_command()

FAKE_SUSPEND_RESUME: int = envint("XPRA_FAKE_SUSPEND_RESUME", 0)
MOUSE_SCROLL_SQRT_SCALE: bool = envbool("XPRA_MOUSE_SCROLL_SQRT_SCALE", OSX)
MOUSE_SCROLL_MULTIPLIER: int = envint("XPRA_MOUSE_SCROLL_MULTIPLIER", 100)

SHOW_DELAY: int = envint("XPRA_SHOW_DELAY", -1)

DRAW_TYPES: dict[type, str] = {bytes: "bytes", str: "bytes", tuple: "arrays", list: "arrays"}


def kill_signalwatcher(proc) -> None:
    clean_signalwatcher(proc)
    exit_code = proc.poll()
    execlog(f"kill_signalwatcher({proc}) {exit_code=}")
    if exit_code is not None:
        return
    try:
        stdin = proc.stdin
        if stdin:
            stdin.write(b"exit\n")
            stdin.flush()
            stdin.close()
    except OSError:
        execlog.warn("Warning: failed to tell the signal watcher to exit", exc_info=True)
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        execlog.warn("Warning: failed to terminate the signal watcher", exc_info=True)
    try:
        proc.wait(0.01)
    except TimeoutExpired:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except OSError as e:
            if e.errno != errno.ESRCH:
                execlog.warn("Warning: failed to tell the signal watcher to exit", exc_info=True)


def clean_signalwatcher(proc) -> None:
    stdout_io_watch = proc.stdout_io_watch
    if stdout_io_watch:
        proc.stdout_io_watch = 0
        GLib.source_remove(stdout_io_watch)
    stdout = proc.stdout
    if stdout:
        execlog(f"stdout={stdout}")
        noerr(stdout.close)
    stderr = proc.stderr
    if stderr:
        noerr(stderr.close)


def parse_window_size(v, attribute="max-size"):
    if v:
        try:
            pv = tuple(int(x.strip()) for x in v.split("x", 1))
            if len(pv) == 2:
                return pv
        except ValueError:
            # the main script does some checking, but we could be called from a config file launch
            log.warn("Warning: invalid window %s specified: %s", attribute, v)
    return None


def show_border_help() -> None:
    if not first_time("border-help"):
        return
    log.info(" border format: color[,size][:off]")
    log.info("  eg: red,10")
    log.info("  eg: ,5")
    log.info("  eg: auto,5")
    log.info("  eg: blue")


def parse_border(border_str="", display_name="", warn=False) -> WindowBorder:
    # ie: "auto,5:off"
    from xpra.gtk.widget import color_parse
    parts = [x.strip() for x in border_str.replace(",", ":").split(":", 2)]
    color_str = parts[0]
    if color_str.lower() in ("none", "no", "off", "0"):
        return WindowBorder(False)
    if color_str.lower() == "help":
        show_border_help()
        return WindowBorder(False)
    if color_str in ("auto", ""):
        from hashlib import sha256
        m = sha256()
        if display_name:
            m.update(strtobytes(display_name))
        color_str = "#%s" % m.hexdigest()[:6]
        log(f"border color derived from {display_name}: {color_str}")
    try:
        color = color_parse(color_str)
        assert color is not None
    except Exception as e:
        if warn:
            log.warn(f"Warning: invalid border color specified '{color_str!r}'")
            if str(e):
                log.warn(" %s", e)
            show_border_help()
        color = color_parse("red")
    alpha = 0.6
    size = 4
    enabled = parts[-1] != "off"
    if enabled and len(parts) >= 2:
        size_str = parts[1]
        try:
            size = int(size_str)
        except Exception as e:
            if warn:
                log.warn(f"Warning: invalid border size specified {size_str!r}")
                log.warn(f" {e}")
                show_border_help()
        if size <= 0:
            log(f"border size is {size}, disabling it")
            enabled = False
            size = 0
        if size >= 45:
            log.warn(f"Warning: border size is too large: {size}, clipping it")
            size = 45
    border = WindowBorder(enabled, color.red / 65536.0, color.green / 65536.0, color.blue / 65536.0, alpha, size)
    log("parse_border(%s)=%s", border_str, border)
    return border


class WindowClient(StubClientMixin):
    """
    Utility superclass for clients that handle windows:
    create, resize, paint, grabs, etc
    """
    PREFIX = "window"

    def __init__(self):
        self._window_to_id: dict[Any, int] = {}
        self._id_to_window: dict[int, Any] = {}

        self.auto_refresh_delay: int = -1
        self.min_window_size: tuple[int, int] = (0, 0)
        self.max_window_size: tuple[int, int] = (0, 0)

        # draw thread:
        self._draw_queue = SimpleQueue()
        self._draw_thread: Thread | None = None
        self._draw_counter: int = 0

        # statistics and server info:
        self.pixel_counter: deque = deque(maxlen=1000)

        self.readonly: bool = False
        self.windows_enabled: bool = True
        self.pixel_depth: int = 0

        self.server_window_frame_extents: bool = False
        self.server_is_desktop: bool = False
        self.server_window_states: Sequence[str] = ()
        self.server_window_signals: Sequence[str] = ()

        self.server_input_devices = None
        self.server_precise_wheel: bool = False

        self.input_devices = "auto"
        self.border = WindowBorder(False)
        self.border_str = "no"

        self.overlay_image = None

        self.client_supports_system_tray: bool = False
        self.client_supports_bell: bool = False
        self.server_bell: bool = False
        self.bell_enabled: bool = False

        self.window_close_action: str = "forward"
        self.modal_windows: bool = True

        self._pid_to_signalwatcher = {}
        self._signalwatcher_to_wids = {}

        self.wheel_smooth: bool = SMOOTH_SCROLL
        self.wheel_map = {}
        self.wheel_deltax: float = 0
        self.wheel_deltay: float = 0

        # state:
        self.lost_focus_timer: int = 0
        self._focused = None
        self._window_with_grab = None
        self.pointer_grabbed = None
        self._suspended_at: float = 0
        self._button_state = {}
        self.poll_pointer_timer = 0
        self.poll_pointer_position = -1, -1

    def init(self, opts) -> None:
        if opts.system_tray:
            try:
                from xpra.client.gui import client_tray
                assert client_tray
            except ImportError:
                log.warn("Warning: the tray forwarding module is missing")
            else:
                self.client_supports_system_tray = True
        self.client_supports_bell = opts.bell
        self.input_devices = opts.input_devices
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.min_window_size = parse_window_size(opts.min_size) or get_window_min_size()
        self.max_window_size = parse_window_size(opts.max_size) or get_window_max_size()
        self.pixel_depth = int(opts.pixel_depth)
        if self.pixel_depth not in (0, 16, 24, 30) and self.pixel_depth < 32:
            log.warn("Warning: invalid pixel depth %i", self.pixel_depth)
            self.pixel_depth = 0

        self.windows_enabled = opts.windows
        if self.windows_enabled:
            if opts.window_close not in ("forward", "ignore", "disconnect", "shutdown", "auto"):
                self.window_close_action = "forward"
                log.warn("Warning: invalid 'window-close' option: '%s'", opts.window_close)
                log.warn(" using '%s'", self.window_close_action)
            else:
                self.window_close_action = opts.window_close
        self.modal_windows = self.windows_enabled and opts.modal_windows

        self.border_str = opts.border
        if opts.border:
            self.border = parse_border(self.border_str)

        # mouse wheel:
        mw = (opts.mousewheel or "").lower().replace("-", "").split(",")
        if "coarse" in mw:
            mw.remove("coarse")
            self.wheel_smooth = False
        if not any(x in FALSE_OPTIONS for x in mw):
            UP = 4
            LEFT = 6
            Z1 = 8
            invertall = len(mw) == 1 and mw[0] in ("invert", "invertall")
            for i in range(20):
                btn = 4 + i * 2
                invert = any((
                    invertall,
                    btn == UP and "inverty" in mw,
                    btn == LEFT and "invertx" in mw,
                    btn == Z1 and "invertz" in mw,
                ))
                if not invert:
                    self.wheel_map[btn] = btn
                    self.wheel_map[btn + 1] = btn + 1
                else:
                    self.wheel_map[btn + 1] = btn
                    self.wheel_map[btn] = btn + 1
        mouselog("wheel_map(%s)=%s, wheel_smooth=%s", mw, self.wheel_map, self.wheel_smooth)

        if 0 < ICON_OVERLAY <= 100:
            icon_filename = opts.tray_icon
            if icon_filename and not os.path.isabs(icon_filename):
                icon_filename = get_icon_filename(icon_filename)
            if not icon_filename or not os.path.exists(icon_filename):
                icon_filename = get_icon_filename("xpra")
            traylog("window icon overlay: %s", icon_filename)
            if icon_filename:
                # pylint: disable=import-outside-toplevel
                # make sure Pillow's PNG image loader doesn't spam the output with debug messages:
                import logging
                logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)
                try:
                    from PIL import Image
                except ImportError:
                    log.info("window icon overlay requires python-pillow")
                else:
                    with log.trap_error(f"Error: failed to load overlay icon {icon_filename!r}"):
                        self.overlay_image = Image.open(icon_filename)
        traylog("overlay_image=%s", self.overlay_image)

    def setup_connection(self, conn) -> None:
        display_name = getattr(self, "display_desc", {}).get("display_name", "")
        if display_name:
            # now that we have display_desc, parse the border again:
            self.border = parse_border(self.border_str, display_name)

    def run(self) -> ExitValue:
        # we decode pixel data in this thread
        self._draw_thread = start_thread(self._draw_thread_loop, "draw")
        if FAKE_SUSPEND_RESUME:
            GLib.timeout_add(FAKE_SUSPEND_RESUME * 1000, self.suspend)
            GLib.timeout_add(FAKE_SUSPEND_RESUME * 1000 * 2, self.resume)
        return ExitCode.OK

    def cleanup(self) -> None:
        log("WindowClient.cleanup()")
        # tell the draw thread to exit:
        dq = self._draw_queue
        if dq:
            dq.put(None)
        # the protocol has been closed, it is now safe to close all the windows:
        # (cleaner and needed when we run embedded in the client launcher)
        self.destroy_all_windows()
        self.cancel_lost_focus_timer()
        self.cancel_poll_pointer_timer()
        if dq:
            dq.put(None)
        dt = self._draw_thread
        log("WindowClient.cleanup() draw thread=%s, alive=%s", dt, dt and dt.is_alive())
        if dt and dt.is_alive():
            dt.join(0.1)
        log("WindowClient.cleanup() done")

    def set_modal_windows(self, modal_windows) -> None:
        self.modal_windows = modal_windows
        # re-set flag on all the windows:
        for w in self._id_to_window.values():
            modal = w._metadata.boolget("modal", False)
            w.set_modal(modal)

    def window_bell(self, window, device, percent: int, pitch: int, duration: int, bell_class,
                    bell_id: int, bell_name: str) -> None:
        raise NotImplementedError()

    def get_info(self) -> dict[str, Any]:
        info: dict[Any, Any] = {
            "count": len(self._window_to_id),
            "min-size": self.min_window_size,
            "max-size": self.max_window_size,
            "draw-counter": self._draw_counter,
            "read-only": self.readonly,
            "wheel": {
                "delta-x": int(self.wheel_deltax * 1000),
                "delta-y": int(self.wheel_deltay * 1000),
            },
            "focused": self._focused or 0,
            "grabbed": self._window_with_grab or 0,
            "pointer-grab": self.pointer_grabbed or 0,
            "buttons": self._button_state,
        }
        for wid, window in tuple(self._id_to_window.items()):
            info[wid] = window.get_info()
        winfo: dict[str, Any] = {"windows": info}
        return winfo

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        # FIXME: the messy bits without proper namespace:
        caps = {
            # generic server flags:
            "mouse": {
                "show": True,  # assumed available in v6
                "initial-position": self.get_mouse_position(),
            },
            "double_click": {
                "time": get_double_click_time(),
                "distance": get_double_click_distance(),
            },
            # features:
            "bell": self.client_supports_bell,
            "windows": self.windows_enabled,
            "auto_refresh_delay": int(self.auto_refresh_delay * 1000),
            # system tray forwarding:
            "system_tray": self.client_supports_system_tray,
            "window": self.get_window_caps(),
            "encoding": {
                "eos": True,
            },
        }
        return caps

    def get_window_caps(self) -> dict[str, Any]:
        return {
            # implemented in the gtk client:
            "min-size": self.min_window_size,
            "max-size": self.max_window_size,
            "restack": True,
            "pre-map": True,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_window_frame_extents = c.boolget("window.frame-extents")
        self.server_bell = c.boolget("bell")  # added in 0.5, default to True!
        self.bell_enabled = self.server_bell and self.client_supports_bell
        if not c.boolget("windows", True):
            log.warn("Warning: window forwarding is not enabled on this server")
        self.server_window_signals = c.strtupleget("window.signals")
        self.server_window_states = c.strtupleget("window.states", (
            "iconified", "fullscreen",
            "above", "below",
            "sticky", "iconified", "maximized",
        ))
        self.server_is_desktop = c.boolget("shadow") or c.boolget("desktop")
        # input devices:
        self.server_input_devices = c.strget("input-devices")
        self.server_precise_wheel = c.boolget("wheel.precise", False)
        if POLL_POINTER:
            if is_Wayland():
                log.warn("Warning: pointer polling is unlikely to work under Wayland")
                log.warn(" and may cause problems")
            self.poll_pointer_timer = GLib.timeout_add(POLL_POINTER, self.poll_pointer)
        return True

    ######################################################################
    # pointer:
    def _process_pointer_position(self, packet: PacketType) -> None:
        wid, x, y = packet[1:4]
        if len(packet) >= 6:
            rx, ry = packet[4:6]
        else:
            rx, ry = -1, -1
        cx, cy = self.get_mouse_position()
        start_time = monotonic()
        mouselog("process_pointer_position: %i,%i (%i,%i relative to wid %i) - current position is %i,%i",
                 x, y, rx, ry, wid, cx, cy)
        size = 10
        for i, w in self._id_to_window.items():
            # not all window implementations have this method:
            # (but GLClientWindow does)
            show_pointer_overlay = getattr(w, "show_pointer_overlay", None)
            if show_pointer_overlay:
                if i == wid:
                    value = rx, ry, size, start_time
                else:
                    value = None
                show_pointer_overlay(value)

    def send_wheel_delta(self, device_id: int, wid: int, button: int, distance, pointer=None, props=None) -> float:
        modifiers = self.get_current_modifiers()
        buttons: Sequence[int] = ()
        mouselog("send_wheel_deltas%s precise wheel=%s, modifiers=%s, pointer=%s",
                 (device_id, wid, button, distance, pointer, props), self.server_precise_wheel, modifiers, pointer)
        if self.server_precise_wheel:
            # send the exact value multiplied by 1000 (as an int)
            idist = round(distance * 1000)
            if abs(idist) > 0:
                packet = ["wheel-motion", wid,
                          button, idist,
                          pointer, modifiers, buttons] + list((props or {}).values())
                mouselog("send_wheel_delta(..) %s", packet)
                self.send_positional(*packet)
            return 0
        # server cannot handle precise wheel,
        # so we have to use discrete events,
        # and send a click for each step:
        scaled_distance = abs(distance * MOUSE_SCROLL_MULTIPLIER / 100)
        if MOUSE_SCROLL_SQRT_SCALE:
            scaled_distance = math.sqrt(scaled_distance)
        steps = round(scaled_distance)
        for _ in range(steps):
            for state in True, False:
                self.send_button(device_id, wid, button, state, pointer, modifiers, buttons, props)
        # return remainder:
        scaled_remainder: float = steps
        if MOUSE_SCROLL_SQRT_SCALE:
            scaled_remainder = steps ** 2
        scaled_remainder = scaled_remainder * (100 / float(MOUSE_SCROLL_MULTIPLIER))
        remain_distance = float(scaled_remainder)
        signed_remain_distance = remain_distance * (-1 if distance < 0 else 1)
        return float(distance) - signed_remain_distance

    def wheel_event(self, device_id=-1, wid=0, deltax=0, deltay=0, pointer=(), props=None) -> None:
        # this is a different entry point for mouse wheel events,
        # which provides finer grained deltas (if supported by the server)
        # accumulate deltas:
        self.wheel_deltax += deltax
        self.wheel_deltay += deltay
        button = self.wheel_map.get(6 + int(self.wheel_deltax > 0), 0)  # RIGHT=7, LEFT=6
        if button > 0:
            self.wheel_deltax = self.send_wheel_delta(device_id, wid, button, self.wheel_deltax, pointer, props)
        button = self.wheel_map.get(5 - int(self.wheel_deltay > 0), 0)  # UP=4, DOWN=5
        if button > 0:
            self.wheel_deltay = self.send_wheel_delta(device_id, wid, button, self.wheel_deltay, pointer, props)
        mouselog("wheel_event%s new deltas=%s,%s",
                 (device_id, wid, deltax, deltay), self.wheel_deltax, self.wheel_deltay)

    def send_button(self, device_id: int, wid: int, button: int, pressed: bool,
                    pointer, modifiers, buttons, props) -> None:
        pressed_state = self._button_state.get(button, False)
        if SKIP_DUPLICATE_BUTTON_EVENTS and pressed_state == pressed:
            mouselog("button action: unchanged state, ignoring event")
            return
        # map wheel buttons via translation table to support inverted axes:
        server_button = button
        if button > 3:
            server_button = self.wheel_map.get(button, -1)
        server_buttons = []
        for b in buttons:
            if b > 3:
                sb = self.wheel_map.get(button)
                if not sb:
                    continue
                b = sb
            server_buttons.append(b)
        self._button_state[button] = pressed
        if "pointer-button" in self.server_packet_types:
            props = props or {}
            if modifiers is not None:
                props["modifiers"] = modifiers
            props["buttons"] = server_buttons
            if server_button != button:
                props["raw-button"] = button
            if server_buttons != buttons:
                props["raw-buttons"] = buttons
            seq = self.next_pointer_sequence(device_id)
            packet = ["pointer-button", device_id, seq, wid, server_button, pressed, pointer, props]
        else:
            if server_button == -1:
                return
            packet = ["button-action", wid, server_button, pressed, pointer, modifiers, server_buttons]
            if props:
                packet += list(props.values())
        mouselog("button packet: %s", packet)
        self.send_positional(*packet)

    def scale_pointer(self, pointer) -> tuple[int, int]:
        # subclass may scale this:
        # return int(pointer[0]/self.xscale), int(pointer[1]/self.yscale)
        return round(pointer[0]), round(pointer[1])

    def send_input_devices(self, fmt: str, input_devices: dict[int, dict[str, Any]]) -> None:
        assert self.server_input_devices
        self.send("input-devices", fmt, input_devices)

    def poll_pointer(self) -> bool:
        pos = self.get_mouse_position()
        if pos != self.poll_pointer_position:
            self.poll_pointer_position = pos
            device_id = -1
            wid = 0
            mouselog(f"poll_pointer() updated position: {pos}")
            self.send_mouse_position(device_id, wid, pos)
        return True

    def cook_metadata(self, _new_window, metadata: dict) -> typedict:
        # subclasses can apply tweaks here:
        return typedict(metadata)

    ######################################################################
    # system tray
    def _process_new_tray(self, packet: PacketType) -> None:
        assert self.client_supports_system_tray
        self._ui_event()
        wid, w, h = packet[1:4]
        w = max(1, self.sx(w))
        h = max(1, self.sy(h))
        metadata = typedict()
        if len(packet) >= 5:
            metadata = typedict(packet[4])
        traylog("tray %i metadata=%s", wid, metadata)
        assert wid not in self._id_to_window, "we already have a window %s: %s" % (wid, self._id_to_window.get(wid))
        app_id = wid
        tray = self.setup_system_tray(self, app_id, wid, w, h, metadata)
        traylog("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid

    def make_system_tray(self, *args):
        """ tray used for application systray forwarding """
        tc = self.get_system_tray_classes()
        traylog("make_system_tray%s system tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    # noinspection PyMethodMayBeStatic
    def get_system_tray_classes(self) -> list[type]:
        # subclasses may add their toolkit specific variants, if any
        # by overriding this method
        # use the native ones first:
        return get_native_system_tray_classes()

    def setup_system_tray(self, client, app_id, wid, w, h, metadata):
        tray_widget = None

        # this is a tray forwarded for a remote application

        def tray_click(button, pressed, event_time=0):
            tray = self._id_to_window.get(wid)
            traylog("tray_click(%s, %s, %s) tray=%s", button, pressed, event_time, tray)
            if tray:
                x, y = self.get_mouse_position()
                modifiers = self.get_current_modifiers()
                button_packet = ["button-action", wid, button, pressed, (x, y), modifiers]
                traylog("button_packet=%s", button_packet)
                self.send_positional(*button_packet)
                tray.reconfigure()

        def tray_mouseover(x, y):
            tray = self._id_to_window.get(wid)
            traylog("tray_mouseover(%s, %s) tray=%s", x, y, tray)
            if tray:
                modifiers = self.get_current_modifiers()
                device_id = -1
                self.send_mouse_position(device_id, wid, self.cp(x, y), modifiers)

        def do_tray_geometry(*args):
            # tell the "ClientTray" where it now lives
            # which should also update the location on the server if it has changed
            tray = self._id_to_window.get(wid)
            if tray_widget:
                geom = tray_widget.get_geometry()
            else:
                geom = None
            traylog("tray_geometry(%s) widget=%s, geometry=%s tray=%s", args, tray_widget, geom, tray)
            if tray and geom:
                tray.move_resize(*geom)

        def tray_geometry(*args):
            # the tray widget may still be None if we haven't returned from make_system_tray yet,
            # in which case we will check the geometry a little bit later:
            if tray_widget:
                do_tray_geometry(*args)
            else:
                GLib.idle_add(do_tray_geometry, *args)

        def tray_exit(*args):
            traylog("tray_exit(%s)", args)

        title = metadata.strget("title")
        tray_widget = self.make_system_tray(app_id, None, title, "",
                                            tray_geometry, tray_click, tray_mouseover, tray_exit)
        traylog("setup_system_tray%s tray_widget=%s", (client, app_id, wid, w, h, title), tray_widget)
        assert tray_widget, "could not instantiate a system tray for tray id %s" % wid
        tray_widget.show()
        from xpra.client.gui.client_tray import ClientTray
        mmap = getattr(self, "mmap", None)
        return ClientTray(client, wid, w, h, metadata, tray_widget, mmap)

    def get_tray_window(self, app_name: str, hints):
        # try to identify the application tray that generated this notification,
        # so we can show it as coming from the correct systray icon
        # on platforms that support it (ie: win32)
        trays = tuple(w for w in self._id_to_window.values() if w.is_tray())
        if trays:
            try:
                pid = int(hints.get("pid") or 0)
            except (TypeError, ValueError):
                pass
            else:
                if pid:
                    for tray in trays:
                        metadata: typedict = typedict(getattr(tray, "_metadata", {}))
                        if metadata.intget("pid") == pid:
                            traylog("tray window: matched pid=%i", pid)
                            return tray.tray_widget
            if app_name and app_name.lower() != "xpra":
                # exact match:
                for tray in trays:
                    # traylog("window %s: is_tray=%s, title=%s", window,
                    #    window.is_tray(), getattr(window, "title", None))
                    if tray.title == app_name:
                        return tray.tray_widget
                for tray in trays:
                    if tray.title.find(app_name) >= 0:
                        return tray.tray_widget
        return self.tray

    def set_tray_icon(self) -> None:
        # find all the window icons,
        # and if they are all using the same one, then use it as tray icon
        # otherwise use the default icon
        traylog("set_tray_icon() DYNAMIC_TRAY_ICON=%s, tray=%s", DYNAMIC_TRAY_ICON, self.tray)
        if not self.tray:
            return
        if not DYNAMIC_TRAY_ICON:
            # the icon ends up looking garbled on win32,
            # and we somehow also lose the settings that can keep us in the visible systray list
            # so don't bother
            return
        windows = tuple(w for w in self._window_to_id if not w.is_tray())
        # get all the icons:
        icons = tuple(getattr(w, "_current_icon", None) for w in windows)
        missing = sum(1 for icon in icons if icon is None)
        traylog("set_tray_icon() %i windows, %i icons, %i missing", len(windows), len(icons), missing)
        if icons and not missing:
            icon = icons[0]
            for i in icons[1:]:
                if i != icon:
                    # found a different icon
                    icon = None
                    break
            if icon:
                has_alpha = icon.mode == "RGBA"
                width, height = icon.size
                traylog("set_tray_icon() using unique %s icon: %ix%i (has-alpha=%s)",
                        icon.mode, width, height, has_alpha)
                rowstride = width * (3 + int(has_alpha))
                rgb_data = icon.tobytes("raw", icon.mode)
                self.tray.set_icon_from_data(rgb_data, has_alpha, width, height, rowstride)
                return
        # this sets the default icon (badly named function!)
        traylog("set_tray_icon() using default icon")
        self.tray.set_icon()

    ######################################################################
    # combine the window icon with our own icon
    def _window_icon_image(self, wid: int, width: int, height: int, coding: str, data):
        # convert the data into a pillow image,
        # adding the icon overlay (if enabled)
        coding = bytestostr(coding)
        try:
            # pylint: disable=import-outside-toplevel
            from PIL import Image
        except ImportError:
            if first_time("window-icons-require-pillow"):
                log.info("showing window icons requires python-pillow")
            return None
        iconlog("%s.update_icon(%s, %s, %s, %s bytes) ICON_SHRINKAGE=%s, ICON_OVERLAY=%s",
                self, width, height, coding, len(data), ICON_SHRINKAGE, ICON_OVERLAY)
        if coding == "default":
            img = self.overlay_image
        elif coding in ("BGRA", "RGBA"):
            rowstride = width * 4
            img = Image.frombytes("RGBA", (width, height), memoryview_to_bytes(data),
                                  "raw", coding, rowstride, 1)
        else:
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.pillow.decoder import open_only
            img = open_only(data, ("png",))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        icon = img
        save_time = int(time())
        if SAVE_WINDOW_ICONS:
            filename = "client-window-%i-icon-%i.png" % (wid, save_time)
            icon.save(filename, "png")
            iconlog("client window icon saved to %s", filename)
        if self.overlay_image and self.overlay_image != img:
            try:
                LANCZOS = Image.Resampling.LANCZOS
            except AttributeError:
                LANCZOS = Image.LANCZOS
            if 0 < ICON_SHRINKAGE < 100:
                # paste the application icon in the top-left corner,
                # shrunk by ICON_SHRINKAGE pct
                shrunk_width = max(1, width * ICON_SHRINKAGE // 100)
                shrunk_height = max(1, height * ICON_SHRINKAGE // 100)
                icon_resized = icon.resize((shrunk_width, shrunk_height), LANCZOS)
                icon = Image.new("RGBA", (width, height))
                icon.paste(icon_resized, (0, 0, shrunk_width, shrunk_height))
                if SAVE_WINDOW_ICONS:
                    filename = "client-window-%i-icon-shrunk-%i.png" % (wid, save_time)
                    icon.save(filename, "png")
                    iconlog("client shrunk window icon saved to %s", filename)
            assert 0 < ICON_OVERLAY <= 100
            overlay_width = max(1, width * ICON_OVERLAY // 100)
            overlay_height = max(1, height * ICON_OVERLAY // 100)
            xpra_resized = self.overlay_image.resize((overlay_width, overlay_height), LANCZOS)
            xpra_corner = Image.new("RGBA", (width, height))
            xpra_corner.paste(xpra_resized, (width - overlay_width, height - overlay_height, width, height))
            if SAVE_WINDOW_ICONS:
                filename = "client-window-%i-icon-xpracorner-%i.png" % (wid, save_time)
                xpra_corner.save(filename, "png")
                iconlog("client xpracorner window icon saved to %s", filename)
            composite = Image.alpha_composite(icon, xpra_corner)
            icon = composite
            if SAVE_WINDOW_ICONS:
                filename = "client-window-%i-icon-composited-%i.png" % (wid, save_time)
                icon.save(filename, "png")
                iconlog("client composited window icon saved to %s", filename)
        return icon

    ######################################################################
    # regular windows:
    def _process_new_common(self, packet: PacketType, override_redirect):
        self._ui_event()
        wid, x, y, w, h = (int(item) for item in packet[1:6])
        assert 0 <= w < 32768 and 0 <= h < 32768
        metadata = self.cook_metadata(True, packet[6])
        metalog("process_new_common: %s, metadata=%s, OR=%s", packet[1:7], metadata, override_redirect)
        assert wid not in self._id_to_window, "we already have a window {}: {}".format(wid, self._id_to_window.get(wid))
        if w < 1 or h < 1:
            log.error("Error: window %i dimensions %ix%i are invalid", wid, w, h)
            w, h = 1, 1
        rel_pos = metadata.inttupleget("relative-position")
        parent = metadata.intget("parent")
        geomlog("relative-position=%s (parent=%s)", rel_pos, parent)
        if parent and rel_pos:
            pwin = self._id_to_window.get(parent)
            if pwin:
                # apply scaling to relative position:
                p_pos = pwin.sp(*rel_pos)
                x = pwin._pos[0] + p_pos[0]
                y = pwin._pos[1] + p_pos[1]
                geomlog("relative position(%s)=%s", rel_pos, (x, y))
        # scaled dimensions of window:
        wx = self.sx(x)
        wy = self.sy(y)
        ww = max(1, self.sx(w))
        wh = max(1, self.sy(h))
        # backing size, same as original (server-side):
        bw, bh = w, h
        client_properties = {}
        if len(packet) >= 8:
            client_properties = dict(packet[7])
        geomlog("process_new_common: wid=%i, OR=%s, geometry(%s)=%s / %s",
                wid, override_redirect, packet[2:6], (wx, wy, ww, wh), (bw, bh))
        return self.make_new_window(wid, wx, wy, ww, wh, bw, bh, metadata, override_redirect, client_properties)

    def _find_pid_focused_window(self, pid: int, OR=False) -> int:
        for twid, twin in self._id_to_window.items():
            if twin.is_tray():
                continue
            if twin.is_OR() != OR:
                continue
            if twin._metadata.intget("pid", -1) == pid:
                if OR or twid == self._focused:
                    return twid
        return 0

    def patch_OR_popup_transient_for(self, metadata: typedict) -> None:
        pid = metadata.intget("pid", 0)
        twid = metadata.intget("transient-for", 0)
        if is_Wayland():
            # if this is a sub-popup (ie: a submenu),
            # then GTK-Wayland refuses to show it unless we set transient-for
            # to point to the parent popup.
            # Even if under X11, `WM_TRANSIENT_FOR` points to the parent / top-level window...
            twid = self._find_pid_focused_window(pid, True)
        # try to ensure popup windows have a transient-for:
        if not twid:
            twid = self._find_pid_focused_window(pid)
        if twid:
            metadata["transient-for"] = twid

    def make_new_window(self, wid: int, wx: int, wy: int, ww: int, wh: int, bw: int, bh: int,
                        metadata: typedict, override_redirect: bool, client_properties):
        client_window_classes = self.get_client_window_classes(ww, wh, metadata, override_redirect)
        group_leader_window = self.get_group_leader(wid, metadata, override_redirect)
        # workaround for "popup" OR windows without a transient-for (like: google chrome popups):
        # prevents them from being pushed under other windows on OSX
        # find a "transient-for" value using the pid to find a suitable window
        # if possible, choosing the currently focused window (if there is one..)
        pid = metadata.intget("pid", 0)
        watcher_pid = self.assign_signal_watcher_pid(wid, pid, metadata.strget("title"))
        if override_redirect and metadata.strget("role").lower() == "popup" and pid:
            self.patch_OR_popup_transient_for(metadata)
        border = None
        if self.border:
            border = self.border.clone()
        window = None
        log("make_new_window(..) client_window_classes=%s, group_leader_window=%s",
            client_window_classes, group_leader_window)
        for cwc in client_window_classes:
            try:
                default_cursor_data = getattr(self, "default_cursor_data", None)
                window = cwc(self, group_leader_window, watcher_pid, wid,
                             wx, wy, ww, wh, bw, bh,
                             metadata, override_redirect, client_properties,
                             border, self.max_window_size, default_cursor_data, self.pixel_depth,
                             self.headerbar)
                break
            except (RuntimeError, ValueError):
                log.warn(f"Warning: failed to instantiate {cwc!r}", exc_info=True)
        if window is None:
            log.warn("no more options.. this window will not be shown, sorry")
            return None
        log("make_new_window(..) window(%i)=%s", wid, window)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        if SHOW_DELAY >= 0:
            GLib.timeout_add(SHOW_DELAY, self.show_window, wid, window, metadata, override_redirect)
        else:
            self.show_window(wid, window, metadata, override_redirect)
        return window

    def show_window(self, wid: int, window, metadata, override_redirect: bool) -> None:
        window.show_all()
        if override_redirect and self.should_force_grab(metadata):
            grablog.warn("forcing grab for OR window %i, matches %s", wid, OR_FORCE_GRAB)
            self.window_grab(wid, window)

    def should_force_grab(self, metadata: typedict) -> bool:
        if not OR_FORCE_GRAB:
            return False
        window_types = metadata.get("window-type", [])
        wm_class = metadata.strtupleget("class-instance", (None, None), 2, 2)
        c = None
        if wm_class:
            c = wm_class[0]
        if c:
            for window_type, force_wm_classes in OR_FORCE_GRAB.items():
                # ie: DIALOG : ["sun-awt-X11"]
                if window_type == "*" or window_type in window_types:
                    for wmc in force_wm_classes:
                        if wmc == "*" or c and c.startswith(wmc):
                            return True
        return False

    ######################################################################
    # listen for process signals using a watcher process:
    def assign_signal_watcher_pid(self, wid: int, pid: int, title="") -> int:
        if not SIGNAL_WATCHER_COMMAND or not pid:
            return 0
        proc = self._pid_to_signalwatcher.get(pid)
        if proc is None or proc.poll():
            from xpra.util.child_reaper import getChildReaper
            if not title:
                title = str(pid)
            cmd = get_python_execfile_command() + [SIGNAL_WATCHER_COMMAND] + [f"signal watcher for {std(title)}"]
            execlog(f"assign_signal_watcher_pid({wid}, {pid}) starting {cmd}")
            try:
                proc = Popen(cmd,
                             stdin=PIPE, stdout=PIPE, stderr=STDOUT,
                             start_new_session=True)
            except OSError as e:
                execlog("assign_signal_watcher_pid(%s, %s)", wid, pid, exc_info=True)
                execlog.error("Error: cannot execute signal listener")
                execlog.estr(e)
                proc = None
            if proc and proc.poll() is None:
                proc.stdout_io_watch = 0

                def watcher_terminated(*args):
                    # watcher process terminated, remove io watch:
                    # this may be redundant since we also return False from signal_watcher_event
                    execlog("watcher_terminated%s", args)
                    clean_signalwatcher(proc)

                getChildReaper().add_process(proc, "signal listener for remote process %s" % pid,
                                             command="xpra_signal_listener", ignore=True, forget=True,
                                             callback=watcher_terminated)
                execlog("using watcher pid=%i for server pid=%i", proc.pid, pid)
                self._pid_to_signalwatcher[pid] = proc
                ioc = GLib.IOCondition
                proc.stdout_io_watch = GLib.io_add_watch(proc.stdout,
                                                         GLib.PRIORITY_DEFAULT, ioc.IN | ioc.HUP | ioc.ERR,
                                                         self.signal_watcher_event, proc, pid, wid)
        if proc:
            self._signalwatcher_to_wids.setdefault(proc, []).append(wid)
            return proc.pid
        return 0

    def signal_watcher_event(self, fd, cb_condition, proc, pid: int, wid: int) -> bool:
        execlog("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid))
        if cb_condition in (GLib.IOCondition.HUP, GLib.IOCondition.ERR):
            kill_signalwatcher(proc)
            proc.stdout_io_watch = None
            return False
        if proc.stdout_io_watch is None:
            # no longer watched
            return False
        if cb_condition == GLib.IOCondition.IN:
            try:
                signame = bytestostr(proc.stdout.readline()).strip("\n\r")
                execlog("signal_watcher_event: %s", signame)
                if signame:
                    if signame in self.server_window_signals:
                        self.send("window-signal", wid, signame)
                    else:
                        execlog(f"Warning: signal {signame!r} cannot be forwarded to this server")
            except Exception as e:
                log.error("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid), exc_info=True)
                log.error("Error: processing signal watcher output for pid %i of window %i", pid, wid)
                log.estr(e)
        if proc.poll():
            # watcher ended, stop watching its stdout
            proc.stdout_io_watch = None
            return False
        return True

    def freeze(self) -> None:
        log("freeze()")
        for window in self._id_to_window.values():
            window.freeze()

    def unfreeze(self) -> None:
        log("unfreeze()")
        for window in self._id_to_window.values():
            window.unfreeze()

    def deiconify_windows(self) -> None:
        log("deiconify_windows()")
        for window in self._id_to_window.values():
            deiconify = getattr(window, "deiconify", None)
            if deiconify:
                deiconify()

    def resize_windows(self, new_size_fn: Callable) -> None:
        for window in self._id_to_window.values():
            if window:
                ww, wh = window._size
                nw, nh = new_size_fn(ww, wh)
                # this will apply the new scaling value to the size constraints:
                window.reset_size_constraints()
                window.resize(nw, nh)
        self.send_refresh_all()

    def reinit_window_icons(self) -> None:
        # make sure the window icons are the ones we want:
        iconlog("reinit_window_icons()")
        for wid in tuple(self._id_to_window.keys()):
            window = self._id_to_window.get(wid)
            if window:
                reset_icon = getattr(window, "reset_icon", None)
                if reset_icon:
                    reset_icon()

    def reinit_windows(self, new_size_fn=None) -> None:
        # now replace all the windows with new ones:
        for wid in tuple(self._id_to_window.keys()):
            window = self._id_to_window.get(wid)
            if window:
                self.reinit_window(wid, window, new_size_fn)
        self.send_refresh_all()

    def reinit_window(self, wid: int, window, new_size_fn=None) -> None:
        geomlog("reinit_window%s", (wid, window, new_size_fn))

        def fake_send(*args):
            log("fake_send%s", args)

        if window.is_tray():
            # trays are never GL enabled, so don't bother re-creating them
            # might cause problems anyway if we did
            # just send a configure event in case they are moved / scaled
            window.send_configure()
            return
        # ignore packets from old window:
        window.send = fake_send
        # copy attributes:
        x, y = window._pos
        ww, wh = window._size
        if new_size_fn:
            ww, wh = new_size_fn(ww, wh)
        try:
            bw, bh = window._backing.size
        except (AttributeError, ValueError, TypeError):
            bw, bh = ww, wh
        client_properties = window._client_properties
        resize_counter = window._resize_counter
        metadata = window._metadata
        override_redirect = window._override_redirect
        backing = window._backing
        current_icon = window._current_icon
        video_decoder, csc_decoder, decoder_lock = None, None, None
        try:
            if backing:
                video_decoder = backing._video_decoder
                csc_decoder = backing._csc_decoder
                decoder_lock = backing._decoder_lock
                if decoder_lock:
                    decoder_lock.acquire()
                    log("reinit_windows() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                    backing._video_decoder = None
                    backing._csc_decoder = None
                    backing._decoder_lock = None
                    backing.close()

            # now we can unmap it:
            self.destroy_window(wid, window)
            # explicitly tell the server we have unmapped it:
            # (so it will reset the video encoders, etc)
            if not window.is_OR():
                self.send("unmap-window", wid)
            self._id_to_window.pop(wid, None)
            self._window_to_id.pop(window, None)
            # create the new window,
            # which should honour the new state of the opengl_enabled flag if that's what we changed,
            # or the new dimensions, etc
            window = self.make_new_window(wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties)
            window._resize_counter = resize_counter
            # if we had a backing already,
            # restore the attributes we had saved from it
            if backing:
                backing = window._backing
                backing._video_decoder = video_decoder
                backing._csc_decoder = csc_decoder
                backing._decoder_lock = decoder_lock
            if current_icon:
                window.update_icon(current_icon)
        finally:
            if decoder_lock:
                decoder_lock.release()

    def get_group_leader(self, _wid: int, _metadata, _override_redirect) -> Any:
        # subclasses that wish to implement the feature may override this method
        return None

    def get_client_window_classes(self, _w, _h, _metadata, _override_redirect) -> Sequence[type]:
        return (self.ClientWindowClass,)

    def _process_new_window(self, packet: PacketType) -> None:
        return self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet: PacketType) -> None:
        if self.modal_windows:
            # find any modal windows and remove the flag
            # so that the OR window can get the focus
            # (it will be re-enabled when the OR window disappears)
            for wid, window in self._id_to_window.items():
                if window.is_OR() or window.is_tray():
                    continue
                if window.get_modal():
                    metalog("temporarily removing modal flag from %s", wid)
                    window.set_modal(False)
        return self._process_new_common(packet, True)

    def _process_initiate_moveresize(self, packet: PacketType) -> None:
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            x_root, y_root, direction, button, source_indication = packet[2:7]
            window.initiate_moveresize(self.sx(x_root), self.sy(y_root), direction, button, source_indication)

    def _process_window_metadata(self, packet: PacketType) -> None:
        wid, metadata = packet[1:3]
        metalog("metadata update for window %i: %s", wid, metadata)
        window = self._id_to_window.get(wid)
        if window:
            metadata = self.cook_metadata(False, metadata)
            window.update_metadata(metadata)

    def _process_window_icon(self, packet: PacketType) -> None:
        wid, w, h, coding, data = packet[1:6]
        img = self._window_icon_image(wid, w, h, coding, data)
        window = self._id_to_window.get(wid)
        iconlog("_process_window_icon(%s, %s, %s, %s, %s bytes) image=%s, window=%s",
                wid, w, h, coding, len(data), img, window)
        if window and img:
            window.update_icon(img)
            self.set_tray_icon()

    def _process_window_move_resize(self, packet: PacketType) -> None:
        wid, x, y, w, h = (int(item) for item in packet[1:6])
        ax = self.sx(x)
        ay = self.sy(y)
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        resize_counter = -1
        if len(packet) > 6:
            resize_counter = int(packet[6])
        window = self._id_to_window.get(wid)
        geomlog("_process_window_move_resize%s moving / resizing window %s (id=%s) to %s",
                packet[1:], window, wid, (ax, ay, aw, ah))
        if window:
            window.move_resize(ax, ay, aw, ah, resize_counter)

    def _process_window_resized(self, packet: PacketType) -> None:
        wid = int(packet[1])
        w = int(packet[2])
        h = int(packet[3])
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        resize_counter = -1
        if len(packet) > 4:
            resize_counter = int(packet[4])
        window = self._id_to_window.get(wid)
        geomlog("_process_window_resized%s resizing window %s (id=%s) to %s", packet[1:], window, wid, (aw, ah))
        if window:
            window.resize(aw, ah, resize_counter)

    def _process_raise_window(self, packet: PacketType) -> None:
        # implemented in gtk subclass
        pass

    def _process_restack_window(self, packet: PacketType) -> None:
        # implemented in gtk subclass
        pass

    def _process_configure_override_redirect(self, packet: PacketType) -> None:
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window.get(wid)
        ax = self.sx(x)
        ay = self.sy(y)
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        geomlog("_process_configure_override_redirect%s move resize window %s (id=%s) to %s",
                packet[1:], window, wid, (ax, ay, aw, ah))
        if window:
            window.move_resize(ax, ay, aw, ah, -1)

    # noinspection PyUnreachableCode
    def window_close_event(self, wid: int) -> None:
        log("window_close_event(%s) close window action=%s", wid, self.window_close_action)
        if self.window_close_action == "forward":
            self.send("close-window", wid)
        elif self.window_close_action == "ignore":
            log("close event for window %i ignored", wid)
        elif self.window_close_action == "disconnect":
            log.info("window-close set to disconnect, exiting (window %i)", wid)
            self.quit(0)
        elif self.window_close_action == "shutdown":
            self.send("shutdown-server", "shutdown on window close")
        elif self.window_close_action == "auto":
            # forward unless this looks like a desktop,
            # this allows us to behave more like VNC:
            window = self._id_to_window.get(wid)
            log("window_close_event(%i) window=%s", wid, window)
            if self.server_is_desktop:
                log.info("window-close event on desktop or shadow window, disconnecting")
                self.quit(0)
                return
            if window:
                metadata = typedict(getattr(window, "_metadata", {}))
                log("window_close_event(%i) metadata=%s", wid, metadata)
                class_instance = metadata.strtupleget("class-instance", (None, None), 2, 2)
                title = metadata.strget("title")
                log("window_close_event(%i) title=%s, class-instance=%s", wid, title, class_instance)
                matching_title_close = [x for x in TITLE_CLOSEEXIT if x and title.startswith(x)]
                close = None
                if matching_title_close:
                    close = "window-close event on %s window" % title
                elif class_instance and class_instance[1] in WM_CLASS_CLOSEEXIT:
                    close = "window-close event on %s window" % class_instance[0]
                if close:
                    # honour this close request if there are no other windows:
                    if len(self._id_to_window) == 1:
                        log.info("%s, disconnecting", close)
                        self.quit(0)
                        return
                    log("there are %i windows, so forwarding %s", len(self._id_to_window), close)
            # default to forward:
            self.send("close-window", wid)
        else:
            log.warn("unknown close-window action: %s", self.window_close_action)

    def _process_lost_window(self, packet: PacketType) -> None:
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            if window.is_OR() and self.modal_windows:
                self.may_reenable_modal_windows(window)
            del self._id_to_window[wid]
            del self._window_to_id[window]
            self.destroy_window(wid, window)
        self.set_tray_icon()

    def may_reenable_modal_windows(self, window) -> None:
        orwids = tuple(wid for wid, w in self._id_to_window.items() if w.is_OR() and w != window)
        if orwids:
            # there are other OR windows left, don't do anything
            return
        for wid, w in self._id_to_window.items():
            if w.is_OR() or w.is_tray():
                # trays and OR windows cannot be made modal
                continue
            if w._metadata.boolget("modal") and not w.get_modal():
                metalog("re-enabling modal flag on %s", wid)
                window.set_modal(True)

    def destroy_window(self, wid: int, window) -> None:
        log("destroy_window(%s, %s)", wid, window)
        window.destroy()
        if self._window_with_grab == wid:
            log("destroying window %s which has grab, ungrabbing!", wid)
            self.window_ungrab()
            self._window_with_grab = None
        if self.pointer_grabbed == wid:
            self.pointer_grabbed = None
        # deal with signal watchers:
        execlog("looking for window %i in %s", wid, self._signalwatcher_to_wids)
        for signalwatcher, wids in tuple(self._signalwatcher_to_wids.items()):
            if wid in wids:
                execlog("removing %i from %s for signalwatcher %s", wid, wids, signalwatcher)
                wids.remove(wid)
                if not wids:
                    execlog("last window, removing watcher %s", signalwatcher)
                    self._signalwatcher_to_wids.pop(signalwatcher, None)
                    kill_signalwatcher(signalwatcher)
                    # now remove any pids that use this watcher:
                    for pid, w in tuple(self._pid_to_signalwatcher.items()):
                        if w == signalwatcher:
                            del self._pid_to_signalwatcher[pid]

    def destroy_all_windows(self) -> None:
        for wid, window in self._id_to_window.items():
            try:
                log("destroy_all_windows() destroying %s / %s", wid, window)
                self.destroy_window(wid, window)
            except (RuntimeError, ValueError):
                log(f"destroy_all_windows() failed to destroy {window}", exc_info=True)
        self._id_to_window = {}
        self._window_to_id = {}
        # signal watchers should have been killed in destroy_window(),
        # make sure we don't leave any behind:
        for signalwatcher in tuple(self._signalwatcher_to_wids.keys()):
            kill_signalwatcher(signalwatcher)

    ######################################################################
    # bell
    def _process_bell(self, packet: PacketType) -> None:
        if not self.bell_enabled:
            return
        wid, device, percent, pitch, duration, bell_class, bell_id, bell_name = packet[1:9]
        window = self._id_to_window.get(wid)
        self.window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    ######################################################################
    # focus:
    def send_focus(self, wid: int) -> None:
        focuslog("send_focus(%s)", wid)
        self.send("focus", wid, self.get_current_modifiers())

    def has_focus(self, wid: int) -> bool:
        return bool(self._focused) and self._focused == wid

    def update_focus(self, wid: int, gotit: bool) -> bool:
        focused = self._focused
        focuslog(f"update_focus({wid}, {gotit}) focused={focused}, grabbed={self._window_with_grab}")
        if gotit:
            if focused is not wid:
                self.send_focus(wid)
                self._focused = wid
            self.cancel_lost_focus_timer()
        else:
            if self._window_with_grab:
                self.window_ungrab()
                wwgrab = self._window_with_grab
                if wwgrab:
                    self.do_force_ungrab(wwgrab)
                self._window_with_grab = None
            if wid and focused and focused != wid:
                # if this window lost focus, it must have had it!
                # (catch up - makes things like OR windows work:
                # their parent receives the focus-out event)
                focuslog(f"window {wid} lost a focus it did not have!? (simulating focus before losing it)")
                self.send_focus(wid)
            if focused and not self.lost_focus_timer:
                # send the lost-focus via a timer and re-check it
                # (this allows a new window to gain focus without having to do a reset_focus)
                self.lost_focus_timer = GLib.timeout_add(20, self.send_lost_focus)
                self._focused = None
        return focused != self._focused

    def send_lost_focus(self) -> None:
        focuslog("send_lost_focus() focused=%s", self._focused)
        self.lost_focus_timer = 0
        # check that a new window has not gained focus since:
        if self._focused is None:
            self.send_focus(0)

    def cancel_lost_focus_timer(self) -> None:
        lft = self.lost_focus_timer
        if lft:
            self.lost_focus_timer = 0
            GLib.source_remove(lft)

    def cancel_poll_pointer_timer(self) -> None:
        ppt = self.poll_pointer_timer
        if ppt:
            self.poll_pointer_timer = 0
            GLib.source_remove(ppt)

    ######################################################################
    # grabs:
    def window_grab(self, wid: int, _window) -> None:
        grablog.warn("Warning: window grab not implemented in %s", self.client_type())
        self._window_with_grab = wid

    def window_ungrab(self) -> None:
        grablog.warn("Warning: window ungrab not implemented in %s", self.client_type())
        self._window_with_grab = None

    def do_force_ungrab(self, wid: int) -> None:
        grablog("do_force_ungrab(%s)", wid)
        # ungrab via dedicated server packet:
        self.send_force_ungrab(wid)

    def _process_pointer_grab(self, packet: PacketType) -> None:
        wid = packet[1]
        window = self._id_to_window.get(wid)
        grablog("grabbing %s: %s", wid, window)
        if window:
            self.window_grab(wid, window)

    def _process_pointer_ungrab(self, packet: PacketType) -> None:
        wid = packet[1]
        window = self._id_to_window.get(wid)
        grablog("ungrabbing %s: %s", wid, window)
        self.window_ungrab()

    ######################################################################
    # window refresh:
    def suspend(self) -> None:
        log.info("system is suspending")
        self._suspended_at = time()
        # tell the server to slow down refresh for all the windows:
        self.control_refresh(-1, True, False)

    def resume(self) -> None:
        elapsed = 0.0
        if self._suspended_at > 0:
            elapsed = max(0.0, time() - self._suspended_at)
            self._suspended_at = 0
        self.send_refresh_all()
        if elapsed < 1:
            # not really suspended
            # happens on macos when switching workspace!
            return
        delta = datetime.timedelta(seconds=int(elapsed))
        log.info("system resumed, was suspended for %s", str(delta).lstrip("0:"))
        # this will reset the refresh rate too:
        if self.opengl_enabled:
            # with opengl, the buffers sometimes contain garbage after resuming,
            # this should create new backing buffers:
            self.reinit_windows()
        self.reinit_window_icons()

    def control_refresh(self, wid: int, suspend_resume, refresh, quality=100,
                        options=None, client_properties=None) -> None:
        packet = ["buffer-refresh", wid, 0, quality]
        options = options or {}
        client_properties = client_properties or {}
        options["refresh-now"] = bool(refresh)
        if suspend_resume is True:
            options["batch"] = {
                "reset": True,
                "delay": 1000,
                "locked": True,
                "always": True,
            }
        elif suspend_resume is False:
            options["batch"] = {"reset": True}
        else:
            pass  # batch unchanged
        log("sending buffer refresh: options=%s, client_properties=%s", options, client_properties)
        packet.append(options)
        packet.append(client_properties)
        self.send(*packet)

    def send_refresh(self, wid: int) -> None:
        packet = [
            "buffer-refresh", wid, 0, 100,
            {
                # explicit refresh (should be assumed True anyway),
                # also force a reset of batch configs:
                "refresh-now": True,
                "batch": {"reset": True},
            },
            {},  # no client_properties
        ]
        self.send(*packet)

    def send_refresh_all(self) -> None:
        log("Automatic refresh for all windows ")
        self.send_refresh(-1)

    ######################################################################
    # painting windows:
    def _process_draw(self, packet: PacketType) -> None:
        if PAINT_DELAY >= 0:
            GLib.timeout_add(PAINT_DELAY, self._draw_queue.put, packet)
        else:
            self._draw_queue.put(packet)

    def _process_eos(self, packet: PacketType) -> None:
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid: int, packet_sequence: int, width: int, height: int,
                             decode_time: int, message="") -> None:
        packet = "damage-sequence", packet_sequence, wid, width, height, decode_time, message
        drawlog("sending ack: %s", packet)
        self.send_now(*packet)

    def _draw_thread_loop(self):
        while self.exit_code is None:
            packet = self._draw_queue.get()
            if packet is None:
                log("draw queue found exit marker")
                break
            with log.trap_error(f"Error processing {packet[0]} packet"):
                self._do_draw(packet)
                sleep(0)
        self._draw_thread = None
        log("draw thread ended")

    def _do_draw(self, packet) -> None:
        """ this runs from the draw thread above """
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if packet[0] == "eos":
            if window:
                window.eos()
            return
        x, y, width, height, coding, data, packet_sequence, rowstride = packet[2:10]
        for v in (x, y, width, height, packet_sequence, rowstride):
            assert isinstance(v, int), "expected int, found {} ({})".format(v, type(v))
        coding = bytestostr(coding)
        if not window:
            # window is gone

            def draw_cleanup() -> None:
                if coding == "mmap":
                    from xpra.net.mmap import int_from_buffer
                    # we need to ack the data to free the space!
                    data_start = int_from_buffer(self.mmap_read_area.mmap, 0)
                    offset, length = data[-1]
                    data_start.value = offset + length
                    # clear the mmap area via idle_add so any pending draw requests
                    # will get a chance to run first (preserving the order)
                self.send_damage_sequence(wid, packet_sequence, width, height, WINDOW_NOT_FOUND, "window not found")

            GLib.idle_add(draw_cleanup)
            return
        # rename old encoding aliases early:
        options = typedict()
        if len(packet) > 10:
            options.update(packet[10])
        dtype = DRAW_TYPES.get(type(data), type(data))
        drawlog(DRAW_LOG_FMT, len(data), dtype, wid, packet_sequence, width, height, x, y, coding, options)
        start = monotonic()

        def record_decode_time(success: bool | int, message="") -> None:
            if success > 0:
                end = monotonic()
                decode_time = round(end * 1000 * 1000 - start * 1000 * 1000)
                self.pixel_counter.append((start, end, width * height))
                dms = "%sms" % (int(decode_time / 100) / 10.0)
                paintlog("record_decode_time(%s, %s) wid=%s, %s: %sx%s, %s",
                         success, message, wid, coding, width, height, dms)
            elif success == 0:
                decode_time = WINDOW_DECODE_ERROR
                paintlog("record_decode_time(%s, %s) decoding error on wid=%s, %s: %sx%s",
                         success, message, wid, coding, width, height)
            else:
                assert success < 0
                decode_time = WINDOW_DECODE_SKIPPED
                paintlog("record_decode_time(%s, %s) decoding or painting skipped on wid=%s, %s: %sx%s",
                         success, message, wid, coding, width, height)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time, repr_ellipsized(message, 512))

        self._draw_counter += 1
        if PAINT_FAULT_RATE > 0 and (self._draw_counter % PAINT_FAULT_RATE) == 0:
            drawlog.warn("injecting paint fault for %s draw packet %i, sequence number=%i",
                         coding, self._draw_counter, packet_sequence)
            if PAINT_FAULT_TELL:
                msg = f"fault injection for {coding} draw packet {self._draw_counter}, sequence no={packet_sequence}"
                GLib.idle_add(record_decode_time, False, msg)
            return
        # we could expose this to the csc step? (not sure how this could be used)
        # if self.xscale!=1 or self.yscale!=1:
        #    options["client-scaling"] = self.xscale, self.yscale
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, options, [record_decode_time])
        except Exception as e:
            drawlog.error("Error drawing on window %i", wid)
            drawlog.error(f" using encoding {coding} with {options=}", exc_info=True)
            GLib.idle_add(record_decode_time, False, str(e))
            raise

    ######################################################################
    # screen scaling:
    @staticmethod
    def fsx(v):
        """ convert X coordinate from server to client """
        return v

    @staticmethod
    def fsy(v):
        """ convert Y coordinate from server to client """
        return v

    @staticmethod
    def sx(v) -> int:
        """ convert X coordinate from server to client """
        return round(v)

    @staticmethod
    def sy(v) -> int:
        """ convert Y coordinate from server to client """
        return round(v)

    def srect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)

    def sp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    @staticmethod
    def cx(v) -> int:
        """ convert X coordinate from client to server """
        return round(v)

    @staticmethod
    def cy(v) -> int:
        """ convert Y coordinate from client to server """
        return round(v)

    def crect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)

    def cp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)

    def redraw_spinners(self) -> None:
        # draws spinner on top of the window, or not (plain repaint)
        # depending on whether the server is ok or not
        ok = self.server_ok()
        log("redraw_spinners() ok=%s", ok)
        for w in self._id_to_window.values():
            if not w.is_tray():
                w.spinner(ok)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(
            "new-window", "new-override-redirect", "new-tray",
            "raise-window", "restack-window",
            "initiate-moveresize",
            "window-move-resize", "window-resized", "window-metadata",
            "configure-override-redirect",
            "lost-window",
            "window-icon",
            "draw", "eos",
            "bell",
            "pointer-position", "pointer-grab", "pointer-ungrab",
            main_thread=True)
