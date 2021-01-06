# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import site

from xpra.util import envbool

SOUND_PYTHON3 = envbool("XPRA_SOUND_PYTHON3", False)

#removed in 2.3:
# we no longer use "~/.xpra" on posix systems to store files or sockets,
# but we still load config files from there if present
LEGACY_DOTXPRA = envbool("XPRA_LEGACY_DOTXPRA", False)


def do_get_desktop_background_paths():
    return [
        "/usr/share/backgrounds/images/default.png",
        "/usr/share/backgrounds/images/*default*.png",
        "/usr/share/backgrounds/*default*png",
        "/usr/share/backgrounds/gnome/adwaita*.jpg",    #Debian Stretch
        "/usr/share/backgrounds/images/*jpg",           #CentOS 7
        ]


def do_get_install_prefix():
    #special case for "user" installations, ie:
    #$HOME/.local/lib/python2.7/site-packages/xpra/platform/paths.py
    try:
        base = site.getuserbase()
    except Exception:
        base = site.USER_BASE
    if __file__.startswith(base):
        return base
    if sys.argv:
        p = sys.argv[0].find("/bin/xpra")
        if p>0:
            return sys.argv[0][:p]
    return sys.prefix

def do_get_resources_dir():
    #is there a better/cleaner way?
    from xpra.platform.paths import get_install_prefix
    options = [get_install_prefix(), sys.exec_prefix] + \
               os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
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

def do_get_app_dir():
    from xpra.platform.paths import get_resources_dir
    return get_resources_dir()

def do_get_icon_dir():
    from xpra.platform.paths import get_app_dir
    return os.path.join(get_app_dir(), "icons")

def do_get_libexec_dir():
    from xpra.os_util import is_Fedora, is_CentOS, is_RedHat
    if is_Fedora() or is_CentOS() or is_RedHat():
        return "/usr/libexec/"
    return "/usr/lib"

def do_get_mmap_dir():
    return _get_xpra_runtime_dir() or os.getenv("TMPDIR", "/tmp")

def do_get_xpra_tmp_dir():
    xrd = _get_xpra_runtime_dir()
    return os.path.join(xrd, "tmp")


def do_get_script_bin_dirs():
    #versions before 0.17 only had "~/.xpra/run-xpra"
    script_bin_dirs = []
    runtime_dir = _get_xpra_runtime_dir()
    if runtime_dir:
        script_bin_dirs.append(runtime_dir)
    if LEGACY_DOTXPRA:
        if os.geteuid()>0:
            script_bin_dirs.append("~/.xpra")
    return script_bin_dirs


def do_get_system_conf_dirs():
    dirs = ["/etc/xpra", "/usr/local/etc/xpra"]
    for d in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":"):
        dirs.append(os.path.join(d, "xpra"))
    #hope the prefix is something like "/usr/local" or "$HOME/.local":
    from xpra.platform.paths import get_install_prefix
    prefix = get_install_prefix()
    if prefix not in ("/usr", "/usr/local"):
        if prefix.endswith(".local"):
            idir= os.path.join(prefix, "xpra")          #ie: ~/.local/xpra
        else:
            idir= os.path.join(prefix, "/etc/xpra/")    #ie: /someinstallpath/etc/xpra
        if idir not in dirs:
            dirs.append(idir)
    return dirs


def do_get_user_conf_dirs(uid):
    #per-user configuration location:
    #(but never use /root/.xpra or /root/.config/xpra)
    if uid is None:
        uid = os.getuid()
    dirs = []
    if uid>0:
        dirs += [os.path.join(os.environ.get("XDG_CONFIG_HOME", "~/.config"), "xpra")]
        dirs.append("~/.xpra")
    return dirs


def get_runtime_dir():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        #replace uid with the string "$UID"
        head, tail = list(os.path.split(runtime_dir))
        try:
            assert int(tail)>=0
            runtime_dir = os.path.join(head, "$UID")
        except (ValueError, AssertionError):
            pass
    elif os.path.exists("/run") and os.path.isdir("/run"):
        runtime_dir = "/run/user/$UID"
    elif os.path.exists("/var/run") and os.path.isdir("/var/run"):
        runtime_dir = "/var/run/user/$UID"
    return runtime_dir

def _get_xpra_runtime_dir():
    runtime_dir = get_runtime_dir()
    if not runtime_dir:
        return None
    return os.path.join(runtime_dir, "xpra")

def do_get_socket_dirs():
    SOCKET_DIRS = []
    runtime_dir = _get_xpra_runtime_dir()
    if runtime_dir:
        #private, per user: /run/user/1000/xpra
        SOCKET_DIRS.append(runtime_dir)
    if LEGACY_DOTXPRA:
        #Debian pretends to be root during build.. check FAKEROOTKEY
        #to ensure we still include "~/.xpra" in the default config
        if os.geteuid()>0 or os.environ.get("FAKEROOTKEY"):
            SOCKET_DIRS.append("~/.xpra")   #the old default path
    #for shared sockets (the 'xpra' group should own this directory):
    if os.path.exists("/run"):
        SOCKET_DIRS.append("/run/xpra")
    elif os.path.exists("/var/run"):
        SOCKET_DIRS.append("/var/run/xpra")
    #Debian and Ubuntu often don't create a reliable XDG_RUNTIME_DIR
    #other distros may not create one when using "su"
    SOCKET_DIRS.append("~/.xpra")
    return SOCKET_DIRS

def do_get_default_log_dirs():
    log_dirs = []
    v = _get_xpra_runtime_dir()
    if v:
        log_dirs.append(v)
    if LEGACY_DOTXPRA and os.geteuid()>0:
        log_dirs.append("~/.xpra")
    log_dirs.append("/tmp")
    return log_dirs

def do_get_sound_command():
    from xpra.platform.paths import get_xpra_command
    if SOUND_PYTHON3:
        return ["python3"]+get_xpra_command()
    return get_xpra_command()

def do_get_xpra_command():
    #try to use the same "xpra" executable that launched this server,
    #whilst also preserving the python interpreter version:
    if sys.argv and sys.argv[0].lower().endswith("/xpra"):
        return ["python%i.%i" % (sys.version_info.major, sys.version_info.minor), sys.argv[0]]
    return ["xpra"]
