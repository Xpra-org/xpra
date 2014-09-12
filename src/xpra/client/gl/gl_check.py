#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import logging
from xpra.log import Logger, CaptureHandler
log = Logger("opengl")

required_extensions = ["GL_ARB_texture_rectangle", "GL_ARB_vertex_program"]


WHITELIST = {}
BLACKLIST = {"vendor" : ["nouveau", "Humper", "VMware, Inc."]}
if False:
    #for testing:
    BLACKLIST["vendor"].append("NVIDIA Corporation")
    WHITELIST["renderer"] = ["GeForce GTX 760/PCIe/SSE2"]
    #crashes were reported with the Intel driver on OSX
    BLACKLIST["vendor"].append("Intel Inc.")
    WHITELIST["renderer"] = ["Intel HD Graphics 4000 OpenGL Engine"]


DEFAULT_ALPHA = not sys.platform.startswith("win") and not sys.platform.startswith("darwin")
GL_ALPHA_SUPPORTED = os.environ.get("XPRA_ALPHA", DEFAULT_ALPHA) in (True, "1")
DEFAULT_DOUBLE_BUFFERED = 0
if sys.platform.startswith("win"):
    #needed on win32?
    DEFAULT_DOUBLE_BUFFERED = 1
DOUBLE_BUFFERED = os.environ.get("XPRA_OPENGL_DOUBLE_BUFFERED", str(DEFAULT_DOUBLE_BUFFERED))=="1"


def get_visual_name(visual):
    from xpra.gtk_common.gtk_util import STATIC_GRAY, GRAYSCALE, STATIC_COLOR, PSEUDO_COLOR, TRUE_COLOR, DIRECT_COLOR
    if not visual:
        return ""
    return {
           STATIC_GRAY      : "STATIC_GRAY",
           GRAYSCALE        : "GRAYSCALE",
           STATIC_COLOR     : "STATIC_COLOR",
           PSEUDO_COLOR     : "PSEUDO_COLOR",
           TRUE_COLOR       : "TRUE_COLOR",
           DIRECT_COLOR     : "DIRECT_COLOR"}.get(visual.type, "unknown")

def get_visual_byte_order(visual):
    from xpra.gtk_common.gtk_util import LSB_FIRST, MSB_FIRST
    if not visual:
        return ""
    return {
            LSB_FIRST   : "LSB",
            MSB_FIRST   : "MSB"}.get(visual.byte_order, "unknown")

def visual_to_str(visual):
    if not visual:
        return ""
    d = {"type"         : get_visual_name(visual),
         "byte_order"   : get_visual_byte_order(visual)}
    for k in ("bits_per_rgb", "depth"):
        d[k] = getattr(visual, k)
    return str(d)

def get_DISPLAY_MODE(want_alpha=GL_ALPHA_SUPPORTED):
    from xpra.client.gl.gtk_compat import MODE_RGBA, MODE_ALPHA, MODE_RGB, MODE_DOUBLE, MODE_SINGLE
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

def get_MODE_names(mode):
    from xpra.client.gl.gtk_compat import MODE_RGB, MODE_RGBA, MODE_ALPHA, MODE_DEPTH, MODE_DOUBLE, MODE_SINGLE
    friendly_mode_names = {MODE_RGB         : "RGB",
                           MODE_RGBA        : "RGBA",
                           MODE_ALPHA       : "ALPHA",
                           MODE_DEPTH       : "DEPTH",
                           MODE_DOUBLE      : "DOUBLE",
                           MODE_SINGLE      : "SINGLE"}
    friendly_modes = [v for k,v in friendly_mode_names.items() if k>0 and (k&mode)==k]
    #special case for single (value is zero!)
    if not (mode&MODE_DOUBLE==MODE_DOUBLE):
        friendly_modes.append("SINGLE")
    return friendly_modes


#by default, we raise an ImportError as soon as we find something missing:
def raise_error(msg):
    raise ImportError(msg)
gl_check_error = raise_error


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
def check_GL_support(widget, min_texture_size=0, force_enable=False):
    from xpra.client.gl.gtk_compat import begin_gl, end_gl
    try:
        if not begin_gl(widget):
            raise ImportError("failed to get an opengl context")
    except Exception as e:
        raise ImportError("error getting an opengl context: %s" % e)
    try:
        return do_check_GL_support(min_texture_size, force_enable)
    finally:
        end_gl(widget)

def do_check_GL_support(min_texture_size, force_enable):
    props = {}
    try:
        #log redirection:
        def redirect_log(logger_name):
            logger = logging.getLogger(logger_name)
            assert logger is not None
            logger.saved_handlers = logger.handlers
            logger.saved_propagate = logger.propagate
            logger.handlers = [CaptureHandler()]
            logger.propagate = 0
            return logger
        fhlogger = redirect_log('OpenGL.formathandler')
        elogger = redirect_log('OpenGL.extensions')
        alogger = redirect_log('OpenGL.acceleratesupport')
        arlogger = redirect_log('OpenGL.arrays')
        clogger = redirect_log('OpenGL.converters')

        import OpenGL
        props["pyopengl"] = OpenGL.__version__
        from OpenGL.GL import GL_VERSION, GL_EXTENSIONS
        from OpenGL.GL import glGetString, glGetInteger
        gl_version_str = glGetString(GL_VERSION)
        if gl_version_str is None:
            gl_check_error("OpenGL version is missing - cannot continue")
            return  {}
        gl_major = int(gl_version_str[0])
        gl_minor = int(gl_version_str[2])
        props["opengl"] = gl_major, gl_minor
        MIN_VERSION = (1,1)
        if (gl_major, gl_minor) < MIN_VERSION:
            gl_check_error("OpenGL output requires version %s or greater, not %s.%s" %
                              (".".join([str(x) for x in MIN_VERSION]), gl_major, gl_minor))
        else:
            log("found valid OpenGL version: %s.%s", gl_major, gl_minor)
        try:
            extensions = glGetString(GL_EXTENSIONS).decode().split(" ")
        except:
            log("error querying extensions", exc_info=True)
            extensions = []
            gl_check_error("OpenGL could not find the list of GL extensions - does the graphics driver support OpenGL?")
        log("OpenGL extensions found: %s", ", ".join(extensions))
        props["extensions"] = extensions

        from OpenGL.arrays.arraydatatype import ArrayDatatype
        try:
            log("found the following array handlers: %s", set(ArrayDatatype.getRegistry().values()))
        except:
            pass

        from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_SHADING_LANGUAGE_VERSION
        for d,s,fatal in (("vendor",     GL_VENDOR,      True),
                          ("renderer",   GL_RENDERER,    True),
                          ("shading language version", GL_SHADING_LANGUAGE_VERSION, False)):
            try:
                v = glGetString(s)
                v = v.decode()
                log("%s: %s", d, v)
            except:
                if fatal:
                    gl_check_error("OpenGL property '%s' is missing" % d)
                else:
                    log("OpenGL property '%s' is missing", d)
                v = ""
            props[d] = v

        from OpenGL.GLU import gluGetString, GLU_VERSION, GLU_EXTENSIONS
        for d,s in {"GLU version": GLU_VERSION, "GLU extensions":GLU_EXTENSIONS}.items():
            v = gluGetString(s)
            v = v.decode()
            log("%s: %s", d, v)
            props[d] = v

        blacklisted = None
        whitelisted = None
        for k,vlist in BLACKLIST.items():
            v = props.get(k)
            if v in vlist:
                log("%s '%s' found in blacklist: %s", k, v, vlist)
                blacklisted = k, v
        for k,vlist in WHITELIST.items():
            v = props.get(k)
            if v in vlist:
                log("%s '%s' found in whitelist: %s", k, v, vlist)
                whitelisted = k, v
        if blacklisted:
            if whitelisted:
                log.info("%s '%s' enabled (found in both blacklist and whitelist)", *whitelisted)
            elif force_enable:
                log.warn("Warning: %s '%s' is blacklisted!", *blacklisted)
            else:
                gl_check_error("%s '%s' is blacklisted!" % (blacklisted))

        #check for specific functions we need:
        from OpenGL.GL import glActiveTexture, glTexSubImage2D, glTexCoord2i, \
            glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
            glEnableClientState, glGenTextures, glDisable, \
            glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
            glTexParameteri, \
            glTexImage2D, \
            glMultiTexCoord2i, \
            glVertex2i, glEnd
        check_functions(glActiveTexture, glTexSubImage2D, glTexCoord2i, \
            glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
            glEnableClientState, glGenTextures, glDisable, \
            glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
            glTexParameteri, \
            glTexImage2D, \
            glMultiTexCoord2i, \
            glVertex2i, glEnd)

        glEnablei = None
        try:
            from OpenGL.GL import glEnablei
        except:
            pass
        if not bool(glEnablei):
            log.warn("OpenGL glEnablei is not available, disabling transparency")
            global GL_ALPHA_SUPPORTED
            GL_ALPHA_SUPPORTED = False

        #check for framebuffer functions we need:
        from OpenGL.GL.ARB.framebuffer_object import GL_FRAMEBUFFER, \
            GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D
        check_functions(GL_FRAMEBUFFER, \
            GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D)

        for ext in required_extensions:
            if ext not in extensions:
                gl_check_error("OpenGL driver lacks support for extension: %s" % ext)
            else:
                log("Extension %s is present", ext)

        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB
        if not glInitFragmentProgramARB():
            gl_check_error("OpenGL output requires glInitFragmentProgramARB")
        else:
            log("glInitFragmentProgramARB works")

        from OpenGL.GL.ARB.texture_rectangle import glInitTextureRectangleARB
        if not glInitTextureRectangleARB():
            gl_check_error("OpenGL output requires glInitTextureRectangleARB")
        else:
            log("glInitTextureRectangleARB works")

        from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glDeleteProgramsARB, \
            glBindProgramARB, glProgramStringARB
        check_functions(glGenProgramsARB, glDeleteProgramsARB, glBindProgramARB, glProgramStringARB)

        try:
            from OpenGL.GL import GL_MAX_TEXTURE_SIZE
            texture_size = glGetInteger(GL_MAX_TEXTURE_SIZE)
            #this one may be missing?
            rect_texture_size = texture_size
            try:
                from OpenGL.GL import GL_MAX_RECTANGLE_TEXTURE_SIZE
                rect_texture_size = glGetInteger(GL_MAX_RECTANGLE_TEXTURE_SIZE)
            except ImportError as e:
                log("OpenGL: %s", e)
                log("using GL_MAX_TEXTURE_SIZE=%s as default", texture_size)
        except Exception as e:
            emsg = str(e)
            if hasattr(e, "description"):
                emsg = e.description
            gl_check_error("unable to query max texture size: %s" % emsg)
            return props

        if min_texture_size>texture_size or min_texture_size>rect_texture_size:
            gl_check_error("The texture size is too small: %s" % texture_size)
        else:
            log("Texture size GL_MAX_RECTANGLE_TEXTURE_SIZE_ARB=%s, GL_MAX_TEXTURE_SIZE=%s", rect_texture_size, texture_size)
        return props
    finally:
        for x in alogger.handlers[0].records:
            #strip default message prefix:
            msg = x.getMessage().replace("No OpenGL_accelerate module loaded: ", "")
            if msg=="No module named OpenGL_accelerate":
                msg = "missing accelerate module"
            if msg!="OpenGL_accelerate module loaded":
                msg = "PyOpenGL warning: %s" % msg
            log.info(msg)

        #format handler messages:
        STRIP_LOG_MESSAGE = "Unable to load registered array format handler "
        missing_handlers = []
        for x in fhlogger.handlers[0].records:
            msg = x.getMessage()
            p = msg.find(STRIP_LOG_MESSAGE)
            if p<0:
                #unknown message, log it:
                log.info(msg)
                continue
            format_handler = msg[p+len(STRIP_LOG_MESSAGE):]
            p = format_handler.find(":")
            if p>0:
                format_handler = format_handler[:p]
                missing_handlers.append(format_handler)
        if len(missing_handlers)>0:
            log.warn("PyOpenGL warning: missing array format handlers: %s", ", ".join(missing_handlers))

        for x in elogger.handlers[0].records:
            msg = x.getMessage()
            #ignore extension messages:
            p = msg.startswith("GL Extension ") and msg.endswith("available")
            if not p:
                log.info(msg)

        missing_accelerators = []
        STRIP_AR_HEAD = "Unable to load"
        STRIP_AR_TAIL = "from OpenGL_accelerate"
        for x in arlogger.handlers[0].records+clogger.handlers[0].records:
            msg = x.getMessage()
            if msg.startswith(STRIP_AR_HEAD) and msg.endswith(STRIP_AR_TAIL):
                m = msg[len(STRIP_AR_HEAD):-len(STRIP_AR_TAIL)].strip()
                m = m.replace("accelerators", "").replace("accelerator", "").strip()
                missing_accelerators.append(m)
                continue
            log.info(msg)
        if missing_accelerators:
            log.info("OpenGL accelerate missing: %s", ", ".join(missing_accelerators))

        def restore_logger(logger):
            logger.handlers = logger.saved_handlers
            logger.propagate = logger.saved_propagate
        restore_logger(fhlogger)
        restore_logger(elogger)
        restore_logger(alogger)
        restore_logger(arlogger)
        restore_logger(clogger)


def check_support(min_texture_size=0, force_enable=False, check_colormap=False):
    #platform checks:
    from xpra.platform.gui import gl_check
    warning = gl_check()
    if warning:
        gl_check_error(warning)

    props = {}
    #this will import gtk.gtkgl / gdkgl or gi.repository.GtkGLExt / GdkGLExt:
    from xpra.client.gl.gtk_compat import get_info, gtkgl, gdkgl, Config_new_by_mode, MODE_DOUBLE, RGBA_TYPE
    props.update(get_info())
    display_mode = get_DISPLAY_MODE()
    glconfig = Config_new_by_mode(display_mode)
    if glconfig is None:
        log("trying to toggle double-buffering")
        display_mode &= ~MODE_DOUBLE
        glconfig = Config_new_by_mode(display_mode)
        if not glconfig:
            raise Exception("cannot setup an OpenGL context")
    props["display_mode"] = get_MODE_names(display_mode)
    props["glconfig"] = glconfig
    props["has_alpha"] = glconfig.has_alpha()
    props["rgba"] = glconfig.is_rgba()
    log("GL props=%s", props)
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
        glarea = gtk.DrawingArea()
        # Set OpenGL-capability to the widget
        gtkgl.widget_set_gl_capability(glarea, glconfig, None, True, RGBA_TYPE)
        glarea.set_size_request(32, 32)
        vbox.add(glarea)
        vbox.show_all()
        w.add(vbox)
        #we don't need to actually show the window!
        #w.show_all()
        glarea.realize()
        gdk_window_process_all_updates()

        gl_props = check_GL_support(glarea, min_texture_size, force_enable)

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
    return props


def main():
    from xpra.platform import init,clean
    from xpra.util import pver
    try:
        init("OpenGL-Check")
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
        props = check_support(0, True, verbose)
        log.info("")
        if len(errors)>0:
            log.info("OpenGL errors:")
            for e in errors:
                log.info("  %s", e)
        log.info("")
        log.info("OpenGL properties:")
        for k in sorted(props.keys()):
            v = props[k]
            #skip not human readable:
            if k not in ("extensions", "glconfig"):
                log.info("* %s : %s", str(k).ljust(24), pver(v))
        return len(errors)
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
