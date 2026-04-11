# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Command-line argument parsing utilities extracted from xpra.scripts.main.
Pure functions with no GTK/platform dependencies.
"""

from typing import Any
from collections.abc import Sequence

from xpra.os_util import POSIX, getuid, getgid
from xpra.net.constants import SOCKET_TYPES
from xpra.util.str_fn import is_valid_hostname, csv
from xpra.scripts.parsing import REVERSE_MODE_ALIAS
from xpra.scripts.config import (
    OPTION_TYPES, NON_COMMAND_LINE_OPTIONS, CLIENT_ONLY_OPTIONS,
    START_COMMAND_OPTIONS, BIND_OPTIONS, OPTIONS_ADDED_SINCE_V5, OPTIONS_COMPAT_NAMES,
    InitException,
    fixup_options, make_defaults_struct,
)


def shellquote(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def strip_defaults_start_child(start_child, defaults_start_child):
    if start_child and defaults_start_child:
        # ensure we don't pass start / start-child commands
        # which came from defaults (the configuration files)
        # only the ones specified on the command line:
        # (and only remove them once so the command line can re-add the same ones!)
        for x in defaults_start_child:
            if x in start_child:
                start_child.remove(x)
    return start_child


def is_display_arg(arg: str) -> bool:
    if arg.startswith(":") or arg.startswith("wayland-"):
        return True
    for prefix in SOCKET_TYPES:
        if arg.startswith(f"{prefix}://"):
            return True
    # could still be a naked display number without the ":" prefix:
    try:
        return int(arg) >= 0
    except ValueError:
        return False


def split_display_arg(args: list[str]) -> tuple[list[str], list[str]]:
    if not args:
        return [], []
    if is_display_arg(args[0]):
        return args[:1], args[1:]
    return [], args


def is_connection_arg(arg) -> bool:
    if POSIX and (arg.startswith(":") or arg.startswith("wayland-")):
        return True
    if any(arg.startswith(f"{mode}://") for mode in SOCKET_TYPES):
        return True
    if any(arg.startswith(f"{mode}:") for mode in SOCKET_TYPES):
        return True
    if any(arg.startswith(f"{mode}/") for mode in SOCKET_TYPES):
        return True
    # could be a plain TCP address, specifying a display,
    # ie: 127.0.0.1:0 or SOMEHOST:0.0
    parts = arg.split(":")
    if len(parts) == 2:
        host, display = parts
        if is_valid_hostname(host) and display.replace(".", "").isdigit():
            # this is a valid connection argument
            return True
    return False


def strip_attach_extra_positional_args(cmdline: list[str]) -> list[str]:
    """
    When reconnecting we re-exec the client using `attach`.

    For `seamless`/`desktop`/`monitor`, positional non-connection arguments are
    treated as implicit `--start-child` commands, but those must not be kept
    during reconnect (otherwise `attach` will treat them as extra display args).

    This function keeps the first display argument after `attach`, plus any
    subsequent options (and their values), and drops any extra positional args.
    """
    try:
        attach_pos = cmdline.index("attach")
    except ValueError:
        return cmdline

    display_pos = None
    for i in range(attach_pos + 1, len(cmdline)):
        arg = cmdline[i]
        if arg.startswith("-"):
            continue
        if is_display_arg(arg) or is_connection_arg(arg):
            display_pos = i
            break
    if display_pos is None:
        return cmdline

    cleaned = cmdline[:display_pos + 1]
    expecting_option_value = False
    for arg in cmdline[display_pos + 1:]:
        if expecting_option_value:
            cleaned.append(arg)
            expecting_option_value = False
        elif arg.startswith("-"):
            cleaned.append(arg)
            expecting_option_value = arg.startswith("--") and "=" not in arg
        # extra positional argument after the display: drop it
    return cleaned


def get_start_server_args(opts, uid=getuid(), gid=getgid(), compat=False, cmdline: Sequence[str] = ()) -> list[str]:
    option_types = {}
    for x, ftype in OPTION_TYPES.items():
        if x not in CLIENT_ONLY_OPTIONS:
            option_types[x] = ftype
    return get_command_args(opts, uid, gid, option_types, compat, cmdline)


def get_command_args(opts, uid: int, gid: int, option_types: dict[str, Any],
                     compat=False, cmdline: Sequence[str] = ()) -> list[str]:
    defaults = make_defaults_struct(uid=uid, gid=gid)
    fdefaults = defaults.clone()
    fixup_options(fdefaults)
    args = []
    for x, ftype in option_types.items():
        if x in NON_COMMAND_LINE_OPTIONS:
            continue
        if compat and x in OPTIONS_ADDED_SINCE_V5:
            continue
        fn = x.replace("-", "_")
        ov = getattr(opts, fn)
        dv = getattr(defaults, fn)
        fv = getattr(fdefaults, fn)
        incmdline = (f"--{x}" in cmdline or f"--no-{x}" in cmdline or any(c.startswith(f"--{x}=") for c in cmdline))
        if not incmdline:
            # we may skip this option if the value is the same as the default:
            if ftype is list:
                # compare lists using their csv representation:
                if csv(ov) == csv(dv) or csv(ov) == csv(fv):
                    continue
            if ov in (dv, fv):
                continue  # same as the default
        argname = f"--{x}="
        if compat:
            argname = OPTIONS_COMPAT_NAMES.get(argname, argname)
        # lists are special cased depending on how OptionParse will be parsing them:
        if ftype is list:
            # warn("%s: %s vs %s\n" % (x, ov, dv))
            if x in START_COMMAND_OPTIONS + BIND_OPTIONS + [
                "pulseaudio-configure-commands",
                "speaker-codec", "microphone-codec",
                "key-shortcut", "start-env", "env",
                "socket-dirs",
            ]:
                # individual arguments (ie: "--start=xterm" "--start=gedit" ..)
                for e in ov:
                    args.append(f"{argname}{e}")
            else:
                # those can be specified as CSV: (ie: "--encodings=png,jpeg,rgb")
                args.append(f"{argname}" + ",".join(str(v) for v in ov))
        elif ftype is bool:
            args.append(f"{argname}" + ["no", "yes"][int(ov)])
        elif ftype in (int, float, str):
            args.append(f"{argname}{ov}")
        else:
            raise InitException(f"unknown option type {ftype!r} for {x!r}")
    return args


def find_mode_pos(args, mode: str) -> int:
    rmode = REVERSE_MODE_ALIAS.get(mode, str(mode))
    mode_strs = [rmode]
    if rmode.find("-") > 0:
        mode_strs.append(rmode.split("-", 1)[1])  # ie: "start-desktop" -> "desktop"
    if mode == "seamless":  # ie: "seamless" -> "start"
        mode_strs.append("start")
    for mstr in mode_strs:
        try:
            return args.index(mstr)
        except ValueError:
            pass
    raise InitException(f"mode {mode!r} not found in command line arguments {args}")
