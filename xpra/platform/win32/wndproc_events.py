#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32 import constants

# `WNDPROC_EVENT_NAMES` maps a window-message code to a readable name.
# It is used only for logging the messages received by xpra's own windows.
#
# The bulk is derived from the generated `constants.py` (a dump of pywin32's
# `win32con`, see packaging/MSWindows/gen_win32con.py) so it stays in sync
# automatically: we reverse-map every standard window message `WM_*` in the
# 0..0x03ff range. Control-class messages (TB_*, TBM_*, RB_*, TTM_*, PSM_*, ...
# which reuse the WM_USER+ range) are deliberately left out: xpra's ordinary
# top-level windows never receive them, so labelling e.g. WM_USER+1 as
# "TB_ENABLEBUTTON" would be misleading rather than helpful.

# range-marker aliases / legacy spellings which must not shadow the real message
# when several names share the same value (e.g. WM_KEYFIRST == WM_KEYDOWN):
_ALIASES = frozenset({
    "WM_KEYFIRST", "WM_KEYLAST", "WM_MOUSEFIRST", "WM_MOUSELAST",
    "WM_IME_KEYLAST", "WM_IMEKEYDOWN", "WM_IMEKEYUP",
})

# standard window messages missing from the (often outdated) pywin32 `win32con`
# dump, plus the WM_USER / WM_APP range markers (which the <0x400 filter drops).
# Keep this list small and curated:
_EXTRA: dict[int, str] = {
    0x0019: "WM_CTLCOLOR",
    0x0049: "WM_COPYGLOBALDATA",
    0x00ab: "WM_NCXBUTTONDOWN",
    0x00ac: "WM_NCXBUTTONUP",
    0x00ad: "WM_NCXBUTTONDBLCLK",
    0x00ae: "WM_NCUAHDRAWCAPTION",
    0x00af: "WM_NCUAHDRAWFRAME",
    0x00ff: "WM_INPUT",
    0x0109: "WM_WNT_CONVERTREQUESTEX",
    0x010a: "WM_CONVERTREQUEST",
    0x010b: "WM_CONVERTRESULT",
    0x010c: "WM_INTERIM",
    0x0118: "WM_SYSTIMER",
    0x0127: "WM_CHANGEUISTATE",
    0x0128: "WM_UPDATEUISTATE",
    0x0129: "WM_QUERYUISTATE",
    0x020b: "WM_XBUTTONDOWN",
    0x020c: "WM_XBUTTONUP",
    0x020d: "WM_XBUTTONDBLCLK",
    0x0280: "WM_IME_REPORT",
    0x02a0: "WM_NCMOUSEHOVER",
    0x02a2: "WM_NCMOUSELEAVE",
    0x02b1: "WM_WTSSESSION_CHANGE",
    0x0319: "WM_APPCOMMAND",
    0x031e: "WM_DWMCOMPOSITIONCHANGED",
    0x0381: "WM_RCRESULT",
    0x0382: "WM_HOOKRCRESULT",
    0x0383: "WM_PENMISCINFO",
    0x0384: "WM_SKB",
    0x0385: "WM_PENCTL",
    0x0386: "WM_PENMISC",
    0x0387: "WM_CTLINIT",
    0x0388: "WM_PENEVENT",
    0x0400: "WM_USER",
    0x8000: "WM_APP",
}


def _build_event_names() -> dict[int, str]:
    names: dict[int, str] = {}
    # reverse-map the standard window messages (0..0x03ff) from the generated
    # win32 constants, so new messages are picked up when constants.py changes:
    for attr in dir(constants):
        if not attr.startswith("WM_"):
            continue
        value = getattr(constants, attr)
        if not isinstance(value, int) or not 0 <= value < 0x0400:
            continue
        current = names.get(value)
        if current is None or (current in _ALIASES and attr not in _ALIASES):
            names[value] = attr
    names.update(_EXTRA)
    return names


WNDPROC_EVENT_NAMES: dict[int, str] = _build_event_names()
