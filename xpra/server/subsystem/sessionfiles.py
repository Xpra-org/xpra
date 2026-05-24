# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra import __version__
from xpra.scripts.config import (
    OPTION_TYPES, CLIENT_ONLY_OPTIONS,
    fixup_options, make_defaults_struct, read_config, dict_to_validated_config,
)
from xpra.scripts.parsing import fixup_defaults
from xpra.scripts.session import clean_session_files, rm_session_dir, save_session_file, session_file_path
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
    diff_contents = [
        f"# xpra server {__version__}",
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
        self.config_contents = ""
        # canonical list of per-session files / glob patterns to clean up
        # at shutdown. Other subsystems append to this via `get_subsystem`.
        self.session_files: list[str] = [
            "cmdline", "server.env", "config", "server.log*",
            # notifications may use a TMP dir:
            "tmp/*", "tmp",
        ]

    def init(self, opts) -> None:
        super().init(opts)
        if not self.config_contents:
            self.config_contents = get_options_file_contents(opts)
            self.write_session_file("config", self.config_contents)

    def late_cleanup(self, stop=True) -> None:
        if stop:
            log("clean_session_files(%s)", self.session_files)
            clean_session_files(*self.session_files)
            if stop:
                rm_session_dir()

    def write_session_file(self, filename: str, contents) -> str:
        return save_session_file(filename, contents, self.uid, self.gid)

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
