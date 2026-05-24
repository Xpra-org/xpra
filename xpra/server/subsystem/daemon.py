# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.common import noerr
from xpra.os_util import POSIX, WIN32
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
        self.log_file = ""
        self.log_dir = ""
        self.log_filename = ""
        self.display_name = ""
        self.username = ""
        self.uid = 0
        self.gid = 0
        self.extra_expand: dict[str, str] = {}
        self.stdout = None
        self.stderr = None

    def init(self, opts) -> None:
        log("DaemonServer.init(%s)", opts)
        self.pidfile = osexpand(opts.pidfile)
        if self.pidfile:
            self.pidinode = write_pidfile(os.path.normpath(self.pidfile))

    def setup_log(self, daemon: bool, start_vfb: bool, log_to_file: bool, log_dir: str, log_file: str,
                  display_name: str, session_dir: str, username: str, uid: int, gid: int, root: bool,
                  extra_expand: dict[str, str], stdout, stderr) -> str:
        self.daemon = daemon
        self.log_file = log_file
        self.display_name = display_name
        self.username = username
        self.uid = uid
        self.gid = gid
        self.extra_expand = extra_expand
        self.stdout = stdout
        self.stderr = stderr
        self.log_dir = self.get_server_log_dir(start_vfb, log_to_file, log_dir, session_dir)
        if not log_to_file:
            os.environ.pop("XPRA_SERVER_LOG", None)
            return self.log_dir

        from xpra.util.daemon import redirect_std_to_log, select_log_file, open_log_file
        self.log_filename = osexpand(select_log_file(self.log_dir, log_file, display_name),
                                     username, uid, gid, extra_expand)
        if os.path.exists(self.log_filename) and not display_name.startswith("S"):
            # Don't overwrite the log file just yet, as we may still fail to start.
            self.log_filename += ".new"
        logfd = open_log_file(self.log_filename)
        if POSIX:
            os.fchmod(logfd, 0o640)
            if root and (uid > 0 or gid > 0):
                try:
                    os.fchown(logfd, uid, gid)
                except OSError as e:
                    noerr(stderr.write, f"failed to chown the log file {self.log_filename!r}\n")
                    noerr(stderr.write, f" {e!r}\n")
                    noerr(stderr.flush)
        self.stdout, self.stderr = redirect_std_to_log(logfd)
        noerr(stderr.write, f"Entering daemon mode; any further errors will be reported to:\n  {self.log_filename!r}\n")
        noerr(stderr.flush)
        os.environ["XPRA_SERVER_LOG"] = self.log_filename
        return self.log_dir

    @staticmethod
    def get_server_log_dir(start_vfb: bool, log_to_file: bool, log_dir: str, session_dir: str) -> str:
        if not (start_vfb or log_to_file):
            return log_dir
        if not log_dir or log_dir.lower() == "auto":
            log_dir = session_dir
        # This is used by Xdummy for the Xorg log file.
        if "XPRA_LOG_DIR" not in os.environ:
            os.environ["XPRA_LOG_DIR"] = log_dir
        return log_dir

    def update_log_dir(self, log_dir: str) -> None:
        self.log_dir = log_dir

    def display_name_changed(self, display_name: str) -> None:
        if WIN32 and os.environ.get("XPRA_LOG_FILENAME"):
            os.environ["XPRA_SERVER_LOG"] = os.environ["XPRA_LOG_FILENAME"]
        if not self.daemon:
            return
        stderr = self.stderr
        if self.display_name != display_name:
            # This may be used by scripts, let's try not to change it.
            noerr(stderr.write, f"Actual display used: {display_name}\n")
            noerr(stderr.flush)
        from xpra.util.daemon import select_log_file
        new_log_filename = osexpand(select_log_file(self.log_dir, self.log_file, display_name),
                                    self.username, self.uid, self.gid, self.extra_expand)
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
            noerr(stderr.write, f"Actual log file name is now: {new_log_filename!r}\n")
            noerr(stderr.flush)
        noerr(self.stdout.close)
        noerr(stderr.close)
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
