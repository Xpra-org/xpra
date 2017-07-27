#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import logging
from xpra.util import envbool
from xpra.os_util import OSX, WIN32, PYTHON3
from xpra.log import Logger, CaptureHandler
log = Logger("opengl")

required_extensions = ["GL_ARB_texture_rectangle", "GL_ARB_vertex_program"]


WHITELIST = {
    "renderer"  : ["Haswell", "Skylake", "Kabylake", "Cannonlake"],
    }
GREYLIST = {
            "vendor"    : ["Intel", "Humper"]
            }
VERSION_REQ = {
               "nouveau" : [3, 0],      #older versions have issues
               }
BLACKLIST = {
             "renderer" : ["Software Rasterizer", "Mesa DRI Intel(R) Ivybridge Desktop"],
             "vendor"    : ["VMware, Inc."]
             }

from xpra.os_util import getUbuntuVersion
uv = getUbuntuVersion()
if uv and uv<[15]:
    #Ubuntu 14.x drivers are just too old
    GREYLIST.setdefault("vendor", []).append("X.Org")
if False:
    #for testing:
    GREYLIST["vendor"].append("NVIDIA Corporation")
    WHITELIST["renderer"] = ["GeForce GTX 760/PCIe/SSE2"]

    if OSX:
        #frequent crashes on osx with GT 650M: (see ticket #808)
        GREYLIST.setdefault("vendor", []).append("NVIDIA Corporation")


#alpha requires gtk3 or *nix only for gtk2:
DEFAULT_ALPHA = PYTHON3 or (not WIN32 and not OSX)
GL_ALPHA_SUPPORTED = envbool("XPRA_ALPHA", DEFAULT_ALPHA)
#not working with gtk3 yet?
CAN_DOUBLE_BUFFER = not PYTHON3
#needed on win32?:
DEFAULT_DOUBLE_BUFFERED = WIN32 or CAN_DOUBLE_BUFFER
DOUBLE_BUFFERED = envbool("XPRA_OPENGL_DOUBLE_BUFFERED", DEFAULT_DOUBLE_BUFFERED)

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

from xpra.client.gl.gtk_compat import MODE_RGBA, MODE_ALPHA, MODE_RGB, MODE_DOUBLE, MODE_SINGLE, MODE_DEPTH


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


#by default, we raise an ImportError as soon as we find something missing:
def raise_error(msg):
    raise ImportError(msg)
gl_check_error = raise_error


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
    from xpra.client.gl.gtk_compat import GLContextManager
    with GLContextManager(widget):
        return do_check_GL_support(force_enable)

def do_check_GL_support(force_enable):
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
        from OpenGL.GL import glGetString, glGetInteger, glGetIntegerv
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

        from OpenGL import version as OpenGL_version
        pyopengl_version = OpenGL_version.__version__
        try:
            import OpenGL_accelerate            #@UnresolvedImport
            accel_version = OpenGL_accelerate.__version__
            props["accelerate"] = accel_version
            log("OpenGL_accelerate version %s", accel_version)
        except:
            log("OpenGL_accelerate not found")
            OpenGL_accelerate = None
            accel_version = None

        if accel_version is not None and pyopengl_version!=accel_version:
            global _version_warning_shown
            if not _version_warning_shown:
                log.warn("Warning: version mismatch between PyOpenGL and PyOpenGL-accelerate")
                log.warn(" this may cause crashes")
                _version_warning_shown = True
        vsplit = pyopengl_version.split('.')
        #we now require PyOpenGL 3.1 or later
        if vsplit[:3]<['3','1'] and not force_enable:
            gl_check_error("PyOpenGL version %s is too old and buggy" % pyopengl_version)
            return {}
        props["zerocopy"] = bool(OpenGL_accelerate) and is_pyopengl_memoryview_safe(pyopengl_version, accel_version)

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
        def fixstring(v):
            try:
                return str(v).strip()
            except:
                return str(v)
        for d,s,fatal in (("vendor",     GL_VENDOR,      True),
                          ("renderer",   GL_RENDERER,    True),
                          ("shading-language-version", GL_SHADING_LANGUAGE_VERSION, False)):
            try:
                v = glGetString(s)
                v = fixstring(v.decode())
                log("%s: %s", d, v)
            except:
                if fatal:
                    gl_check_error("OpenGL property '%s' is missing" % d)
                else:
                    log("OpenGL property '%s' is missing", d)
                v = ""
            props[d] = v
        vendor = props["vendor"]
        version_req = VERSION_REQ.get(vendor)
        if version_req:
            req_maj, req_min = version_req
            if gl_major<req_maj or (gl_major==req_maj and gl_minor<req_min):
                if force_enable:
                    log.warn("Warning: '%s' OpenGL driver requires version %i.%i", vendor, req_maj, req_min)
                    log.warn(" version %i.%i was found", gl_major, gl_minor)
                else:
                    gl_check_error("OpenGL version %i.%i is too old, %i.%i is required for %s" % (gl_major, gl_minor, req_maj, req_min, vendor))

        from OpenGL.GLU import gluGetString, GLU_VERSION, GLU_EXTENSIONS
        for d,s in {"GLU.version": GLU_VERSION, "GLU.extensions":GLU_EXTENSIONS}.items():
            v = gluGetString(s)
            v = v.decode()
            log("%s: %s", d, v)
            props[d] = v

        def match_list(thelist, listname):
            for k,vlist in thelist.items():
                v = props.get(k)
                matches = [x for x in vlist if v.find(x)>=0]
                if matches:
                    log("%s '%s' found in %s: %s", k, v, listname, vlist)
                    return (k, v)
                log("%s '%s' not found in %s: %s", k, v, listname, vlist)
            return None
        blacklisted = match_list(BLACKLIST, "blacklist")
        greylisted = match_list(GREYLIST, "greylist")
        whitelisted = match_list(WHITELIST, "whitelist")
        if blacklisted:
            if whitelisted:
                log.info("%s '%s' enabled (found in both blacklist and whitelist)", *whitelisted)
            elif force_enable:
                log.warn("Warning: %s '%s' is blacklisted!", *blacklisted)
            else:
                gl_check_error("%s '%s' is blacklisted!" % (blacklisted))
        safe = bool(whitelisted) or not bool(blacklisted)
        if safe and PYTHON3:
            log.warn("Warning: OpenGL python3 support is not enabled by default")
            safe = False
        if greylisted and not whitelisted:
            log.warn("Warning: %s '%s' is greylisted,", *greylisted)
            log.warn(" you may want to turn off OpenGL if you encounter bugs")
        props["safe"] = safe

        #check for specific functions we need:
        from OpenGL.GL import glActiveTexture, glTexSubImage2D, glTexCoord2i, \
            glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
            glEnableClientState, glGenTextures, glDisable, \
            glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
            glTexParameteri, glTexEnvi, glHint, glBlendFunc, glLineStipple, \
            glTexImage2D, \
            glMultiTexCoord2i, \
            glVertex2i, glEnd
        check_functions(glActiveTexture, glTexSubImage2D, glTexCoord2i, \
            glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
            glEnableClientState, glGenTextures, glDisable, \
            glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
            glTexParameteri, glTexEnvi, glHint, glBlendFunc, glLineStipple, \
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
        props["transparency"] = GL_ALPHA_SUPPORTED

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

        log("Texture size GL_MAX_RECTANGLE_TEXTURE_SIZE=%s, GL_MAX_TEXTURE_SIZE=%s", rect_texture_size, texture_size)
        texture_size_limit = min(rect_texture_size, texture_size)
        props["texture-size-limit"] = texture_size_limit

        try:
            from OpenGL.GL import GL_MAX_VIEWPORT_DIMS
            v = glGetIntegerv(GL_MAX_VIEWPORT_DIMS)
            max_viewport_dims = v[0], v[1]
            assert max_viewport_dims[0]>=texture_size_limit and max_viewport_dims[1]>=texture_size_limit
            log("GL_MAX_VIEWPORT_DIMS=%s", max_viewport_dims)
        except ImportError as e:
            log.error("Error querying max viewport dims: %s", e)
            max_viewport_dims = texture_size_limit, texture_size_limit
        props["max-viewport-dims"] = max_viewport_dims
        return props
    finally:
        for x in alogger.handlers[0].records:
            #strip default message prefix:
            msg = x.getMessage().replace("No OpenGL_accelerate module loaded: ", "")
            if msg=="No module named OpenGL_accelerate":
                msg = "missing accelerate module"
            if msg=="OpenGL_accelerate module loaded":
                log.info(msg)
            else:
                log.warn("PyOpenGL warning: %s", msg)

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
            elif msg.startswith("Using accelerated"):
                log(msg)
            else:
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
        from xpra.client.gl.gtk_compat import get_info, gdkgl, Config_new_by_mode, GLDrawingArea
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
