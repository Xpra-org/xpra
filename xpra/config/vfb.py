#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Virtual display commands and host-dependent Xorg discovery."""

import os
import sys
from collections.abc import Callable
from xpra import config
from xpra.os_util import WIN32, OSX, POSIX
from xpra.util.system import is_DEB, is_DEB_Xdummy_safe, can_use_fakescreenfps


X11_ENABLED_EXTENSIONS = tuple(os.environ.get("XPRA_X11_ENABLED_EXTENSIONS", "GLX,RANDR,RENDER,Composite").split(","))
X11_DISABLED_EXTENSIONS = tuple(os.environ.get("XPRA_X11_DISABLED_EXTENSIONS", "DOUBLE-BUFFER").split(","))


def get_xorg_bin() -> str:
    if xorg := os.environ.get("XPRA_XORG_BIN"):
        return xorg
    # Detect Xorg Binary
    for p in (
        "/usr/libexec/Xorg",              # fedora 22+
        "/usr/lib/xorg/Xorg",             # ubuntu 16.10
        "/usr/lib/xorg-server/Xorg",      # arch linux
        "/usr/lib/Xorg",                  # arch linux (new 2019)
        "/usr/X11/bin/X",                 # OSX
    ):
        if os.path.exists(p):
            return p
    # look for it in $PATH:
    for x in os.environ.get("PATH", "").split(os.pathsep):   # pragma: no cover
        xorg = os.path.join(x, "Xorg")
        if os.path.isfile(xorg):
            return xorg
    return ""


def get_Xdummy_confdir() -> str:
    from xpra.platform.posix.paths import get_runtime_dir
    if get_runtime_dir():
        base = "${XPRA_SESSION_DIR}"
    else:   # pragma: no cover
        base = "${HOME}/.xpra"
    return base+"/xorg.conf.d/$PID"


def add_ext_net_dpi_fps(cmd: list[str], depth=24, dpi=0, fps=0) -> list[str]:
    extensions = list(X11_ENABLED_EXTENSIONS)
    if depth <= 8 and "Composite" in extensions:
        extensions.remove("Composite")
    if os.environ.get("XPRA_XPRESENT", "0") == "1":
        extensions.append("Present")
    for extension in extensions:
        cmd += ["+extension", extension]
    for extension in X11_DISABLED_EXTENSIONS:
        cmd += ["-extension", extension]
    cmd += [
        "-nolisten", "tcp",
        "-noreset",
        "-auth", "$XAUTHORITY",
    ]
    if POSIX and not OSX and fps > 0 and can_use_fakescreenfps():
        cmd += ["-fakescreenfps", str(fps)]
    if dpi > 0:
        cmd += ["-dpi", f"{dpi}x{dpi}"]
    return cmd


def get_Xdummy_command(xorg_cmd="Xorg",
                       log_dir="${XPRA_SESSION_DIR}",
                       xorg_conf="${XORG_CONFIG_PREFIX}/etc/xpra/xorg.conf",
                       depth=24, dpi=0, fps=0) -> list[str]:
    return add_ext_net_dpi_fps([
        # ie: "Xorg" or "xpra_Xdummy" or "./install/bin/xpra_Xdummy"
        xorg_cmd,
        "-novtswitch",
        "-logfile", f"{log_dir}/Xorg.log",
        # must be specified with some Xorg versions (ie: arch linux)
        # this directory can store xorg config files, it does not need to be created:
        "-configdir", f"{get_Xdummy_confdir()}",
        "-config", f"{xorg_conf}",
    ], depth, dpi, fps)


def get_Xvfb_command(width=8192, height=4096, depth=24, dpi=96, fps=0) -> list[str]:
    return add_ext_net_dpi_fps([
        "Xvfb",
        "-screen", "0", f"{width}x{height}x{depth}",
    ], depth, dpi, fps)


def get_Xephyr_command(width=1920, height=1080, depth=24, dpi=96, fps=0) -> list[str]:
    return add_ext_net_dpi_fps([
        "Xephyr",
        "-screen", f"{width}x{height}x{depth}+32",
    ], depth, dpi, fps)


def get_weston_Xwayland_command(depth=24, dpi=96, fps=0) -> list[str]:
    return add_ext_net_dpi_fps([
        "/usr/libexec/xpra/xpra_weston_xvfb",
    ], depth, dpi, fps)


def xvfb_command(cmd: str, depth=24, dpi=0, fps=0) -> list[str]:
    import shlex
    parts = shlex.split(cmd)
    if len(parts) > 1:
        return parts
    if depth == 0:
        depth = 24
    exe = parts[0]
    if os.path.isabs(exe):
        return parts
    if exe == "Xvfb":
        return get_Xvfb_command(depth=depth, dpi=dpi, fps=fps)
    if exe == "Xephyr":
        return get_Xephyr_command(depth=depth, dpi=dpi, fps=fps)
    if exe in ("weston", "weston+Xwayland"):
        return get_weston_Xwayland_command(depth=depth, dpi=dpi, fps=fps)
    if exe in ("Xorg", "Xdummy"):
        xorg_bin = get_xorg_bin()
        return get_Xdummy_command(xorg_bin, depth=depth, dpi=dpi, fps=fps)
    if exe == "auto":
        return detect_xvfb_command(depth=depth, dpi=dpi, fps=fps)
    return parts


def detect_xvfb_command(conf_dir="/etc/xpra/", bin_dir="",
                        Xdummy_ENABLED: bool | None = None, Xdummy_wrapper_ENABLED: bool | None = None,
                        warn_fn: Callable = config.warn,
                        depth=24, dpi=0, fps=0,
                        ) -> list[str]:
    """
    This function returns the xvfb command to use.
    It can either be an `Xvfb` command or one that uses `Xdummy`,
    depending on the platform and file attributes.
    """
    if WIN32:   # pragma: no cover
        return []

    def vfb_default() -> list[str]:
        return get_Xvfb_command(depth=depth, dpi=dpi, fps=fps)

    if OSX:     # pragma: no cover
        return vfb_default()
    if sys.platform.find("bsd") >= 0 and Xdummy_ENABLED is None:  # pragma: no cover
        warn_fn(f"Warning: sorry, no support for Xdummy on {sys.platform}")
        return vfb_default()
    if is_DEB() and not is_DEB_Xdummy_safe():
        # Older versions of these distros do weird things and this can cause the real X11 server to crash
        # see ticket #2834
        return vfb_default()

    if Xdummy_ENABLED is False:
        return vfb_default()

    if Xdummy_ENABLED is None:
        config.debug("Xdummy support unspecified, will try to detect")
        # RHEL 10 needs to use `xpra_weston_xvfb` instead of Xorg:

        from xpra.util.system import is_distribution_variant, get_distribution_version_id
        rhel10 = get_distribution_version_id() == "10" and any(is_distribution_variant(x) for x in (
            "RedHat", "AlmaLinux", "RockyLinux", "OracleLinux",
        ))
        if rhel10:
            config.debug(" using `xpra_weston_xvfb` on RHEL 10")
            return get_weston_Xwayland_command(depth=depth, dpi=dpi, fps=fps)
    return detect_xdummy_command(conf_dir, bin_dir, Xdummy_wrapper_ENABLED, warn_fn, depth=depth, dpi=dpi, fps=fps)


def detect_xdummy_command(conf_dir="/etc/xpra/", bin_dir="",
                          Xdummy_wrapper_ENABLED: bool | None = None,
                          warn_fn: Callable = config.warn,
                          depth=24, dpi=0, fps=0) -> list[str]:
    if not POSIX or OSX:
        return get_Xvfb_command(depth=depth, dpi=dpi, fps=fps)
    xorg_bin = get_xorg_bin()
    if Xdummy_wrapper_ENABLED is not None:
        # honour what was specified:
        use_wrapper = Xdummy_wrapper_ENABLED
    elif not xorg_bin:
        warn_fn("Warning: Xorg binary not found, assuming the wrapper is needed!")
        use_wrapper = True
    else:
        # auto-detect
        import stat
        xorg_stat = os.stat(xorg_bin)
        if (xorg_stat.st_mode & stat.S_ISUID) != 0:
            if (xorg_stat.st_mode & stat.S_IROTH) == 0:
                warn_fn(f"{xorg_bin} is suid and not readable, Xdummy support unavailable")
                return get_Xvfb_command(depth=depth, dpi=dpi, fps=fps)
            config.debug(f"{xorg_bin} is suid and readable, using the xpra_Xdummy wrapper")
            use_wrapper = True
        else:
            use_wrapper = False
    xorg_conf = "${XORG_CONFIG_PREFIX}"+os.path.join(conf_dir, "xorg.conf")
    if use_wrapper:
        xorg_cmd = "xpra_Xdummy"
    else:
        xorg_cmd = xorg_bin or "Xorg"
    # so we can run from install dir:
    if bin_dir and os.path.exists(os.path.join(bin_dir, xorg_cmd)):
        if bin_dir not in os.environ.get("PATH", "/bin:/usr/bin:/usr/local/bin").split(os.pathsep):
            xorg_cmd = os.path.join(bin_dir, xorg_cmd)
    return get_Xdummy_command(xorg_cmd, xorg_conf=xorg_conf, depth=depth, dpi=dpi, fps=fps)


def wrap_cmd_str(cmd) -> str:
    xvfb_str = ""
    cr = " \\\n    "
    while cmd:
        s = ""
        while cmd:
            item = cmd[0]
            l = len(item)
            if (item.startswith("-") or item.startswith("+")) and len(cmd) > 1:
                l += len(cmd[1])
            if s and len(s)+l > 55:
                break
            v = cmd.pop(0)
            if not s:
                s += v
            else:
                s += " "+v
        if xvfb_str:
            xvfb_str += cr
        xvfb_str += s
    return xvfb_str


def run_xvfb_command(options) -> int:
    import shlex
    from xpra.util.parsing import get_refresh_rate_for_value
    fps = get_refresh_rate_for_value(options.refresh_rate, 60) if options.refresh_rate else 0
    print(shlex.join(xvfb_command(options.xvfb, options.pixel_depth, options.dpi, fps)))
    return 0
