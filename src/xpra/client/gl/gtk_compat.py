# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.gtk_common.gobject_compat import is_gtk3

from xpra.log import Logger
log = Logger("gtk", "util", "opengl")


if is_gtk3():
    from gi.repository import GdkGLExt, GtkGLExt    #@UnresolvedImport
    MODE_DEPTH  = GdkGLExt.ConfigMode.DEPTH
    MODE_RGBA   = GdkGLExt.ConfigMode.RGBA
    MODE_ALPHA  = GdkGLExt.ConfigMode.ALPHA
    MODE_RGB    = GdkGLExt.ConfigMode.RGB
    MODE_DOUBLE = GdkGLExt.ConfigMode.DOUBLE
    MODE_SINGLE = GdkGLExt.ConfigMode.SINGLE

    RGBA_TYPE   = GdkGLExt.RenderType.RGBA_TYPE

    def get_info():
        return {"gdkgl_version"         : GdkGLExt._version,
                "gtkgl_version"         : GtkGLExt._version,
                }
    gdkgl = GdkGLExt
    gtkgl = GtkGLExt
    def Config_new_by_mode(display_mode):
        try:
            return GdkGLExt.Config.new_by_mode(display_mode)
        except Exception as e:
            log("no configuration for mode: %s", e)
        return None

    def begin_gl(widget):
        return GtkGLExt.widget_begin_gl(widget)

    def end_gl(widget):
        GtkGLExt.widget_end_gl(widget, False)

else:
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
        return {
                 "pygdkglext_version"   : gdkgl.pygdkglext_version,
                 "gtkglext_version"     : gtkgl.gtkglext_version,
                 "gdkglext_version"     : gdkgl.gdkglext_version,
                 "gdkgl_version"        : gdkgl.query_version()
                 }

    def begin_gl(widget):
        gldrawable = gtkgl.widget_get_gl_drawable(widget)
        glcontext = gtkgl.widget_get_gl_context(widget)
        return gldrawable.gl_begin(glcontext)

    def end_gl(widget):
        gldrawable = gtkgl.widget_get_gl_drawable(widget)
        gldrawable.gl_end()
