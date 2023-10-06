#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from io import BytesIO
from math import cos, sin
from typing import Type, Tuple, Dict, Any

from xpra.common import noop
from xpra.util import typedict, envint, AtomicInteger
from xpra.os_util import WIN32, load_binary_file, is_X11
from xpra.log import Logger
from xpra.platform.paths import get_icon_filename
from xpra.client.gui.fake_client import FakeClient

log = Logger("opengl", "paint")


def get_gl_client_window_module(force_enable=False) -> Tuple[Dict,Any]:
    log("get_gl_client_window_module()")
    try:
        from xpra.client.gl.gtk3 import nativegl_client_window
    except ImportError as e:
        log("cannot import opengl window module", exc_info=True)
        log.warn("Warning: cannot import native OpenGL module")
        log.warn(" %s", e)
        return {}, None
    opengl_props = nativegl_client_window.check_support(force_enable)
    log("check_support(%s)=%s", force_enable, opengl_props)
    if opengl_props:
        return opengl_props, nativegl_client_window
    return {}, None


def get_test_gl_icon():
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
        encoding  = "rgb32"
    return encoding, w, h, stride, data

def no_idle_add(fn, *args, **kwargs):
    fn(*args, **kwargs)

def test_gl_client_window(gl_client_window_class : Type, max_window_size=(1024, 1024), pixel_depth=24, show=False):
    #try to render using a temporary window:
    draw_result = {}
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
        default_cursor_data = None
        noclient = FakeClient()
        #test with alpha, but not on win32
        #because we can't do alpha on win32 with opengl
        metadata = typedict({"has-alpha" : not WIN32})
        class NoHeaderGLClientWindow(gl_client_window_class):
            def add_header_bar(self):
                """ pretend to add the header bar """
            def schedule_recheck_focus(self):
                """ pretend to handle focus checks """
        window = NoHeaderGLClientWindow(noclient, None, 0, 2**32-1, x, y, ww, wh, ww, wh,
                                        metadata, False, typedict({}),
                                        border, max_window_size, default_cursor_data, pixel_depth)
        window_backing = window._backing
        window_backing.idle_add = no_idle_add
        window_backing.timeout_add = noop
        window_backing.source_remove = noop
        window.realize()
        window_backing.paint_screen = True
        pixel_format = "BGRX"
        options = typedict({"pixel_format" : pixel_format})
        widget = window_backing._backing
        widget.realize()
        def paint_callback(success, message=""):
            log("paint_callback(%s, %s)", success, message)
            draw_result["success"] = success
            if message:
                draw_result["message"] = message.replace("\n", " ")
        pix = AtomicInteger(0x7f)
        REPAINT_DELAY = envint("XPRA_REPAINT_DELAY", int(show)*16)

        coding, w, h, stride, icon_data = get_test_gl_icon()
        log("OpenGL: testing draw on %s widget %s with %s : %s", window, widget, coding, pixel_format)
        def draw():
            v = pix.increase()
            img_data = bytes([v % 256]*w*4*h)
            options["flush"] = 1
            window.draw_region(0, 0, w, h, "rgb32", img_data, w*4, v, options, [paint_callback])
            options["flush"] = 0
            mx = ww//2-w//2
            my = wh//2-h//2
            draw_x = round(mx*(1+sin(v/100)))
            draw_y = round(my*(1+cos(v/100)))
            log("calling draw_region for test gl icon")
            window.draw_region(draw_x, draw_y, w, h, coding, icon_data, stride, v, options, [paint_callback])
            return REPAINT_DELAY>0
        #the paint code is actually synchronous here,
        #so we can check the present_fbo() result:
        if show:
            widget.show()
            window.show()
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk, GLib  # @UnresolvedImport
            def window_close_event(*_args):
                Gtk.main_quit()
            noclient.window_close_event = window_close_event
            GLib.timeout_add(REPAINT_DELAY, draw)
            Gtk.main()
        else:
            draw()
            #ugly workaround for calling the paint handler
            #when the main loop is not running:
            if hasattr(window_backing, "on_realize"):
                window_backing.on_realize()
        if window_backing.last_present_fbo_error:
            return {
                "success" : False,
                "message" : "failed to present FBO on screen: %s" % window_backing.last_present_fbo_error
                }
    finally:
        if window:
            window.destroy()
    log("test_gl_client_window(..) draw_result=%s", draw_result)
    return draw_result or {"success" : False, "message" : "not painted on screen"}



def main(argv):
    from xpra.platform import program_context
    with program_context("opengl", "OpenGL"):
        try:
            if "-v" in argv or "--verbose" in argv:
                log.enable_debug()
            if is_X11():
                from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
                init_gdk_display_source()
            opengl_props, gl_client_window_module = get_gl_client_window_module(True)
            log("do_run_glcheck() opengl_props=%s, gl_client_window_module=%s", opengl_props, gl_client_window_module)
            gl_client_window_class = gl_client_window_module.GLClientWindow
            pixel_depth = 0
            log("do_run_glcheck() gl_client_window_class=%s, pixel_depth=%s", gl_client_window_class, pixel_depth)
            #if pixel_depth not in (0, 16, 24, 30) and pixel_depth<32:
            #    pixel_depth = 0
            draw_result = test_gl_client_window(gl_client_window_class, pixel_depth=pixel_depth, show=True)
            success = draw_result.pop("success", False)
            opengl_props.update(draw_result)
            if not success:
                opengl_props["safe"] = False
            return 0
        except Exception:
            log("do_run_glcheck(..)", exc_info=True)
            return 1

if __name__ == "__main__":
    r = main(sys.argv)
    sys.exit(r)
