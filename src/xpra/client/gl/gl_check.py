#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import logging
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_OPENGL_DEBUG")

required_extensions = ["GL_ARB_texture_rectangle", "GL_ARB_vertex_program"]

#warnings seem unavoidable on win32, so silence them
#(other platforms should fix their packages instead)
SILENCE_FORMAT_HANDLER_LOGGER = sys.platform.startswith("win") or sys.platform.startswith("darwin")

BLACKLIST = {"vendor" : ["nouveau", "Humper"]}

DEFAULT_HAS_ALPHA = not sys.platform.startswith("win") and not sys.platform.startswith("darwin")
HAS_ALPHA = os.environ.get("XPRA_ALPHA", DEFAULT_HAS_ALPHA) in (True, "1")
DEFAULT_DOUBLE_BUFFERED = 0
if sys.platform.startswith("win"):
    #needed on win32?
    DEFAULT_DOUBLE_BUFFERED = 1
DOUBLE_BUFFERED = os.environ.get("XPRA_OPENGL_DOUBLE_BUFFERED", str(DEFAULT_DOUBLE_BUFFERED))=="1"


def get_DISPLAY_MODE():
    import gtk.gdkgl
    #gtk.gdkgl.MODE_DEPTH
    mode = 0
    if HAS_ALPHA:
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
                           gtk.gdkgl.MODE_RGB       : "RGBA",
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

if sys.version > '3':
    unicode = str           #@ReservedAssignment


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
        debug("All the required OpenGL functions are available: %s " % (", ".join(available)))

#sanity checks: OpenGL version and fragment program support:
def check_GL_support(gldrawable, glcontext, min_texture_size=0, force_enable=False):
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    props = {}
    try:
        if SILENCE_FORMAT_HANDLER_LOGGER:
            debug("silencing formathandler warnings")
            logging.getLogger('OpenGL.formathandler').setLevel(logging.WARN)
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
            debug("found valid OpenGL version: %s.%s", gl_major, gl_minor)
        try:
            extensions = glGetString(GL_EXTENSIONS).split(" ")
        except:
            gl_check_error("OpenGL could not find the list of GL extensions - does the graphics driver support OpenGL?")
        debug("OpenGL extensions found: %s", ", ".join(extensions))
        props["extensions"] = extensions

        from OpenGL.arrays.arraydatatype import ArrayDatatype
        try:
            debug("found the following array handlers: %s", set(ArrayDatatype.getRegistry().values()))
        except:
            pass

        from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_SHADING_LANGUAGE_VERSION
        for d,s,fatal in (("vendor",     GL_VENDOR,      True),
                          ("renderer",   GL_RENDERER,    True),
                          ("shading language version", GL_SHADING_LANGUAGE_VERSION, False)):
            try:
                v = glGetString(s)
                debug("%s: %s", d, v)
            except:
                if fatal:
                    gl_check_error("OpenGL property '%s' is missing" % d)
                else:
                    log.warn("OpenGL property '%s' is missing" % d)
                v = ""
            props[d] = v

        from OpenGL.GLU import gluGetString, GLU_VERSION, GLU_EXTENSIONS
        for d,s in {"GLU version": GLU_VERSION, "GLU extensions":GLU_EXTENSIONS}.items():
            v = gluGetString(s)
            debug("%s: %s", d, v)
            props[d] = v

        for k,vlist in BLACKLIST.items():
            v = props.get(k)
            if v in vlist:
                if force_enable:
                    log.warn("Warning: %s '%s' is blacklisted!", k, v)
                else:
                    gl_check_error("%s '%s' is blacklisted!" % (k, v))

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

        #check for framebuffer functions we need:
        from OpenGL.GL.ARB.framebuffer_object import GL_FRAMEBUFFER, \
            GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D
        check_functions(GL_FRAMEBUFFER, \
            GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D)

        for ext in required_extensions:
            if ext not in extensions:
                gl_check_error("OpenGL driver lacks support for extension: %s" % ext)
            else:
                debug("Extension %s is present", ext)

        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB
        if not glInitFragmentProgramARB():
            gl_check_error("OpenGL output requires glInitFragmentProgramARB")
        else:
            debug("glInitFragmentProgramARB works")

        from OpenGL.GL.ARB.texture_rectangle import glInitTextureRectangleARB
        if not glInitTextureRectangleARB():
            gl_check_error("OpenGL output requires glInitTextureRectangleARB")
        else:
            debug("glInitTextureRectangleARB works")

        from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glDeleteProgramsARB, \
            glBindProgramARB, glProgramStringARB
        check_functions(glGenProgramsARB, glDeleteProgramsARB, glBindProgramARB, glProgramStringARB)

        from OpenGL.GL import GL_MAX_RECTANGLE_TEXTURE_SIZE, GL_MAX_TEXTURE_SIZE
        texture_size = glGetInteger(GL_MAX_TEXTURE_SIZE)
        rect_texture_size = glGetInteger(GL_MAX_RECTANGLE_TEXTURE_SIZE)
        if min_texture_size>texture_size or min_texture_size>rect_texture_size:
            gl_check_error("The texture size is too small: %s" % texture_size)
        else:
            debug("Texture size GL_MAX_RECTANGLE_TEXTURE_SIZE_ARB=%s, GL_MAX_TEXTURE_SIZE=%s", rect_texture_size, texture_size)
        return props
    finally:
        if SILENCE_FORMAT_HANDLER_LOGGER:
            try:
                logging.getLogger('OpenGL.formathandler').setLevel(logging.INFO)
            except:
                pass
        gldrawable.gl_end()

def check_support(min_texture_size=0, force_enable=False):
    try:
        from xpra.platform.paths import get_icon_dir
        opengl_icon = os.path.join(get_icon_dir(), "opengl.png")
    except:
        opengl_icon = None
    #tricks to get py2exe to include what we need / load it from its unusual path:
    if sys.platform.startswith("win"):
        #This is supposed to help py2exe
        #(must be done after we setup the sys.path in platform.win32.paths):
        from OpenGL.platform import win32   #@UnusedImport

    props = {}
    import gtk.gdk
    import gtk.gdkgl, gtk.gtkgl
    assert gtk.gdkgl is not None and gtk.gtkgl is not None
    debug("pygdkglext version=%s", gtk.gdkgl.pygdkglext_version)
    props["pygdkglext_version"] = gtk.gdkgl.pygdkglext_version
    debug("pygdkglext OpenGL version=%s", gtk.gdkgl.query_version())
    props["gdkgl_version"] = gtk.gdkgl.query_version()
    display_mode = get_DISPLAY_MODE()
    try:
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    except gtk.gdkgl.NoMatches, e:
        debug("no match: %s, toggling double-buffering", e)
        display_mode &= ~gtk.gdkgl.MODE_DOUBLE
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    props["display_mode"] = get_MODE_names(display_mode)
    props["glconfig"] = glconfig
    props["has_alpha"] = glconfig.has_alpha()
    props["rgba"] = glconfig.is_rgba()
    debug("GL props=%s", props)
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
        width, height = 32, 32
        if opengl_icon and os.path.exists(opengl_icon):
            pixbuf = gtk.gdk.pixbuf_new_from_file(opengl_icon)
            image = gtk.image_new_from_pixbuf(pixbuf)
            vbox.add(image)
            width, height = pixbuf.get_width(), pixbuf.get_height()
            w.set_default_size(width, height)
            w.set_resizable(False)
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
    finally:
        if w:
            w.destroy()
        del glcontext, gldrawable, glext, glconfig
    props.update(gl_props)
    return props


def main():
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.DEBUG)
    #replace ImportError with a log message:
    global gl_check_error
    def log_error(msg):
        log.error("ERROR: %s", msg)
    gl_check_error = log_error
    check_support(True)
    if sys.platform.startswith("win"):
        print("\nPress Enter to close")
        sys.stdin.readline()


if __name__ == "__main__":
    main()
