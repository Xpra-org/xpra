# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.os_util import OSX, POSIX, monotonic_time
from xpra.util import envbool
from xpra.log import Logger
log = Logger("opengl")
fpslog = Logger("opengl", "fps")

HIGH_BIT_DEPTH = envbool("XPRA_HIGH_BIT_DEPTH", True)
FORCE_HIGH_BIT_DEPTH = envbool("XPRA_FORCE_HIGH_BIT_DEPTH", False)


from xpra.gtk_common.gtk_util import is_realized
from xpra.gtk_common.gobject_compat import import_glib
glib = import_glib()

from xpra.gtk_common.gtk_util import POINTER_MOTION_MASK, POINTER_MOTION_HINT_MASK
from xpra.client.gl.gl_window_backing_base import GLWindowBackingBase
from xpra.client.gl.gtk_base.gtk_compat import Config_new_by_mode, MODE_DOUBLE, GtkGLExtContext, GLDrawingArea
from xpra.client.gl.gtk_base.gtkgl_check import get_DISPLAY_MODE
from xpra.client.gl.gl_check import GL_ALPHA_SUPPORTED, CAN_DOUBLE_BUFFER


class GTKGLWindowBackingBase(GLWindowBackingBase):

    def idle_add(self, *args, **kwargs):
        glib.idle_add(*args, **kwargs)

    def init_gl_config(self, window_alpha):
        #setup gl config:
        alpha = GL_ALPHA_SUPPORTED and window_alpha
        display_mode = get_DISPLAY_MODE(want_alpha=alpha)
        self.glconfig = Config_new_by_mode(display_mode)
        if self.glconfig is None and CAN_DOUBLE_BUFFER:
            log("trying to toggle double-buffering")
            display_mode &= ~MODE_DOUBLE
            self.glconfig = Config_new_by_mode(display_mode)
        if not self.glconfig:
            raise Exception("cannot setup an OpenGL context")

    def is_double_buffered(self):
        return self.glconfig.is_double_buffered()


    def init_backing(self):
        self._backing = GLDrawingArea(self.glconfig)
        #must be overriden in subclasses to setup self._backing
        assert self._backing
        log("init_backing() backing=%s, alpha_enabled=%s", self._backing, self._alpha_enabled)
        if self._alpha_enabled:
            assert GL_ALPHA_SUPPORTED, "BUG: cannot enable alpha if GL backing does not support it!"
            screen = self._backing.get_screen()
            rgba = screen.get_rgba_colormap()
            display = screen.get_display()
            if not display.supports_composite() and not OSX:
                log.warn("display %s does not support compositing, transparency disabled", display.get_name())
                self._alpha_enabled = False
            elif rgba:
                log("%s.__init__() using rgba colormap %s", self, rgba)
                self._backing.set_colormap(rgba)
            else:
                log.warn("Warning: failed to enable transparency, no RGBA colormap")
                self._alpha_enabled = False
        self._backing.set_events(self._backing.get_events() | POINTER_MOTION_MASK | POINTER_MOTION_HINT_MASK)

    def get_bit_depth(self, pixel_depth=0):
        gl_depth = self.glconfig.get_depth()
        log("get_bit_depth() glconfig depth=%i, HIGH_BIT_DEPTH=%s, requested pixel depth=%i", gl_depth, HIGH_BIT_DEPTH, pixel_depth)
        bit_depth = 24
        if HIGH_BIT_DEPTH:
            if pixel_depth==0:
                #auto detect
                if POSIX and gl_depth>=24:
                    bit_depth = gl_depth
            elif pixel_depth>0:
                bit_depth = pixel_depth
        log("get_bit_depth()=%i", bit_depth)
        return bit_depth

    def gl_context(self):
        b = self._backing
        if not b:
            log("cannot get an OpenGL context: no backing defined")
            return None
        if not is_realized(b):
            log.error("Error: OpenGL backing %s is not realized", b)
            return None
        w, h = self.size
        if w<=0 or h<=0:
            log.error("Error: invalid OpenGL backing size: %ix%i", w, h)
            return None
        try:
            context = GtkGLExtContext(b)
        except Exception as e:
            log.error("Error: %s", e)
            return None
        log("%s.gl_context() GL Pixmap backing size: %d x %d, context=%s", self, w, h, context)
        return context

    def gl_show(self, rect_count):
        start = monotonic_time()
        if self.glconfig.is_double_buffered():
            # Show the backbuffer on screen
            log("%s.gl_show() swapping buffers now", self)
            gldrawable = self.get_gl_drawable()
            gldrawable.swap_buffers()
        else:
            #glFlush was enough
            pass
        end = monotonic_time()
        flush_elapsed = end-self.last_flush
        self.last_flush = end
        fpslog("gl_show after %3ims took %2ims, %2i updates", flush_elapsed*1000, (end-start)*1000, rect_count)

    def close(self):
        GLWindowBackingBase.close(self)
        self.glconfig = None
