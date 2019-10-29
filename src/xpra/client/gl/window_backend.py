#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018, 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import typedict, AdHocStruct
from xpra.os_util import WIN32
from xpra.log import Logger

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

def test_gl_client_window(gl_client_window_class, max_window_size=(1024, 1024), pixel_depth=24, show=False):
    #try to render using a temporary window:
    draw_result = {}
    window = None
    try:
        x, y = -100, -100
        if show:
            x, y = 100, 100
        w, h = 250, 250
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
        img_data = b"\x7f"*stride*h
        coding = "rgb32"
        widget = window_backing._backing
        widget.realize()
        def paint_callback(success, message):
            log("paint_callback(%s, %s)", success, message)
            draw_result.update({
                "success"   : success,
                "message"   : message,
                })
        log("OpenGL: testing draw on %s widget %s with %s : %s", window, widget, coding, pixel_format)
        def draw():
            window.draw_region(0, 0, w, h, coding, img_data, stride, 1, options, [paint_callback])
        #the paint code is actually synchronous here,
        #so we can check the present_fbo() result:
        if show:
            widget.show()
            window.show()
            from gi.repository import Gtk, GLib
            def window_close_event(*_args):
                Gtk.main_quit()
            noclient.window_close_event = window_close_event
            GLib.timeout_add(100, draw)
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
