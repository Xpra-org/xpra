#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
from wimpiggy.log import Logger
log = Logger()

required_extensions = ["GL_ARB_texture_rectangle", "GL_ARB_vertex_program"]

#by default, we raise an ImportError as soon as we find something missing:
def raise_error(msg):
    raise ImportError(msg)
gl_check_error = raise_error


def check_functions(*functions):
    for x in functions:
        try:
            name = x.__name__
        except:
            name = str(x)
        if not bool(x):
            gl_check_error("required function %s is not available" % name)
        else:
            log("Function %s is available" % name)

#sanity checks: OpenGL version and fragment program support:
def check_GL_support(gldrawable, glcontext):
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    props = {}
    try:
        from OpenGL.GL import GL_VERSION, GL_EXTENSIONS
        from OpenGL.GL import glGetString
        gl_major = int(glGetString(GL_VERSION)[0])
        gl_minor = int(glGetString(GL_VERSION)[2])
        MIN_VERSION = (1,1)
        if (gl_major, gl_minor) < MIN_VERSION:
            gl_check_error("OpenGL output requires version %s or greater, not %s.%s" %
                              (".".join([str(x) for x in MIN_VERSION]), gl_major, gl_minor))
        else:
            log("found valid OpenGL version: %s.%s", gl_major, gl_minor)
        extensions = glGetString(GL_EXTENSIONS).split(" ")
        log("OpenGL extensions found: %s", ", ".join(extensions))
        props["extensions"] = extensions

        from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_SHADING_LANGUAGE_VERSION
        for d,s in {"vendor":GL_VENDOR, "renderer":GL_RENDERER,
                    "shading language version":GL_SHADING_LANGUAGE_VERSION}.items():
            v = glGetString(s)
            log("%s: %s", d, v)
            props[d] = v

        from OpenGL.GLU import gluGetString, GLU_VERSION, GLU_EXTENSIONS
        for d,s in {"GLU version": GLU_VERSION, "GLU extensions":GLU_EXTENSIONS}.items():
            v = gluGetString(s)
            log("%s: %s", d, v)
            props[d] = v

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

        from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glDeleteProgramsARB, \
            glBindProgramARB, glProgramStringARB
        check_functions(glGenProgramsARB, glDeleteProgramsARB, glBindProgramARB, glProgramStringARB)

        return props
    finally:
        gldrawable.gl_end()

def check_support():
    #tricks to get py2exe to include what we need / load it from its unusual path:
    if sys.platform.startswith("win"):
        log("is frozen: %s", hasattr(sys, "frozen"))
        if hasattr(sys, "frozen"):
            log("found frozen path: %s", sys.frozen)
            if sys.frozen in ("windows_exe", "console_exe"):
                main_dir = os.path.dirname(unicode(sys.executable, sys.getfilesystemencoding()))
                log("main_dir=%s", main_dir)
                sys.path.insert(0, main_dir)
                os.chdir(main_dir)
            else:
                sys.path.insert(0, ".")
        #This is supposed to help py2exe (after we setup the path):
        from OpenGL.platform import win32   #@UnusedImport

    props = {}
    from gtk import gdk
    import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
    assert gtk.gdkgl is not None and gtk.gtkgl is not None
    log("pygdkglext version=%s", gtk.gdkgl.pygdkglext_version)
    props["pygdkglext_version"] = gtk.gdkgl.pygdkglext_version
    log("pygdkglext OpenGL version=%s", gtk.gdkgl.query_version())
    props["gdkgl_version"] = gtk.gdkgl.query_version()
    display_mode = (gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_DEPTH | gtk.gdkgl.MODE_DOUBLE)
    try:
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    except gtk.gdkgl.NoMatches:
        display_mode &= ~gtk.gdkgl.MODE_DOUBLE
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    friendly_mode_names = {gtk.gdkgl.MODE_RGB : "RGB", gtk.gdkgl.MODE_DEPTH:"DEPTH",
                           gtk.gdkgl.MODE_DOUBLE : "DOUBLE"}
    friendly_modes = [v for k,v in friendly_mode_names.items() if (k&display_mode)==k]
    log("using display mode: %s", friendly_modes)
    props["display_mode"] = friendly_modes
    props["glconfig"] = glconfig
    assert gtk.gdkgl.query_extension()
    if sys.platform.startswith("win"):
        #FIXME: ugly win32 hack for getting a drawable and context, we must use a window...
        w = gtk.Window()
        glarea = gtk.gtkgl.DrawingArea(glconfig)
        glarea.show()
        w.add(glarea)
        w.show()
        w.process_updates(True)
        #gtk.gdk.window_process_all_updates()
        gldrawable = glarea.get_gl_drawable()
        glcontext = glarea.get_gl_context()
        try:
            gl_props = check_GL_support(gldrawable, glcontext)
        finally:
            w.destroy()
            del glcontext, gldrawable, glconfig
    else:
        glext = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), 1, 1))
        gldrawable = glext.set_gl_capability(glconfig)
        glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
        try:
            gl_props = check_GL_support(gldrawable, glcontext)
        finally:
            del glcontext, gldrawable, glext, glconfig
    props.update(gl_props)
    return props


def main():
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.DEBUG)
    #replace ImportError with a log message:
    global gl_check_error
    def log_error(msg):
        log.error("ERROR: %s", msg)
    gl_check_error = log_error
    check_support()
    if sys.platform.startswith("win"):
        print("\nPress Enter to close")
        sys.stdin.readline()


if __name__ == "__main__":
    main()
