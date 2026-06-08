# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any

from xpra.common import noerr
from xpra.os_util import POSIX, WIN32, getuid, get_username_for_uid
from xpra.util.pid import write_pidfile, rm_pidfile
from xpra.util.env import osexpand
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")


class DaemonServer(StubSubsystem):
    PREFIX = "daemon"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.pidfile = ""
        self.pidinode: int = 0
        self.daemon = False
        self.log_dir_option = ""
        self.log_file = ""
        self.log_dir = ""
        self.log_filename = ""
        self.display_name = ""
        self.session_dir = ""
        self.uid = 0
        self.gid = 0
        self.extra_expand: dict[str, str] = {}
        self.stdout = sys.stdout
        self.stderr = sys.stderr

    def init(self, opts) -> None:
        log("DaemonServer.init(%s)", opts)
        pidfile = osexpand(opts.pidfile)
        self.daemon = bool(opts.daemon)
        self.log_dir_option = str(opts.log_dir or "")
        self.log_file = str(opts.log_file or "")
        self.uid = int(opts.uid)
        self.gid = int(opts.gid)
        self.pidfile = pidfile

    def errwrite(self, msg: str):
        noerr(self.stderr.write, f"{msg}\n")
        noerr(self.stderr.flush)

    def write_pid(self) -> None:
        self.pidinode = write_pidfile(os.path.normpath(self.pidfile))

    def setup_log(self, start_vfb: bool, log_to_file: bool, display_name: str,
                  extra_expand: dict[str, str]) -> str:
        self.display_name = display_name
        self.extra_expand = extra_expand
        self.session_dir = os.environ.get("XPRA_SESSION_DIR", "")
        self.log_dir = self.get_server_log_dir(start_vfb, log_to_file, self.log_dir_option)
        if not log_to_file:
            os.environ.pop("XPRA_SERVER_LOG", None)
            return self.log_dir

        from xpra.util.daemon import redirect_std_to_log, select_log_file, open_log_file
        username = get_username_for_uid(self.uid)
        self.log_filename = osexpand(select_log_file(self.log_dir, self.log_file, display_name),
                                     username, self.uid, self.gid, extra_expand)
        if os.path.exists(self.log_filename) and not display_name.startswith("S"):
            # Don't overwrite the log file just yet, as we may still fail to start.
            self.log_filename += ".new"
        logfd = open_log_file(self.log_filename)
        if POSIX:
            os.fchmod(logfd, 0o640)
            if getuid() == 0 and (self.uid > 0 or self.gid > 0):
                try:
                    os.fchown(logfd, self.uid, self.gid)
                except OSError as e:
                    self.errwrite(f"failed to chown the log file {self.log_filename!r}")
                    self.errwrite(f" {e!r}")
        self.stdout, self.stderr = redirect_std_to_log(logfd)
        self.errwrite("Entering daemon mode; any further errors will be reported to:")
        self.errwrite(f"  {self.log_filename!r}")
        os.environ["XPRA_SERVER_LOG"] = self.log_filename
        return self.log_dir

    @staticmethod
    def get_server_log_dir(start_vfb: bool, log_to_file: bool, log_dir: str) -> str:
        if not (start_vfb or log_to_file):
            return log_dir
        if not log_dir or log_dir.lower() == "auto":
            log_dir = os.environ.get("XPRA_SESSION_DIR", "")
        # This is used by Xdummy for the Xorg log file.
        if "XPRA_LOG_DIR" not in os.environ:
            os.environ["XPRA_LOG_DIR"] = log_dir
        return log_dir

    def update_log_dir(self, log_dir: str) -> None:
        self.log_dir = log_dir

    def session_dir_changed(self, session_dir: str) -> None:
        old_session_dir = self.session_dir
        self.session_dir = session_dir
        if not self.log_dir_option or self.log_dir_option.lower() == "auto":
            self.log_dir = session_dir
        if self.daemon and old_session_dir != session_dir:
            self.errwrite(f"Actual session directory is now: {session_dir!r}")

    def display_name_changed(self, display_name: str) -> None:
        if WIN32 and os.environ.get("XPRA_LOG_FILENAME"):
            os.environ["XPRA_SERVER_LOG"] = os.environ["XPRA_LOG_FILENAME"]
        if not self.daemon:
            return
        if self.display_name != display_name:
            # This may be used by scripts, let's try not to change it.
            self.errwrite(f"Actual display used: {display_name}")
        from xpra.util.daemon import select_log_file
        username = get_username_for_uid(self.uid)
        new_log_filename = osexpand(select_log_file(self.log_dir, self.log_file, display_name),
                                    username, self.uid, self.gid, self.extra_expand)
        if self.log_filename != new_log_filename:
            session_dir = os.environ.get("XPRA_SESSION_DIR", "")
            if not os.path.exists(self.log_filename) and os.path.exists(new_log_filename) and new_log_filename.startswith(
                    session_dir):  # noqa: E501
                # The session dir was renamed with the log file inside it.
                pass
            else:
                try:
                    os.rename(self.log_filename, new_log_filename)
                except OSError:
                    pass
            os.environ["XPRA_SERVER_LOG"] = new_log_filename
            self.errwrite(f"Actual log file name is now: {new_log_filename!r}")
        noerr(self.stdout.close)
        noerr(self.stderr.close)
        self.log_filename = new_log_filename
        self.display_name = display_name

    def late_cleanup(self, stop=True) -> None:
        if self.pidfile:
            log("cleanup removing pidfile %s", self.pidfile)
            rm_pidfile(self.pidfile, self.pidinode)
            self.pidinode = 0

    def get_info(self, _proto) -> dict[str, Any]:
        if self.pidfile:
            return {
                "pidfile": {
                    "path": self.pidfile,
                    "inode": self.pidinode,
                }
            }
        return {}
