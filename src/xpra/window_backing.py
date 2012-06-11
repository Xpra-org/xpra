# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gobject, import_gdk, is_gtk3
gobject = import_gobject()
gdk = import_gdk()

import gtk
import gtk.gtkgl

import cairo
import ctypes

from wimpiggy.log import Logger
log = Logger()

from xpra.scripts.main import ENCODINGS
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.ARB.vertex_program import *
from OpenGL.GL.ARB.fragment_program import *

PREFER_CAIRO = False        #just for testing the CairoBacking with gtk2

"""
Generic superclass for Backing code,
see CairoBacking and PixmapBacking for implementations
"""
class Backing(object):
    def __init__(self, wid, mmap_enabled, mmap):
        self.wid = wid
        self.mmap_enabled = mmap_enabled
        self.mmap = mmap
        self._backing = None
        self._on_close = []

    def close(self):
        for cb in self._on_close:
            try:
                log("calling %s", cb)
                cb()
            except:
                log.error("error on close callback %s", cb, exc_info=True)
        self._on_close = []

    def jpegimage(self, img_data, width, height):
        import Image
        try:
            from io import BytesIO          #@Reimport
            data = bytearray(img_data)
            buf = BytesIO(data)
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO(img_data)
        return Image.open(buf)
        #return Image.fromstring("RGB", (width, height), img_data, 'jpeg', 'RGB')

    def rgb24image(self, img_data, width, height, rowstride):
        import Image
        if rowstride>0:
            assert len(img_data) == rowstride * height
        else:
            assert len(img_data) == width * 3 * height
        return Image.fromstring("RGB", (width, height), img_data, 'raw', 'RGB', rowstride, 1)

    def paint_rgb24(self, img_data, x, y, width, height, rowstride):
        raise Exception("override me!")
    def paint_png(self, img_data, x, y, width, height):
        raise Exception("override me!")

    def paint_x264(self, img_data, x, y, width, height, rowstride):
        assert "x264" in ENCODINGS
        from xpra.x264.codec import DECODERS, Decoder     #@UnresolvedImport
        self.paint_with_video_decoder(DECODERS, Decoder, "x264", img_data, x, y, width, height, rowstride)

    def paint_vpx(self, img_data, x, y, width, height, rowstride):
        assert "vpx" in ENCODINGS
        from xpra.vpx.codec import DECODERS, Decoder     #@UnresolvedImport
        self.paint_with_video_decoder(DECODERS, Decoder, "vpx", img_data, x, y, width, height, rowstride)

    def paint_with_video_decoder(self, decoders, factory, coding, img_data, x, y, width, height, rowstride):
        assert x==0 and y==0
        decoder = decoders.get(self.wid)
        if decoder and (decoder.get_width()!=width or decoder.get_height()!=height):
            log("paint_with_video_decoder: window dimensions have changed from %s to %s", (decoder.get_width(), decoder.get_height()), (width, height))
            decoder.clean()
            decoder.init(width, height)
        if decoder is None:
            decoder = factory()
            decoder.init(width, height)
            decoders[self.wid] = decoder
            def close_decoder():
                log("closing %s decoder for window %s", coding, self.wid)
                decoder.clean()
                del decoders[self.wid]
            self._on_close.append(close_decoder)
        try:
            err, outstride, data = decoder.decompress_image_to_rgb(img_data)
            if err!=0:
                log.error("paint_with_video_decoder: ouch, decompression error %s", err)
                return
            if not data:
                log.error("paint_with_video_decoder: ouch, no data from %s decoder", coding)
                return
            log("paint_with_video_decoder: decompressed %s to %s bytes (%s%%) of rgb24 (%s*%s*3=%s) (outstride: %s)", len(img_data), len(data), int(100*len(img_data)/len(data)),width, height, width*height*3, outstride)
            self.paint_rgb24(data, x, y, width, height, outstride)
        finally:
            decoder.free_image()


"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG!
This is a complete waste of CPU! Please complain to pycairo.
"""
class CairoBacking(Backing):
    def __init__(self, wid, w, h, old_backing, mmap_enabled, mmap):
        Backing.__init__(self, wid, mmap_enabled, mmap)
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(self._backing)
        if old_backing is not None and old_backing._backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(old_backing._backing, 0, 0)
            cr.paint()
            old_w = old_backing._backing.get_width()
            old_h = old_backing._backing.get_height()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
            old_backing._backing.finish()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def close(self):
        Backing.close(self)
        self._backing.finish()

    def paint_png(self, img_data, x, y, width, height):
        try:
            from io import BytesIO          #@Reimport
            import sys
            if sys.version>='3':
                data = bytearray(img_data.encode("latin1"))
            else:
                data = bytearray(img_data)
            buf = BytesIO(data)
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO(img_data)
        surf = cairo.ImageSurface.create_from_png(buf)
        gc = cairo.Context(self._backing)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()

    def paint_pil_image(self, pil_image, width, height):
        try:
            from io import BytesIO
            buf = BytesIO()
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO()
        pil_image.save(buf, format="PNG")
        png_data = buf.getvalue()
        buf.close()
        self.cairo_paint_png(png_data, 0, 0, width, height)

    def paint_rgb24(self, img_data, x, y, width, height, rowstride):
        log.info("cairo_paint_rgb24(..,%s,%s,%s,%s,%s)" % (x, y, width, height, rowstride))
        gc = cairo.Context(self._backing)
        if rowstride==0:
            rowstride = width*3
        surf = cairo.ImageSurface.create_for_data(img_data, cairo.FORMAT_RGB24, width, height, rowstride)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()

    def paint_mmap(self, img_data, x, y, width, height, rowstride):
        """ see _mmap_send() in server.py for details """
        assert "rgb24" in ENCODINGS
        assert self.mmap_enabled
        data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
        if len(img_data)==1:
            #construct an array directly from the mmap zone:
            offset, length = img_data[0]
            arraytype = ctypes.c_char * length
            data = arraytype.from_buffer(self.mmap, offset)
            image = self.rgb24image(data, width, height, rowstride)
            data_start.value = offset+length
        else:
            #re-construct the buffer from discontiguous chunks:
            log("drawing from discontiguous area: %s", img_data)
            data = ""
            for offset, length in img_data:
                self.mmap.seek(offset)
                data += self.mmap.read(length)
                data_start.value = offset+length
            image = self.rgb24image(data, width, height, rowstride)
        self.paint_pil_image(image, width, height)

    def draw_region(self, x, y, width, height, coding, img_data, rowstride):
        log.debug("draw_region(%s,%s,%s,%s,%s,..,%s)", x, y, width, height, coding, rowstride)
        if coding == "mmap":
            self.paint_mmap(img_data, x, y, width, height, rowstride)
        elif coding in ["rgb24", "jpeg"]:
            assert coding in ENCODINGS
            if coding=="rgb24":
                image = self.rgb24image(img_data, width, height, rowstride)
            else:   #if coding=="jpeg":
                image = self.jpegimage(img_data, width, height)
            self.paint_pil_image(image, width, height)
        elif coding == "png":
            assert coding in ENCODINGS
            self.paint_png(img_data, x, y, width, height)
        else:
            raise Exception("invalid picture encoding: %s" % coding)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_surface(self._backing, x, y)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)


"""
This is the gtk2 version.
Works much better than gtk3!
"""
class PixmapBacking(Backing):

    def __init__(self, wid, w, h, old_backing, mmap_enabled, mmap):
        Backing.__init__(self, wid, mmap_enabled, mmap)
        self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
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
        assert "rgb24" in ENCODINGS
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)

    def paint_pixbuf(self, coding, img_data, x, y, width, height, rowstride):
        assert coding in ENCODINGS
        loader = gdk.PixbufLoader(coding)
        loader.write(img_data, len(img_data))
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
            return
        gc = self._backing.new_gc()
        self._backing.draw_pixbuf(gc, pixbuf, 0, 0, x, y, width, height)

    def paint_mmap(self, img_data, x, y, width, height, rowstride):
        """ see _mmap_send() in server.py for details """
        assert self.mmap_enabled
        data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
        if len(img_data)==1:
            #construct an array directly from the mmap zone:
            offset, length = img_data[0]
            arraytype = ctypes.c_char * length
            data = arraytype.from_buffer(self.mmap, offset)
            self.paint_rgb24(data, x, y, width, height, rowstride)
            data_start.value = offset+length
        else:
            #re-construct the buffer from discontiguous chunks:
            log("drawing from discontiguous area: %s", img_data)
            data = ""
            for offset, length in img_data:
                self.mmap.seek(offset)
                data += self.mmap.read(length)
                data_start.value = offset+length
            self.paint_rgb24(data, x, y, width, height, rowstride)

    def draw_region(self, x, y, width, height, coding, img_data, rowstride):
        log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s)", x, y, width, height, coding, len(img_data), rowstride)
        if coding == "mmap":
            self.paint_mmap(img_data, x, y, width, height, rowstride)
        elif coding == "rgb24":
            if rowstride>0:
                assert len(img_data) == rowstride * height
            else:
                assert len(img_data) == width * 3 * height
            self.paint_rgb24(img_data, x, y, width, height, rowstride)
        elif coding == "x264":
            self.paint_x264(img_data, x, y, width, height, rowstride)
        elif coding == "vpx":
            self.paint_vpx(img_data, x, y, width, height, rowstride)
        else:
            self.paint_pixbuf(coding, img_data, x, y, width, height, rowstride)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_pixmap(self._backing, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return False
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)

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
        except gtk.gdkgl.NoMatches:
            raise SystemExit
        self._backing = gtk.gdkgl.ext(gdk.Pixmap(gdk.get_default_root_window(), w, h))
        log.info("Creating GL pixmap size %d %d " % (w, h))
        self.gldrawable = self._backing.set_gl_capability(self.glconfig)
        log.info("drawable ok")
        # Then create an indirect OpenGL rendering context.
        self.glcontext = gtk.gdkgl.Context(self.gldrawable,
                                               direct=True)
        log.info("context ok")
        if not self.glcontext:
            raise SystemExit, "** Cannot create OpenGL rendering context!"
        print "OpenGL rendering context is created."
        self.texture = None
        self.textures = None
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
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)
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
        import time
        before=time.time()
        
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
        glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstride)
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_RGB, width, height, 0, GL_RGB, GL_UNSIGNED_BYTE, img_data);

        vtxarrays=0
        if vtxarrays == 1:
            texcoords = [ [ 0, 0 ],    
                          [ 0, height],
                          [ width, height],
                          [ width, 0] ]
            vtxcoords = texcoords

            glVertexPointeri(vtxcoords)
            glTexCoordPointeri(texcoords)
            glDrawArrays(GL_QUADS, 0, 10);
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
        end=time.time()
#        log.info("Took %f ms" % (end - before))

    def paint_yuv420(self, img_data, x, y, width, height, rowstrides):
        import time
        before=time.time()
        
        # OpenGL begin
        if not self.gldrawable.gl_begin(self.glcontext):
            log.error("OUCH")
            return False
       
        # Upload texture
        if not self.textures:
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
        glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, rowstrides[0], height, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[0]);

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

            glVertexPointeri(vtxcoords)
            glTexCoordPointeri(texcoords)
            glDrawArrays(GL_QUADS, 0, 10);
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
        end=time.time()
#        log.info("Took %f ms" % (end - before))

    def paint_with_video_decoder(self, decoders, factory, coding, img_data, x, y, width, height, rowstride):
        assert x==0 and y==0
        decoder = decoders.get(self.wid)
        if decoder and (decoder.get_width()!=width or decoder.get_height()!=height):
            log("paint_with_video_decoder: window dimensions have changed from %s to %s", (decoder.get_width(), decoder.get_height()), (width, height))
            decoder.clean()
            decoder.init(width, height)
        if decoder is None:
            decoder = factory()
            decoder.init(width, height)
            decoders[self.wid] = decoder
            def close_decoder():
                log("closing %s decoder for window %s", coding, self.wid)
                decoder.clean()
                del decoders[self.wid]
            self._on_close.append(close_decoder)
        try:
            if self.use_openGL_CSC == True:
                err, outstride, data = decoder.decompress_image_to_yuv(img_data)
                if err!=0:
                    log.error("paint_with_video_decoder: ouch, decompression error %s", err)
                    return
                if not data:
                    log.error("paint_with_video_decoder: ouch, no data from %s decoder", coding)
                    return
                log("paint_with_video_decoder: decompressed %s to %s bytes (%s%%) of rgb24 (%s*%s*3=%s) (outstride: %s)", len(img_data), len(data), int(100*len(img_data)/len(data)),width, height, width*height*3, outstride)
                self.paint_yuv420(data, x, y, width, height, outstride)
            else:
                err, outstride, data = decoder.decompress_image_to_rgb(img_data)
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
                decoder.free_image()
            log("done")

        
def new_backing(wid, w, h, old_backing, mmap_enabled, mmap):
    if is_gtk3() or PREFER_CAIRO:
        b = CairoBacking(wid, w, h, old_backing, mmap_enabled, mmap)
    else:
        b = GLPixmapBacking(wid, w, h, old_backing, mmap_enabled, mmap)
    if old_backing:
        old_backing.close()
    return b
