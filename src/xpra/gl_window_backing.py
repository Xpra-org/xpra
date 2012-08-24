# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gobject, import_gdk
gobject = import_gobject()
gdk = import_gdk()

import gtk.gdkgl
import cairo

from wimpiggy.log import Logger
log = Logger()

from xpra.window_backing import PixmapBacking, Backing
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_FRAGMENT_PROGRAM_ARB, \
    GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, \
    GL_TEXTURE_RECTANGLE_ARB, GL_UNPACK_ROW_LENGTH, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_RGB, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, \
    GL_UNPACK_ALIGNMENT, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE, \
    glActiveTexture, glClientActiveTexture, glTexEnvi, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glGenTextures, \
    glBindTexture, glPixelStorei, glEnable, glBegin, \
    glTexParameteri, glVertexPointeri, glTexCoordPointeri, \
    glTexImage2D, glTexCoord2i, \
    glDrawArrays, glMultiTexCoord2i, \
    glVertex2i, glEnd, glFinish
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glBindProgramARB, glProgramStringARB

"""
This is the gtk2 + OpenGL version.
"""
class GLPixmapBacking(PixmapBacking):

    def __init__(self, wid, w, h, old_backing, mmap_enabled, mmap):
        Backing.__init__(self, wid, mmap_enabled, mmap)
        display_mode = (gtk.gdkgl.MODE_RGB    |
                        gtk.gdkgl.MODE_SINGLE)
# We use single buffer because double doesn't work, figure out why
        try:
            self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        except gtk.gdkgl.NoMatches, e:
            raise Exception("could not find matching mode for %s: %s" % (display_mode, e))
        self._backing = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), w, h))
        log.info("Creating GL pixmap size %d %d " % (w, h))
        self.gldrawable = self._backing.set_gl_capability(self.glconfig)
        log.info("drawable ok")
        # Then create an indirect OpenGL rendering context.
        self.glcontext = gtk.gdkgl.Context(self.gldrawable,
                                               direct=True)
        log.info("context ok")
        if not self.glcontext:
            raise Exception("** Cannot create OpenGL rendering context!")
        log.info("OpenGL rendering context is created.")
        self.texture = None
        self.textures = [ 0 ]
        self.use_openGL_CSC = True
        self.yuv420_shader = None

        # OpenGL begin
        if not self.gldrawable.gl_begin(self.glcontext):
            return False

        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0.0, w, h, 0.0, -1.0, 1.0);
        glMatrixMode(GL_MODELVIEW)
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_TEXTURE_COORD_ARRAY);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        self.gldrawable.gl_end()

        cr = self._backing.cairo_create()
        if old_backing is not None and old_backing._backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing._backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing._backing.get_size()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def paint_rgb24(self, img_data, x, y, width, height, rowstride):
        # OpenGL begin
        if not self.gldrawable.gl_begin(self.glcontext):
            log.error("OUCH")
            return False

        # Upload texture
        if not self.texture:
            self.texture = glGenTextures(1)

        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.texture)
        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstride/3)
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, width, height, 0, GL_RGB, GL_UNSIGNED_BYTE, img_data);

        vtxarrays=1
        if vtxarrays == 1:
            texcoords = [ [ 0, 0 ],
                          [ 0, height],
                          [ width, height],
                          [ width, 0] ]
            vtxcoords = texcoords

            glVertexPointeri(vtxcoords)
            glTexCoordPointeri(texcoords)
            glDrawArrays(GL_QUADS, 0, 4);
        else:
            glBegin(GL_QUADS);
            glTexCoord2i(0, 0);
            glVertex2i(0, 0);

            glTexCoord2i(0, height);
            glVertex2i(0, height);

            glTexCoord2i(width, height);
            glVertex2i(width, height);

            glTexCoord2i(width, 0);
            glVertex2i(width, 0);
            glEnd()

        # OpenGL end
#self.gldrawable.swap_buffers()
#       self.gldrawable.swap_buffers()
        glFinish()
        self.gldrawable.gl_end()

    def paint_yuv420(self, img_data, x, y, width, height, rowstrides):
        #import time
        #before=time.time()

        # OpenGL begin
        if not self.gldrawable.gl_begin(self.glcontext):
            log.error("OUCH")
            return False

        # Upload texture
        if self.textures[0] == 0:
            self.textures = glGenTextures(3)

        glEnable(GL_FRAGMENT_PROGRAM_ARB)

        if not self.yuv420_shader:
            self.yuv420_shader = [ 1 ]
            glGenProgramsARB(1, self.yuv420_shader)
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])
# The following fragprog is:
# * MIT X11 license, Copyright (c) 2007 by:
# *      Michael Dominic K. <mdk@mdk.am>
#http://www.mdk.org.pl/2007/11/17/gl-colorspace-conversions
            prog = """!!ARBfp1.0
# cgc version 3.1.0010, build date Feb 10 2012
# command line args: -profile arbfp1
# source file: yuv.cg
#vendor NVIDIA Corporation
#version 3.1.0.10
#profile arbfp1
#program main
#semantic main.IN
#var float2 IN.texcoord1 : $vin.TEXCOORD0 : TEX0 : 0 : 1
#var float2 IN.texcoord2 : $vin.TEXCOORD1 : TEX1 : 0 : 1
#var float2 IN.texcoord3 : $vin.TEXCOORD2 : TEX2 : 0 : 1
#var samplerRECT IN.texture1 : TEXUNIT0 : texunit 0 : 0 : 1
#var samplerRECT IN.texture2 : TEXUNIT1 : texunit 1 : 0 : 1
#var samplerRECT IN.texture3 : TEXUNIT2 : texunit 2 : 0 : 1
#var float4 IN.color : $vin.COLOR0 : COL0 : 0 : 1
#var float4 main.color : $vout.COLOR0 : COL : -1 : 1
#const c[0] = 1.1643835 2.017231 0 0.5
#const c[1] = 0.0625 1.1643835 -0.3917616 -0.81296802
#const c[2] = 1.1643835 0 1.5960271
PARAM c[3] = { { 1.1643835, 2.017231, 0, 0.5 },
        { 0.0625, 1.1643835, -0.3917616, -0.81296802 },
        { 1.1643835, 0, 1.5960271 } };
TEMP R0;
TEMP R1;
TEX R0.x, fragment.texcoord[2], texture[2], RECT;
ADD R1.z, R0.x, -c[0].w;
TEX R1.x, fragment.texcoord[0], texture[0], RECT;
TEX R0.x, fragment.texcoord[1], texture[1], RECT;
ADD R1.x, R1, -c[1];
ADD R1.y, R0.x, -c[0].w;
DP3 result.color.z, R1, c[0];
DP3 result.color.y, R1, c[1].yzww;
DP3 result.color.x, R1, c[2];
MOV result.color.w, fragment.color.primary;
END
# 10 instructions, 2 R-regs

                    """
            glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(prog), prog)
            log.error(glGetString(GL_PROGRAM_ERROR_STRING_ARB))

        glEnable(GL_FRAGMENT_PROGRAM_ARB)

        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv420_shader[0])

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[0])
        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[0])
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width, height, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[0]);

        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[1])
        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[1])
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width/2, height/2, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[1]);

        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[2])
        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[2])
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width/2, height/2, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[2]);

        vtxarrays=0
        if vtxarrays == 1:
            texcoords = [ [ 0, 0 ],
                          [ 0, height],
                          [ width, height],
                          [ width, 0] ]
            vtxcoords = texcoords
            texcoords_half = [ [ 0, 0 ],
                          [ 0, height/2],
                          [ width/2, height/2],
                          [ width/2, 0] ]

            glVertexPointeri(vtxcoords)

            glActiveTexture(GL_TEXTURE0);
            glClientActiveTexture(GL_TEXTURE0)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY);
            glTexCoordPointeri(texcoords)

            glActiveTexture(GL_TEXTURE1);
            glClientActiveTexture(GL_TEXTURE1)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY);
            glTexCoordPointeri(texcoords_half)

            glActiveTexture(GL_TEXTURE2);
            glClientActiveTexture(GL_TEXTURE2)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY);
            glTexCoordPointeri(texcoords_half)

            glDrawArrays(GL_QUADS, 0, 4);

        else:
            glBegin(GL_QUADS);
            glMultiTexCoord2i(GL_TEXTURE0, 0, 0);
            glMultiTexCoord2i(GL_TEXTURE1, 0, 0);
            glMultiTexCoord2i(GL_TEXTURE2, 0, 0);
            glVertex2i(0, 0);

            glMultiTexCoord2i(GL_TEXTURE0, 0, height);
            glMultiTexCoord2i(GL_TEXTURE1, 0, height/2);
            glMultiTexCoord2i(GL_TEXTURE2, 0, height/2);
            glVertex2i(0, height);

            glMultiTexCoord2i(GL_TEXTURE0, width, height);
            glMultiTexCoord2i(GL_TEXTURE1, width/2, height/2);
            glMultiTexCoord2i(GL_TEXTURE2, width/2, height/2);
            glVertex2i(width, height);

            glMultiTexCoord2i(GL_TEXTURE0, width, 0);
            glMultiTexCoord2i(GL_TEXTURE1, width/2, 0);
            glMultiTexCoord2i(GL_TEXTURE2, width/2, 0);
            glVertex2i(width, 0);
            glEnd()

        # OpenGL end
#self.gldrawable.swap_buffers()
#       self.gldrawable.swap_buffers()
        glFinish()
        self.gldrawable.gl_end()
        #end=time.time()
        #log.info("Took %f ms" % (end - before))

    def paint_with_video_decoder(self, factory, coding, img_data, x, y, width, height, rowstride, options):
        assert x==0 and y==0
        if self._video_decoder:
            if self._video_decoder_codec!=coding:
                self._video_decoder.clean()
                self._video_decoder = None
            elif self._video_decoder.get_width()!=width or self._video_decoder.get_height()!=height:
                log("paint_with_video_decoder: window dimensions have changed from %s to %s", (self._video_decoder.get_width(), self._video_decoder.get_height()), (width, height))
                self._video_decoder.clean()
                self._video_decoder.init_context(width, height, options)
        if self._video_decoder is None:
            self._video_decoder = factory()
            self._video_decoder_codec = coding
            self._video_decoder.init_context(width, height, options)
        try:
            if self.use_openGL_CSC == True:
                err, outstride, data = self._video_decoder.decompress_image_to_yuv(img_data, options)
                if err!=0:
                    log.error("paint_with_video_decoder: ouch, decompression error %s", err)
                    return
                if not data:
                    log.error("paint_with_video_decoder: ouch, no data from %s decoder", coding)
                    return
                log("paint_with_video_decoder: decompressed %s to %s bytes (%s%%) of rgb24 (%s*%s*3=%s) (outstride: %s)", len(img_data), len(data), int(100*len(img_data)/len(data)),width, height, width*height*3, outstride)
                self.paint_yuv420(data, x, y, width, height, outstride)
            else:
                err, outstride, data = self._video_decoder.decompress_image_to_rgb(img_data)
                if err!=0:
                    log.error("paint_with_video_decoder: ouch, decompression error %s", err)
                    return
                if not data:
                    log.error("paint_with_video_decoder: ouch, no data from %s decoder", coding)
                    return
                log("paint_with_video_decoder: decompressed %s to %s bytes (%s%%) of rgb24 (%s*%s*3=%s) (outstride: %s)", len(img_data), len(data), int(100*len(img_data)/len(data)),width, height, width*height*3, outstride)
                self.paint_rgb24(data, x, y, width, height, outstride)
        finally:
            if self.use_openGL_CSC == False:
                self._video_decoder.free_image()
            log("done")
