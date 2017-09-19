#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.client.gl.gl_check import check_PyOpenGL_support, GL_ALPHA_SUPPORTED, gl_check_error

from xpra.util import envbool
from xpra.os_util import WIN32, PYTHON3
from xpra.log import Logger
log = Logger("opengl")


#not working with gtk3 yet?
CAN_DOUBLE_BUFFER = not PYTHON3
#needed on win32?:
DEFAULT_DOUBLE_BUFFERED = WIN32 or CAN_DOUBLE_BUFFER
DOUBLE_BUFFERED = envbool("XPRA_OPENGL_DOUBLE_BUFFERED", DEFAULT_DOUBLE_BUFFERED)
TEST_GTKGL_RENDERING = envbool("XPRA_TEST_GTKGL_RENDERING", 1)

from xpra.gtk_common.gtk_util import STATIC_GRAY, GRAYSCALE, STATIC_COLOR, PSEUDO_COLOR, TRUE_COLOR, DIRECT_COLOR
VISUAL_NAMES = {
                STATIC_GRAY      : "STATIC_GRAY",
                GRAYSCALE        : "GRAYSCALE",
                STATIC_COLOR     : "STATIC_COLOR",
                PSEUDO_COLOR     : "PSEUDO_COLOR",
                TRUE_COLOR       : "TRUE_COLOR",
                DIRECT_COLOR     : "DIRECT_COLOR",
                }

from xpra.gtk_common.gtk_util import LSB_FIRST, MSB_FIRST
VISUAL_TYPES = {
                LSB_FIRST   : "LSB",
                MSB_FIRST   : "MSB",
                }

from xpra.client.gl.gtk_base.gtk_compat import MODE_RGBA, MODE_ALPHA, MODE_RGB, MODE_DOUBLE, MODE_SINGLE, MODE_DEPTH


def get_visual_name(visual):
    if not visual:
        return ""
    global VISUAL_NAMES
    return VISUAL_NAMES.get(visual.type, "unknown")

def get_visual_byte_order(visual):
    if not visual:
        return ""
    global VISUAL_TYPES
    return VISUAL_TYPES.get(visual.byte_order, "unknown")

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

def get_DISPLAY_MODE(want_alpha=GL_ALPHA_SUPPORTED):
    #MODE_DEPTH
    if want_alpha:
        mode = MODE_RGBA | MODE_ALPHA
    else:
        mode = MODE_RGB
    if DOUBLE_BUFFERED:
        mode = mode | MODE_DOUBLE
    else:
        mode = mode | MODE_SINGLE
    return mode

FRIENDLY_MODE_NAMES = {
                       MODE_RGB         : "RGB",
                       MODE_RGBA        : "RGBA",
                       MODE_ALPHA       : "ALPHA",
                       MODE_DEPTH       : "DEPTH",
                       MODE_DOUBLE      : "DOUBLE",
                       MODE_SINGLE      : "SINGLE",
                       }

def get_MODE_names(mode):
    global FRIENDLY_MODE_NAMES
    friendly_modes = [v for k,v in FRIENDLY_MODE_NAMES.items() if k>0 and (k&mode)==k]
    #special case for single (value is zero!)
    if not (mode&MODE_DOUBLE==MODE_DOUBLE):
        friendly_modes.append("SINGLE")
    return friendly_modes


_version_warning_shown = False
#support for memory views requires Python 2.7 and PyOpenGL 3.1
def is_pyopengl_memoryview_safe(pyopengl_version, accel_version):
    if accel_version is not None and pyopengl_version!=accel_version:
        #mismatch is not safe!
        return False
    vsplit = pyopengl_version.split('.')
    if vsplit[:2]<['3','1']:
        #requires PyOpenGL >= 3.1, earlier versions will not work
        return False
    if vsplit[:2]>=['3','2']:
        #assume that newer versions are OK too
        return True
    #at this point, we know we have a 3.1.x version, but which one?
    if len(vsplit)<3:
        #not enough parts to know for sure, assume it's not supported
        return False
    micro = vsplit[2]
    #ie: '0', '1' or '0b2'
    if micro=='0':
        return True     #3.1.0 is OK
    if micro>='1':
        return True     #3.1.1 onwards should be too
    return False        #probably something like '0b2' which is broken


def check_functions(*functions):
    missing = []
    available = []
    for x in functions:
        try:
            name = x.__name__
        except:
            name = str(x)
        if not bool(x):
            missing.append(name)
        else:
            available.append(name)
    if len(missing)>0:
        gl_check_error("some required OpenGL functions are not available: %s" % (", ".join(missing)))
    else:
        log("All the required OpenGL functions are available: %s " % (", ".join(available)))


#sanity checks: OpenGL version and fragment program support:
def check_GL_support(widget, force_enable=False):
    from xpra.client.gl.gtk_base.gtk_compat import GLContextManager
    with GLContextManager(widget):
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
    except RuntimeError as e:
        gl_check_error(str(e))
        return {}
    props.update(get_info())
    display_mode = get_DISPLAY_MODE()
    glconfig = Config_new_by_mode(display_mode)
    if glconfig is None and CAN_DOUBLE_BUFFER:
        log("trying to toggle double-buffering")
        display_mode &= ~MODE_DOUBLE
        glconfig = Config_new_by_mode(display_mode)
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
        log("testing gtkgl rendering")
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
        props.update(gl_props)
    else:
        log("gtkgl rendering test skipped")
    return props


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
            from xpra.client.gl.gtk_compat import log as clog
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
