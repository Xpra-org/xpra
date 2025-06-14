# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=import-outside-toplevel

import os.path
import sys
import site
import tempfile

from collections.abc import Sequence

from xpra.common import BACKWARDS_COMPATIBLE


def do_get_desktop_background_paths() -> Sequence[str]:
    return [
        "/usr/share/backgrounds/images/default.png",
        "/usr/share/backgrounds/images/*default*.png",
        "/usr/share/backgrounds/*default*png",
        "/usr/share/backgrounds/gnome/adwaita*.jpg",  # Debian Stretch
        "/usr/share/backgrounds/images/*jpg",  # CentOS 7
        "/usr/share/backgrounds/images/default.jxl",  # Fedora 42
        "/usr/share/backgrounds/images/*default*.jxl",
        "/usr/share/backgrounds/images/*.jxl",
    ]


def do_get_install_prefix() -> str:
    # special case for "user" installations, ie:
    # $HOME/.local/lib/python3.8/site-packages/xpra/platform/paths.py
    try:
        base = site.getuserbase()
    except Exception:
        base = site.USER_BASE or ""
    if __file__.startswith(base):
        return base
    if sys.argv:
        p = sys.argv[0].find("/bin/xpra")
        if p > 0:
            return sys.argv[0][:p]
    return sys.prefix


def do_get_resources_dir() -> str:
    # is there a better/cleaner way?
    from xpra.common import DEFAULT_XDG_DATA_DIRS
    from xpra.platform.paths import get_install_prefix
    options = [
        get_install_prefix(),
        sys.exec_prefix,
    ] + os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS).split(":")
    for x in options:
        p = os.path.join(x, "share", "xpra")
        if os.path.exists(p) and os.path.isdir(p):
            return p
    try:
        # test for a local installation path (run from source tree):
        local_share_path = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), "..", "share", "xpra"))
        if os.path.exists(local_share_path) and os.path.isdir(local_share_path):
            return local_share_path
    except Exception:
        pass
    return os.getcwd()


def do_get_app_dir() -> str:
    from xpra.platform.paths import get_resources_dir
    return get_resources_dir()


def do_get_image_dir() -> str:
    from xpra.platform.paths import get_app_dir
    return os.path.join(get_app_dir(), "images")


def do_get_icon_dir() -> str:
    from xpra.platform.paths import get_app_dir
    return os.path.join(get_app_dir(), "icons")


def do_get_mmap_dir() -> str:
    return _get_xpra_runtime_dir() or tempfile.gettempdir()


def do_get_xpra_tmp_dir() -> str:
    xrd = os.environ.get("XPRA_SESSION_DIR", _get_xpra_runtime_dir())
    return os.path.join(xrd, "tmp")


def do_get_script_bin_dirs() -> list[str]:
    script_bin_dirs = []
    runtime_dir = _get_xpra_runtime_dir()
    if runtime_dir:
        script_bin_dirs.append(runtime_dir)
    return script_bin_dirs


def do_get_system_conf_dirs() -> list[str]:
    dirs = ["/etc/xpra", "/usr/local/etc/xpra"]
    for d in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":"):
        dirs.append(os.path.join(d, "xpra"))
    # hope the prefix is something like "/usr/local" or "$HOME/.local":
    from xpra.platform.paths import get_install_prefix
    prefix = get_install_prefix()
    if prefix not in ("/usr", "/usr/local"):
        if prefix.endswith(".local"):
            idir = os.path.join(prefix, "xpra")  # ie: ~/.local/xpra
        else:
            idir = os.path.join(prefix, "/etc/xpra/")  # ie: /someinstallpath/etc/xpra
        if idir not in dirs:
            dirs.append(idir)
    return dirs


def do_get_system_menu_dirs() -> list[str]:
    from xpra.common import DEFAULT_XDG_DATA_DIRS
    data_dirs = os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS).split(":")
    menu_dirs = []
    for data_dir in data_dirs:
        menu_dir = os.path.join(os.path.expanduser(data_dir), "applications")
        if os.path.exists(menu_dir) and os.path.isdir(menu_dir):
            menu_dirs.append(menu_dir)
    return menu_dirs


def do_get_state_dir() -> str:
    if os.getuid() > 0:
        xdg_state = os.path.expanduser(os.environ.get("XDG_STATE_HOME", "~/.local/state"))
        state_dir = os.path.expanduser(xdg_state)
        if state_dir and os.path.exists(state_dir):
            xpra_state = os.path.join(state_dir, "xpra")
            if not os.path.exists(xpra_state):
                os.mkdir(xpra_state)
            return os.path.join(xdg_state, "xpra")
    return "~/.xpra/state"


def do_get_user_conf_dirs(uid) -> list[str]:
    # per-user configuration location:
    # (but never use /root/.xpra or /root/.config/xpra)
    if uid is None:
        uid = os.getuid()
    dirs = []
    if uid > 0:
        dirs += [os.path.join(os.environ.get("XDG_CONFIG_HOME", "~/.config"), "xpra")]
        dirs.append("~/.xpra")
    return dirs


def get_runtime_dir() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime_dir:
        return runtime_dir
    if sys.platform.startswith("linux"):
        for d in ("/run/user", "/var/run/user"):
            if os.path.exists(d) and os.path.isdir(d):
                runtime_dir = d + "/$UID"
                break
        if not runtime_dir:
            return "$XDG_RUNTIME_DIR"
    return runtime_dir


def _get_xpra_runtime_dir() -> str:
    runtime_dir = get_runtime_dir()
    if not runtime_dir:
        return ""
    return os.path.join(runtime_dir, "xpra")


def do_get_socket_dirs() -> list[str]:
    SOCKET_DIRS = []
    if BACKWARDS_COMPATIBLE:
        runtime_dir = _get_xpra_runtime_dir()
        if runtime_dir:
            # private, per user: XDG_RUNTIME_DIR/xpra
            # (ie: "/run/user/1000/xpra")
            SOCKET_DIRS.append(runtime_dir)
    # for shared sockets (the 'xpra' group should own this directory):
    if os.path.exists("/run"):
        SOCKET_DIRS.append("/run/xpra")
    elif os.path.exists("/var/run"):
        SOCKET_DIRS.append("/var/run/xpra")
    if BACKWARDS_COMPATIBLE:
        # Debian and Ubuntu often don't create a reliable XDG_RUNTIME_DIR
        # other distros may not create one when using "su"
        SOCKET_DIRS.append("~/.xpra")
    return SOCKET_DIRS


def do_get_client_socket_dirs() -> list[str]:
    DIRS = []
    runtime_dir = _get_xpra_runtime_dir()
    if runtime_dir:
        DIRS.append(os.path.join(runtime_dir, "clients"))
    return DIRS


def do_get_default_log_dirs() -> list[str]:
    log_dirs = []
    v = _get_xpra_runtime_dir()
    if v:
        log_dirs.append(v)
    log_dirs.append(tempfile.gettempdir())
    return log_dirs


def do_get_audio_command() -> list[str]:
    from xpra.platform.paths import get_xpra_command
    return get_xpra_command()


def do_get_xpra_command() -> list[str]:
    # try to use the same "xpra" executable that launched this server,
    # whilst also preserving the python interpreter version:
    if sys.argv and sys.argv[0].lower().endswith("/xpra"):
        if sys.executable and sys.executable.find("python") >= 0:
            return [sys.executable, sys.argv[0]]
        return ["python%i.%i" % (sys.version_info.major, sys.version_info.minor), sys.argv[0]]
    return ["xpra"]
