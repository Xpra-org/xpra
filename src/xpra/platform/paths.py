#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import inspect
import os.path
import sys

from xpra.platform import platform_import



def valid_dir(path):
    try:
        return bool(path) and os.path.exists(path) and os.path.isdir(path)
    except TypeError:
        return False


#helpers to easily override using env vars:
def envaslist_or_delegate(env_name, impl, *args):
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return [env_value]
    return impl(*args)
def env_or_delegate(env_name, impl, *args):
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return env_value
    return impl(*args)


def get_install_prefix():
    return env_or_delegate("XPRA_INSTALL_PREFIX", do_get_install_prefix)
def do_get_install_prefix():
    return sys.prefix


def get_system_conf_dirs():
    return envaslist_or_delegate("XPRA_SYSTEM_CONF_DIRS", do_get_system_conf_dirs)
def do_get_system_conf_dirs():
    #overriden in all platforms
    return []


def get_ssh_conf_dirs():
    return envaslist_or_delegate("XPRA_SSH_CONF_DIRS", do_get_ssh_conf_dirs)
def do_get_ssh_conf_dirs():
    return ["/etc/ssh", "/usr/local/etc/ssh", "~/.ssh", "~/ssh"]

def get_ssh_known_hosts_files():
    return envaslist_or_delegate("XPRA_SSH_KNOWN_HOSTS", do_get_ssh_known_hosts_files)
def do_get_ssh_known_hosts_files():
    return ("~/.ssh/known_hosts", "~/ssh/known_hosts")


def get_user_conf_dirs(uid=None):
    return envaslist_or_delegate("XPRA_USER_CONF_DIRS", do_get_user_conf_dirs, uid)
def do_get_user_conf_dirs(_uid):
    return []

def get_default_conf_dirs():
    return envaslist_or_delegate("XPRA_DEFAULT_CONF_DIRS", do_get_default_conf_dirs)
def do_get_default_conf_dirs():
    #some platforms may also ship a default config with the application
    return []


def get_socket_dirs():
    return envaslist_or_delegate("XPRA_SOCKET_DIRS", do_get_socket_dirs)
def do_get_socket_dirs():
    return ["~/.xpra"]

def get_default_log_dirs():
    return envaslist_or_delegate("XPRA_LOG_DIRS", do_get_default_log_dirs)
def do_get_default_log_dirs():
    return ["~/.xpra"]

def get_download_dir():
    return env_or_delegate("XPRA_DOWNLOAD_DIR", do_get_download_dir)
def do_get_download_dir():
    d = "~/Downloads"
    if not os.path.exists(os.path.expanduser(d)):
        return "~"
    return d


def get_libexec_dir():
    return env_or_delegate("XPRA_LIBEXEC_DIR", do_get_libexec_dir)
def do_get_libexec_dir():
    return get_app_dir()


def get_mmap_dir():
    return env_or_delegate("XPRA_MMAP_DIR", do_get_mmap_dir)
def do_get_mmap_dir():
    import tempfile
    return tempfile.gettempdir()


def get_xpra_tmp_dir():
    return env_or_delegate("XPRA_TMP_DIR", do_get_xpra_tmp_dir)
def do_get_xpra_tmp_dir():
    import tempfile
    return tempfile.gettempdir()


def get_script_bin_dirs():
    return envaslist_or_delegate("XPRA_SCRIPT_BIN_DIRS", do_get_script_bin_dirs)
def do_get_script_bin_dirs():
    return ["~/.xpra"]

def get_remote_run_xpra_scripts():
    return envaslist_or_delegate("XPRA_REMOTE_RUN_XPRA_SCRIPTS", do_get_remote_run_xpra_scripts)
def do_get_remote_run_xpra_scripts():
    return ["$XDG_RUNTIME_DIR/xpra/run-xpra", "xpra", "/usr/local/bin/xpra", "~/.xpra/run-xpra"]


def get_sshpass_command():
    return env_or_delegate("XPRA_SSHPASS", do_get_sshpass_command)
def do_get_sshpass_command():
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)
    SSHPASS = "sshpass"
    from xpra.platform.features import EXECUTABLE_EXTENSION
    if EXECUTABLE_EXTENSION:
        SSHPASS = "sshpass.%s" % EXECUTABLE_EXTENSION
    paths = os.environ["PATH"].split(os.pathsep)
    for path in paths:
        path = path.strip('"')
        exe_file = os.path.join(path, SSHPASS)
        if is_exe(exe_file):
            return exe_file
    return None


#overriden in platform code:
def get_app_dir():
    return env_or_delegate("XPRA_APP_DIR", do_get_app_dir)
def do_get_app_dir():
    return default_get_app_dir()

def default_get_app_dir():
    if os.name=="posix":
        for prefix in (
            os.environ.get("RPM_BUILD_ROOT"),
            get_install_prefix(),
            sys.exec_prefix,
            "/usr",
            "/usr/local",
            ):
            if not prefix:
                continue
            adir = os.path.join(prefix, "share", "xpra")
            if valid_dir(adir):
                return adir
    adir = os.path.dirname(inspect.getfile(sys._getframe(1)))
    def root_module(d):
        for psep in (os.path.sep, "/", "\\"):
            pos = d.find("xpra%splatform" % psep)
            if pos>=0:
                return d[:pos]
        return d
    if valid_dir(adir):
        return root_module(adir)
    adir = os.path.dirname(sys.argv[0])
    if valid_dir(adir):
        return root_module(adir)
    adir = os.getcwd()
    return adir       #tried our best, hope this works!

#may be overriden in platform code:
def get_resources_dir():
    return env_or_delegate("XPRA_RESOURCES_DIR", do_get_resources_dir)
def do_get_resources_dir():
    return get_app_dir()

#may be overriden in platform code:
def get_icon_dir():
    return env_or_delegate("XPRA_ICON_DIR", do_get_icon_dir)
def do_get_icon_dir():
    adir = get_app_dir()
    idir = os.path.join(adir, "icons")
    if valid_dir(idir):
        return idir
    for prefix in (sys.exec_prefix, "/usr", "/usr/local"):
        idir = os.path.join(prefix, "icons")
        if os.path.exists(idir):
            return idir
    return adir     #better than nothing :(

def get_icon(name):
    filename = get_icon_filename(name)
    if not filename:
        return    None
    from xpra.gtk_common.gtk_util import get_icon_from_file
    return get_icon_from_file(filename)

def get_icon_filename(basename=None, ext="png"):
    if not basename:
        return None
    filename = basename
    fext = os.path.splitext(filename)[1]
    if not fext:
        filename = "%s.%s" % (basename, ext)
    if not os.path.isabs(filename):
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, filename)
    if not os.path.exists(filename):
        return None
    return os.path.abspath(filename)


def get_desktop_background_paths():
    return envaslist_or_delegate("XPRA_DESKTOP_BACKGROUND_PATHS", do_get_desktop_background_paths)
def do_get_desktop_background_paths():
    return []


def get_xpra_command():
    envvalue = os.environ.get("XPRA_COMMAND")
    if envvalue:
        import shlex
        return shlex.split(envvalue)
    return do_get_xpra_command()
def do_get_xpra_command():
    return default_do_get_xpra_command()
def default_do_get_xpra_command():
    #try to use the same "xpra" executable that launched this server:
    if sys.argv and sys.argv[0].lower().endswith("/xpra"):
        return [sys.argv[0]]
    return ["xpra"]


def get_nodock_command():
    envvalue = os.environ.get("XPRA_NODOCK_COMMAND")
    if envvalue:
        import shlex
        return shlex.split(envvalue)
    return do_get_nodock_command()
def do_get_nodock_command():
    return get_xpra_command()


def get_sound_command():
    envvalue = os.environ.get("XPRA_SOUND_COMMAND")
    if envvalue:
        import shlex
        return shlex.split(envvalue)
    return do_get_sound_command()
def do_get_sound_command():
    return get_xpra_command()


platform_import(globals(), "paths", True,
                "do_get_resources_dir",
                "do_get_app_dir",
                "do_get_icon_dir")
platform_import(globals(), "paths", False,
                "do_get_sshpass_command",
                "do_get_xpra_command",
                "do_get_sound_command",
                "do_get_nodock_command",
                "do_get_install_prefix",
                "do_get_default_conf_dirs",
                "do_get_system_conf_dirs",
                "do_get_ssh_conf_dirs",
                "do_get_ssh_known_hosts_files",
                "do_get_user_conf_dirs",
                "do_get_socket_dirs",
                "do_get_default_log_dirs",
                "do_get_download_dir",
                "do_get_libexec_dir",
                "do_get_mmap_dir",
                "do_get_xpra_tmp_dir",
                "do_get_script_bin_dirs",
                "do_get_desktop_background_paths",
                )

def get_info():
    try:
        import xpra
        XPRA_MODULE_PATH = xpra.__file__
        pos = XPRA_MODULE_PATH.find("__init__.py")
        if pos>0:
            XPRA_MODULE_PATH = XPRA_MODULE_PATH[:pos]
    except AttributeError:
        XPRA_MODULE_PATH = ""
    return {
        "install"           : {"prefix" : get_install_prefix()},
        "default_conf"      : {"dirs"   : get_default_conf_dirs()},
        "system_conf"       : {"dirs"   : get_system_conf_dirs()},
        "ssh_conf"          : {"dirs"   : get_ssh_conf_dirs()},
        "user_conf"         : {"dirs"   : get_user_conf_dirs()},
        "socket"            : {"dirs"   : get_socket_dirs()},
        "log"               : {"dirs"   : get_default_log_dirs()},
        "download"          : {"dir"    : get_download_dir()},
        "libexec"           : {"dir"    : get_libexec_dir()},
        "mmap"              : {"dir"    : get_mmap_dir()},
        "xpra-tmp"          : {"dir"    : get_xpra_tmp_dir()},
        "xpra-module"       : XPRA_MODULE_PATH,
        "app"               : {"default" : {"dir"   : default_get_app_dir()}},
        "desktop-background": get_desktop_background_paths(),
        "ssh-known-hosts"   : get_ssh_known_hosts_files(),
        "resources"         : get_resources_dir(),
        "icons"             : get_icon_dir(),
        "home"              : os.path.expanduser("~"),
        "xpra_command"      : get_xpra_command(),
        "nodock_command"    : get_nodock_command(),
        "sound_command"     : get_sound_command(),
        "sshpass_command"   : get_sshpass_command(),
        }


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category
        add_debug_category("util")

    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    with program_context("Path-Info", "Path Info"):
        print_nested_dict(get_info())


if __name__ == "__main__":
    main()
