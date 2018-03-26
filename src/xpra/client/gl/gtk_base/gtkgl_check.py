#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.gtk_common.gtk_util import VISUAL_NAMES, BYTE_ORDER_NAMES
from xpra.client.gl.gtk_base.gtk_compat import get_DISPLAY_MODE, get_MODE_names
from xpra.client.gl.gl_check import check_PyOpenGL_support, gl_check_error, GL_ALPHA_SUPPORTED, CAN_DOUBLE_BUFFER

from xpra.util import envbool
from xpra.log import Logger
log = Logger("opengl")


TEST_GTKGL_RENDERING = envbool("XPRA_TEST_GTKGL_RENDERING", True)


def get_visual_name(visual):
    if not visual:
        return ""
    return VISUAL_NAMES.get(visual.type, "unknown")

def get_visual_byte_order(visual):
    if not visual:
        return ""
    return BYTE_ORDER_NAMES.get(visual.byte_order, "unknown")

def visual_to_str(visual):
    if not visual:
        return ""
    d = {
         "type"         : get_visual_name(visual),
         "byte_order"   : get_visual_byte_order(visual),
         }
    for k in ("bits_per_rgb", "depth"):
        d[k] = getattr(visual, k)
    return str(d)


#sanity checks: OpenGL version and fragment program support:
def check_GL_support(widget, force_enable=False):
    from xpra.client.gl.gtk_base.gtk_compat import GtkGLExtContext
    with GtkGLExtContext(widget):
        return check_PyOpenGL_support(force_enable)

def check_support(force_enable=False, check_colormap=False):
    #platform checks:
    from xpra.platform.gui import gl_check
    warning = gl_check()
    if warning:
        if force_enable:
            log.warn("Warning: trying to continue despite '%s'" % warning)
        else:
            gl_check_error(warning)

    props = {}
    #this will import gtk.gtkgl / gdkgl or gi.repository.GtkGLExt / GdkGLExt:
    try:
        from xpra.client.gl.gtk_base.gtk_compat import get_info, gdkgl, Config_new_by_mode, GLDrawingArea
        assert GLDrawingArea
    except RuntimeError as e:
        gl_check_error(str(e))
        return {}
    props.update(get_info())
    for want_alpha in (GL_ALPHA_SUPPORTED, not GL_ALPHA_SUPPORTED):
        for double_buffered in (CAN_DOUBLE_BUFFER, not CAN_DOUBLE_BUFFER):
            display_mode = get_DISPLAY_MODE(want_alpha, double_buffered)
            log("get_DISPLAY_MODE(%s, %s)=%s", want_alpha, double_buffered, display_mode)
            glconfig = Config_new_by_mode(display_mode)
            log("Config_new_by_mode(%s)=%s", display_mode, glconfig)
            if glconfig:
                break
    if not glconfig:
        gl_check_error("cannot setup an OpenGL context")
        return {}
    props["display_mode"] = get_MODE_names(display_mode)
    #on OSX, we had to patch out get_depth...
    #so take extra precautions when querying properties:
    for x,fn_name in {
        "has_alpha"           : "has_alpha",
        "rgba"                : "is_rgba",
        "stereo"              : "is_stereo",
        "double-buffered"     : "is_double_buffered",
        "depth"               : "get_depth",
        "has-depth-buffer"    : "has_depth_buffer",
        "has-stencil-buffer"  : "has_stencil_buffer",
        }.items():
        fn = getattr(glconfig, fn_name, None)
        if fn:
            props[x] = fn()
        else:
            log("%s does not support %s()", glconfig, fn_name)
    for x in ("RED_SIZE", "GREEN_SIZE", "BLUE_SIZE", "ALPHA_SIZE",
              "AUX_BUFFERS", "DEPTH_SIZE", "STENCIL_SIZE",
              "ACCUM_RED_SIZE", "ACCUM_GREEN_SIZE", "ACCUM_BLUE_SIZE",
              "SAMPLE_BUFFERS", "SAMPLES"):
        prop = getattr(gdkgl, x)
        if not prop:
            continue
        try:
            v = glconfig.get_attrib(prop)[0]
            props[x.lower().replace("_", "-")] = v
        except:
            pass
    log("GL props=%s", props)

    if TEST_GTKGL_RENDERING:
        gl_props = test_gtkgl_rendering(glconfig, force_enable, check_colormap)
        if not gl_props:
            #if we fail the test rendering, don't return anything
            #so the client will know this backend should not be used
            return {}
        props.update(gl_props)
    else:
        log("gtkgl rendering test skipped")
    return props

def test_gtkgl_rendering(glconfig, force_enable=False, check_colormap=False):
    log("testing gtkgl rendering")
    from xpra.client.gl.gl_window_backing_base import paint_context_manager
    from xpra.client.gl.gtk_base.gtk_compat import gdkgl, GLDrawingArea
    gl_props = {}
    try:
        with paint_context_manager:
            from xpra.gtk_common.gtk_util import import_gtk, gdk_window_process_all_updates
            gtk = import_gtk()
            assert gdkgl.query_extension()
            glext, w = None, None
            try:
                #ugly code for win32 and others (virtualbox broken GL drivers)
                #for getting a GL drawable and context: we must use a window...
                #(which we do not even show on screen)
                #
                #here is the old simpler alternative which does not work on some platforms:
                # glext = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), 1, 1))
                # gldrawable = glext.set_gl_capability(glconfig)
                # glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
                w = gtk.Window()
                w.set_decorated(False)
                vbox = gtk.VBox()
                glarea = GLDrawingArea(glconfig)
                glarea.set_size_request(32, 32)
                vbox.add(glarea)
                vbox.show_all()
                w.add(vbox)
                #we don't need to actually show the window!
                #w.show_all()
                glarea.realize()
                gdk_window_process_all_updates()

                gl_props = check_GL_support(glarea, force_enable)

                if check_colormap:
                    s = w.get_screen()
                    for x in ("rgb_visual", "rgba_visual", "system_visual"):
                        try:
                            visual = getattr(s, "get_%s" % x)()
                            gl_props[x] = visual_to_str(visual)
                        except:
                            pass
                    #i = 0
                    #for v in s.list_visuals():
                    #    gl_props["visual[%s]" % i] = visual_to_str(v)
                    #    i += 1
            finally:
                if w:
                    w.destroy()
                del glext, glconfig
    except Exception as e:
        log("check_support failed", exc_info=True)
        log.error("Error: gtkgl rendering failed its sanity checks:")
        log.error(" %s", e)
        return {}
    return gl_props


def main(force_enable=False):
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    from xpra.util import print_nested_dict
    from xpra.log import enable_color
    with program_context("OpenGL-Check"):
        gui_init()
        enable_color()
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            log.enable_debug()
            from xpra.client.gl.gtk_base.gtk_compat import log as clog
            clog.enable_debug()
        #replace ImportError with a log message:
        global gl_check_error
        errors = []
        def log_error(msg):
            log.error("ERROR: %s", msg)
            errors.append(msg)
        gl_check_error = log_error
        props = check_support(force_enable, verbose)
        log.info("")
        if len(errors)>0:
            log.info("OpenGL errors:")
            for e in errors:
                log.info("  %s", e)
        log.info("")
        log.info("OpenGL properties:")
        print_nested_dict(props)
        return len(errors)


if __name__ == "__main__":
    sys.exit(main())
