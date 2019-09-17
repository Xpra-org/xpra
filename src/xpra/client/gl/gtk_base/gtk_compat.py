# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger

log = Logger("gtk", "util", "opengl")


from gi.repository import Gtk, GdkGLExt, GtkGLExt    #@UnresolvedImport
gtk = Gtk
GdkGLExt.init_check(0, "")
GtkGLExt.init_check(0, "")
MODE_DEPTH  = GdkGLExt.ConfigMode.DEPTH
MODE_RGBA   = GdkGLExt.ConfigMode.RGBA
MODE_ALPHA  = GdkGLExt.ConfigMode.ALPHA
MODE_RGB    = GdkGLExt.ConfigMode.RGB
MODE_DOUBLE = GdkGLExt.ConfigMode.DOUBLE
MODE_SINGLE = GdkGLExt.ConfigMode.SINGLE

RGBA_TYPE   = GdkGLExt.RenderType.RGBA_TYPE

def get_info():
    return {
        "gdkgl"     : {"version"    : GdkGLExt._version},   #pylint: disable=protected-access
        "gtkgl"     : {"version"    : GtkGLExt._version},   #pylint: disable=protected-access
        }
gdkgl = GdkGLExt
gtkgl = GtkGLExt
def Config_new_by_mode(display_mode):
    try:
        return GdkGLExt.Config.new_by_mode(display_mode)
    except Exception as e:
        log("no configuration for mode: %s", e)
    return None

class GtkGLExtContext(object):

    def __init__(self, widget):
        self.widget = widget
    def __enter__(self):
        #self.context = GtkGLExt.widget_create_gl_context(self.widget)
        assert GtkGLExt.widget_begin_gl(self.widget)
        #log("dir(%s)=%s", self.widget, dir(self.widget))
    def __exit__(self, exc_type, exc_val, exc_tb):
        #doing this crashes!
        #GtkGLExt.widget_end_gl(self.widget, False)
        pass
    def __repr__(self):
        return "gtk3.GtkGLExtContext(%s)" % self.widget


def GLDrawingArea(glconfig):
    assert glconfig, "missing GLConfig"
    glarea = gtk.DrawingArea()
    # Set OpenGL-capability to the widget
    gtkgl.widget_set_gl_capability(glarea, glconfig, None, True, RGBA_TYPE)
    return glarea


def get_DISPLAY_MODE(want_alpha=True, double_buffered=True):
    #MODE_DEPTH
    if want_alpha:
        mode = MODE_RGBA | MODE_ALPHA
    else:
        mode = MODE_RGB
    if double_buffered:
        mode = mode | MODE_DOUBLE
    else:
        mode = mode | MODE_SINGLE
    return mode


MODE_STRS = {
    MODE_RGB         : "RGB",
    MODE_RGBA        : "RGBA",
    MODE_ALPHA       : "ALPHA",
    MODE_DEPTH       : "DEPTH",
    MODE_DOUBLE      : "DOUBLE",
    MODE_SINGLE      : "SINGLE",
    }

def get_MODE_names(mode):
    friendly_modes = [v for k,v in MODE_STRS.items() if k>0 and (k&mode)==k]
    #special case for single (value is zero!)
    if not (mode&MODE_DOUBLE==MODE_DOUBLE):
        friendly_modes.append("SINGLE")
    return friendly_modes
