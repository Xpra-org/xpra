# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.log import Logger
log = Logger()

from xpra.client_window import ClientWindow
from xpra.gl.gl_window_backing import GLPixmapBacking

import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None

from OpenGL.GL import GL_VERSION, glGetString
from OpenGL.GL.ARB.fragment_program import glInitFragmentProgramARB

#sanity checks: OpenGL version
try:
    from gtk import gdk
    glconfig = gtk.gdkgl.Config(mode=gtk.gdkgl.MODE_RGB|gtk.gdkgl.MODE_SINGLE)
    glext = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), 1, 1))
    gldrawable = glext.set_gl_capability(glconfig)
    glcontext = gtk.gdkgl.Context(gldrawable, direct=True)
    if not gldrawable.gl_begin(glcontext):
        raise ImportError("gl_begin failed on %s" % gldrawable)
    try:
        gl_major = int(glGetString(GL_VERSION)[0])
        gl_minor = int(glGetString(GL_VERSION)[2])
        if gl_major<=1 and gl_minor<1:
            raise ImportError("** OpenGL output requires OpenGL version 1.1 or greater, not %s.%s" % (gl_major, gl_minor))
        log("found valid OpenGL: %s.%s", gl_major, gl_minor)
        #this allows us to do CSC via OpenGL:
        #see http://www.opengl.org/registry/specs/ARB/fragment_program.txt
        if not glInitFragmentProgramARB():
            raise ImportError("** OpenGL output requires glInitFragmentProgramARB")
    finally:
        gldrawable.gl_end()
        del glcontext, gldrawable, glext, glconfig
except Exception, e:
    raise ImportError("** OpenGL initialization error: %s" % e)


class GLClientWindow(ClientWindow):

    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        log("GLClientWindow(..)")
        self._configured = False
        ClientWindow.__init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
        self.add(self._backing.glarea)

    def do_configure_event(self, event):
        log("GL do_configure_event(%s)", event)
        self._configured = True
        ClientWindow.do_configure_event(self, event)

    def new_backing(self, w, h):
        log("GL new_backing(%s, %s)", w, h)
        w = max(1, w)
        h = max(1, h)
        lock = None
        if self._backing:
            lock = self._backing._video_decoder_lock
        try:
            if lock:
                lock.acquire()
            if self._backing is None:
                self._backing = GLPixmapBacking(self._id, w, h, self._client.supports_mmap, self._client.mmap)
            if self._configured:
                self._backing.init(w, h)
        finally:
            if lock:
                lock.release()
