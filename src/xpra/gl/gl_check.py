#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
from wimpiggy.log import Logger
log = Logger()

#sanity checks: OpenGL version and fragment program support:
def check_GL_support(gldrawable, glcontext):
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    try:
        from OpenGL.GL import GL_VERSION, GL_EXTENSIONS
        from OpenGL.GL import glGetString
        gl_major = int(glGetString(GL_VERSION)[0])
        gl_minor = int(glGetString(GL_VERSION)[2])
        MIN_VERSION = (1,1)
        if (gl_major, gl_minor) < MIN_VERSION:
            raise ImportError("** OpenGL output requires OpenGL version %s or greater, not %s.%s" %
                              (".".join([str(x) for x in MIN_VERSION]), gl_major, gl_minor))
        log("found valid OpenGL version: %s.%s", gl_major, gl_minor)
        log("OpenGL extensions found: %s", glGetString(GL_EXTENSIONS))

        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB
        if not glInitFragmentProgramARB():
            raise ImportError("OpenGL output requires glInitFragmentProgramARB")
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

    from gtk import gdk
    import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
    assert gtk.gdkgl is not None and gtk.gtkgl is not None
    log("pygdkglext version=%s", gtk.gdkgl.pygdkglext_version)
    log("pygdkglext OpenGL version=%s", gtk.gdkgl.query_version())
    display_mode = (gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_DEPTH | gtk.gdkgl.MODE_DOUBLE)
    try:
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    except gtk.gdkgl.NoMatches:
        display_mode &= ~gtk.gdkgl.MODE_DOUBLE
        glconfig = gtk.gdkgl.Config(mode=display_mode)
    log("using display mode: %s", display_mode)
    assert gtk.gdkgl.query_extension()
    if sys.platform.startswith("win"):
        #FIXME: ugly win32 hack for getting a drawable and context, we must use a window...
        w = gtk.Window()
        glarea = gtk.gtkgl.DrawingArea(glconfig)
        glarea.show()
        w.add(glarea)
        w.show()
        gldrawable = glarea.get_gl_drawable()
        glcontext = glarea.get_gl_context()
        try:
            check_GL_support(gldrawable, glcontext)
        finally:
            w.destroy()
            del glcontext, gldrawable, glconfig
    else:
        glext = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), 1, 1))
        gldrawable = glext.set_gl_capability(glconfig)
        glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
        try:
            check_GL_support(gldrawable, glcontext)
        finally:
            del glcontext, gldrawable, glext, glconfig


def main():
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.DEBUG)
    check_support()


if __name__ == "__main__":
    main()
