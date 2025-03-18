#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import shlex
import inspect
import os.path
import tempfile
from collections.abc import Callable

from xpra.platform import platform_import


def valid_dir(path) -> bool:
    try:
        return bool(path) and os.path.exists(path) and os.path.isdir(path)
    except TypeError:
        return False


# helpers to easily override using env vars:
def envaslist_or_delegate(env_name: str, impl: Callable, *args):
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return [env_value]
    return impl(*args)


def env_or_delegate(env_name: str, impl: Callable, *args):
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return env_value
    return impl(*args)


def get_install_prefix() -> str:
    return env_or_delegate("XPRA_INSTALL_PREFIX", do_get_install_prefix)


def do_get_install_prefix() -> str:
    return sys.prefix


def get_system_conf_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SYSTEM_CONF_DIRS", do_get_system_conf_dirs)


def do_get_system_conf_dirs() -> list[str]:
    # overridden in all platforms
    return []


def get_system_menu_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SYSTEM_MENU_DIRS", do_get_system_menu_dirs)


def do_get_system_menu_dirs() -> list[str]:
    return []


def get_ssl_cert_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SSL_CERT_PATHS", do_get_ssl_cert_dirs)


def do_get_ssl_cert_dirs() -> list[str]:
    dirs = ["/etc/xpra/ssl", "/usr/local/etc/xpra/ssl", "/etc/xpra/", "/usr/local/etc/xpra"]
    if os.name != "posix" or os.getuid() != 0:
        dirs = ["~/.config/xpra/ssl", "~/.xpra/ssl"] + dirs + ["./"]
    return dirs


def get_ssl_hosts_config_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SSL_HOSTS_CONFIG_DIRS", do_get_ssl_hosts_config_dirs)


def do_get_ssl_hosts_config_dirs() -> list[str]:
    dirs = []
    for d in get_ssl_cert_dirs():
        if d.rstrip("/\\").endswith("ssl"):
            dirs.append(os.path.join(d, "hosts"))
    return dirs


def get_ssh_conf_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SSH_CONF_DIRS", do_get_ssh_conf_dirs)


def do_get_ssh_conf_dirs() -> list[str]:
    return ["/etc/ssh", "/usr/local/etc/ssh", "~/.ssh", "~/ssh"]


def get_ssh_known_hosts_files() -> list[str]:
    return envaslist_or_delegate("XPRA_SSH_KNOWN_HOSTS", do_get_ssh_known_hosts_files)


def do_get_ssh_known_hosts_files() -> list[str]:
    return ["~/.ssh/known_hosts", "~/ssh/known_hosts"]


def get_user_conf_dirs(uid=None) -> list[str]:
    return envaslist_or_delegate("XPRA_USER_CONF_DIRS", do_get_user_conf_dirs, uid)


def do_get_user_conf_dirs(_uid) -> list[str]:
    return []


def get_default_conf_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_DEFAULT_CONF_DIRS", do_get_default_conf_dirs)


def do_get_default_conf_dirs() -> list[str]:
    # some platforms may also ship a default config with the application
    return []


def get_state_dir() -> str:
    return env_or_delegate("XPRA_STATE_DIR", do_get_state_dir)


def do_get_state_dir() -> str:
    d = "~/.local/state"
    if not os.path.exists(os.path.expanduser(d)):
        return "~"
    return d


def get_sessions_dir() -> str:
    return env_or_delegate("XPRA_SESSIONS_DIR", do_get_sessions_dir)


def do_get_sessions_dir() -> str:
    return "$XDG_RUNTIME_DIR/xpra"


def get_socket_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SOCKET_DIRS", do_get_socket_dirs)


def do_get_socket_dirs() -> list[str]:
    return ["~/.xpra"]


def get_client_socket_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_CLIENT_SOCKET_DIRS", do_get_client_socket_dirs)


def do_get_client_socket_dirs() -> list[str]:
    return []


def get_default_log_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_LOG_DIRS", do_get_default_log_dirs)


def do_get_default_log_dirs() -> list[str]:
    return ["~/.xpra"]


def get_download_dir() -> str:
    return env_or_delegate("XPRA_DOWNLOAD_DIR", do_get_download_dir)


def do_get_download_dir() -> str:
    d = "~/Downloads"
    if not os.path.exists(os.path.expanduser(d)):
        return "~"
    return d


def get_mmap_dir() -> str:
    return env_or_delegate("XPRA_MMAP_DIR", do_get_mmap_dir)


def do_get_mmap_dir() -> str:
    return tempfile.gettempdir()


def get_xpra_tmp_dir() -> str:
    return env_or_delegate("XPRA_TMP_DIR", do_get_xpra_tmp_dir)


def do_get_xpra_tmp_dir() -> str:
    return tempfile.gettempdir()


def get_script_bin_dirs() -> list[str]:
    return envaslist_or_delegate("XPRA_SCRIPT_BIN_DIRS", do_get_script_bin_dirs)


def do_get_script_bin_dirs() -> list[str]:
    return ["~/.xpra"]


def get_remote_run_xpra_scripts() -> list[str]:
    return envaslist_or_delegate("XPRA_REMOTE_RUN_XPRA_SCRIPTS", do_get_remote_run_xpra_scripts)


def do_get_remote_run_xpra_scripts() -> list[str]:
    return ["xpra", "$XDG_RUNTIME_DIR/xpra/run-xpra", "/usr/local/bin/xpra", "~/.xpra/run-xpra", "Xpra_cmd.exe"]


def get_sshpass_command() -> str:
    return env_or_delegate("XPRA_SSHPASS", do_get_sshpass_command)


def do_get_sshpass_command() -> str:
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    SSHPASS = "sshpass"
    from xpra.platform.features import EXECUTABLE_EXTENSION  # pylint: disable=import-outside-toplevel
    if EXECUTABLE_EXTENSION:
        SSHPASS = f"sshpass.{EXECUTABLE_EXTENSION}"
    paths = os.environ["PATH"].split(os.pathsep)
    for path in paths:
        path = path.strip('"')
        exe_file = os.path.join(path, SSHPASS)
        if is_exe(exe_file):
            return exe_file
    return ""


# overridden in platform code:
def get_app_dir() -> str:
    return env_or_delegate("XPRA_APP_DIR", do_get_app_dir)


def do_get_app_dir() -> str:
    return default_get_app_dir()


def default_get_app_dir() -> str:
    if os.name == "posix":
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
    adir = os.path.dirname(inspect.getfile(sys._getframe(1)))  # pylint: disable=protected-access

    def root_module(d):
        for psep in (os.path.sep, "/", "\\"):
            pos = d.find(f"xpra{psep}platform")
            if pos >= 0:
                return d[:pos]
        return d

    if valid_dir(adir):
        return root_module(adir)
    adir = os.path.dirname(sys.argv[0])
    if valid_dir(adir):
        return root_module(adir)
    adir = os.getcwd()
    return adir  # tried our best, hope this works!


# may be overridden in platform code:
def get_resources_dir() -> str:
    return env_or_delegate("XPRA_RESOURCES_DIR", do_get_resources_dir)


def do_get_resources_dir() -> str:
    return get_app_dir()


# may be overridden in platform code:

def get_image(name: str):
    filename = os.path.join(get_image_dir(), name)
    from xpra.gtk.pixbuf import get_icon_from_file
    return get_icon_from_file(filename)


def get_image_dir() -> str:
    return env_or_delegate("XPRA_IMAGE_DIR", do_get_image_dir)


def do_get_image_dir() -> str:
    raise NotImplementedError()


def get_icon_dir() -> str:
    return env_or_delegate("XPRA_ICON_DIR", do_get_icon_dir)


def do_get_icon_dir() -> str:
    raise NotImplementedError()


def get_icon(name: str):
    filename = get_icon_filename(name)
    if not filename:
        return None
    from xpra.gtk.pixbuf import get_icon_from_file
    return get_icon_from_file(filename)


def get_icon_filename(basename: str = "", ext="png") -> str:
    if not basename:
        return ""
    filename = basename
    fext = os.path.splitext(filename)[1]
    if not fext:
        filename = f"{basename}.{ext}"
    if not os.path.isabs(filename):
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, filename)
    if not os.path.exists(filename):
        return ""
    return os.path.abspath(filename)


def get_desktop_background_paths() -> list[str]:
    return envaslist_or_delegate("XPRA_DESKTOP_BACKGROUND_PATHS", do_get_desktop_background_paths)


def do_get_desktop_background_paths() -> list[str]:
    return []


def get_xpra_command() -> list[str]:
    envvalue = os.environ.get("XPRA_COMMAND")
    if envvalue:
        return shlex.split(envvalue)
    return do_get_xpra_command()


def do_get_xpra_command() -> list[str]:
    return default_do_get_xpra_command()


def default_do_get_xpra_command() -> list[str]:
    # try to use the same "xpra" executable that launched this server:
    if sys.argv and sys.argv[0].lower().endswith("/xpra"):
        return [sys.argv[0]]
    return ["xpra"]


def get_nodock_command() -> list[str]:
    envvalue = os.environ.get("XPRA_NODOCK_COMMAND")
    if envvalue:
        return shlex.split(envvalue)
    return do_get_nodock_command()


def do_get_nodock_command() -> list[str]:
    return get_xpra_command()


def get_audio_command() -> list[str]:
    envvalue = os.environ.get("XPRA_AUDIO_COMMAND")
    if envvalue:
        return shlex.split(envvalue)
    return do_get_audio_command()


def do_get_audio_command() -> list[str]:
    return get_xpra_command()


def get_python_exec_command() -> list[str]:
    envvalue = os.environ.get("XPRA_PYTHON_EXEC_COMMAND") or os.environ.get("XPRA_PYTHON_COMMAND")
    if envvalue:
        return shlex.split(envvalue)
    return do_get_python_exec_command()


def do_get_python_exec_command() -> list[str]:
    vi = sys.version_info
    return [f"python{vi.major}.{vi.minor}", "-c"]


def get_python_execfile_command() -> list[str]:
    envvalue = os.environ.get("XPRA_PYTHON_EXECFILE_COMMAND") or os.environ.get("XPRA_PYTHON_COMMAND")
    if envvalue:
        return shlex.split(envvalue)
    return do_get_python_execfile_command()


def do_get_python_execfile_command() -> list[str]:
    vi = sys.version_info
    return [f"python{vi.major}.{vi.minor}"]


platform_import(globals(), "paths", True,
                "do_get_resources_dir",
                "do_get_app_dir",
                "do_get_icon_dir",
                "do_get_image_dir",
                )
platform_import(globals(), "paths", False,
                "do_get_sshpass_command",
                "do_get_xpra_command",
                "do_get_audio_command",
                "do_get_nodock_command",
                "do_get_install_prefix",
                "do_get_default_conf_dirs",
                "do_get_system_conf_dirs",
                "do_get_system_menu_dirs",
                "do_get_ssl_cert_dirs",
                "do_get_ssl_hosts_config_dirs",
                "do_get_ssh_conf_dirs",
                "do_get_ssh_known_hosts_files",
                "do_get_user_conf_dirs",
                "do_get_state_dir",
                "do_get_sessions_dir",
                "do_get_socket_dirs",
                "do_get_client_socket_dirs",
                "do_get_default_log_dirs",
                "do_get_download_dir",
                "do_get_mmap_dir",
                "do_get_xpra_tmp_dir",
                "do_get_script_bin_dirs",
                "do_get_desktop_background_paths",
                "do_get_python_exec_command",
                "do_get_python_execfile_command",
                )


def get_info():
    try:
        import xpra  # pylint: disable=import-outside-toplevel
        XPRA_MODULE_PATH = xpra.__file__
        pos = XPRA_MODULE_PATH.find("__init__.py")
        if pos > 0:
            XPRA_MODULE_PATH = XPRA_MODULE_PATH[:pos]
    except AttributeError:
        XPRA_MODULE_PATH = ""
    return {
        "install": {"prefix": get_install_prefix()},
        "default_conf": {"dirs": get_default_conf_dirs()},
        "system_conf": {"dirs": get_system_conf_dirs()},
        "system-menu": {"dirs" : get_system_menu_dirs()},
        "ssl-cert": {"dirs": get_ssl_cert_dirs()},
        "ssl-hosts-config": {"dirs": get_ssl_hosts_config_dirs()},
        "ssh_conf": {"dirs": get_ssh_conf_dirs()},
        "user_conf": {"dirs": get_user_conf_dirs()},
        "state": {"dir": get_state_dir()},
        "sessions": {"dir": get_sessions_dir()},
        "socket": {"dirs": get_socket_dirs()},
        "client-socket": {"dirs": get_client_socket_dirs()},
        "log": {"dirs": get_default_log_dirs()},
        "download": {"dir": get_download_dir()},
        "mmap": {"dir": get_mmap_dir()},
        "xpra-tmp": {"dir": get_xpra_tmp_dir()},
        "script": {"dir": get_script_bin_dirs()},
        "xpra-module": XPRA_MODULE_PATH,
        "app": {"default": {"dir": default_get_app_dir()}},
        "desktop-background": get_desktop_background_paths(),
        "ssh-known-hosts": get_ssh_known_hosts_files(),
        "resources": get_resources_dir(),
        "icons": get_icon_dir(),
        "images": get_image_dir(),
        "home": os.path.expanduser("~"),
        "xpra_command": get_xpra_command(),
        "nodock_command": get_nodock_command(),
        "audio_command": get_audio_command(),
        "sshpass_command": get_sshpass_command(),
        "python-exec": get_python_exec_command(),
        "python-execfile": get_python_execfile_command(),
    }


def main():
    from xpra.log import consume_verbose_argv
    from xpra.util.str_fn import print_nested_dict
    from xpra.platform import program_context
    with program_context("Path-Info", "Path Info"):
        consume_verbose_argv(sys.argv, "util")
        print_nested_dict(get_info())


if __name__ == "__main__":
    main()
