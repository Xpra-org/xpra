#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018, 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from io import BytesIO
from math import cos, sin

from xpra.util import typedict, envint, AdHocStruct, AtomicInteger, iround
from xpra.os_util import WIN32
from xpra.log import Logger
from xpra.platform.paths import get_icon_filename

log = Logger("opengl", "paint")


def get_gl_client_window_module(force_enable=False):
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

def noop(*_args):
    pass
def no_scaling(*args):
    if len(args)==1:
        return args[0]
    return args
def get_None(*_args):
    return None
def no_idle_add(fn, *args, **kwargs):
    fn(*args, **kwargs)
def no_timeout_add(*_args, **_kwargs):
    raise Exception("timeout_add should not have been called")
def no_source_remove(*_args, **_kwargs):
    raise Exception("source_remove should not have been called")

class FakeClient(AdHocStruct):
    def __init__(self):
        self.sp = self.sx = self.sy = self.srect = no_scaling
        self.cx = self.cy = no_scaling
        self.xscale = self.yscale = 1
        self.server_window_decorations = True
        self.mmap_enabled = False
        self.mmap = None
        self.readonly = False
        self.encoding_defaults = {}
        self.get_window_frame_sizes = get_None
        self._focused = None
        self.request_frame_extents = noop
        self.server_window_states = ()
        self.server_window_frame_extents = False
        self.server_readonly = False
        self.server_pointer = False
        self.update_focus = noop
        self.handle_key_action = noop
        self.idle_add = no_idle_add
        self.timeout_add = no_timeout_add
        self.source_remove = no_source_remove

    def send(self, *args):
        log("send%s", args)
    def get_current_modifiers(self):
        return ()
    def get_mouse_position(self):
        return 0, 0
    def server_ok(self):
        return True
    def mask_to_names(self, *_args):
        return ()

def test_gl_client_window(gl_client_window_class, max_window_size=(1024, 1024), pixel_depth=24, show=False):
    #try to render using a temporary window:
    draw_result = {}
    window = None
    try:
        x, y = -100, -100
        if show:
            x, y = 100, 100
        w, h = 250, 250
        from xpra.codecs.loader import load_codec
        load_codec("dec_pillow")
        from xpra.client.window_border import WindowBorder
        border = WindowBorder()
        default_cursor_data = None
        noclient = FakeClient()
        #test with alpha, but not on win32
        #because we can't do alpha on win32 with opengl
        metadata = typedict({b"has-alpha" : not WIN32})
        window = gl_client_window_class(noclient, None, None, 2**32-1, x, y, w, h, w, h,
                                        metadata, False, typedict({}),
                                        border, max_window_size, default_cursor_data, pixel_depth)
        window_backing = window._backing
        window_backing.idle_add = no_idle_add
        window_backing.timeout_add = no_timeout_add
        window_backing.source_remove = no_source_remove
        window.realize()
        window_backing.paint_screen = True
        pixel_format = "BGRX"
        bpp = len(pixel_format)
        options = typedict({"pixel_format" : pixel_format})
        stride = bpp*w
        coding = "rgb32"
        widget = window_backing._backing
        widget.realize()
        def paint_callback(success, message=""):
            log("paint_callback(%s, %s)", success, message)
            draw_result["success"] = success
            if message:
                draw_result["message"] = message.replace("\n", " ")
        log("OpenGL: testing draw on %s widget %s with %s : %s", window, widget, coding, pixel_format)
        pix = AtomicInteger(0x7f)
        REPAINT_DELAY = envint("XPRA_REPAINT_DELAY", int(show)*16)
        gl_icon = get_icon_filename("opengl", ext="png")
        icon_data = None
        if os.path.exists(gl_icon):
            from PIL import Image
            img = Image.open(gl_icon)
            img.load()
            icon_w, icon_h = img.size
            icon_stride = icon_w * 4
            noalpha = Image.new("RGB", img.size, (255, 255, 255))
            noalpha.paste(img, mask=img.split()[3]) # 3 is the alpha channel
            buf = BytesIO()
            noalpha.save(buf, format="JPEG")
            icon_data = buf.getvalue()
            buf.close()
            icon_format = "jpeg"
        if not icon_data:
            icon_w = 32
            icon_h = 32
            icon_stride = icon_w * 4
            icon_data = bytes([0])*icon_stride*icon_h
            icon_format = "rgb32"
        def draw():
            v = pix.increase()
            img_data = bytes([v % 256]*stride*h)
            options["flush"] = 1
            window.draw_region(0, 0, w, h, coding, img_data, stride, v, options, [paint_callback])
            options["flush"] = 0
            mx = w//2-icon_w//2
            my = h//2-icon_h//2
            x = iround(mx*(1+sin(v/100)))
            y = iround(my*(1+cos(v/100)))
            window.draw_region(x, y, icon_w, icon_h, icon_format, icon_data, icon_stride, v, options, [paint_callback])
            return REPAINT_DELAY>0
        #the paint code is actually synchronous here,
        #so we can check the present_fbo() result:
        if show:
            widget.show()
            window.show()
            from gi.repository import Gtk, GLib
            def window_close_event(*_args):
                Gtk.main_quit()
            noclient.window_close_event = window_close_event
            GLib.timeout_add(REPAINT_DELAY, draw)
            Gtk.main()
        else:
            draw()
        if window_backing.last_present_fbo_error:
            return {
                "success" : False,
                "message" : "failed to present FBO on screen: %s" % window_backing.last_present_fbo_error
                }
    finally:
        if window:
            window.destroy()
    log("test_gl_client_window(..) draw_result=%s", draw_result)
    return draw_result



def main():
    log = Logger("opengl")
    try:
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
    r = main()
    sys.exit(r)
