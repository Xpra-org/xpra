# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Native (Gtk-free) OpenGL backend for the win32 client.

Rendering uses the WGL context from `xpra.platform.win32.gl_context` bound
directly to the client window's own `HWND` - there is no toolkit widget and no
Gtk drawing area involved.
"""

from typing import Any

from xpra.util.parsing import FALSE_OPTIONS
from xpra.util.env import numpy_import_context
from xpra.log import Logger

log = Logger("opengl", "win32")


def get_gl_client_window_module(enable_opengl: str = "on") -> tuple[dict[str, Any], Any]:
    """
    Resolve the win32 OpenGL window backend.

    Mirrors `xpra.opengl.window.get_gl_client_window_module` but only offers the
    single native WGL backend (no `glarea`/Gtk variant), so it never imports Gtk.
    Returns `(properties, window_module)` or `(properties, None)` on failure.
    """
    parts = enable_opengl.lower().split(":")
    if parts[0] in FALSE_OPTIONS:
        return {}, None
    with numpy_import_context("OpenGL", True):
        from importlib import import_module
        try:
            import_module("OpenGL")
        except ImportError as e:
            log("cannot import the OpenGL module", exc_info=True)
            log.warn("Warning: cannot import the 'OpenGL' module")
            log.warn(" %s", e)
            return {"success": False, "message": str(e)}, None
    force_enable = parts[0] == "force"
    nocheck = parts[0] == "nocheck"
    # delay the import until we know `OpenGL` is available:
    from xpra.client.win32.opengl import window as window_module
    if nocheck:
        return {"nocheck": True}, window_module
    props = window_module.check_support(force_enable)
    log("check_support(%s)=%s", force_enable, props)
    if props:
        props.setdefault("module", "native")
        props.setdefault("backend", "wgl")
        return props, window_module
    return {"success": False, "message": "no valid OpenGL backend found"}, None
