#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gdk

import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None

#trick to get py2exe to include what we need:
import sys
if sys.platform.startswith("win"):
    print("has frozen: %s" % hasattr( sys, "frozen" ))
    if hasattr( sys, "frozen" ):
        print("frozen: %s" % sys.frozen)
        if sys.frozen in ("windows_exe", "console_exe"):
            import os
            main_dir = os.path.dirname( unicode( sys.executable, sys.getfilesystemencoding() ) )
            print("main_dir=%s" % main_dir)
            sys.path.insert( 0, main_dir )
            os.chdir( main_dir )
        else:
            sys.path.insert(0, ".")
    from ctypes import util             #@UnusedImport
    print("ctypes loaded")
    from OpenGL.platform import win32   #@UnusedImport
    print("OpenGL.platform loaded")
    #import OpenGL_accelerate            #@UnusedImport @UnresolvedImport

print("loading OpenGL.GL")
from OpenGL.GL import GL_VERSION, glGetString
from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB

glconfig = gtk.gdkgl.Config(mode=gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_DOUBLE | gtk.gdkgl.MODE_DEPTH)
print("glconfig=%s" % glconfig)
pixmap = gdk.Pixmap(gdk.get_default_root_window(), 1, 1)
print("pixmap=%s" % glconfig)
glext = gtk.gdkgl.ext(pixmap)
print("glext=%s" % glext)
gldrawable = glext.set_gl_capability(glconfig)
print("set_gl_capability gldrawable=%s" % gldrawable)
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
