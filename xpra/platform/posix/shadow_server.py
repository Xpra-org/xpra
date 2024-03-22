# This file is part of Xpra.
# Copyright (C) 2013-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
from xpra.util.env import envbool


GSTREAMER_CAPTURE_ELEMENTS: tuple[str, ...] = ("ximagesrc", "pipewiresrc")

XSHM: bool = envbool("XPRA_SHADOW_XSHM", True)
NVFBC: bool = envbool("XPRA_SHADOW_NVFBC", True)
GSTREAMER: bool = envbool("XPRA_SHADOW_GSTREAMER", True)
PIPEWIRE: bool = envbool("XPRA_SHADOW_PIPEWIRE", True)


def warn(*messages) -> None:
    log = Logger("server", "shadow")
    log("warning loading backend", exc_info=True)
    for m in messages:
        log.warn(m)


def load_screencast(display: str = "") -> type | None:
    try:
        from xpra.platform.posix import screencast
        return screencast.ScreenCast
    except ImportError as e:
        warn("Warning: unable to load the screencast backend", f" {e}")
    return None


def load_remotedesktop(display: str = "") -> type | None:
    try:
        from xpra.platform.posix import remotedesktop
        return remotedesktop.RemoteDesktop
    except ImportError as e:
        warn("Warning: unable to load the remotedesktop backend", f" {e}")
    return None


def load_pipewire(display: str = "") -> type | None:
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


def load_xshm(display: str = "") -> type | None:
    gdkb = os.environ.get("GDK_BACKEND")
    try:
        os.environ["GDK_BACKEND"] = "x11"
        from xpra.x11.server import shadow
        return shadow.ShadowX11Server
    except ImportError as e:
        if gdkb:
            os.environ["GDK_BACKEND"] = gdkb
        warn("Warning: unable to load x11 shadow server", f" {e}")
    return None


def load_auto(display: str = "") -> type | None:
    c: type | None = None
    if display.startswith("wayland-") or os.path.isabs(display):
        c = load_wayland(display)
    elif display.startswith(":"):
        c = load_xshm(display)
    return c or load_remotedesktop(display) or load_screencast(display) or load_xshm(display)


def ShadowServer(display: str = "", multi_window: bool = True):
    env_setting = os.environ.get("XPRA_SHADOW_BACKEND", "auto").lower()
    if env_setting not in SHADOW_OPTIONS:
        raise ValueError(f"invalid 'XPRA_SHADOW_BACKEND' {env_setting!r}, use: {SHADOW_OPTIONS}")
    load_fn = globals().get(f"load_{env_setting}")
    shadow_server = load_fn()
    if not shadow_server:
        raise RuntimeError(f"shadow backend {env_setting} is not available")
    log = Logger("server", "shadow")
    log(f"ShadowServer({display}, {multi_window}) {env_setting}={shadow_server}")
    return shadow_server(multi_window)


def check_nvfbc() -> bool:
    return NVFBC


def check_gstreamer() -> bool:
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


def check_xshm() -> bool:
    from xpra.x11.bindings.ximage import XImageBindings  # pylint: disable=import-outside-toplevel
    assert XImageBindings
    return True


def nocheck() -> bool:
    return True


SHADOW_OPTIONS = {
    "auto": nocheck,
    "nvfbc": check_nvfbc,
    "gstreamer": check_gstreamer,
    "pipewire": check_pipewire,
    "xshm": check_xshm,
    "gtk": nocheck,
}
