# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable
from typing import Any

import glob
import os
import sys

from xpra.common import noerr, noop
from xpra.os_util import POSIX, OSX, getuid, get_username_for_uid, find_group
from xpra.server.subsystem.stub import StubSubsystem
from xpra.scripts.server import (
    VFBStartResult,
    verify_display,
)
from xpra.scripts.config import InitException, xvfb_command
from xpra.scripts.common import no_gtk
from xpra.scripts.display import stat_display_socket, X11_SOCKET_DIR
from xpra.scripts.session import load_session_file
from xpra.util.child_reaper import get_child_reaper
from xpra.util.env import envbool, osexpand
from xpra.util.io import is_writable
from xpra.util.io import warn
from xpra.util.parsing import ALL_BOOLEAN_OPTIONS, parse_resolutions, get_refresh_rate_for_value
from xpra.util.str_fn import get_rand_chars
from xpra.os_util import get_hex_uuid

SHARED_XAUTHORITY = envbool("XPRA_SHARED_XAUTHORITY", True)


def validate_pixel_depth(pixel_depth, desktop_or_monitor=False) -> int:
    try:
        pixel_depth = int(pixel_depth)
    except ValueError:
        raise InitException(f"invalid value {pixel_depth} for pixel depth, must be a number") from None
    if pixel_depth == 0:
        pixel_depth = 24
    if pixel_depth not in (8, 16, 24, 30):
        raise InitException(f"invalid pixel depth: {pixel_depth}")
    if not desktop_or_monitor and pixel_depth == 8:
        raise InitException("pixel depth 8 is only supported in 'desktop' mode")
    return pixel_depth


class XvfbManager(StubSubsystem):
    PREFIX = "xvfb"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.displayfd = ""
        self.backend = ""
        self.input_devices = ""
        self.pixel_depth = 0
        self.resize_display = ""
        self.refresh_rate = ""
        self.sessions_dir = ""
        self.log_dir = ""
        self.xvfb_cmd: list[str] = []
        self.cwd = ""
        self.uid = 0
        self.gid = 0
        self.username = ""
        self.start_vfb = False
        self.xauth_data = ""
        self.use_display = None

    def init(self, opts) -> None:
        self.displayfd = str(opts.displayfd or "")
        self.backend = str(opts.backend or "")
        self.input_devices = str(opts.input_devices or "")
        self.pixel_depth = int(opts.pixel_depth or 0)
        self.resize_display = str(opts.resize_display or "")
        self.refresh_rate = str(opts.refresh_rate or "")
        self.sessions_dir = str(opts.sessions_dir or "")
        self.log_dir = str(opts.log_dir or "")
        self.xvfb_cmd = xvfb_command(opts.xvfb, self.pixel_depth, opts.dpi)
        try:
            self.cwd = str(opts.chdir or os.getcwd())
        except OSError:
            self.cwd = os.path.expanduser("~")
        self.uid = int(opts.uid)
        self.gid = int(opts.gid)
        if POSIX and self.uid and not self.gid:
            self.gid = find_group(self.uid)
        self.username = get_username_for_uid(self.uid)

    def setup_vfb(self, display_name: str, start_vfb: bool,
                  xauth_data: str, protected_env: dict,
                  pam, shadowing: bool, proxying: bool, encoder: bool, runner: bool, starting: str,
                  clobber: int, use_display: bool | None, upgrading: bool,
                  error_cb: Callable, progress: Callable, log) -> VFBStartResult:
        old_display_name = display_name
        xauthority = None
        session_files = self.get_subsystem("session-files")
        assert session_files
        if POSIX and (start_vfb or clobber or (shadowing and display_name.startswith(":"))) and "wayland" not in display_name:
            xauthority = self.setup_xauthority(display_name, shadowing, log)
            start_vfb, xauth_data, use_display = self.resolve_x11_display(
                display_name, xauthority, xauth_data, start_vfb, use_display,
                upgrading, shadowing, proxying, encoder, pam, error_cb, progress, log,
            )

        self.start_vfb = start_vfb
        self.xauth_data = xauth_data
        self.use_display = use_display
        return self.start_server_vfb(display_name, old_display_name, xauthority, protected_env,
                                     pam, shadowing, proxying, encoder, runner, starting,
                                     progress, log)

    def resolve_x11_display(self, display_name: str, xauthority: str, xauth_data: str,
                            start_vfb: bool, use_display: bool | None, upgrading: bool,
                            shadowing: bool, proxying: bool, encoder: bool, pam,
                            error_cb: Callable, progress: Callable, log) -> tuple[bool, str, bool | None]:
        if (use_display is not None and not upgrading) or proxying or encoder:
            return start_vfb, xauth_data, use_display

        # Figure out if we have to start the vfb or not.
        # Bail out if we need a display that is not running.
        if not display_name:
            if upgrading:
                error_cb("no displays found to upgrade")
            return start_vfb, xauth_data, False

        progress(40, "connecting to the display")
        no_gtk()
        if verify_display(None, display_name, log_errors=False, timeout=1):
            progress(40, "connected to the display")
            return False, xauth_data, use_display

        stat = {}
        if display_name.startswith(":"):
            x11_socket_path = os.path.join(X11_SOCKET_DIR, "X" + display_name[1:])
            stat = stat_display_socket(x11_socket_path)
            log(f"stat_display_socket({x11_socket_path})={stat}")
            if not stat and (upgrading or shadowing):
                error_cb(f"cannot access display {display_name!r}")
            # No X11 socket to connect to, so we have to start one.
            start_vfb = True
        if stat:
            # We can't connect to the X11 display, but we can still stat its socket.
            # Perhaps we need to re-add an xauth entry.
            if not xauth_data:
                xauth_data = get_hex_uuid()
                if pam:
                    pam.set_items({"XAUTHDATA": xauth_data})
            from xpra.x11.vfb_util import xauth_add
            xauth_add(xauthority, display_name, xauth_data, self.uid, self.gid)
            if not verify_display(None, display_name, log_errors=False, timeout=1):
                warn(f"display {display_name!r} is not accessible")
            else:
                start_vfb = False
        return start_vfb, xauth_data, use_display

    def start_server_vfb(self, display_name: str, old_display_name: str, xauthority: str | None,
                         protected_env: dict, pam, shadowing: bool, proxying: bool, encoder: bool,
                         runner: bool, starting: str, progress: Callable, log) -> VFBStartResult:
        xvfb = None
        xvfb_pid = 0
        devices = {}
        displayfd = 0
        if POSIX and self.displayfd:
            try:
                displayfd = int(self.displayfd)
            except ValueError as e:
                noerr(sys.stderr.write, f"Error: invalid displayfd {self.displayfd!r}:\n")
                noerr(sys.stderr.write, f" {e}\n")
                del e
        result_cmd = tuple(self.xvfb_cmd)
        if not POSIX or proxying or encoder or runner:
            return VFBStartResult(xvfb, xvfb_pid, devices, display_name, result_cmd, displayfd)

        create_input_devices = noop
        uinput_uuid_len = 0
        use_uinput = False
        if self.backend != "wayland":
            try:
                from xpra.x11.uinput.setup import has_uinput, create_input_devices, UINPUT_UUID_LEN
                uinput_uuid_len = UINPUT_UUID_LEN
                use_uinput = not (shadowing or proxying or encoder or runner) and self.input_devices.lower() in (
                    "uinput", "auto",
                ) and has_uinput()
            except ImportError:
                use_uinput = False

        uinput_uuid = ""
        if self.start_vfb:
            progress(40, "starting a virtual display")
            from xpra.x11.vfb_util import start_Xvfb, xauth_add
            assert not proxying and self.xauth_data
            pixel_depth = validate_pixel_depth(self.pixel_depth, starting in ("desktop", "monitor"))
            session_files = self.get_subsystem("session-files")
            if use_uinput:
                # This only needs to be fairly unique.
                uinput_uuid = get_rand_chars(uinput_uuid_len).decode("latin1")
                if session_files:
                    session_files.write_session_file("uinput-uuid", uinput_uuid)
            vfb_geom: tuple | None = ()
            resize = self.resize_display.lower()
            if resize not in ALL_BOOLEAN_OPTIONS and resize != "auto":
                sizes = self.resize_display.split(":", 1)[-1]
                resolutions = parse_resolutions(sizes, self.refresh_rate)
                if resolutions:
                    vfb_geom = resolutions[0]
            fps = get_refresh_rate_for_value(self.refresh_rate, 60) if self.refresh_rate else 0
            xvfb, display_name = start_Xvfb(result_cmd, vfb_geom, pixel_depth, fps, display_name, self.cwd,
                                            self.uid, self.gid, self.username, uinput_uuid)
            assert xauthority
            xauth_add(xauthority, display_name, self.xauth_data, self.uid, self.gid)
            xvfb_pid = xvfb.pid
            xvfb_pidfile = ""
            if session_files:
                xvfb_pidfile = session_files.write_session_file("xvfb.pid", str(xvfb.pid))
            log(f"saved xvfb.pid={xvfb.pid}")

            def xvfb_terminated() -> None:
                log(f"xvfb_terminated() removing {xvfb_pidfile}")
                if xvfb_pidfile:
                    os.unlink(xvfb_pidfile)

            vfb_procinfo = get_child_reaper().add_process(xvfb, "xvfb", self.xvfb_cmd, ignore=True,
                                                          callback=xvfb_terminated)
            log("xvfb process info=%s", vfb_procinfo.get_info())
            os.environ["DISPLAY"] = display_name
            os.environ["CKCON_X11_DISPLAY"] = display_name
            os.environ.update(protected_env)
            if display_name != old_display_name:
                if pam:
                    pam.set_items({"XDISPLAY": display_name})
        elif not OSX and not shadowing and not proxying:
            try:
                xvfb_pid = int(load_session_file("xvfb.pid") or 0)
            except ValueError:
                pass
            log(f"reloaded xvfb.pid={xvfb_pid} from session file")
            if use_uinput:
                uinput_uuid = load_session_file("uinput-uuid").decode("latin1")
        if uinput_uuid:
            devices = create_input_devices(uinput_uuid, self.uid) or {}
        return VFBStartResult(xvfb, xvfb_pid, devices, display_name, result_cmd, displayfd)

    def setup_xauthority(self, display_name: str, shadowing: bool, log) -> str:
        from xpra.x11.vfb_util import get_xauthority_path, valid_xauth
        session_files = self.get_subsystem("session-files")
        assert session_files
        root = POSIX and getuid() == 0
        xauthority = valid_xauth((load_session_file("xauthority")).decode(), self.uid, self.gid)
        if xauthority:
            os.environ["XAUTHORITY"] = xauthority
            return xauthority

        if SHARED_XAUTHORITY:
            # Re-using this value is not always safe, but users expect commands
            # such as `DISPLAY=:10 xterm` to work in most cases.
            xauthority = os.environ.get("XAUTHORITY", "")
        if shadowing and not valid_xauth(xauthority, self.uid, self.gid):
            # Look for xauth files in magic directories, see ticket #3917.
            xauth_time = 0.0
            candidates = (
                "/tmp/xauth*",
                "/tmp/.Xauth*",
                "/var/run/*dm/xauth*",
                "/var/run/lightdm/$USER/xauthority",
                "$XDG_RUNTIME_DIR/xauthority",
                "$XDG_RUNTIME_DIR/Xauthority",
                "$XDG_RUNTIME_DIR/gdm/xauthority",
                "$XDG_RUNTIME_DIR/gdm/Xauthority",
            )
            for globstr in candidates:
                for filename in glob.glob(osexpand(globstr, actual_username=self.username, uid=self.uid, gid=self.gid)):
                    if not os.path.isfile(filename):
                        continue
                    try:
                        stat_info = os.stat(filename)
                    except OSError:
                        continue
                    if not root and stat_info.st_uid != self.uid:
                        continue
                    if xauth_time == 0.0 or stat_info.st_mtime > xauth_time:
                        xauthority = filename
                        xauth_time = stat_info.st_mtime
        if not valid_xauth(xauthority, self.uid, self.gid):
            xauthority = get_xauthority_path(display_name)
            xauthority = osexpand(xauthority, actual_username=self.username, uid=self.uid, gid=self.gid)
        assert xauthority
        if not os.path.exists(xauthority):
            if os.path.islink(xauthority):
                # broken symlink
                os.unlink(xauthority)
            log(f"creating XAUTHORITY file {xauthority!r}")
            with open(xauthority, "ab") as xauth_file:
                os.fchmod(xauth_file.fileno(), 0o640)
                if root and (self.uid != 0 or self.gid != 0):
                    os.fchown(xauth_file.fileno(), self.uid, self.gid)
        elif not is_writable(xauthority, self.uid, self.gid) and not root:
            log(f"chmoding XAUTHORITY file {xauthority!r}")
            os.chmod(xauthority, 0o640)
        session_files.write_session_file("xauthority", xauthority)
        log(f"using XAUTHORITY file {xauthority!r}")
        os.environ["XAUTHORITY"] = xauthority
        return xauthority

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "xvfb": {
                "backend": self.backend,
                "input-devices": self.input_devices,
                "displayfd": self.displayfd,
                "pixel-depth": self.pixel_depth,
                "resize-display": self.resize_display,
                "refresh-rate": self.refresh_rate,
                "start": self.start_vfb,
                "use-display": self.use_display,
            },
        }
