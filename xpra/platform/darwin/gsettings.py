# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger

log = Logger("osx", "gsettings")


def _uses_dark_theme() -> bool:
    try:
        from Foundation import NSUserDefaults
        defaults = NSUserDefaults.standardUserDefaults()
        return defaults.stringForKey_("AppleInterfaceStyle") == "Dark"
    except (AttributeError, ImportError):
        log("failed to query AppleInterfaceStyle", exc_info=True)
        return False


def _uses_high_contrast() -> bool | None:
    try:
        from AppKit import NSWorkspace
        workspace = NSWorkspace.sharedWorkspace()
        return bool(workspace.accessibilityDisplayShouldIncreaseContrast())
    except (AttributeError, ImportError):
        log("failed to query high contrast mode", exc_info=True)
        return None


def get_auto_gsettings() -> dict[tuple[str, str], str]:
    values = {
        ("org.gnome.desktop.wm.preferences", "button-layout"): "'close,minimize,maximize:'",
        ("org.gnome.desktop.interface", "color-scheme"):
            "'prefer-dark'" if _uses_dark_theme() else "'default'",
    }
    high_contrast = _uses_high_contrast()
    if high_contrast is not None:
        values[("org.gnome.desktop.a11y.interface", "high-contrast")] = str(high_contrast).lower()
    return values
