# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from shutil import copy2
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.platform.posix.paths import do_get_resources_dir


def get_autostart_file() -> str:
    # find the 'xdg autostart' directory:
    if os.getuid() == 0:
        adir = None
        for cdir in (os.environ.get("XDG_CONFIG_DIRS", "") or "/etc/xdg").split(":"):
            if not cdir:
                continue
            adir = os.path.join(cdir, "autostart")
            if os.path.exists(adir) and os.path.isdir(adir):
                break
    else:
        adir = os.path.join(os.environ.get("XDG_CONFIG_HOME", "~/.config"), "autostart")
    if not adir:
        return ""
    adir = os.path.expanduser(adir)
    if not os.path.exists(adir):
        os.mkdir(adir, mode=0o755)
    return os.path.join(adir, "xpra.desktop")


def set_autostart(enabled):
    target = get_autostart_file()
    if not target:
        raise RuntimeError("unable to locate autostart directory")
    if enabled:
        # find the file to copy there:
        autostart = os.path.join(do_get_resources_dir(), "autostart.desktop")
        if not os.path.exists(autostart):
            raise InitExit(ExitCode.FILE_NOT_FOUND, f"{autostart!r} file not found")
        copy2(autostart, target)
    else:
        os.unlink(target)


def get_status() -> str:
    return ["disabled", "enabled"][os.path.exists(get_autostart_file())]
