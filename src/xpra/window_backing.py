# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gdk, is_gtk3
gdk = import_gdk()

import ctypes
import cairo
import gobject
import zlib

from wimpiggy.log import Logger
log = Logger()

from threading import Lock
from xpra.scripts.main import ENCODINGS
from xpra.xor import xor_str

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
        self._last_pixmap_data = None
        self._video_decoder = None
        self._video_decoder_lock = Lock()

    def close(self):
        log("%s.close() video_decoder=%s", type(self), self._video_decoder)
        if self._video_decoder:
            try:
                self._video_decoder_lock.acquire()
                self._video_decoder.clean()
                self._video_decoder = None
            finally:
                self._video_decoder_lock.release()

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

    def rgb24image(self, img_data, width, height, rowstride):
        import Image
        if rowstride>0:
            assert len(img_data) == rowstride * height
        else:
            assert len(img_data) == width * 3 * height
        return Image.fromstring("RGB", (width, height), img_data, 'raw', 'RGB', rowstride, 1)

    def fire_paint_callbacks(self, callbacks, success):
        for x in callbacks:
            try:
                x(success)
            except:
                log.error("error calling %s(%s)", x, success, exc_info=True)

    def paint_rgb24(self, raw_data, x, y, width, height, rowstride, options, callbacks):
        img_data = raw_data
        if options and options.get("zlib", 0)>0:
            img_data = zlib.decompress(raw_data)
        assert len(img_data) == rowstride * height, "expected %s bytes but received %s" % (rowstride * height, len(img_data))
        gobject.idle_add(self.do_paint_rgb24, img_data, x, y, width, height, rowstride, options, callbacks)

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        raise Exception("override me!")

    def paint_x264(self, img_data, x, y, width, height, rowstride, options, callbacks):
        assert "x264" in ENCODINGS
        from xpra.x264.codec import Decoder     #@UnresolvedImport
        self.paint_with_video_decoder(Decoder, "x264", img_data, x, y, width, height, rowstride, options, callbacks)

    def paint_vpx(self, img_data, x, y, width, height, rowstride, options, callbacks):
        assert "vpx" in ENCODINGS
        from xpra.vpx.codec import Decoder     #@UnresolvedImport
        self.paint_with_video_decoder(Decoder, "vpx", img_data, x, y, width, height, rowstride, options, callbacks)

    def paint_with_video_decoder(self, factory, coding, img_data, x, y, width, height, rowstride, options, callbacks):
        assert x==0 and y==0
        try:
            self._video_decoder_lock.acquire()
            if self._video_decoder:
                if self._video_decoder.get_type()!=coding:
                    log("paint_with_video_decoder: encoding changed from %s to %s", self._video_decoder.get_type(), coding)
                    self._video_decoder.clean()
                    self._video_decoder = None
                elif self._video_decoder.get_width()!=width or self._video_decoder.get_height()!=height:
                    log("paint_with_video_decoder: window dimensions have changed from %s to %s", (self._video_decoder.get_width(), self._video_decoder.get_height()), (width, height))
                    self._video_decoder.clean()
                    self._video_decoder.init_context(width, height, options)
            if self._video_decoder is None:
                log("paint_with_video_decoder: new %s(%s,%s,%s)", factory, width, height, options)
                self._video_decoder = factory()
                self._video_decoder.init_context(width, height, options)
            log("paint_with_video_decoder: options=%s, decoder=%s", options, type(self._video_decoder))
            self.do_video_paint(coding, img_data, x, y, width, height, options, callbacks)
        finally:
            self._video_decoder_lock.release()
        return  False

    def do_video_paint(self, coding, img_data, x, y, width, height, options, callbacks):
        log("paint_with_video_decoder: options=%s, decoder=%s", options, type(self._video_decoder))
        err, rgb_image = self._video_decoder.decompress_image_to_rgb(img_data, options)
        success = err==0 and rgb_image and rgb_image.get_size()>0
        if success:
            #this will also take care of firing callbacks (from UI thread):
            gobject.idle_add(self.do_paint_rgb24, rgb_image.get_data(), x, y, width, height, rgb_image.get_rowstride(), options, callbacks)
        else:
            log.error("paint_with_video_decoder: %s decompression error %s on %s bytes of picture data for %sx%s pixels, options=%s",
                      coding, err, len(img_data), width, height, options)
            self.fire_paint_callbacks(callbacks, False)
        del rgb_image


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

    def init(self, w, h):
        old_backing = self._backing
        #should we honour self.depth here?
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(self._backing)
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(old_backing, 0, 0)
            cr.paint()
            old_w = old_backing.get_width()
            old_h = old_backing.get_height()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
            old_backing.finish()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def close(self):
        Backing.close(self)
        self._backing.finish()

    def paint_png(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
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
        self.fire_paint_callbacks(callbacks, True)
        return  False

    def paint_pil_image(self, pil_image, width, height, rowstride, options, callbacks):
        try:
            from io import BytesIO
            buf = BytesIO()
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO()
        pil_image.save(buf, format="PNG")
        png_data = buf.getvalue()
        buf.close()
        gobject.idle_add(self.paint_png, png_data, 0, 0, width, height, rowstride, options, callbacks)

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        log("cairo_paint_rgb24(..,%s,%s,%s,%s,%s,%s,%s)", x, y, width, height, rowstride, options, callbacks)
        gc = cairo.Context(self._backing)
        if rowstride==0:
            rowstride = width*3
        surf = cairo.ImageSurface.create_for_data(img_data, cairo.FORMAT_RGB24, width, height, rowstride)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()
        self.fire_paint_callbacks(callbacks, True)
        del img_data
        return  False

    def paint_mmap(self, img_data, x, y, width, height, rowstride, options, callbacks):
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
        self.paint_pil_image(image, width, height, rowstride, options, callbacks)
        return  False

    def draw_region(self, *args):
        #FIXME: I am lazy and gtk3 support is lagging anyway:
        gobject.idle_add(self.do_draw_region, *args)

    def do_draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        log.debug("do_draw_region(%s,%s,%s,%s,%s,..,%s,%s,%s)", x, y, width, height, coding, rowstride, options, callbacks)
        if coding == "mmap":
            return  self.paint_mmap(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding in ["rgb24", "jpeg"]:
            assert coding in ENCODINGS
            if coding=="rgb24":
                image = self.rgb24image(img_data, width, height, rowstride, options, callbacks)
            else:   #if coding=="jpeg":
                image = self.jpegimage(img_data, width, height, rowstride, options, callbacks)
            return  self.paint_pil_image(image, width, height, rowstride, options, callbacks)
        elif coding == "png":
            assert coding in ENCODINGS
            gobject.idle_add(self.paint_png, img_data, x, y, width, height, rowstride, options, callbacks)
        raise Exception("invalid picture encoding: %s" % coding)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_surface(self._backing, x, y)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return True
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)
            return False


"""
This is the gtk2 version.
Works much better than gtk3!
"""
class PixmapBacking(Backing):

    def __init__(self, wid, w, h, mmap_enabled, mmap):
        Backing.__init__(self, wid, mmap_enabled, mmap)

    def init(self, w, h):
        old_backing = self._backing
        self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        cr = self._backing.cairo_create()
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing.get_size()
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

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        assert "rgb24" in ENCODINGS
        delta = options.get("delta", -1)        #the delta frame we reference
        if delta>=0:
            if self._last_pixmap_data:
                lwidth, lheight, store, ldata = self._last_pixmap_data
                assert width==lwidth and height==lheight and delta==store
                img_data = xor_str(img_data, ldata)
            else:
                raise Exception("delta region references pixmap data we do not have!")
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        self.fire_paint_callbacks(callbacks, True)
        store = options.get("store", -1)
        if store>=0:
            self._last_pixmap_data =  width, height, store, img_data
        return  False

    def paint_webp(self, img_data, x, y, width, height, rowstride, options, callbacks):
        assert "webp" in ENCODINGS
        from xpra.webm.decode import DecodeRGB
        rgb24 = DecodeRGB(img_data)
        gobject.idle_add(self.do_paint_rgb24, str(rgb24.bitmap), x, y, width, height, width*3, options, callbacks)
        return  False

    def paint_pixbuf(self, coding, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        assert coding in ENCODINGS
        loader = gdk.PixbufLoader(coding)
        loader.write(img_data, len(img_data))
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
            self.fire_paint_callbacks(callbacks, False)
            return  False
        self.do_paint_pixbuf(pixbuf, x, y, width, height, options, callbacks)
        return  False

    def do_paint_pixbuf(self, pixbuf, x, y, width, height, options, callbacks):
        img_data = pixbuf.get_pixels()
        rowstride = pixbuf.get_rowstride()
        self.do_paint_rgb24(img_data, x, y, width, height, rowstride, options, callbacks)

    def paint_mmap(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        #we could run just paint_rgb24 from the UI thread,
        #but this would not make much of a difference
        #and would complicate the code (add a callback to free mmap area)
        """ see _mmap_send() in server.py for details """
        assert self.mmap_enabled
        data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
        if len(img_data)==1:
            #construct an array directly from the mmap zone:
            offset, length = img_data[0]
            arraytype = ctypes.c_char * length
            data = arraytype.from_buffer(self.mmap, offset)
            self.do_paint_rgb24(data, x, y, width, height, rowstride, options, callbacks)
            data_start.value = offset+length
        else:
            #re-construct the buffer from discontiguous chunks:
            log("drawing from discontiguous area: %s", img_data)
            data = ""
            for offset, length in img_data:
                self.mmap.seek(offset)
                data += self.mmap.read(length)
                data_start.value = offset+length
            self.do_paint_rgb24(data, x, y, width, height, rowstride, options, callbacks)
        return  False

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s, %s)", x, y, width, height, coding, len(img_data), rowstride, options, callbacks)
        if coding == "mmap":
            gobject.idle_add(self.paint_mmap, img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "rgb24":
            if rowstride==0:
                rowstride = width * 3
            self.paint_rgb24(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "x264":
            self.paint_x264(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "vpx":
            self.paint_vpx(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "webp":
            self.paint_webp(img_data, x, y, width, height, rowstride, options, callbacks)
        else:
            gobject.idle_add(self.paint_pixbuf, coding, img_data, x, y, width, height, rowstride, options, callbacks)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_pixmap(self._backing, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return True
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)
            return False

def new_backing(wid, w, h, backing, mmap_enabled, mmap):
    if is_gtk3() or PREFER_CAIRO:
        backing_class = CairoBacking
    else:
        backing_class = PixmapBacking
    return make_new_backing(backing_class, wid, w, h, backing, mmap_enabled, mmap)

def make_new_backing(backing_class, wid, w, h, backing, mmap_enabled, mmap):
    w = max(1, w)
    h = max(1, h)
    lock = None
    if backing:
        lock = backing._video_decoder_lock
    try:
        if lock:
            lock.acquire()
        if backing is None:
            backing = backing_class(wid, w, h, mmap_enabled, mmap)
        backing.init(w, h)
    finally:
        if lock:
            lock.release()
    return backing
