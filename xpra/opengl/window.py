#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from io import BytesIO
from math import cos, sin
from typing import Any
from collections.abc import Callable, Sequence

from xpra.util.parsing import FALSE_OPTIONS
from xpra.util.objects import AtomicInteger, typedict
from xpra.util.env import envint, numpy_import_context
from xpra.os_util import WIN32, POSIX, gi_import
from xpra.util.io import load_binary_file
from xpra.log import Logger
from xpra.platform.paths import get_icon_filename
from xpra.client.gui.fake_client import FakeClient

log = Logger("opengl", "paint")


def get_opengl_module_names(opengl="on") -> Sequence[str]:
    log(f"get_opengl_module_names({opengl})")
    # ie: "auto", "no", "probe-success", "yes:gtk", "gtk", "yes:native", "native"
    parts = opengl.lower().split(":")
    if parts[0].lower() in FALSE_OPTIONS:
        return ()
    arg = parts[-1]
    if arg in ("gtk", "glarea"):
        return ("glarea",)
    if arg == "native" or (arg == "x11" and POSIX):
        return ("native",)
    # auto-detect:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "glarea", "native"
    return "native", "glarea",


def get_gl_client_window_module(opengl="on") -> tuple[dict[str, Any], Any]:
    with numpy_import_context("OpenGL", True):
        from importlib import import_module
        try:
            opengl_module = import_module("OpenGL")
            log(f"{opengl_module=}")
        except ImportError as e:
            log("cannot import the OpenGL module", exc_info=True)
            log.warn("Warning: cannot import the 'OpenGL' module")
            log.warn(" %s", e)
            return {
                "success": False,
                "message": str(e),
            }, None
    module_names = get_opengl_module_names(opengl)
    log(f"get_gl_client_window_module({opengl}) module names={module_names}")
    parts = opengl.lower().split(":")
    force_enable = parts[0] == "force"
    for module_name in module_names:
        props, window_module = test_window_module(module_name, force_enable)
        if window_module:
            return props, window_module
    return {}, None


def test_window_module(module_name="glarea", force_enable=False) -> tuple[dict, Any]:
    from importlib import import_module
    try:
        mod = import_module(f"xpra.client.gtk3.opengl.{module_name}_window")
        log(f"gl client window module {module_name!r}={mod}")
    except (AttributeError, ImportError) as e:
        log(f"cannot import opengl window module {module_name}", exc_info=True)
        log.warn(f"Warning: cannot import OpenGL window module {module_name}")
        log.warn(" %s", e)
        return {
            "success": False,
            "message": str(e),
        }, None
    opengl_props = mod.check_support(force_enable)
    log(f"{mod}.check_support({force_enable})={opengl_props}")
    if opengl_props:
        opengl_props["module"] = module_name
        return opengl_props, mod
    return {
        "success": False,
        "message": "no valid OpenGL backend found",
    }, None


def get_test_gl_icon() -> tuple[str, int, int, int, bytes]:
    data = b""
    encoding = "png"
    w = 32
    h = 32
    stride = w * 4
    gl_icon = get_icon_filename("opengl", ext="png")
    if gl_icon:
        try:
            from PIL import Image  # @UnresolvedImport pylint: disable=import-outside-toplevel
        except ImportError as e:
            log(f"testing without icon: {e}")
        else:
            img = Image.open(gl_icon)
            img.load()
            w, h = img.size
            stride = w * 4
            noalpha = Image.new("RGB", img.size, (255, 255, 255))
            noalpha.paste(img, mask=img.split()[3])  # 3 is the alpha channel
            buf = BytesIO()
            try:
                noalpha.save(buf, format="JPEG")
                data = buf.getvalue()
                buf.close()
                encoding = "jpeg"
            except KeyError as e:
                log("save()", exc_info=True)
                log.warn("OpenGL using png as jpeg is not supported by Pillow: %s", e)
                data = load_binary_file(gl_icon)
    if not data:
        data = bytes([0]) * stride * h
        encoding = "rgb32"
    return encoding, w, h, stride, data


def test_gl_client_window(gl_client_window_class: Callable,
                          max_window_size=(1024, 1024),
                          pixel_depth=24,
                          show=False) -> dict[str, int | bool | str]:
    # try to render using a temporary window:
    draw_result: dict[str, int | bool | str] = {}
    window = None
    try:
        x, y = -100, -100
        if show:
            x, y = 100, 100
        ww, wh = 250, 250
        from xpra.codecs.loader import load_codec
        load_codec("dec_pillow")
        from xpra.client.gui.window_border import WindowBorder
        border = WindowBorder()
        noclient = FakeClient()
        # test with alpha, but not on win32
        # because we can't do alpha on win32 with opengl
        metadata = typedict({"has-alpha": not WIN32})

        class NoHeaderGLClientWindow(gl_client_window_class):

            def add_header_bar(self) -> None:
                """ pretend to add the header bar """

            def schedule_recheck_focus(self) -> None:
                """ pretend to handle focus checks """

        window = NoHeaderGLClientWindow(noclient, None, 0,
                                        (x, y, ww, wh), (ww, wh),
                                        metadata, False, typedict({}),
                                        border, max_window_size, pixel_depth)
        window_backing = window._backing
        window.realize()
        window_backing.paint_screen = True
        # we run this function single threaded,
        # so this is already the UI thread,
        # bypass the call to idle_add:
        window_backing.with_gfx_context = window_backing.with_gl_context
        pixel_format = "BGRX"
        options = typedict({"pixel_format": pixel_format})
        widget = window_backing._backing
        widget.realize()

        def paint_callback(success: int | bool, message="") -> None:
            log("paint_callback(%s, %s)", success, message)
            draw_result["success"] = success
            if message:
                draw_result["message"] = message.replace("\n", " ")

        pix = AtomicInteger(0x7f)
        REPAINT_DELAY = envint("XPRA_REPAINT_DELAY", int(show) * 16)

        coding, w, h, stride, icon_data = get_test_gl_icon()
        log("OpenGL: testing draw on %s widget %s with %s : %s", window, widget, coding, pixel_format)

        def draw() -> bool:
            v = pix.increase()
            img_data = bytes([v % 256] * w * 4 * h)
            options["flush"] = 1
            window.draw_region(0, 0, w, h, "rgb32", img_data, w * 4, options, [paint_callback])
            options["flush"] = 0
            mx = ww // 2 - w // 2
            my = wh // 2 - h // 2
            draw_x = round(mx * (1 + sin(v / 100)))
            draw_y = round(my * (1 + cos(v / 100)))
            log("calling draw_region for test gl icon")
            window.draw_region(draw_x, draw_y, w, h, coding, icon_data, stride, options, [paint_callback])
            return REPAINT_DELAY > 0

        # the paint code is actually synchronous here,
        # so we can check the present_fbo() result:
        if show:
            widget.show()
            window.show()
            Gtk = gi_import("Gtk")  # @UndefinedVariable
            GLib = gi_import("GLib")

            def window_close_event(*_args) -> None:
                Gtk.main_quit()

            from xpra.gtk.window import add_close_accel
            add_close_accel(window, window_close_event)
            noclient.window_close_event = window_close_event
            GLib.timeout_add(REPAINT_DELAY, draw)
            Gtk.main()
        else:
            draw()
            # ugly workaround for calling the paint handler
            # when the main loop is not running:
            if hasattr(window_backing, "on_realize"):
                window_backing.on_realize()
        last_error = window_backing.get_info().get("last-error", "")
        if last_error:
            return {
                "success": False,
                "message": f"failed to present FBO on screen: {last_error!r}",
            }
    except Exception as e:
        log(f"test_gl_client_window({gl_client_window_class}, {max_window_size}, {pixel_depth}, {show})", exc_info=True)
        msg = str(e)
        if len(msg) > 128:
            msg = msg.split(":", 1)[0]
        draw_result.update({
            "success": False,
            "safe": False,
            "message": msg,
        })
    finally:
        if window:
            window.close()
    log("test_gl_client_window(..) draw_result=%s", draw_result)
    return draw_result or {"success": False, "message": "not painted on screen"}
