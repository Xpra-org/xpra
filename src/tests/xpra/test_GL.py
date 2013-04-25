#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def main():
    import pygtk
    pygtk.require('2.0')

    import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
    assert gtk.gdkgl is not None and gtk.gtkgl is not None

    print("loading OpenGL.GL")
    from OpenGL.GL import GL_VERSION, glGetString
    from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB

    glconfig = gtk.gdkgl.Config(mode=gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_DOUBLE | gtk.gdkgl.MODE_DEPTH)
    print("glconfig=%s" % glconfig)

    win = gtk.Window()
    win.set_title('test GL')

    glarea = gtk.gtkgl.DrawingArea(glconfig=glconfig, share_list=None, render_type=gtk.gdkgl.RGBA_TYPE)
    win.add(glarea)
    glarea.realize()

    glcontext = glarea.get_gl_context()
    print("glcontext=%s" % glcontext)

    pixmap = gtk.gdk.Pixmap(None, 120, 120, 24)
    print("pixmap=%s" % pixmap)
    glext = gtk.gdkgl.ext(pixmap)
    print("glext=%s" % glext)
    gldrawable = gtk.gdkgl.Pixmap(glconfig, pixmap)
    print("gldrawable=%s" % gldrawable)
    if gldrawable is None:
        raise ImportError("failed to initialize")
    glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    try:
        gl_major = int(glGetString(GL_VERSION)[0])
        gl_minor = int(glGetString(GL_VERSION)[2])
        if gl_major<=1 and gl_minor<1:
            raise ImportError("** OpenGL output requires OpenGL version 1.1 or greater, not %s.%s" % (gl_major, gl_minor))
        print("found valid OpenGL: %s.%s" % (gl_major, gl_minor))
        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        if not glInitFragmentProgramARB():
            raise ImportError("** OpenGL output requires glInitFragmentProgramARB")
    finally:
        gldrawable.gl_end()
        del glcontext, gldrawable, glext, glconfig


if __name__ == "__main__":
    main()
