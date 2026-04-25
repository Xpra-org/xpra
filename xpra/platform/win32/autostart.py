# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger

log = Logger("win32", "util")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Xpra"


def _get_hive():
    from winreg import HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER  # pylint: disable=import-outside-toplevel
    from xpra.os_util import is_admin  # pylint: disable=import-outside-toplevel
    return HKEY_LOCAL_MACHINE if is_admin() else HKEY_CURRENT_USER


def _get_xpra_command() -> str:
    """
    Return the quoted path to Xpra-Shadow.exe if it exists in the app
    directory, otherwise fall back to Xpra.exe.
    """
    from xpra.platform.paths import get_app_dir  # pylint: disable=import-outside-toplevel
    exe_dir = get_app_dir()
    for exe_name in ("Xpra-Shadow.exe", "Xpra.exe"):
        exe_path = os.path.join(exe_dir, exe_name)
        if os.path.isfile(exe_path):
            return exe_path
    return "Xpra.exe"


def set_autostart(enabled: bool) -> None:
    from winreg import (  # pylint: disable=import-outside-toplevel
        OpenKey, CreateKey, DeleteValue, SetValueEx,
        KEY_SET_VALUE, REG_SZ,
    )
    hive = _get_hive()
    if enabled:
        cmd = _get_xpra_command()
        log("set_autostart(%s) command=%r", enabled, cmd)
        with CreateKey(hive, RUN_KEY) as key:
            SetValueEx(key, VALUE_NAME, 0, REG_SZ, cmd)
    else:
        log("set_autostart(%s) removing registry value", enabled)
        try:
            with OpenKey(hive, RUN_KEY, 0, KEY_SET_VALUE) as key:
                DeleteValue(key, VALUE_NAME)
        except OSError:
            # key or value does not exist — already disabled
            pass


def get_status() -> str:
    from winreg import (  # pylint: disable=import-outside-toplevel
        OpenKey, QueryValueEx, KEY_READ,
    )
    try:
        with OpenKey(_get_hive(), RUN_KEY, 0, KEY_READ) as key:
            QueryValueEx(key, VALUE_NAME)
        return "enabled"
    except OSError:
        return "disabled"
