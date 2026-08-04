# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import Structure, byref, sizeof
from ctypes.wintypes import BOOL, DWORD, LPVOID, LPWSTR, UINT

from xpra.log import Logger
from xpra.platform.win32 import constants as win32con

log = Logger("win32", "gsettings")


class HIGHCONTRAST(Structure):
    _fields_ = (
        ("cbSize", UINT),
        ("dwFlags", DWORD),
        ("lpszDefaultScheme", LPWSTR),
    )


def _uses_dark_theme() -> bool:
    try:
        from winreg import HKEY_CURRENT_USER, OpenKey, QueryValueEx
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with OpenKey(HKEY_CURRENT_USER, sub_key) as key:
            return QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        log("failed to query AppsUseLightTheme", exc_info=True)
        return False


def _uses_high_contrast() -> bool | None:
    try:
        from ctypes import WinDLL  # @UnresolvedImport
        high_contrast = HIGHCONTRAST()
        high_contrast.cbSize = sizeof(high_contrast)
        user32 = WinDLL("user32", use_last_error=True)
        system_parameters_info = user32.SystemParametersInfoW
        system_parameters_info.argtypes = (UINT, UINT, LPVOID, UINT)
        system_parameters_info.restype = BOOL
        if not system_parameters_info(
                win32con.SPI_GETHIGHCONTRAST, sizeof(high_contrast), byref(high_contrast), 0):
            return None
        return bool(high_contrast.dwFlags & win32con.HCF_HIGHCONTRASTON)
    except (AttributeError, OSError):
        log("failed to query high contrast mode", exc_info=True)
        return None


def get_auto_gsettings() -> dict[tuple[str, str], str]:
    values = {
        ("org.gnome.desktop.wm.preferences", "button-layout"): "':minimize,maximize,close'",
        ("org.gnome.desktop.interface", "color-scheme"):
            "'prefer-dark'" if _uses_dark_theme() else "'default'",
    }
    high_contrast = _uses_high_contrast()
    if high_contrast is not None:
        values[("org.gnome.desktop.a11y.interface", "high-contrast")] = str(high_contrast).lower()
    return values
