# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.log import Logger
from xpra.util.env import envbool
from xpra.util.str_fn import csv
from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitExit


GSTREAMER_CAPTURE_ELEMENTS: Sequence[str] = ("ximagesrc", "pipewiresrc")

XSHM: bool = envbool("XPRA_SHADOW_XSHM", True)
NVFBC: bool = envbool("XPRA_SHADOW_NVFBC", True)
PIPEWIRE: bool = envbool("XPRA_SHADOW_PIPEWIRE", True)


def warn(*messages) -> None:
    log = Logger("server", "shadow")
    log("warning loading backend", exc_info=True)
    for m in messages:
        log.warn(m)


def debug_error(message: str) -> None:
    log = Logger("server", "shadow")
    log(message, exc_info=True)


def load_screencast(display: str = "") -> type | None:
    try:
        from xpra.platform.posix import screencast
        return screencast.ScreenCast
    except ImportError as e:
        debug_error(f"load_screencast({display})")
        warn("Warning: unable to load the screencast backend", f" {e}")
    return None


def load_remotedesktop(display: str = "") -> type | None:
    try:
        from xpra.platform.posix import remotedesktop
        return remotedesktop.RemoteDesktop
    except ImportError as e:
        debug_error(f"load_remotedesktop({display})")
        warn("Warning: unable to load the remotedesktop backend", f" {e}")
    return None


def load_pipewire(_display: str = "") -> type | None:
    return load_remotedesktop() or load_screencast()


def load_wayland(display: str = "") -> type | None:
    c = load_remotedesktop() or load_screencast()
    if c:
        os.environ["GDK_BACKEND"] = "wayland"
        if display:
            os.environ["WAYLAND_DISPLAY"] = display
        if os.environ.get("XPRA_NOX11") is None:
            os.environ["XPRA_NOX11"] = "1"
    return c


def load_x11(display: str = "") -> type | None:
    gdkb = os.environ.get("GDK_BACKEND", "")
    try:
        os.environ["GDK_BACKEND"] = "x11"
        from xpra.x11.shadow.server import ShadowX11Server
        return ShadowX11Server
    except ImportError as e:
        debug_error(f"load_x11({display})")
        if gdkb:
            os.environ["GDK_BACKEND"] = gdkb
        warn("Warning: unable to load x11 shadow server", f" {e}")
    return None


def load_gstreamer(display: str = "") -> type | None:
    os.environ["XPRA_STREAM_MODE"] = "gstreamer"
    os.environ["XPRA_SHADOW_GSTREAMER"] = "1"
    return load_x11()


# the ShadowX11Server supports multiple sub-backends:
load_nvfbc = load_x11
load_xshm = load_x11
load_gtk = load_x11


def load_auto(display: str = "") -> type | None:
    c: type | None = None
    if display.startswith("wayland-") or os.path.isabs(display):
        c = load_wayland(display)
    elif display.startswith(":"):
        c = load_x11(display)
    return c or load_remotedesktop(display) or load_screencast(display) or load_x11(display)


def ShadowServer(display: str, attrs: dict[str, str]):
    log = Logger("server", "shadow")
    setting = (attrs.get("backend", os.environ.get("XPRA_SHADOW_BACKEND", "auto"))).lower()
    log(f"ShadowServer({display}, {attrs}) {setting=}")
    if setting not in SHADOW_OPTIONS:
        raise InitExit(ExitCode.UNSUPPORTED, f"invalid shadow backend {setting!r}, use: {csv(SHADOW_OPTIONS.keys())}")
    load_fn = globals().get(f"load_{setting}")
    if not load_fn:
        raise RuntimeError(f"missing shadow loader for {setting!r}")
    shadow_server = load_fn(display)
    if not shadow_server:
        raise RuntimeError(f"shadow backend {setting} is not available")
    log(f"ShadowServer({display}, {attrs}) {setting}={shadow_server}")
    return shadow_server(attrs)


def check_nvfbc() -> bool:
    return NVFBC


def check_gstreamer() -> bool:
    GSTREAMER: bool = envbool("XPRA_SHADOW_GSTREAMER", True)
    if not GSTREAMER:
        return False
    from xpra.gstreamer.common import has_plugins, import_gst
    import_gst()
    return has_plugins("ximagesrc")


def check_pipewire() -> bool:
    if not PIPEWIRE:
        return False
    from xpra.gstreamer.common import has_plugins, import_gst
    import_gst()
    return has_plugins("pipewiresrc")


def check_x11() -> bool:
    from xpra.x11.bindings.ximage import XImageBindings  # pylint: disable=import-outside-toplevel
    assert XImageBindings
    return True


def check_xshm() -> bool:
    from xpra.x11.bindings.shm import XShmBindings
    assert XShmBindings
    return XShmBindings().has_XShm()


def nocheck() -> bool:
    return True


SHADOW_OPTIONS = {
    "auto": nocheck,
    "nvfbc": check_nvfbc,
    "gstreamer": check_gstreamer,
    "pipewire": check_pipewire,
    "x11": check_x11,
    "xshm": check_xshm,
    "gtk": check_x11,
}
