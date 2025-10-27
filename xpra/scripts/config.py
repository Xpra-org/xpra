#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import glob
import shlex
from typing import Any
from collections.abc import Callable, Iterable, Sequence

from xpra.common import noop, Self, BACKWARDS_COMPATIBLE
from xpra.util.parsing import (
    TRUE_OPTIONS, FALSE_OPTIONS,
    str_to_bool, parse_bool_or, parse_bool_or_number, parse_number,
)
from xpra.util.str_fn import csv
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import WIN32, OSX, POSIX, getuid, getgid, get_username_for_uid, is_arm
from xpra.util.env import osexpand
from xpra.util.io import stderr_print, which
from xpra.util.system import is_DEB, can_use_fakescreenfps


def warn(msg: str) -> None:
    stderr_print(msg)


# can be overridden
debug = noop


class InitException(Exception):
    pass


class InitInfo(Exception):
    pass


class InitExit(Exception):
    def __init__(self, status: ExitValue, msg):
        self.status = status
        super().__init__(msg)


DEBUG_CONFIG_PROPERTIES: list[str] = os.environ.get("XPRA_DEBUG_CONFIG_PROPERTIES", "").split()

DEFAULT_XPRA_CONF_FILENAME: str = os.environ.get("XPRA_CONF_FILENAME", 'xpra.conf')
DEFAULT_NET_WM_NAME: str = os.environ.get("XPRA_NET_WM_NAME", "Xpra")

DEFAULT_POSTSCRIPT_PRINTER: str = ""
if POSIX:
    DEFAULT_POSTSCRIPT_PRINTER = os.environ.get("XPRA_POSTSCRIPT_PRINTER", "drv:///sample.drv/generic.ppd")
DEFAULT_PULSEAUDIO = None   # auto
if OSX or WIN32:   # pragma: no cover
    DEFAULT_PULSEAUDIO = False

# pylint: disable=import-outside-toplevel


def remove_dupes(seq: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    seen_add: Callable = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]


_has_audio_support: bool | None = None


def has_audio_support() -> bool:
    global _has_audio_support
    if _has_audio_support is None:
        try:
            from importlib.util import find_spec
            _has_audio_support = bool(find_spec("xpra.audio"))
        except ImportError:
            _has_audio_support = False
    return bool(_has_audio_support)


def find_html5_path(page="connect.html") -> str:
    from xpra.platform.paths import get_resources_dir, get_app_dir
    return valid_html_path(
        os.path.join(get_resources_dir(), "html5", page),
        os.path.join(get_resources_dir(), "www", page),
        os.path.join(get_app_dir(), "www", page),
    )


def find_docs_path() -> str:
    from xpra.platform.paths import get_resources_dir, get_app_dir
    paths = []
    prefixes = {get_resources_dir(), get_app_dir()}
    if POSIX:
        prefixes.add("/usr/share")
        prefixes.add("/usr/local/share")
    for prefix in prefixes:
        for parts in (
                ("doc", "xpra", "index.html"),
                ("xpra", "doc", "index.html"),
                ("doc", "index.html"),
                ("doc", "index.html"),
        ):
            paths.append(os.path.join(prefix, *parts))
    return valid_html_path(*paths)


def valid_html_path(*path_options: str) -> str:
    for f in path_options:
        af = os.path.abspath(f)
        if os.path.exists(af) and os.path.isfile(af):
            return af
    return ""


def get_xorg_bin() -> str:
    xorg = os.environ.get("XPRA_XORG_BIN")
    if xorg:
        return xorg
    # Detect Xorg Binary
    if is_arm() and is_DEB() and os.path.exists("/usr/bin/Xorg"):
        # Raspbian breaks if we use a different binary..
        return "/usr/bin/Xorg"
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
    xrd = get_runtime_dir()
    if xrd:
        base = "${XPRA_SESSION_DIR}"
    else:   # pragma: no cover
        base = "${HOME}/.xpra"
    return base+"/xorg.conf.d/$PID"


def add_ext_net_dpi_fps(cmd: list[str], depth=24, dpi=0, fps=0) -> list[str]:
    if depth > 8:
        cmd += ["+extension", "Composite"]
    cmd += [
        "+extension", "GLX",
        "+extension", "RANDR",
        "+extension", "RENDER",
        "-extension", "DOUBLE-BUFFER",
    ]
    if os.environ.get("XPRA_XPRESENT", "0") == "1":
        cmd += ["+extension", "Present"]
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
                        warn_fn: Callable = warn,
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
    if is_DEB():
        # These distros do weird things and this can cause the real X11 server to crash
        # see ticket #2834
        return vfb_default()

    if Xdummy_ENABLED is False:
        return vfb_default()

    if Xdummy_ENABLED is None:
        debug("Xdummy support unspecified, will try to detect")
        # RHEL 10 needs to use `xpra_weston_xvfb` instead of Xorg:

        from xpra.util.system import is_distribution_variant, get_distribution_version_id
        rhel10 = get_distribution_version_id() == "10" and any(is_distribution_variant(x) for x in (
            "RedHat", "AlmaLinux", "RockyLinux", "OracleLinux",
        ))
        if rhel10:
            debug(" using `xpra_weston_xvfb` on RHEL 10")
            return get_weston_Xwayland_command(dpi)
    return detect_xdummy_command(conf_dir, bin_dir, Xdummy_wrapper_ENABLED, warn_fn, depth=depth, dpi=dpi, fps=fps)


def detect_xdummy_command(conf_dir="/etc/xpra/", bin_dir="",
                          Xdummy_wrapper_ENABLED: bool | None = None,
                          warn_fn: Callable = warn,
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
                return get_Xvfb_command(dpi=dpi, fps=fps)
            debug(f"{xorg_bin} is suid and readable, using the xpra_Xdummy wrapper")
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


def get_build_info() -> list[str]:
    info = []
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT
        info.append(f"revision {REVISION}")
        if COMMIT:
            info.append(f"commit {COMMIT} from {BRANCH} branch")
        try:
            mods = int(LOCAL_MODIFICATIONS)
            info.append(f"with {mods} local changes")
        except ValueError:
            pass
    except Exception as e:
        warn(f"Error: could not find the source information: {e}")
    try:
        from xpra.build_info import build
    except ImportError as e:
        warn(f"Error: could not find the build information: {e}")
        build = {}
    info.append(build.get("type", "") + " build")
    info.insert(0, "")
    einfo = "Python " + ".".join(str(v) for v in sys.version_info[:2])
    machine = build.get("machine", "")
    if machine:
        einfo += ", "+machine
    else:
        bit = build.get("bit")
        if bit:
            einfo += ", "+bit
    info.insert(0, einfo)
    by = build.get("by", "")
    on = build.get("on", "")
    if by and on:
        info.append(f"built on {on} by {by}")
    date = build.get("date", "")
    time = build.get("time", "")
    if date and time:
        info.append(f"{date} {time}")
    cython = build.get("cython", "unknown")
    compiler = build.get("compiler", "unknown")
    if cython != "unknown" or compiler != "unknown":
        info.append("")
    if cython != "unknown":
        info.append(f"using Cython {cython}")
    if compiler != "unknown":
        cv = compiler.replace("Optimizing Compiler Version", "Optimizing Compiler\nVersion")
        info += cv.splitlines()
    return info


def name_to_field(name: str) -> str:
    return name.replace("-", "_")


def save_config(conf_file: str, config, keys, extras_types=None) -> None:
    with open(conf_file, "w", encoding="utf8") as f:
        option_types = OPTION_TYPES.copy()
        if extras_types:
            option_types.update(extras_types)
        saved = {}
        for key in keys:
            if key not in option_types:
                raise ValueError(f"invalid configuration key {key!r}")
            v = getattr(config, name_to_field(key))
            saved[key] = v
            f.write(f"{key}={v}{os.linesep}")
        debug(f"save_config: saved {saved} to {conf_file!r}")


def read_config(conf_file: str) -> dict[str, Any]:
    """
        Parses a config file into a dict of strings.
        If the same key is specified more than once,
        the value for this key will be an array of strings.
    """
    d: dict[str, str | list[str]] = {}
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        debug("read_config(%s) is not a file or does not exist", conf_file)
        return d
    with open(conf_file, encoding="utf8") as f:
        lines = []
        no = 0
        for line in f:
            sline = line.strip().strip('\r\n').strip()
            no += 1
            if not sline:
                debug("%4s empty line", no)
                continue
            if sline[0] in ('!', '#'):
                debug("%4s skipping comments   : %s", no, sline[:16]+"..")
                continue
            debug("%4s loaded              : %s", no, sline)
            lines.append(sline)
    debug("loaded %s lines", len(lines))
    # aggregate any lines with trailing backslash
    agg_lines = []
    l = ""
    for line in lines:
        if line.endswith("\\"):
            l += line[:-1]+" "
        else:
            l += line
            agg_lines.append(l)
            l = ""
    if l:
        # last line had a trailing backslash... meh
        agg_lines.append(l)
    debug("loaded %s aggregated lines", len(agg_lines))
    # parse name=value pairs:
    for sline in agg_lines:
        if sline.find("=") <= 0:
            debug(f"skipping line which is missing an equal sign: {sline!r}")
            continue
        props = sline.split("=", 1)
        assert len(props) == 2
        name = props[0].strip()
        value = props[1].strip()
        current_value = d.get(name)
        if current_value:
            if isinstance(current_value, list):
                d[name] = current_value + [value]
            else:
                d[name] = [current_value, value]
            debug("added to: %s='%s'", name, d[name])
        else:
            debug("assigned (new): %s='%s'", name, value)
            d[name] = value
        if name in DEBUG_CONFIG_PROPERTIES:
            from xpra.log import Logger
            log = Logger("util")
            log.info(f"{name}={d[name]} (was {current_value}), from {conf_file!r}")
    return d


def conf_files(conf_dir: str, xpra_conf_filename: str = DEFAULT_XPRA_CONF_FILENAME) -> list[str]:
    """
        Returns all the config file paths found in the config directory
        ie: ["/etc/xpra/conf.d/15_features.conf", ..., "/etc/xpra/xpra.conf"]
    """
    d: list[str] = []
    cdir = os.path.expanduser(conf_dir)
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        debug(f"invalid config directory: {cdir!r}")
        return d
    # look for conf.d subdirectory:
    conf_d_dir = os.path.join(cdir, "conf.d")
    if os.path.exists(conf_d_dir) and os.path.isdir(conf_d_dir):
        for f in sorted(os.listdir(conf_d_dir)):
            if f.endswith(".conf"):
                conf_file = os.path.join(conf_d_dir, f)
                if os.path.isfile(conf_file):
                    d.append(conf_file)
    conf_file = os.path.join(cdir, xpra_conf_filename)
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        debug(f"config file does not exist: {conf_file!r}")
    else:
        d.append(conf_file)
    return d


def read_xpra_conf(conf_dir: str) -> dict[str, Any]:
    """
        Reads all config files from the directory,
        returns a dict with key as strings,
        values as strings or arrays of strings.
    """
    cdir = os.path.expanduser(conf_dir)
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        debug(f"invalid config directory: {cdir!r}")
        return {}
    files = glob.glob(f"{cdir}/{DEFAULT_XPRA_CONF_FILENAME}") + glob.glob(f"{cdir}/conf.d/*.conf")
    debug(f"read_xpra_conf({conf_dir}) found conf files: {files}")
    d = {}
    for f in files:
        cd = read_config(f)
        debug(f"config({f})={cd}")
        d.update(cd)
    return d


def read_xpra_defaults(username: str | None = None, uid=None, gid=None) -> dict[str, Any]:
    """
        Reads the global <xpra_conf_filename> from the <conf_dir>
        and then the user-specific one.
        (the latter overrides values from the former)
        returns a dict with values as strings and arrays of strings.
        If the <conf_dir> is not specified, we figure out its location.
    """
    dirs = get_xpra_defaults_dirs(username, uid, gid)
    defaults: dict[str, Any] = {}
    for d in dirs:
        conf_data = read_xpra_conf(d)
        defaults.update(conf_data)
        debug(f"read_xpra_defaults: updated defaults with {d!r} : {conf_data}")
    may_create_user_config()
    return defaults


def get_xpra_defaults_dirs(username: str | None = None, uid=None, gid=None) -> list[str]:
    from xpra.platform.paths import get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs
    # load config files in this order (the later ones override earlier ones):
    # * application defaults, ie:
    #   "/Volumes/Xpra/Xpra.app/Contents/Resources/" on OSX
    #   "C:\Program Files\Xpra\" on win32
    #   None on others
    # * system defaults, ie:
    #   "/etc/xpra" on Posix - not on OSX
    #   "/Library/Application Support/Xpra" on OSX
    #   "C:\ProgramData\Xpra" with Vista onwards
    # * user config, ie:
    #   "~/.xpra/" on all Posix, including OSX
    #   "C:\Users\<user name>\AppData\Roaming" with Visa onwards
    dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs(uid)
    defaults_dirs = []
    for d in dirs:
        if not d:
            continue
        ad = osexpand(d, actual_username=username, uid=uid, gid=gid)
        if not os.path.exists(ad):
            debug(f"get_xpra_defaults_dirs: skipped missing directory {ad!r}")
            continue
        defaults_dirs.append(ad)
    return defaults_dirs


def may_create_user_config(xpra_conf_filename: str = DEFAULT_XPRA_CONF_FILENAME) -> None:
    from xpra.platform.paths import get_user_conf_dirs
    # save a user config template:
    udirs = get_user_conf_dirs()
    if any(os.path.exists(osexpand(d)) for d in udirs):
        return
    debug("no user configuration file found, trying to create one")
    for d in udirs:
        ad = os.path.expanduser(d)
        conf_file = os.path.join(ad, xpra_conf_filename)
        try:
            if not os.path.exists(ad):
                os.makedirs(ad, int('700', 8))
            with open(conf_file, 'w', encoding="utf8") as f:
                f.write("""# xpra user configuration file
# place your custom settings in this file
# they will take precedence over the system default ones.

# Examples:
# speaker=off
# dpi=144

# For more information on the file format,
# see the xpra manual at:
# https://github.com/Xpra-org/xpra/tree/master/docs/
""")
                f.flush()
            debug(f"created default config in {d!r}")
            return
        except Exception as e:
            debug(f"failed to create default config in {conf_file!r}: {e}")


OPTIONS_VALIDATION: dict[str, Callable] = {}

OPTION_TYPES: dict[str, Any] = {
    # string options:
    "encoding"          : str,
    "opengl"            : str,
    "title"             : str,
    "username"          : str,
    "password"          : str,
    "wm-name"           : str,
    "session-name"      : str,
    "dock-icon"         : str,
    "tray-icon"         : str,
    "window-icon"       : str,
    "keyboard-raw"      : bool,
    "keyboard-backend"  : str,
    "keyboard-model"    : str,
    "keyboard-layout"   : str,
    "keyboard-layouts"  : list,
    "keyboard-variant"  : str,
    "keyboard-variants" : list,
    "keyboard-options"  : str,
    "clipboard"         : str,
    "clipboard-direction" : str,
    "clipboard-filter-file" : str,
    "remote-clipboard"  : str,
    "local-clipboard"   : str,
    "pulseaudio-command": str,
    "bandwidth-limit"   : str,
    "tcp-encryption"    : str,
    "tcp-encryption-keyfile": str,
    "encryption"        : str,
    "encryption-keyfile": str,
    "pidfile"           : str,
    "mode"              : str,
    "ssh"               : str,
    "systemd-run"       : str,
    "systemd-run-args"  : str,
    "system-proxy-socket" : str,
    "chdir"             : str,
    "xvfb"              : str,
    "socket-dir"        : str,
    "sessions-dir"      : str,
    "mmap"              : str,
    "log-dir"           : str,
    "log-file"          : str,
    "border"            : str,
    "window-close"      : str,
    "min-size"          : str,
    "max-size"          : str,
    "desktop-scaling"   : str,
    "refresh-rate"      : str,
    "display"           : str,
    "download-path"     : str,
    "open-command"      : str,
    "remote-logging"    : str,
    "lpadmin"           : str,
    "lpinfo"            : str,
    "add-printer-options" : list,
    "pdf-printer"       : str,
    "postscript-printer": str,
    "debug"             : str,
    "input-method"      : str,
    "video-scaling"     : str,
    "video"             : bool,
    "audio"             : bool,
    "microphone"        : str,
    "speaker"           : str,
    "audio-source"      : str,
    "html"              : str,
    "http-scripts"      : str,
    "socket-permissions": str,
    "exec-wrapper"      : str,
    "dbus"              : bool,
    "dbus-launch"       : str,
    "webcam"            : str,
    "pointer"           : str,
    "mousewheel"        : str,
    "input-devices"     : str,
    "shortcut-modifiers": str,
    "open-files"        : str,
    "open-url"          : str,
    "file-transfer"     : str,
    "printing"          : str,
    "headerbar"         : str,
    "challenge-handlers": list,
    # ssl options:
    "ssl"               : str,
    "ssl-key"           : str,
    "ssl-key-password"  : str,
    "ssl-cert"          : str,
    "ssl-protocol"      : str,
    "ssl-ca-certs"      : str,
    "ssl-ca-data"       : str,
    "ssl-ciphers"       : str,
    "ssl-client-verify-mode"   : str,
    "ssl-server-verify-mode"   : str,
    "ssl-verify-flags"  : str,
    "ssl-check-hostname": bool,
    "ssl-server-hostname" : str,
    "ssl-options"       : str,
    "backend"           : str,
    # int options:
    "displayfd"         : int,
    "pings"             : int,
    "quality"           : int,
    "min-quality"       : int,
    "speed"             : int,
    "min-speed"         : int,
    "compression_level" : int,
    "dpi"               : int,
    "file-size-limit"   : str,
    "idle-timeout"      : int,
    "server-idle-timeout" : int,
    "sync-xvfb"         : int,
    "pixel-depth"       : int,
    "uid"               : int,
    "gid"               : int,
    "min-port"          : int,
    "rfb-upgrade"       : int,
    "rdp-upgrade"       : bool,
    # float options:
    "auto-refresh-delay": float,
    # boolean options:
    "minimal"           : bool,
    "daemon"            : bool,
    "start-via-proxy"   : bool,
    "attach"            : bool,
    "use-display"       : str,
    "resize-display"    : str,
    "reconnect"         : bool,
    "tray"              : bool,
    "pulseaudio"        : bool,
    "mmap-group"        : str,
    "readonly"          : bool,
    "keyboard-sync"     : bool,
    "cursors"           : bool,
    "bell"              : bool,
    "notifications"     : bool,
    "xsettings"         : str,
    "system-tray"       : bool,
    "sharing"           : bool,
    "lock"              : bool,
    "delay-tray"        : bool,
    "windows"           : bool,
    "terminate-children": bool,
    "exit-with-children": bool,
    "exit-with-client"  : bool,
    "exit-with-windows" : bool,
    "exit-ssh"          : bool,
    "dbus-control"      : bool,
    "av-sync"           : bool,
    "mdns"              : bool,
    "swap-keys"         : bool,
    "commands"          : bool,
    "control"           : bool,
    "shell"             : bool,
    "http"              : bool,
    "start-new-commands": bool,
    "proxy-start-sessions": bool,
    "desktop-fullscreen": bool,
    "forward-xdg-open"  : bool,
    "modal-windows"     : bool,
    "bandwidth-detection" : bool,
    "ssl-upgrade"       : bool,
    "websocket-upgrade" : bool,
    "ssh-upgrade"       : bool,
    "splash"            : bool,
    "gstreamer"         : bool,
    # arrays of strings:
    "pulseaudio-configure-commands" : list,
    "socket-dirs"       : list,
    "client-socket-dirs" : list,
    "remote-xpra"       : list,
    "encodings"         : list,
    "video-encoders"    : list,
    "csc-modules"       : list,
    "video-decoders"    : list,
    "speaker-codec"     : list,
    "microphone-codec"  : list,
    "compressors"       : list,
    "packet-encoders"   : list,
    "key-shortcut"      : list,
    "source"            : list,
    "source-start"      : list,
    "start"             : list,
    "start-late"        : list,
    "start-child"       : list,
    "start-child-late"  : list,
    "start-after-connect"       : list,
    "start-child-after-connect" : list,
    "start-on-connect"          : list,
    "start-child-on-connect"    : list,
    "start-on-disconnect"       : list,
    "start-child-on-disconnect" : list,
    "start-on-last-client-exit" : list,
    "start-child-on-last-client-exit"   : list,
    "bind"              : list,
    "bind-vsock"        : list,
    "bind-tcp"          : list,
    "bind-ws"           : list,
    "bind-wss"          : list,
    "bind-ssl"          : list,
    "bind-ssh"          : list,
    "bind-rfb"          : list,
    "bind-rdp"          : list,
    "bind-quic"         : list,
    "auth"              : list,
    "vsock-auth"        : list,
    "tcp-auth"          : list,
    "ws-auth"           : list,
    "wss-auth"          : list,
    "ssl-auth"          : list,
    "ssh-auth"          : list,
    "rfb-auth"          : list,
    "rdp-auth"          : list,
    "quic-auth"         : list,
    "password-file"     : list,
    "start-env"         : list,
    "env"               : list,
}

# options removed in v6,
# don't show warnings when running with older config files:
OLD_OPTIONS: Sequence[str] = ("fake-xinerama", "dbus-proxy", "proxy-video-encoders") if BACKWARDS_COMPATIBLE else ()


# in the options list, available in session files,
# but not on the command line:
NON_COMMAND_LINE_OPTIONS : list[str] = [
    "mode",
    "wm-name",
    "download-path",
    "display",
    "pdf-printer",
    "postscript-printer",
    "add-printer-options",
]

START_COMMAND_OPTIONS : list[str] = [
    "start", "start-child",
    "start-late", "start-child-late",
    "start-after-connect", "start-child-after-connect",
    "start-on-connect", "start-child-on-connect",
    "start-on-disconnect", "start-child-on-disconnect",
    "start-on-last-client-exit", "start-child-on-last-client-exit",
]
BIND_OPTIONS : list[str] = [
    "bind", "bind-tcp", "bind-ssl", "bind-ws", "bind-wss", "bind-vsock", "bind-rfb", "bind-rdp", "bind-quic",
]

# keep track of the options added since v5,
# so we can generate command lines that work with older supported versions:
OPTIONS_ADDED_SINCE_V5: list[str] = [
    "minimal", "dbus", "gstreamer",
    "keyboard-backend", "keyboard-model",
    "bind-rdp", "rdp-auth", "rdp-upgrade",
]
OPTIONS_COMPAT_NAMES: dict[str, str] = {
    "--compression_level=": "-z"
}

CLIENT_OPTIONS: list[str] = [
    "title", "username", "password", "session-name",
    "dock-icon", "tray-icon", "window-icon",
    "clipboard", "clipboard-direction", "clipboard-filter-file",
    "remote-clipboard", "local-clipboard",
    "tcp-encryption", "tcp-encryption-keyfile", "encryption", "encryption-keyfile",
    "systemd-run", "systemd-run-args",
    "socket-dir", "socket-dirs", "client-socket-dirs",
    "border", "window-close", "min-size", "max-size", "desktop-scaling",
    "file-transfer", "file-size-limit", "download-path",
    "open-command", "open-files", "printing", "open-url",
    "headerbar",
    "challenge-handlers",
    "remote-logging",
    "lpadmin", "lpinfo",
    "debug",
    "microphone", "speaker", "audio-source",
    "microphone-codec", "speaker-codec",
    "mmap", "encodings", "encoding",
    "quality", "min-quality", "speed", "min-speed",
    "compression_level",
    "dpi", "video-scaling", "auto-refresh-delay",
    "webcam", "mousewheel", "pointer", "input-devices", "shortcut-modifiers", "pings",
    "tray", "keyboard-sync", "cursors", "bell", "notifications",
    "xsettings", "system-tray", "sharing", "lock",
    "delay-tray", "windows", "readonly",
    "av-sync", "swap-keys",
    "opengl",
    "start-new-commands",
    "desktop-fullscreen",
    "video-encoders", "csc-modules", "video-decoders",
    "compressors", "packet-encoders",
    "key-shortcut",
    "env",
    "ssh",
]

CLIENT_ONLY_OPTIONS: list[str] = [
    "username", "swap-keys", "dock-icon",
    "tray", "delay-tray", "tray-icon",
    "attach",
    "reconnect",
]

# options that clients can pass to the proxy
# and which will be forwarded to the new proxy instance process:
PROXY_START_OVERRIDABLE_OPTIONS: list[str] = [
    "env", "start-env", "chdir",
    "dpi",
    "encoding", "encodings",
    "quality", "min-quality", "speed", "min-speed",
    # "auto-refresh-delay",    float!
    # no corresponding command line option:
    # "wm-name", "download-path",
    "compression_level", "video-scaling",
    "title", "session-name",
    "clipboard", "clipboard-direction", "clipboard-filter-file",
    "input-method",
    "video",
    "audio", "microphone", "speaker", "audio-source", "pulseaudio",
    "idle-timeout", "server-idle-timeout",
    "use-display",
    "resize-display", "dpi", "pixel-depth",
    "readonly", "keyboard-sync", "cursors", "bell", "notifications", "xsettings",
    "system-tray", "sharing", "lock", "windows", "webcam", "html", "http-scripts",
    "terminate-children", "exit-with-children", "exit-with-client", "exit-with-windows",
    "av-sync",
    "forward-xdg-open", "modal-windows", "bandwidth-detection",
    "ssh-upgrade",
    "splash",
    "gstreamer",
    "printing", "file-transfer", "open-command", "open-files", "open-url", "start-new-commands",
    "mmap", "mmap-group", "mdns",
    "auth", "vsock-auth", "tcp-auth", "ws-auth", "wss-auth", "ssl-auth", "ssh-auth", "rfb-auth", "rdp-auth", "quic-auth",
    "bind", "bind-vsock", "bind-tcp", "bind-ssl", "bind-ws", "bind-wss", "bind-ssh", "bind-rfb", "bind-rdp", "bind-quic",
    "rfb-upgrade", "rdp-upgrade", "bandwidth-limit",
    "start", "start-child",
    "start-late", "start-child-late",
    "source", "source-start",
    "start-after-connect", "start-child-after-connect",
    "start-on-connect", "start-child-on-connect",
    "start-on-disconnect", "start-child-on-disconnect",
    "start-on-last-client-exit", "start-child-on-last-client-exit",
    "sessions-dir",
]
tmp: str = os.environ.get("XPRA_PROXY_START_OVERRIDABLE_OPTIONS", "")
if tmp:
    PROXY_START_OVERRIDABLE_OPTIONS = tmp.split(",")
del tmp


def get_default_key_shortcuts() -> list[str]:
    return [shortcut for e, shortcut in (
        (True, "Control+Menu:toggle_keyboard_grab"),
        (True, "Shift+Menu:toggle_pointer_grab"),
        (not OSX, "Shift+F11:toggle_fullscreen"),
        (OSX, "Control+F11:toggle_fullscreen"),
        (True, "#+F1:show_menu"),
        (True, "Control+F1:show_window_menu"),
        (True, "#+F2:show_start_new_command"),
        (True, "#+F3:show_bug_report"),
        (True, "#+F4:quit"),
        (True, "#+F5:show_window_info"),
        (True, "#+F6:show_shortcuts"),
        (True, "#+F7:show_docs"),
        (True, "#+F8:toggle_keyboard_grab"),
        (True, "#+F9:toggle_pointer_grab"),
        (True, "#+F10:magic_key"),
        (True, "#+F11:show_session_info"),
        (True, "#+F12:toggle_debug"),
        (True, "#+plus:scaleup"),
        (OSX, "#+plusminus:scaleup"),
        (True, "#+minus:scaledown"),
        (True, "#+underscore:scaledown"),
        (OSX, "#+emdash:scaledown"),
        (True, "#+KP_Add:scaleup"),
        (True, "#+KP_Subtract:scaledown"),
        (True, "#+KP_Multiply:scalereset"),
        (True, "#+bar:scalereset"),
        (True, "#+question:scalingoff"),
        (OSX, "#+degree:scalereset"),
        (OSX, "meta+grave:void"),
        (OSX, "meta+shift+asciitilde:void"),
    )
        if e]


def get_default_systemd_run() -> str:
    if WIN32 or OSX:
        return "no"
    # systemd-run was previously broken in Fedora 26:
    # https://github.com/systemd/systemd/issues/3388
    # but with newer kernels, it is working again..
    # now that we test it before using it,
    # it should be safe to leave it on auto:
    return "auto"


def unexpand(path: str) -> str:
    xrd = os.environ.get("XDG_RUNTIME_DIR", "")
    if POSIX and xrd and path.startswith(xrd):
        return "$XDG_RUNTIME_DIR/" + path[len(xrd):].lstrip("/")
    home = os.environ.get("HOME", "")
    if POSIX and home and path.startswith(home):
        return "~/" + path[len(home):].lstrip("/")
    return path


def unexpand_all(paths: list[str]) -> list[str]:
    return [unexpand(x) for x in paths]


GLOBAL_DEFAULTS: dict[str, Any] | None = None
# lowest common denominator here
# (the xpra.conf file shipped is generally better tuned than this - especially for 'xvfb')


def get_defaults() -> dict[str, Any]:
    global GLOBAL_DEFAULTS
    if GLOBAL_DEFAULTS is not None:
        return GLOBAL_DEFAULTS
    from xpra.platform.features import (
        OPEN_COMMAND,
        SOURCE, DEFAULT_ENV, DEFAULT_START_ENV, CAN_DAEMONIZE, SYSTEM_PROXY_SOCKET,
    )
    from xpra.platform.paths import (
        get_download_dir, get_remote_run_xpra_scripts,
        get_sessions_dir, get_socket_dirs, get_client_socket_dirs,
    )
    conf_dirs = [os.environ.get("XPRA_CONF_DIR", "")]
    build_root = os.environ.get("RPM_BUILD_ROOT", "")
    if build_root:
        conf_dirs.append(os.path.join(build_root, "etc", "xpra"))
    bin_dir = ""
    if sys.argv:
        xpra_cmd = sys.argv[0]
        for strip in ("/usr/bin", "/bin"):
            pos = xpra_cmd.find(strip)
            if pos >= 0:
                bin_dir = xpra_cmd[:pos+len(strip)]
                root = xpra_cmd[:pos] or "/"
                conf_dirs.append(os.path.join(root, "etc", "xpra"))
                break
    if sys.prefix == "/usr":
        conf_dirs.append("/etc/xpra")
    else:
        conf_dirs.append(os.path.join(sys.prefix, "etc", "xpra"))
    try:
        conf_dirs.append(os.getcwd())
    except FileNotFoundError:
        pass
    conf_dir = ""
    for conf_dir in conf_dirs:
        if conf_dir and os.path.exists(conf_dir):
            break
    xvfb = detect_xvfb_command(conf_dir, bin_dir, warn_fn=noop)
    xdummy = detect_xdummy_command(conf_dir, bin_dir, warn_fn=noop)

    ssl_protocol = "TLS"

    GLOBAL_DEFAULTS = {
        "encoding"          : "auto",
        "title"             : "@title@ on @hostinfo@",
        "username"          : "",
        "password"          : "",
        "wm-name"           : DEFAULT_NET_WM_NAME,
        "session-name"      : "",
        "dock-icon"         : "",
        "tray-icon"         : "",
        "window-icon"       : "",
        "keyboard-raw"      : False,
        "keyboard-backend"  : "",
        "keyboard-model"    : "",
        "keyboard-layout"   : "",
        "keyboard-layouts"  : [],
        "keyboard-variant"  : "",
        "keyboard-variants" : [],
        "keyboard-options"  : "",
        "clipboard"         : "yes",
        "clipboard-direction" : "both",
        "clipboard-filter-file" : "",
        "remote-clipboard"  : "CLIPBOARD",
        "local-clipboard"   : "CLIPBOARD",
        "pulseaudio-command": "auto",
        "bandwidth-limit"   : "auto",
        "encryption"        : "",
        "tcp-encryption"    : "",
        "encryption-keyfile": "",
        "tcp-encryption-keyfile": "",
        "pidfile"           : "${XPRA_SESSION_DIR}/server.pid",
        "ssh"               : "auto",
        "systemd-run"       : get_default_systemd_run(),
        "systemd-run-args"  : "",
        "system-proxy-socket" : SYSTEM_PROXY_SOCKET,
        "xvfb"              : " ".join(xvfb),
        "xdummy"            : " ".join(xdummy),
        "chdir"             : "",
        "socket-dir"        : "",
        "sessions-dir"      : get_sessions_dir(),
        "log-dir"           : "auto",
        "log-file"          : "server.log",
        "border"            : "auto,5:off",
        "window-close"      : "auto",
        "min-size"          : "",
        "max-size"          : "",
        "desktop-scaling"   : "on",
        "refresh-rate"      : "auto",
        "display"           : "",
        "download-path"     : get_download_dir(),
        "open-command"      : " ".join(OPEN_COMMAND),
        "remote-logging"    : "both",
        "lpadmin"           : "/usr/sbin/lpadmin",
        "lpinfo"            : "/usr/sbin/lpinfo",
        "add-printer-options" : ["-u allow:$USER", "-E", "-o printer-is-shared=false"],
        "pdf-printer"       : "",
        "postscript-printer": DEFAULT_POSTSCRIPT_PRINTER,
        "debug"             : "",
        "input-method"      : "auto",
        "audio-source"      : "",
        "html"              : "auto",
        "http-scripts"      : "all",
        "socket-permissions": "600",
        "exec-wrapper"      : "",
        "dbus"              : POSIX and not OSX,
        "dbus-launch"       : "dbus-launch --sh-syntax --close-stderr",
        "webcam"            : ["auto", "no"][OSX or WIN32],
        "mousewheel"        : ["on", "invert-x"][OSX],
        "pointer"           : "auto",
        "input-devices"     : "auto",
        "shortcut-modifiers": "auto",
        "open-files"        : "auto",
        "open-url"          : "auto",
        "file-transfer"     : "auto",
        "printing"          : "yes",
        "headerbar"         : ["auto", "no"][OSX or WIN32],
        "challenge-handlers": ["all"],
        # ssl options:
        "ssl"               : "auto",
        "ssl-key"           : "",
        "ssl-key-password"  : "",
        "ssl-cert"          : "",
        "ssl-protocol"      : ssl_protocol,
        "ssl-ca-certs"      : "default",
        "ssl-ca-data"       : "",
        "ssl-ciphers"       : "DEFAULT",
        "ssl-client-verify-mode"   : "optional",
        "ssl-server-verify-mode"   : "required",
        "ssl-verify-flags"  : "X509_STRICT",
        "ssl-check-hostname": True,
        "ssl-server-hostname": "",
        "ssl-options"       : "ALL,NO_COMPRESSION",
        "backend"           : "auto",
        "quality"           : 0,
        "min-quality"       : 1,
        "speed"             : 0,
        "min-speed"         : 1,
        "compression_level" : 1,
        "dpi"               : 0,
        "file-size-limit"   : "1G",
        "idle-timeout"      : 0,
        "server-idle-timeout" : 0,
        "sync-xvfb"         : None,
        "pixel-depth"       : 0,
        "uid"               : getuid(),
        "gid"               : getgid(),
        "min-port"          : 1024,
        "rfb-upgrade"       : 5,
        "rdp-upgrade"       : False,
        "auto-refresh-delay": 0.15,
        "minimal"           : False,
        "daemon"            : CAN_DAEMONIZE,
        "start-via-proxy"   : False,
        "attach"            : None,
        "use-display"       : "auto",
        "resize-display"    : ["no", "auto"][not OSX and not WIN32],
        "reconnect"         : True,
        "tray"              : True,
        "pulseaudio"        : DEFAULT_PULSEAUDIO,
        "mmap"              : "auto",
        "mmap-group"        : "auto",
        "video"             : True,
        "audio"             : True,
        "speaker"           : ["disabled", "on"][has_audio_support() and not is_arm()],
        "microphone"        : ["disabled", "off"][has_audio_support()],
        "video-scaling"     : "auto",
        "readonly"          : False,
        "keyboard-sync"     : True,
        "displayfd"         : 0,
        "pings"             : 5,
        "cursors"           : True,
        "bell"              : True,
        "notifications"     : True,
        "xsettings"         : ["auto", "no"][int(OSX or WIN32)],
        "system-tray"       : True,
        "sharing"           : None,
        "lock"              : None,
        "delay-tray"        : False,
        "windows"           : True,
        "terminate-children": False,
        "exit-with-children": False,
        "exit-with-client"  : False,
        "exit-with-windows" : False,
        "commands"          : True,
        "control"           : True,
        "shell"             : False,
        "http"              : True,
        "start-new-commands": True,
        "proxy-start-sessions": True,
        "av-sync"           : True,
        "exit-ssh"          : True,
        "dbus-control"      : not WIN32 and not OSX,
        "opengl"            : "no" if OSX else "probe",
        "mdns"              : not WIN32,
        "swap-keys"         : OSX,  # only used on osx
        "desktop-fullscreen": False,
        "forward-xdg-open"  : None,
        "modal-windows"     : False,
        "bandwidth-detection" : False,
        "ssl-upgrade"       : True,
        "websocket-upgrade" : True,
        "ssh-upgrade"       : True,
        "splash"            : None,
        "gstreamer"         : True,
        "pulseaudio-configure-commands"  : ["auto"],
        "socket-dirs"       : unexpand_all(get_socket_dirs()),
        "client-socket-dirs" : unexpand_all(get_client_socket_dirs()),
        "remote-xpra"       : get_remote_run_xpra_scripts(),
        "encodings"         : ["all"],
        "video-encoders"    : ["all,no-gstreamer"],
        "csc-modules"       : ["all"],
        "video-decoders"    : ["all,no-gstreamer"],
        "speaker-codec"     : [],
        "microphone-codec"  : [],
        "compressors"       : ["all"],
        "packet-encoders"   : ["all"],
        "key-shortcut"      : get_default_key_shortcuts(),
        "bind"              : ["auto"],
        "bind-vsock"        : [],
        "bind-tcp"          : [],
        "bind-ws"           : [],
        "bind-wss"          : [],
        "bind-ssl"          : [],
        "bind-ssh"          : [],
        "bind-rfb"          : [],
        "bind-rdp"          : [],
        "bind-quic"         : [],
        "auth"              : [],
        "vsock-auth"        : [],
        "tcp-auth"          : [],
        "ws-auth"           : [],
        "wss-auth"          : [],
        "ssl-auth"          : [],
        "ssh-auth"          : [],
        "rfb-auth"          : [],
        "rdp-auth"          : [],
        "quic-auth"         : [],
        "password-file"     : [],
        "source"            : SOURCE,
        "source-start"      : [],
        "start"             : [],
        "start-late"        : [],
        "start-child"       : [],
        "start-child-late"  : [],
        "start-after-connect"       : [],
        "start-child-after-connect" : [],
        "start-on-connect"          : [],
        "start-child-on-connect"    : [],
        "start-on-disconnect"          : [],
        "start-child-on-disconnect"    : [],
        "start-on-last-client-exit" : [],
        "start-child-on-last-client-exit"   : [],
        "start-env"         : list(DEFAULT_ENV),
        "env"               : list(DEFAULT_START_ENV),
    }
    return GLOBAL_DEFAULTS


# fields that got renamed:
CLONES: dict[str, str] = {}

# these options should not be specified in config files:
NO_FILE_OPTIONS = ("daemon", )


def validate_config(d=None, discard=NO_FILE_OPTIONS, extras_types=None, extras_validation=None) -> dict[str,Any]:
    return do_validate_config(d or {}, discard, extras_types or {}, extras_validation or {})


def do_validate_config(d:dict, discard, extras_types:dict, extras_validation:dict) -> dict[str, Any]:
    """
        Validates all the options given in a dict with fields as keys and
        strings or arrays of strings as values.
        Each option is strongly typed and invalid value are discarded.
        We get the required datatype from OPTION_TYPES
    """
    validations = OPTIONS_VALIDATION.copy()
    validations.update(extras_validation)
    option_types = OPTION_TYPES.copy()
    option_types.update(extras_types)
    nd: dict[str, Any] = {}
    for k, v in d.items():
        if k in discard:
            warn(f"Warning: option {k!r} is not allowed in configuration files")
            continue
        vt = option_types.get(k)
        if vt is None:
            if k in OLD_OPTIONS:
                continue
            warn(f"Warning: invalid option: {k!r}")
            continue
        if vt is str:
            if not isinstance(v, str):
                warn(f"invalid value for {k!r}: {type(v)} (string required)")
                continue
        elif vt is int:
            v = parse_bool_or_number(int, k, v)
            if v is None:
                continue
        elif vt is float:
            v = parse_number(float, k, v)
            if v is None:
                continue
        elif vt is bool:
            v = parse_bool_or(k, v)
            if v is None:
                continue
        elif vt is list:
            if isinstance(v, str):
                # could just be that we specified it only once..
                v = [v]
            elif isinstance(v, list) or v is None:
                # ok so far..
                pass
            else:
                warn(f"Warning: invalid value for {k!r}: {type(v)} (a string or list of strings is required)")
                continue
        else:
            warn(f"Error: unknown option type for {k!r}: {vt}")
        validation = validations.get(k)
        if validation and v is not None:
            msg = validation(v)
            if msg:
                warn(f"Warning: invalid value for {k!r}: {v}, {msg}")
                continue
        nd[k] = v
    return nd


class XpraConfig:
    def __repr__(self):
        return f"XpraConfig({self.__dict__})"

    def clone(self) -> Self:
        c = XpraConfig()
        c.__dict__ = dict(self.__dict__)
        return c


def make_defaults_struct(extras_defaults=None, extras_types=None, extras_validation=None,
                         username="", uid=getuid(), gid=getgid()) -> XpraConfig:
    return do_make_defaults_struct(extras_defaults or {}, extras_types or {}, extras_validation or {},
                                   username, uid, gid)


def do_make_defaults_struct(extras_defaults: dict, extras_types: dict, extras_validation: dict,
                            username:str, uid: int, gid: int) -> XpraConfig:
    # populate config with default values:
    if not username and uid:
        username = get_username_for_uid(uid)
    defaults = read_xpra_defaults(username, uid, gid)
    return dict_to_validated_config(defaults, extras_defaults, extras_types, extras_validation)


def dict_to_validated_config(d: dict, extras_defaults=None, extras_types=None, extras_validation=None) -> XpraConfig:
    options = get_defaults().copy()
    if extras_defaults:
        options.update(extras_defaults)
    # parse config:
    validated = validate_config(d, extras_types=extras_types, extras_validation=extras_validation)
    options.update(validated)
    for k,v in CLONES.items():
        if k in options:
            options[v] = options[k]
    return dict_to_config(options)


def dict_to_config(options) -> XpraConfig:
    config = XpraConfig()
    for k,v in options.items():
        setattr(config, name_to_field(k), v)
    return config


def fixup_debug_option(value: str) -> str:
    """ backwards compatible parsing of the debug option, which used to be a boolean """
    if not value:
        return ""
    value = str(value)
    if value.strip().lower() in ("yes", "true", "on", "1"):
        return "all"
    if value.strip().lower() in ("no", "false", "off", "0"):
        return ""
    # if we're here, the value should be a CSV list of categories
    return value


def csvstr(value) -> str:
    if isinstance(value, (list, tuple, set, dict)):
        return ",".join(str(x).strip() for x in value if x)
    if isinstance(value, str):
        return value.strip()
    raise ValueError(f"don't know how to convert {type(value)} to a csv list!")


def csvstrl(value) -> str:
    return csvstr(value).lower()


def nodupes(s) -> list[str]:
    return remove_dupes(x.strip().lower() for x in s.split(","))


def fixup_socketdirs(options) -> None:
    for option_name in ("socket_dirs", "client_socket_dirs"):
        value = getattr(options, option_name)
        if isinstance(value, str):
            value = value.split(os.path.pathsep)
        else:
            assert isinstance(getattr(options, option_name), (list, tuple))
            value = [v for x in value for v in x.split(os.path.pathsep)]
        setattr(options, option_name, value)


def fixup_pings(options) -> None:
    # pings used to be a boolean, True mapped to "5"
    if isinstance(options.pings, int):
        return
    try:
        pings = str(options.pings).lower()
        if pings in TRUE_OPTIONS:
            options.pings = 5
        elif pings in FALSE_OPTIONS:
            options.pings = 0
        else:
            options.pings = int(options.pings)
    except ValueError:
        options.pings = 5


def fixup_encodings(options) -> None:
    from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
    estr = csvstr(options.encodings)
    RENAME = {
        "jpg"   : "jpeg",
        "png/l" : "png/L",
        "pngl"  : "png/L",
        "png/p" : "png/P",
        "pngp"  : "png/P",
    }
    options.encoding = RENAME.get(options.encoding, options.encoding)
    encodings = [RENAME.get(x, x) for x in nodupes(estr)]
    while True:
        try:
            i = encodings.index("all")
        except ValueError:
            break
        else:
            # replace 'all' with the actual value:
            encodings = encodings[:i]+list(PREFERRED_ENCODING_ORDER)+encodings[i+1:]
    # if the list only has items to exclude (ie: '-scroll,-jpeg')
    # then 'all' is implied:

    def isneg(enc: str) -> bool:
        return enc.startswith("-") or enc.startswith("no-")

    def stripneg(enc) -> str:
        if enc.startswith("-"):
            return enc[1:]
        if enc.startswith("no-"):
            return enc[3:]
        return enc

    if not any(True for e in encodings if not isneg(e)):
        encodings = list(PREFERRED_ENCODING_ORDER)+encodings
    if "rgb" in encodings:
        if "rgb24" not in encodings:
            encodings.append("rgb24")
        if "rgb32" not in encodings:
            encodings.append("rgb32")
    encodings = remove_dupes(encodings)
    invalid = [stripneg(e) for e in encodings if stripneg(e) not in PREFERRED_ENCODING_ORDER]
    if invalid:
        raise InitExit(ExitCode.UNSUPPORTED, "invalid encodings specified: " + csv(invalid))
    # remove the negated encodings:
    for rm in tuple(stripneg(e) for e in encodings if isneg(e)):
        while True:
            try:
                encodings.remove(rm)
            except ValueError:
                break
    options.encodings = tuple(encodings)
    if not options.video:
        options.csc_modules = ["none"]
        options.video_encoders = ["none"]
        options.video_decoders = ["none"]
    else:
        from xpra.codecs.video import ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS, ALL_VIDEO_DECODER_OPTIONS
        for name, all_list in (
            ("csc-modules", ALL_CSC_MODULE_OPTIONS),
            ("video-encoders", ALL_VIDEO_ENCODER_OPTIONS),
            ("video-decoders", ALL_VIDEO_DECODER_OPTIONS),
        ):
            # ensure value is always a sequence:
            attr_name = name.replace("-", "_")
            value = getattr(options, attr_name)
            if not isinstance(value, Sequence):
                value = [x for x in csvstrl(value).split(",") if x.strip()]
                setattr(options, attr_name, value)
            if "help" in value:
                raise InitInfo(f"the following {name} are defined: {csv(all_list)}")


def fixup_compression(options) -> None:
    from xpra.net import compression
    cstr = csvstrl(options.compressors)
    if cstr == "all":
        compressors = compression.PERFORMANCE_ORDER
    elif cstr == "none":
        compressors = ()
    else:
        compressors = nodupes(cstr)
        unknown = tuple(x for x in compressors if x and x not in compression.ALL_COMPRESSORS)
        if unknown:
            warn("Warning: invalid compressor(s) specified: " + csv(unknown))
        # keep only valid ones
        # (ignores `lzo` and `zlib` which have been removed but may still exist in config files)
        compressors = [x for x in compressors if x in compression.VALID_COMPRESSORS]
    options.compressors = list(compressors)


def fixup_packetencoding(options) -> None:
    from xpra.net import packet_encoding
    pestr = csvstrl(options.packet_encoders)
    if pestr == "all":
        packet_encoders = packet_encoding.PERFORMANCE_ORDER
    else:
        packet_encoders = nodupes(pestr)
        unknown = [x for x in packet_encoders if x and x not in packet_encoding.ALL_ENCODERS]
        if unknown:
            warn("Warning: invalid packet encoder(s) specified: " + csv(unknown))
        # keep only valid ones
        # (ignores `rencode`, `bencode` and `yaml` which have been removed but may still exist in config files)
        packet_encoders = [x for x in packet_encoders if x in packet_encoding.VALID_ENCODERS]
    options.packet_encoders = packet_encoders


def fixup_keyboard(options) -> None:
    # variants and layouts can be specified as CSV, convert them to lists:
    def p(v) -> list[str]:
        try:
            if isinstance(v, Sequence):
                seq = v
            else:
                seq = str(v).split(",")
            r = remove_dupes(x.strip() for x in seq)
            # remove empty string if that's the only value:
            if r and len(r) == 1 and r[0] == "":
                r = []
            return r
        except Exception:
            return []

    options.keyboard_backend = "" if options.keyboard_backend == "auto" else options.keyboard_backend
    options.keyboard_layouts = p(options.keyboard_layouts)
    options.keyboard_variants = p(options.keyboard_variants)
    options.keyboard_raw = str_to_bool(options.keyboard_raw)


def fixup_clipboard(options) -> None:
    cd = options.clipboard_direction.lower().replace("-", "")
    if cd == "toserver":
        options.clipboard_direction = "to-server"
    elif cd == "toclient":
        options.clipboard_direction = "to-client"
    elif cd == "both":
        options.clipboard_direction = "both"
    elif cd in ("disabled", "none"):
        options.clipboard_direction = "disabled"
    else:
        warn(f"Warning: invalid value for clipboard-direction: {options.clipboard_direction!r}")
        warn(" specify 'to-server', 'to-client' or 'both'")
        options.clipboard_direction = "disabled"


def abs_paths(options) -> None:
    ew = options.exec_wrapper
    if ew:
        ewp = shlex.split(ew)
        if ewp and not os.path.isabs(ewp[0]):
            abscmd = which(ewp[0])
            if abscmd:
                ewp[0] = abscmd
                options.exec_wrapper = shlex.join(ewp)
    # convert to absolute paths before we daemonize
    for k in ("clipboard-filter-file",
              "tcp-encryption-keyfile", "encryption-keyfile",
              "log-dir",
              "download-path", "exec-wrapper",
              "ssl-key", "ssl-cert", "ssl-ca-certs"):
        f = k.replace("-", "_")
        v = getattr(options, f)
        if v and (k != "ssl-ca-certs" or v != "default"):
            if os.path.isabs(v) or v == "auto":
                continue
            if v.startswith("~") or v.startswith("$"):
                continue
            setattr(options, f, os.path.abspath(v))


def fixup_options(options) -> None:
    fixup_encodings(options)
    fixup_pings(options)
    fixup_compression(options)
    fixup_packetencoding(options)
    fixup_socketdirs(options)
    fixup_clipboard(options)
    fixup_keyboard(options)
    abs_paths(options)
    # remote-xpra is meant to be a list, but the user can specify a string using the command line,
    # in which case we replace all the default values with this single entry:
    if not isinstance(options.remote_xpra, (list, tuple)):
        options.remote_xpra = [options.remote_xpra]


def main(argv=()):
    from xpra.util.str_fn import nonl

    def print_options(o):
        for k, ot in sorted(OPTION_TYPES.items()):
            v = getattr(o, name_to_field(k), "")
            if ot is bool and v is None:
                v = "Auto"
            if isinstance(v, list):
                v = csv(str(x) for x in v)
            print("* %-32s : %s" % (k, nonl(v)))
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Config-Info", "Config Info"):
        enable_color()
        if consume_verbose_argv(argv, "all"):
            global debug

            def print_debug(*args):
                print(args[0] % args[1:])
            debug = print_debug

        if len(argv) > 1:
            for filename in argv[1:]:
                print("")
                print(f"Configuration file {filename!r}")
                if not os.path.exists(filename):
                    print(" Error: file not found")
                    continue
                d = read_config(filename)
                config = dict_to_validated_config(d)
                print_options(config)
        else:
            print("Default Configuration:")
            print_options(make_defaults_struct())


if __name__ == "__main__":
    main(sys.argv)
