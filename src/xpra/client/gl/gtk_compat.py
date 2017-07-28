# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.gtk_common.gobject_compat import is_gtk3

from xpra.log import Logger
log = Logger("gtk", "util", "opengl")


if is_gtk3():
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
                "gdkgl"     : {"version"    : GdkGLExt._version},
                "gtkgl"     : {"version"    : GtkGLExt._version},
                }
    gdkgl = GdkGLExt
    gtkgl = GtkGLExt
    def Config_new_by_mode(display_mode):
        try:
            return GdkGLExt.Config.new_by_mode(display_mode)
        except Exception as e:
            log("no configuration for mode: %s", e)
        return None

    class GLContextManager(object):

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
            return "gtk3.GLContextManager(%s)" % self.widget

else:
    import gtk
    from gtk import gdkgl, gtkgl
    MODE_DEPTH  = gdkgl.MODE_DEPTH
    MODE_RGBA   = gdkgl.MODE_RGBA
    MODE_ALPHA  = gdkgl.MODE_ALPHA
    MODE_RGB    = gdkgl.MODE_RGB
    MODE_DOUBLE = gdkgl.MODE_DOUBLE
    MODE_SINGLE = gdkgl.MODE_SINGLE

    RGBA_TYPE   = gdkgl.RGBA_TYPE

    def Config_new_by_mode(display_mode):
        try:
            return gdkgl.Config(mode=display_mode)
        except gdkgl.NoMatches as e:
            log("no match: %s", e)
        return None

    def get_info():
        def v(x):
            return {"version" : x}
        return {
                 "pygdkglext"   : v(gdkgl.pygdkglext_version),
                 "gtkglext"     : v(gtkgl.gtkglext_version),
                 "gdkglext"     : v(gdkgl.gdkglext_version),
                 "gdkgl"        : v(gdkgl.query_version())
                 }

    class GLContextManager(object):

        def __init__(self, widget):
            self.widget = widget
            self.gldrawable = gtkgl.widget_get_gl_drawable(widget)
            assert self.gldrawable, "failed to get the GL drawable for %s" % widget
            self.glcontext = gtkgl.widget_get_gl_context(widget)
            assert self.glcontext, "failed to get a GL context from %s" % widget

        def __enter__(self):
            assert self.gldrawable.gl_begin(self.glcontext)

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.gldrawable.gl_end()

        def __repr__(self):
            return "gtk2.GLContextManager(%s)" % self.widget

def GLDrawingArea(glconfig):
    assert glconfig, "missing GLConfig"
    glarea = gtk.DrawingArea()
    # Set OpenGL-capability to the widget
    gtkgl.widget_set_gl_capability(glarea, glconfig, None, True, RGBA_TYPE)
    return glarea
