# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Command-line argument parsing utilities extracted from xpra.scripts.main.
Pure functions with no GTK/platform dependencies.
"""

from xpra.os_util import POSIX
from xpra.net.constants import SOCKET_TYPES
from xpra.util.str_fn import is_valid_hostname
from xpra.scripts.parsing import REVERSE_MODE_ALIAS
from xpra.scripts.config import InitException


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
