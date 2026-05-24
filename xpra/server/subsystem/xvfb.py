# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable
from typing import Any

import glob
import os

from xpra.os_util import POSIX, getuid, get_username_for_uid, find_group
from xpra.server.subsystem.stub import StubSubsystem
from xpra.scripts.server import (
    VFBStartResult,
    resolve_x11_display,
    start_server_vfb,
)
from xpra.scripts.config import xvfb_command
from xpra.scripts.session import load_session_file
from xpra.util.env import envbool, osexpand
from xpra.util.io import is_writable

SHARED_XAUTHORITY = envbool("XPRA_SHARED_XAUTHORITY", True)


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

    def setup_vfb(self, mode: str, display_name: str, start_vfb: bool,
                  xauth_data: str, protected_env: dict,
                  pam, shadowing: bool, proxying: bool, encoder: bool, runner: bool, starting: str,
                  clobber: int, use_display: bool | None, upgrading: bool,
                  error_cb: Callable, progress: Callable, log) -> VFBStartResult:
        old_display_name = display_name
        xauthority = None
        session_files = self.get_subsystem("session-files")
        assert session_files
        write_session_file = session_files.write_session_file
        if POSIX and (start_vfb or clobber or (shadowing and display_name.startswith(":"))) and "wayland" not in display_name:
            xauthority = self.setup_xauthority(display_name, shadowing, log)
            display_resolution = resolve_x11_display(display_name, xauthority, xauth_data, start_vfb, use_display,
                                                     upgrading, shadowing, proxying, encoder, pam, self.uid, self.gid,
                                                     error_cb, progress, log)
            start_vfb = display_resolution.start_vfb
            xauth_data = display_resolution.xauth_data
            use_display = display_resolution.use_display

        self.start_vfb = start_vfb
        self.xauth_data = xauth_data
        self.use_display = use_display
        return start_server_vfb(self, mode, display_name, old_display_name, start_vfb, self.xvfb_cmd,
                                xauth_data, xauthority, self.cwd, self.uid, self.gid, self.username, protected_env,
                                pam, shadowing, proxying, encoder, runner, starting,
                                write_session_file, progress, log)

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
