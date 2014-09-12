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
    import gtk.gdk
    if not visual:
        return ""
    return {
           gtk.gdk.VISUAL_STATIC_GRAY   : "STATIC_GRAY",
           gtk.gdk.VISUAL_GRAYSCALE     : "GRAYSCALE",
           gtk.gdk.VISUAL_STATIC_COLOR  : "STATIC_COLOR",
           gtk.gdk.VISUAL_PSEUDO_COLOR  : "PSEUDO_COLOR",
           gtk.gdk.VISUAL_TRUE_COLOR    : "TRUE_COLOR",
           gtk.gdk.VISUAL_DIRECT_COLOR  : "DIRECT_COLOR"}.get(visual.type, "unknown")

def get_visual_byte_order(visual):
    import gtk.gdk
    if not visual:
        return ""
    return {
            gtk.gdk.LSB_FIRST   : "LSB",
            gtk.gdk.MSB_FIRST   : "MSB"}.get(visual.byte_order, "unknown")

def visual_to_str(visual):
    if not visual:
        return ""
    d = {"type"         : get_visual_name(visual),
         "byte_order"   : get_visual_byte_order(visual)}
    for k in ("bits_per_rgb", "depth"):
        d[k] = getattr(visual, k)
    return str(d)

def get_DISPLAY_MODE(want_alpha=GL_ALPHA_SUPPORTED):
    import gtk.gdkgl
    #gtk.gdkgl.MODE_DEPTH
    mode = 0
    if want_alpha:
        mode = mode | gtk.gdkgl.MODE_RGBA | gtk.gdkgl.MODE_ALPHA
    else:
        mode = mode | gtk.gdkgl.MODE_RGB
    if DOUBLE_BUFFERED:
        mode = mode | gtk.gdkgl.MODE_DOUBLE
    else:
        mode = mode | gtk.gdkgl.MODE_SINGLE
    return mode

def get_MODE_names(mode):
    import gtk.gdkgl
    friendly_mode_names = {gtk.gdkgl.MODE_RGB       : "RGB",
                           gtk.gdkgl.MODE_RGBA      : "RGBA",
                           gtk.gdkgl.MODE_ALPHA     : "ALPHA",
                           gtk.gdkgl.MODE_DEPTH     : "DEPTH",
                           gtk.gdkgl.MODE_DOUBLE    : "DOUBLE",
                           gtk.gdkgl.MODE_SINGLE    : "SINGLE"}
    friendly_modes = [v for k,v in friendly_mode_names.items() if k>0 and (k&mode)==k]
    #special case for single (value is zero!)
    if not (mode&gtk.gdkgl.MODE_DOUBLE==gtk.gdkgl.MODE_DOUBLE):
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
def check_GL_support(gldrawable, glcontext, min_texture_size=0, force_enable=False):
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
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
            extensions = glGetString(GL_EXTENSIONS).split(" ")
        except:
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
        gldrawable.gl_end()

def check_support(min_texture_size=0, force_enable=False, check_colormap=False):
    #platform checks:
    from xpra.platform.gui import gl_check
    warning = gl_check()
    if warning:
        gl_check_error(warning)

    props = {}
    import gtk.gdk
    import gtk.gdkgl, gtk.gtkgl
    assert gtk.gdkgl is not None and gtk.gtkgl is not None
    log("pygdkglext version=%s", gtk.gdkgl.pygdkglext_version)
    props["pygdkglext_version"] = gtk.gdkgl.pygdkglext_version
    log("gtkglext_version=%s", gtk.gdkgl.gdkglext_version)
    props["gdkglext_version"] = gtk.gdkgl.gdkglext_version
    log("pygdkglext OpenGL version=%s", gtk.gdkgl.query_version())
    props["gdkgl_version"] = gtk.gdkgl.query_version()
    display_mode = get_DISPLAY_MODE()
    try:
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    except gtk.gdkgl.NoMatches as e:
        log("no match: %s, toggling double-buffering", e)
        display_mode &= ~gtk.gdkgl.MODE_DOUBLE
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    props["display_mode"] = get_MODE_names(display_mode)
    props["glconfig"] = glconfig
    props["has_alpha"] = glconfig.has_alpha()
    props["rgba"] = glconfig.is_rgba()
    log("GL props=%s", props)
    assert gtk.gdkgl.query_extension()
    glcontext, gldrawable, glext, w = None, None, None, None
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
        glarea = gtk.gtkgl.DrawingArea(glconfig)
        glarea.set_size_request(32, 32)
        vbox.add(glarea)
        vbox.show_all()
        w.add(vbox)
        #we don't need to actually show the window!
        #w.show_all()
        glarea.realize()
        gtk.gdk.window_process_all_updates()
        gldrawable = glarea.get_gl_drawable()
        glcontext = glarea.get_gl_context()

        gl_props = check_GL_support(gldrawable, glcontext, min_texture_size, force_enable)

        if check_colormap:
            rgb_visual = w.get_screen().get_rgb_visual()
            rgba_visual = w.get_screen().get_rgba_visual()
            gl_props["rgb_visual"] = visual_to_str(rgb_visual)
            gl_props["rgba_visual"] = visual_to_str(rgba_visual)
            #i = 0
            #for v in w.get_screen().list_visuals():
            #    gl_props["visual[%s]" % i] = visual_to_str(v)
            #    i += 1
    finally:
        if w:
            w.destroy()
        del glcontext, gldrawable, glext, glconfig
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
