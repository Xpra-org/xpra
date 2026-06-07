# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import datetime
import socket
from typing import Any

from xpra import __version__
from xpra.scripts.config import (
    OPTION_TYPES, CLIENT_ONLY_OPTIONS,
    fixup_options, make_defaults_struct, read_config, dict_to_validated_config,
)
from xpra.scripts.parsing import fixup_defaults
from xpra.scripts.session import (
    clean_session_files, get_session_dir, make_session_dir, rm_session_dir, save_session_file, session_file_path,
)
from xpra.util.io import warn
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")


SERVER_SAVE_SKIP_OPTIONS: tuple[str, ...] = (
    "systemd-run",
    "daemon",
)

SERVER_LOAD_SKIP_OPTIONS: tuple[str, ...] = (
    "systemd-run",
    "daemon",
    "start",
    "start-child",
    "start-after-connect",
    "start-child-after-connect",
    "start-on-connect",
    "start-child-on-connect",
    "start-on-disconnect",
    "start-child-on-disconnect",
    "start-on-last-client-exit",
    "start-child-on-last-client-exit",
)


def get_options_file_contents(opts) -> str:
    defaults = make_defaults_struct()
    fixup_defaults(defaults)
    fixup_options(defaults)
    now = datetime.datetime.now()
    diff_contents = [
        f"# xpra server {__version__}",
        "# " + now.strftime("%Y-%m-%d %H:%M:%S"),
        "# on %r" % socket.gethostname(),
        "",
        f"mode={opts.mode}",
    ]
    for attr, dtype in OPTION_TYPES.items():
        if attr in CLIENT_ONLY_OPTIONS:
            continue
        if attr in SERVER_SAVE_SKIP_OPTIONS:
            continue
        aname = attr.replace("-", "_")
        dval = getattr(defaults, aname, None)
        cval = getattr(opts, aname, None)
        if dval != cval:
            if dtype is bool:
                BOOL_STR = {True: "yes", False: "no"}
                diff_contents.append(f"{attr}=" + BOOL_STR.get(cval, "auto"))
            elif dtype in (tuple, list):
                for x in cval or ():
                    diff_contents.append(f"{attr}={x}")
            else:
                diff_contents.append(f"{attr}={cval}")
    diff_contents.append("")
    return "\n".join(diff_contents)


def load_options() -> dict[str, Any]:
    config_file = session_file_path("config")
    return read_config(config_file)


def apply_config(opts, options: dict[str, Any], cmdline: list[str]) -> None:
    # if we had saved the start / start-desktop config, reload it:
    if opts.mode.find("upgrade") >= 0:
        # unspecified upgrade, try to find the original mode used:
        opts.mode = options.pop("mode") or opts.mode
    upgrade_config = dict_to_validated_config(options)
    # apply the previous session options:
    for k in options:
        if k in CLIENT_ONLY_OPTIONS:
            continue
        if k in SERVER_LOAD_SKIP_OPTIONS:
            continue
        incmdline = f"--{k}" in cmdline or f"--no-{k}" in cmdline or any(c.startswith(f"--{k}=") for c in cmdline)
        if incmdline:
            continue
        dtype = OPTION_TYPES.get(k)
        if not dtype:
            continue
        fn = k.replace("-", "_")
        if not hasattr(upgrade_config, fn):
            warn(f"{k!r} not found in saved config")
            continue
        if not hasattr(opts, fn):
            warn(f"{k!r} not found in config")
            continue
        value = getattr(upgrade_config, fn)
        setattr(opts, fn, value)


class SessionFilesServer(StubSubsystem):
    PREFIX = "session-files"

    def __init__(self, server):
        StubSubsystem.__init__(self, server)
        self.uid = 0
        self.gid = 0
        self.config_contents = ""
        self.mode = ""
        self.sessions_dir = ""
        self.display_name = ""
        self.session_dir = ""
        # canonical list of per-session files / glob patterns to clean up
        # at shutdown. Other subsystems append to this via `get_subsystem`.
        self.session_files: list[str] = [
            "server.log*",
            # notifications may use a TMP dir:
            "tmp/*", "tmp",
        ]

    def init(self, opts) -> None:
        self.uid = opts.uid
        self.gid = opts.gid

    def late_cleanup(self, stop=True) -> None:
        if stop:
            log("clean_session_files(%s)", self.session_files)
            clean_session_files(*self.session_files)
            if stop:
                rm_session_dir()

    def write_session_file(self, filename: str, contents) -> str:
        if filename not in self.session_files:
            self.session_files.append(filename)
        return save_session_file(filename, contents, self.uid, self.gid)

    def setup_session_dir(self, mode: str, sessions_dir: str, display_name: str) -> str:
        self.mode = mode
        self.sessions_dir = sessions_dir
        self.display_name = display_name
        self.session_dir = make_session_dir(mode, sessions_dir, display_name, self.uid, self.gid)
        import os
        os.environ["XPRA_SESSION_DIR"] = self.session_dir
        return self.session_dir

    def display_name_changed(self, _xvfb, display_name: str) -> None:
        old_display_name = self.display_name
        if display_name != old_display_name and self.session_dir:
            new_session_dir = get_session_dir(self.mode, self.sessions_dir, display_name, self.uid)
            if new_session_dir != self.session_dir:
                import os
                try:
                    if os.path.exists(new_session_dir):
                        for sess_e in os.listdir(self.session_dir):
                            os.rename(os.path.join(self.session_dir, sess_e), os.path.join(new_session_dir, sess_e))
                        os.rmdir(self.session_dir)
                    else:
                        os.rename(self.session_dir, new_session_dir)
                except OSError as e:
                    log.error("Error moving the session directory")
                    log.error(f" from {self.session_dir!r} to {new_session_dir!r}")
                    log.error(f" {e}")
                os.environ["XPRA_SESSION_DIR"] = new_session_dir
                self.session_dir = new_session_dir
                if daemon := self.get_subsystem("daemon"):
                    daemon.session_dir_changed(new_session_dir)
        self.display_name = display_name
        if daemon := self.get_subsystem("daemon"):
            daemon.display_name_changed(display_name)

    def write_config(self, opts) -> None:
        if not self.config_contents:
            self.config_contents = get_options_file_contents(opts)
        self.write_session_file("config", self.config_contents)

    def load_options(self) -> dict[str, Any]:
        return load_options()

    def apply_config(self, opts, cmdline: list[str]) -> None:
        options = self.load_options()
        if options:
            apply_config(opts, options, cmdline)

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            SessionFilesServer.PREFIX: self.session_files,
        }
