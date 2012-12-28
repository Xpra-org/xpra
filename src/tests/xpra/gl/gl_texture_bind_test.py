#!/usr/bin/env python
# originaly found here: https://bitbucket.org/aalex/toonplayer
#
# Toonloop is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""
Testing OpenGL in a GTK Window.

This is quite long to startup, though.
"""
import pygtk
pygtk.require('2.0')
import gtk.gtkgl
import gtk.gdkgl
import gobject

from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, \
    GL_RGB, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE,  GL_QUADS, GL_LINES, GL_BLEND, GL_SMOOTH, \
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_UNPACK_ALIGNMENT, \
    glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, glFlush, \
    glTexCoord2f, glVertex2f, glTexParameterf, \
    glTexImage2D, \
    glClearColor, glColor4f, glBlendFunc, glShadeModel, \
    glPushMatrix, glScale, glPopMatrix, \
    glClear, \
    glEnd
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB

WIDTH = 640
HEIGHT = 480

def draw_square():
    """
    Draws a square of 2 x 2 size centered at 0, 0
    
    Make sure to call glDisable(GL_TEXTURE_RECTANGLE_ARB) first.
    """
    glBegin(GL_QUADS)
    glVertex2f(-1.0, -1.0) # Bottom Left of Quad
    glVertex2f(1.0, -1.0) # Bottom Right of Quad
    glVertex2f(1.0, 1.0) # Top Right Of Quad
    glVertex2f(-1.0, 1.0) # Top Left Of Quad
    glEnd()

def draw_textured_square(w=None, h=None):
    """
    Draws a texture square of 2 x 2 size centered at 0, 0
    
    Make sure to call glEnable(GL_TEXTURE_RECTANGLE_ARB) first.

    :param w: width of the image in pixels
    :param h: height of the image in pixels
    """
    if w is None or h is None:
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, 0.0)
        glVertex2f(-1.0, -1.0) # Bottom Left Of The Texture and Quad
        glTexCoord2f(1.0, 0.0)
        glVertex2f(1.0, -1.0) # Bottom Right Of The Texture and Quad
        glTexCoord2f(1.0, 1.0)
        glVertex2f(1.0, 1.0) # Top Right Of The Texture and Quad
        glTexCoord2f(0.0, 1.0)
        glVertex2f(-1.0, 1.0) # Top Left Of The Texture and Quad
        glEnd()
    else:
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, 0.0)
        glVertex2f(-1.0, -1.0) # Bottom Left
        glTexCoord2f(w, 0.0)
        glVertex2f(1.0, -1.0) # Bottom Right
        glTexCoord2f(w, h)
        glVertex2f(1.0, 1.0) # Top Right
        glTexCoord2f(0.0, h)
        glVertex2f(-1.0, 1.0) # Top Left
        glEnd()

def draw_line(from_x, from_y, to_x, to_y):
    """
    Draws a line between given points.
    """
    glBegin(GL_LINES)
    glVertex2f(from_x, from_y) 
    glVertex2f(to_x, to_y) 
    glEnd()

class GlDrawingArea(gtk.DrawingArea, gtk.gtkgl.Widget):
    """
    OpenGL drawing area for simple demo.
    
    OpenGL-capable gtk.DrawingArea by subclassing
    gtk.gtkgl.Widget mixin.
    """
    def __init__(self, glconfig):
        gtk.DrawingArea.__init__(self)
        self.set_gl_capability(glconfig)
        self.connect_after('realize', self._on_realize)
        self.connect('configure_event', self._on_configure_event)
        self.connect('expose_event', self._on_expose_event)
        self.texture_id = None

    def _on_realize(self, *args):
        """
        Called at the creation of the drawing area.

        Sets up the OpenGL rendering context.
        """
        gldrawable = self.get_gl_drawable()
        glcontext = self.get_gl_context()
        if not gldrawable.gl_begin(glcontext):
            return

        self._set_view(WIDTH / float(HEIGHT))

        glEnable(GL_TEXTURE_RECTANGLE_ARB) # 2D)
        glEnable(GL_BLEND)
        glShadeModel(GL_SMOOTH)
        glClearColor(0.0, 0.0, 0.0, 1.0) # black background
        glColor4f(1.0, 1.0, 1.0, 1.0) # default color is white
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        gldrawable.gl_end()

    def _set_view(self, ratio):
        """
        Sets up the orthographic projection.

        Height is always 1.0 in GL modelview coordinates.
        
        Coordinates should give a rendering area height of 1
        and a width of 1.33, when in 4:3 ratio.
        """
        w = ratio
        h = 1.

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(-w, w, -h, h, -1.0, 1.0)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def _on_configure_event(self, *args):
        """
        Called when the drawing area is resized.

        Sets up the OpenGL view port dimensions.
        """
        gldrawable = self.get_gl_drawable()
        glcontext = self.get_gl_context()
        if gldrawable is None:
            return False
        if not gldrawable.gl_begin(glcontext):
            return False
        glViewport(0, 0, self.allocation.width, self.allocation.height)
        ratio = self.allocation.width / float(self.allocation.height)
        self._set_view(ratio)
        if self.texture_id is None:
            self._create_texture()
        gldrawable.gl_end()
        return False

    def _on_expose_event(self, *args):
        """
        Called on every frame rendering of the drawing area.

        Calls self.draw() and swaps the buffers.
        """
        gldrawable = self.get_gl_drawable()
        glcontext = self.get_gl_context()
        if gldrawable is None:
            return False
        if not gldrawable.gl_begin(glcontext):
            return False
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        
        self.draw()

        if gldrawable.is_double_buffered():
            gldrawable.swap_buffers()
        else:
            glFlush()
        gldrawable.gl_end()
        return False
    
    def _create_texture(self):
        pixels = "\0" * 320 * 240 * 4
        w = 320
        h = 240
        
        # Create Texture
        tex_id = glGenTextures(1)
        print("glBindTexture(GL_TEXTURE_RECTANGLE_ARB)")
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, tex_id)
        print("done")

        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0,
                     GL_RGB, GL_UNSIGNED_BYTE, pixels)
        glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        self.texture_id = tex_id

    def draw(self):
        """
        Draws each frame.
        """
        # DRAW STUFF HERE
        glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glColor4f(1.0, 0.8, 0.2, 1.0)
        glPushMatrix()
        glScale(0.5, 0.5, 1.0)
        draw_square()
        glPopMatrix()

        glColor4f(1.0, 1.0, 0.0, 0.8)
        num = 64
        for i in range(num):
            x = (i / float(num)) * 4 - 2
            draw_line(float(x), -2.0, float(x), 2.0)
            draw_line(-2.0, float(x), 2.0, float(x))

        if self.texture_id is not None:
            glColor4f(1.0, 1.0, 1.0, 1.0)
            glEnable(GL_TEXTURE_RECTANGLE_ARB)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.texture_id)
            glPushMatrix()
            glScale(0.4, 0.3, 1.0)
            draw_textured_square(320, 240)
            glPopMatrix()
        else:
            print "No texture to draw"


class App(object):
    """
    Main window of the application.
    """
    def __init__(self):
        """
        Creates the drawing area and other widgets.
        """
        self.window = gtk.Window()
        self.window.set_title('Testing OpenGL')
        self.window.set_reallocate_redraws(True)
        self.window.connect('delete_event', self.on_delete_event)
        self.actual_size = (WIDTH, HEIGHT) # should actually be bigger
        # Query the OpenGL extension version.
        print "OpenGL extension version - %d.%d\n" % gtk.gdkgl.query_version()
        # Configure OpenGL framebuffer.
        # Try to get a double-buffered framebuffer configuration,
        # if not successful then try to get a single-buffered one.
        display_mode = (
            gtk.gdkgl.MODE_RGB |
            gtk.gdkgl.MODE_DEPTH |
            gtk.gdkgl.MODE_DOUBLE
            )
        try:
            glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches:
            display_mode &= ~gtk.gdkgl.MODE_DOUBLE
            glconfig = gtk.gdkgl.Config(mode=display_mode)
        print("is RGBA:", glconfig.is_rgba())
        print("is double-buffered:", glconfig.is_double_buffered())
        print("is stereo:", glconfig.is_stereo())
        print("has alpha:", glconfig.has_alpha())
        print("has depth buffer:", glconfig.has_depth_buffer())
        print("has stencil buffer:", glconfig.has_stencil_buffer())
        print("has accumulation buffer:", glconfig.has_accum_buffer())
        # Drawing Area
        self.drawing_area = GlDrawingArea(glconfig)
        self.drawing_area.set_size_request(WIDTH, HEIGHT)
        self.window.add(self.drawing_area)
        self.drawing_area.show()
        self.window.show() # not show_all() !

        gobject.timeout_add(1000, self.update_image)

    def update_image(self, *args):
        import random
        pixels = chr(int(random.random()*256.0))*WIDTH*HEIGHT*4
        self._update_texture(WIDTH, HEIGHT, pixels)
        return True

    def _update_texture(self, w, h, pixels):
        print("update_texture id=%s", self.drawing_area.texture_id)
        if self.drawing_area.texture_id is not None:
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.drawing_area.texture_id)

            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, w, h, 0,
                GL_RGB, GL_UNSIGNED_BYTE, pixels)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameterf(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
 
    def on_delete_event(self, widget, event=None):
        """
        Closing the window quits.
        """
        gtk.main_quit()


if __name__ == '__main__':
    print "screen is %sx%s" % (gtk.gdk.screen_width(), gtk.gdk.screen_height())
    app = App()
    gtk.main()
