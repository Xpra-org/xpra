#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import signal
from typing import Any
from subprocess import Popen, PIPE

from xpra.os_util import POSIX, LINUX, OSX, WIN32
from xpra.util.env import _saved_env, envbool
from xpra.util.io import load_binary_file, get_util_logger


SIGNAMES: dict[int, str] = {}
for signame in (sig for sig in dir(signal) if sig.startswith("SIG") and not sig.startswith("SIG_")):
    try:
        SIGNAMES[int(getattr(signal, signame))] = signame
    except ValueError:
        pass


def set_proc_title(title: str) -> None:
    try:
        import setproctitle  # pylint: disable=import-outside-toplevel
        setproctitle.setproctitle(title)  # @UndefinedVariable pylint: disable=c-extension-no-member
    except ImportError as e:
        get_util_logger().debug("setproctitle is not installed: %s", e)


def no_idle(fn, *args, **kwargs) -> None:
    fn(*args, **kwargs)


def register_SIGUSR_signals(idle_add=no_idle) -> None:
    if os.name != "posix":
        return
    from xpra.util.pysystem import dump_gc_frames
    from xpra.util.pysystem import dump_all_frames

    def sigusr1(*_args) -> None:
        log = get_util_logger().info
        log("SIGUSR1")
        idle_add(dump_all_frames, log)

    def sigusr2(*_args) -> None:
        log = get_util_logger().info
        log("SIGUSR2")
        idle_add(dump_gc_frames, log)

    signal.signal(signal.SIGUSR1, sigusr1)
    signal.signal(signal.SIGUSR2, sigusr2)


def is_VirtualBox() -> bool:
    if os.name != "nt":
        # detection not supported yet
        return False
    # try to detect VirtualBox:
    # based on the code found here:
    # http://spth.virii.lu/eof2/articles/WarGame/vboxdetect.html
    try:
        from ctypes import cdll
        if cdll.LoadLibrary("VBoxHook.dll"):
            # "VirtualBox is present (VBoxHook.dll)
            return True
    except (ImportError, OSError):
        pass
    try:
        with open("\\\\.\\VBoxMiniRdrDN", "r"):
            # "VirtualBox is present (VBoxMiniRdrDN)"
            return True
    except Exception as e:
        import errno
        if e.args[0] == errno.EACCES:
            # "VirtualBox is present (VBoxMiniRdrDN)"
            return True
    return False


def is_Wayland() -> bool:
    return _is_Wayland(_saved_env)


def _is_Wayland(env: dict) -> bool:
    backend = env.get("GDK_BACKEND", "")
    if backend == "wayland":
        return True
    return backend != "x11" and (
        bool(env.get("WAYLAND_DISPLAY")) or env.get("XDG_SESSION_TYPE") == "wayland"
    )


def is_distribution_variant(variant="Debian") -> bool:
    if not POSIX:
        return False
    try:
        v = load_os_release_file()
        return any(line.find(variant) >= 0 for line in v.splitlines() if line.startswith("NAME="))
    except Exception:
        pass
    try:
        d = get_linux_distribution()[0]
        if d == variant:
            return True
        if variant == "RedHat" and d.startswith(variant):
            return True
    except Exception:
        pass
    return False


def get_distribution_version_id() -> str:
    if not POSIX:
        return ""
    try:
        v = load_os_release_file()
        for bline in v.splitlines():
            line = bline.decode()
            if line.startswith("VERSION_ID="):
                return line.split("=", 1)[1].strip('"')
    except Exception:
        pass
    return ""


os_release_file_data: str | None = None


def load_os_release_file() -> str:
    global os_release_file_data
    if os_release_file_data is None:
        try:
            os_release_file_data = load_binary_file("/etc/os-release").decode() or ""
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            os_release_file_data = ""
    return os_release_file_data


def is_Ubuntu() -> bool:
    return is_distribution_variant("Ubuntu")


def is_LinuxMint() -> bool:
    return is_distribution_variant("Linux Mint")


def is_Debian() -> bool:
    return is_distribution_variant("Debian")


def is_DEB() -> bool:
    return is_Debian() or is_Ubuntu() or is_LinuxMint()


def is_RPM() -> bool:
    return any(is_distribution_variant(x) for x in (
        "Fedora", "RedHat", "AlmaLinux", "Rocky Linux", "CentOS", "openSUSE", "Oracle Linux",
    ))


_linux_distribution = ("", "", "")


def get_linux_distribution() -> tuple[str, str, str]:
    global _linux_distribution
    if LINUX and _linux_distribution == ("", "", ""):
        # linux_distribution is deprecated in Python 3.5,
        # and it causes warnings,
        # so we use our own code first:
        cmd = ["lsb_release", "-a"]
        try:
            p = Popen(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
            out = p.communicate()[0]
            assert p.returncode == 0 and out
        except Exception:
            try:
                import platform
                _linux_distribution = platform.linux_distribution()  # pylint: disable=deprecated-method, no-member
            except Exception:
                _linux_distribution = ("unknown", "unknown", "unknown")
        else:
            d = {}
            for line in out.splitlines():
                parts = line.rstrip("\n\r").split(":", 1)
                if len(parts) == 2:
                    d[parts[0].lower().replace(" ", "_")] = parts[1].strip()
            _linux_distribution = (
                d.get("distributor_id", "unknown"),
                d.get("release", "unknown"),
                d.get("codename", "unknown"),
            )
    return _linux_distribution


def is_unity() -> bool:
    d = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return d.find("unity") >= 0 or d.find("ubuntu") >= 0


def is_gnome() -> bool:
    if os.environ.get("XDG_SESSION_DESKTOP", "").split("-", 1)[0] in ("i3", "ubuntu",):
        # "i3-gnome" is not really gnome... ie: the systray does work!
        return False
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("gnome") >= 0


def is_kde() -> bool:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("kde") >= 0


def get_loaded_kernel_modules(*modlist):
    loaded = []
    if LINUX and os.path.exists("/sys/module"):
        for mod in modlist:
            if os.path.exists(f"/sys/module/{mod}"):  # pragma: no cover
                loaded.append(mod)
    return loaded


def is_WSL() -> bool:
    if not POSIX:
        return False
    for f in ("/proc/sys/kernel/osrelease", "/proc/version"):
        r = load_binary_file(f)
        if r:
            return r.find(b"Microsoft") >= 0
    return False


def get_generic_os_name() -> str:
    return do_get_generic_os_name().lower()


def do_get_generic_os_name() -> str:
    for k, v in {
        "linux": "Linux",
        "darwin": "MacOS",
        "win": "MS Windows",
        "freebsd": "FreeBSD",
    }.items():
        if sys.platform.startswith(k):
            return v
    return sys.platform  # pragma: no cover


def is_X11() -> bool:
    if OSX or WIN32:
        return False
    if envbool("XPRA_NOX11", False):
        return False
    try:
        from xpra import x11
        assert x11
    except ImportError:
        # x11 is not installed, so assume it isn't used
        return False
    try:
        from xpra.x11.gtk.bindings import is_X11_Display
        return is_X11_Display()
    except ImportError:
        get_util_logger().debug("failed to load x11 bindings", exc_info=True)
        return True


def nn(x) -> str:
    if x is None:
        return ""
    return str(x)


def get_env_info() -> dict[str, str]:
    filtered_env = os.environ.copy()
    if filtered_env.get('XPRA_PASSWORD'):
        filtered_env['XPRA_PASSWORD'] = "*****"
    if filtered_env.get('XPRA_ENCRYPTION_KEY'):
        filtered_env['XPRA_ENCRYPTION_KEY'] = "*****"
    return filtered_env


def get_sysconfig_info() -> dict[str, Any]:
    import sysconfig
    sysinfo: dict[str, Any] = {}
    log = get_util_logger()
    for attr in (
            "platform",
            "python-version",
            "config-vars",
            "paths",
    ):
        fn = "get_" + attr.replace("-", "_")
        getter = getattr(sysconfig, fn, None)
        if getter:
            try:
                sysinfo[attr] = getter()  # pylint: disable=not-callable
            except ModuleNotFoundError:
                log("sysconfig.%s", fn, exc_info=True)
                if attr == "config-vars" and WIN32:
                    continue
                log.warn("Warning: failed to collect %s sysconfig information", attr)
            except Exception:
                log.error("Error calling sysconfig.%s", fn, exc_info=True)
    return sysinfo


def platform_release(release):
    log = get_util_logger()
    if WIN32:
        try:
            import wmi
        except ImportError:
            log(f"platform_release({release}) no wmi", exc_info=True)
            if release.endswith("Server"):
                return release.replace("Server", "-Server")  # ie: "2025Server" -> "2025-Server"
        else:
            try:
                computer = wmi.WMI()
                os_info = computer.Win32_OperatingSystem()[0]
                return os_info.Name.split('|')[0]
            except Exception as e:
                log.debug("wmi query", exc_info=True)
                log.warn("Warning: failed to query OS using wmi")
                log.warn(f" {e}")
    if OSX:
        systemversion_plist = "/System/Library/CoreServices/SystemVersion.plist"
        try:
            import plistlib
            with open(systemversion_plist, "rb") as f:
                pl = plistlib.load(f)
            return pl['ProductUserVisibleVersion']
        except Exception as e:
            log.debug("platform_release(%s)", release, exc_info=True)
            log.warn("Warning: failed to get release information")
            log.warn(f" from {systemversion_plist}:")
            log.warn(f" {e}")
    return release


def platform_name(sys_platform=sys.platform, release="") -> str:
    if not sys_platform:
        return "unknown"
    platforms = {
        "win32": "Microsoft Windows",
        "cygwin": "Windows/Cygwin",
        "linux.*": "Linux",
        "darwin": "Mac OS X",
        "freebsd.*": "FreeBSD",
        "os2": "OS/2",
    }

    def rel(v):
        if isinstance(release, (tuple, list)):
            values = [v] + list(release)
        else:
            values = []
            if not release.startswith(v):
                values.append(v)
            values.append(release)
        return " ".join(str(x) for x in values if x and x not in ("", "unknown", "n/a"))

    for k, v in platforms.items():
        regexp = re.compile(k)
        if regexp.match(sys_platform):
            return rel(v)
    return rel(sys_platform)


def is_systemd_pid1() -> bool:
    if not POSIX:
        return False
    d = load_binary_file("/proc/1/cmdline")
    return d.find(b"/systemd") >= 0


def get_processor_name() -> str:
    import platform
    sysname = platform.system()
    if sysname == "Windows":
        return platform.processor()
    if sysname == "Darwin":
        from xpra.util.env import OSEnvContext
        from subprocess import check_output
        with OSEnvContext():
            os.environ['PATH'] = os.environ['PATH'] + os.pathsep + '/usr/sbin'
            command = ["sysctl", "-n", "machdep.cpu.brand_string"]
            return check_output(command, text=True).strip()
    if sysname == "Linux":
        with open("/proc/cpuinfo", encoding="latin1") as f:
            data = f.read()
        import re
        for line in data.split("\n"):
            if "model name" in line:
                return re.sub(".*model name.*:", "", line, count=1).strip()
    return platform.processor()
