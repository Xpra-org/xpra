# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import zlib

from xpra.log import Logger
log = Logger()

from threading import Lock
from xpra.codecs.xor import xor_str
from xpra.net.mmap_pipe import mmap_read
from xpra.os_util import BytesIOClass, strtobytes
from xpra.codecs.codec_constants import get_colorspace_from_avutil_enum
from xpra.scripts.config import dec_avcodec, dec_vpx, dec_webp, PIL

#logging in the draw path is expensive:
DRAW_DEBUG = os.environ.get("XPRA_DRAW_DEBUG", "0")=="1"


def fire_paint_callbacks(callbacks, success):
    for x in callbacks:
        try:
            x(success)
        except KeyboardInterrupt:
            raise
        except:
            log.error("error calling %s(%s)", x, success, exc_info=True)

"""
Generic superclass for all Backing code,
see CairoBacking and GTKWindowBacking for actual implementations
"""
class WindowBackingBase(object):
    def __init__(self, wid, idle_add):
        self.wid = wid
        self.idle_add = idle_add
        self._has_alpha = False
        self._backing = None
        self._last_pixmap_data = None
        self._video_decoder = None
        self._csc_prep = None
        self._csc_decoder = None
        self._decoder_lock = Lock()
        self.draw_needs_refresh = True
        self.mmap = None
        self.mmap_enabled = False

    def __str__(self):
        return "WindowBackingBase"

    def enable_mmap(self, mmap_area):
        self.mmap = mmap_area
        self.mmap_enabled = True

    def close(self):
        self._backing = None
        log("%s.close() video_decoder=%s", self, self._video_decoder)
        #try without blocking, if that fails then
        #the lock is held by the decoding thread,
        #and it will run the cleanup after releasing the lock
        #(it checks for self._backing None)
        self.close_decoder(False)

    def close_decoder(self, blocking=False):
        if self._decoder_lock is None or not self._decoder_lock.acquire(blocking):
            return False
        try:
            self.do_clean_csc_prep()
            self.do_clean_video_decoder()
            self.do_clean_csc_decoder()
            return True
        finally:
            self._decoder_lock.release()

    def do_clean_csc_prep(self):
        if self._csc_prep:
            self._csc_prep.clean()
            self._csc_prep = None

    def do_clean_video_decoder(self):
        if self._video_decoder:
            self._video_decoder.clean()
            self._video_decoder = None

    def do_clean_csc_decoder(self):
        if self._csc_decoder:
            self._csc_decoder.clean()
            self._csc_decoder = None


    def process_delta(self, raw_data, width, height, rowstride, options):
        """
            Can be called from any thread, decompresses and xors the rgb raw_data,
            then stores it for later xoring if needed.
        """
        img_data = raw_data
        if options and options.get("zlib", 0)>0:
            img_data = zlib.decompress(raw_data)
        assert len(img_data) == rowstride * height, "expected %s bytes for %sx%s with rowstride=%s but received %s (%s compressed)" % (rowstride * height, width, height, rowstride, len(img_data), len(raw_data))
        delta = options.get("delta", -1)
        rgb_data = img_data
        if delta>=0:
            if not self._last_pixmap_data:
                raise Exception("delta region references pixmap data we do not have!")
            lwidth, lheight, store, ldata = self._last_pixmap_data
            assert width==lwidth and height==lheight and delta==store
            rgb_data = xor_str(img_data, ldata)
        #store new pixels for next delta:
        store = options.get("store", -1)
        if store>=0:
            self._last_pixmap_data =  width, height, store, rgb_data
        return rgb_data


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        """ can be called from any thread """
        #log("paint_image(%s, %s bytes, %s, %s, %s, %s, %s, %s)", coding, len(img_data), x, y, width, height, options, callbacks)
        assert PIL
        buf = BytesIOClass(img_data)
        img = PIL.Image.open(buf)
        assert img.mode in ("L", "P", "RGB", "RGBA"), "invalid image mode: %s" % img.mode
        if img.mode in ("P", "L"):
            #TODO: use RGB for images without transparency
            img = img.convert("RGB")
        raw_data = img.tostring("raw", img.mode)
        if img.mode=="RGB":
            #PIL flattens the data to a continuous straightforward RGB format:
            rowstride = width*3
            img_data = self.process_delta(raw_data, width, height, rowstride, options)
            self.idle_add(self.do_paint_rgb24, img_data, x, y, width, height, rowstride, options, callbacks)
        elif img.mode=="RGBA":
            rowstride = width*4
            img_data = self.process_delta(raw_data, width, height, rowstride, options)
            self.idle_add(self.do_paint_rgb32, img_data, x, y, width, height, rowstride, options, callbacks)
        return False

    def paint_webp(self, img_data, x, y, width, height, options, callbacks):
        """ can be called from any thread """
        assert dec_webp is not None
        if options.get("has_alpha", False):
            decode = dec_webp.DecodeRGBA
            rowstride = width*4
            paint_rgb = self.do_paint_rgb32
        else:
            decode = dec_webp.DecodeRGB
            rowstride = width*3
            paint_rgb = self.do_paint_rgb24
        if DRAW_DEBUG:
            log.info("paint_webp(%s) using decode=%s, paint=%s",
                 ("%s bytes" % len(img_data), x, y, width, height, options, callbacks), decode, paint_rgb)
        rgb_data = decode(img_data)
        pixels = str(rgb_data.bitmap)
        self.idle_add(paint_rgb, pixels, x, y, width, height, rowstride, options, callbacks)
        return  False

    def paint_rgb24(self, raw_data, x, y, width, height, rowstride, options, callbacks):
        """ called from non-UI thread
            this method calls process_delta before calling do_paint_rgb24 from the UI thread via idle_add
        """
        rgb24_data = self.process_delta(raw_data, width, height, rowstride, options)
        self.idle_add(self.do_paint_rgb24, rgb24_data, x, y, width, height, rowstride, options, callbacks)
        return  False

    def do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread
            this method is only here to ensure that we always fire the callbacks,
            the actual paint code is in _do_paint_rgb24
        """
        try:
            success = self._do_paint_rgb24(img_data, x, y, width, height, rowstride, options, callbacks)
            fire_paint_callbacks(callbacks, success)
        except KeyboardInterrupt:
            raise
        except:
            log.error("do_paint_rgb24 error", exc_info=True)
            fire_paint_callbacks(callbacks, False)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        raise Exception("override me!")


    def paint_rgb32(self, raw_data, x, y, width, height, rowstride, options, callbacks):
        """ called from non-UI thread
            this method calls process_delta before calling do_paint_rgb32 from the UI thread via idle_add
        """
        rgb32_data = self.process_delta(raw_data, width, height, rowstride, options)
        self.idle_add(self.do_paint_rgb32, rgb32_data, x, y, width, height, rowstride, options, callbacks)
        return  False

    def do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread
            this method is only here to ensure that we always fire the callbacks,
            the actual paint code is in _do_paint_rgb32
        """
        try:
            success = self._do_paint_rgb32(img_data, x, y, width, height, rowstride, options, callbacks)
            fire_paint_callbacks(callbacks, success)
        except KeyboardInterrupt:
            raise
        except:
            log.error("do_paint_rgb32 error", exc_info=True)
            fire_paint_callbacks(callbacks, False)

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        raise Exception("override me!")


    def paint_with_video_decoder(self, decoder_module, coding, img_data, x, y, width, height, options, callbacks):
        assert x==0 and y==0
        assert hasattr(decoder_module, "Decoder"), "decoder module %s does not have 'Decoder' factory function!" % decoder_module
        assert hasattr(decoder_module, "get_colorspaces"), "decoder module %s does not have 'get_colorspaces' function!" % decoder_module
        factory = getattr(decoder_module, "Decoder")
        get_colorspaces = getattr(decoder_module, "get_colorspaces")
        try:
            self._decoder_lock.acquire()
            if self._backing is None:
                log("window %s is already gone!", self.wid)
                fire_paint_callbacks(callbacks, False)
                return  False
            enc_width, enc_height = options.get("scaled_size", (width, height))
            input_colorspace = options.get("csc")
            if not input_colorspace:
                # Backwards compatibility with pre 0.10.x clients
                # We used to specify the colorspace as an avutil PixelFormat constant
                old_csc_fmt = options.get("csc_pixel_format")
                input_colorspace = get_colorspace_from_avutil_enum(old_csc_fmt)
                assert input_colorspace is not None, "csc was not specified and we cannot find a colorspace from csc_pixel_format=%s" % old_csc_fmt

            #do we need a prep step for decoders that cannot handle the input_colorspace directly?
            decoder_colorspaces = get_colorspaces()
            decoder_colorspace = input_colorspace
            #if input_colorspace not in decoder_colorspaces:
            if input_colorspace not in decoder_colorspaces:
                log("colorspace not supported by %s directly", decoder_module)
                assert input_colorspace in ("BGRA", "BGRX"), "colorspace %s cannot be handled directly or via a csc preparation step!" % input_colorspace
                decoder_colorspace = "YUV444P"
                if self._csc_prep:
                    if self._csc_prep.get_src_format()!=input_colorspace:
                        #this should not happen!
                        log.warn("input colorspace has changed from %s to %s", self._csc_prep.get_src_format(), input_colorspace)
                        self.do_clean_csc_prep()
                    elif self._csc_prep.get_dst_format() not in decoder_colorspaces:
                        #this should not happen!
                        log.warn("csc prep colorspace %s is now invalid!?", self._csc_prep.get_dst_format())
                        self.do_clean_csc_prep()
                    elif self._csc_prep.get_src_width()!=enc_width or self._csc_prep.get_src_height()!=enc_height:
                        log("csc prep dimensions have changed from %s to %s", (self._csc_prep.get_src_width(), self._csc_prep.get_src_height()), (enc_width, enc_height))
                        self.do_clean_csc_prep()
                if self._csc_prep is None:
                    from xpra.codecs.csc_swscale.colorspace_converter import ColorspaceConverter    #@UnresolvedImport
                    self._csc_prep = ColorspaceConverter()
                    csc_speed = 0   #always best quality
                    self._csc_prep.init_context(enc_width, enc_height, input_colorspace,
                                           width, height, decoder_colorspace, csc_speed)
                    log("csc preparation step: %s", self._csc_prep)
            elif self._csc_prep:
                #no longer needed?
                self.do_clean_csc_prep()

            if self._video_decoder:
                if self._video_decoder.get_type()!=coding:
                    if DRAW_DEBUG:
                        log.info("paint_with_video_decoder: encoding changed from %s to %s", self._video_decoder.get_type(), coding)
                    self.do_clean_video_decoder()
                elif self._video_decoder.get_width()!=enc_width or self._video_decoder.get_height()!=enc_height:
                    if DRAW_DEBUG:
                        log.info("paint_with_video_decoder: window dimensions have changed from %s to %s", (self._video_decoder.get_width(), self._video_decoder.get_height()), (enc_width, enc_height))
                    self.do_clean_video_decoder()
                elif self._video_decoder.get_colorspace()!=decoder_colorspace:
                    if DRAW_DEBUG:
                        log.info("paint_with_video_decoder: colorspace changed from %s to %s", self._video_decoder.get_colorspace(), decoder_colorspace)
                    self.do_clean_video_decoder()
            if self._video_decoder is None:
                if DRAW_DEBUG:
                    log.info("paint_with_video_decoder: new %s(%s,%s,%s)", factory, width, height, decoder_colorspace)
                self._video_decoder = factory()
                self._video_decoder.init_context(enc_width, enc_height, decoder_colorspace)
                if DRAW_DEBUG:
                    log.info("paint_with_video_decoder: info=%s", self._video_decoder.get_info())

            img = self._video_decoder.decompress_image(img_data, options)
            if not img:
                raise Exception("paint_with_video_decoder: wid=%s, %s decompression error on %s bytes of picture data for %sx%s pixels, options=%s" % (
                      self.wid, coding, len(img_data), width, height, options))
            self.do_video_paint(img, x, y, enc_width, enc_height, width, height, options, callbacks)
        finally:
            self._decoder_lock.release()
            if self._backing is None:
                self.close_decoder(True)
        return  False

    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        rgb_format = "RGB"  #we may want to be able to change this (RGBA, BGR, ..)
        #as some video formats like vpx can forward transparency
        #also we could skip the csc step in some cases:
        pixel_format = img.get_pixel_format()
        #to handle this, we would need the decoder to handle buffers allocation properly:
        assert pixel_format!=rgb_format, "no csc needed! but we don't handle this scenario yet!"
        if self._csc_decoder is not None:
            if self._csc_decoder.get_src_format()!=pixel_format:
                if DRAW_DEBUG:
                    log.info("do_video_paint csc: switching src format from %s to %s", self._csc_decoder.get_src_format(), pixel_format)
                self.do_clean_csc_decoder()
            elif self._csc_decoder.get_dst_format()!=rgb_format:
                if DRAW_DEBUG:
                    log.info("do_video_paint csc: switching dst format from %s to %s", self._csc_decoder.get_dst_format(), rgb_format)
                self.do_clean_csc_decoder()
            elif self._csc_decoder.get_src_width()!=enc_width or self._csc_decoder.get_src_height()!=enc_height:
                if DRAW_DEBUG:
                    log.info("do_video_paint csc: switching src size from %sx%s to %sx%s",
                         enc_width, enc_height, self._csc_decoder.get_src_width(), self._csc_decoder.get_src_height())
                self.do_clean_csc_decoder()
            elif self._csc_decoder.get_dst_width()!=width or self._csc_decoder.get_dst_height()!=height:
                if DRAW_DEBUG:
                    log.info("do_video_paint csc: switching src size from %sx%s to %sx%s",
                         width, height, self._csc_decoder.get_dst_width(), self._csc_decoder.get_dst_height())
                self.do_clean_csc_decoder()
        if self._csc_decoder is None:
            from xpra.codecs.csc_swscale.colorspace_converter import ColorspaceConverter    #@UnresolvedImport
            self._csc_decoder = ColorspaceConverter()
            #use higher quality csc to compensate for lower quality source
            #(which generally means that we downscaled via YUV422P or lower)
            #or when upscaling the video:
            q = options.get("quality", 50)
            csc_speed = int(min(100, 100-q, 100.0 * (enc_width*enc_height) / (width*height)))
            self._csc_decoder.init_context(enc_width, enc_height, pixel_format,
                                           width, height, rgb_format, csc_speed)
            if DRAW_DEBUG:
                log.info("do_video_paint new csc decoder: %s", self._csc_decoder)
        rgb = self._csc_decoder.convert_image(img)
        if DRAW_DEBUG:
            log.info("do_video_paint rgb(%s)=%s", img, rgb)
        img.free()
        assert rgb.get_planes()==0, "invalid number of planes for %s: %s" % (rgb_format, rgb.get_planes())
        #this will also take care of firing callbacks (from the UI thread):
        def paint():
            data = rgb.get_pixels()
            rowstride = rgb.get_rowstride()
            self.do_paint_rgb24(data, x, y, width, height, rowstride, options, callbacks)
            rgb.free()
        self.idle_add(paint)

    def paint_mmap(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread """
        #we could run just paint_rgb24 from the UI thread,
        #but this would not make much of a difference
        #and would complicate the code (add a callback to free mmap area)
        """ see _mmap_send() in server.py for details """
        assert self.mmap_enabled
        data = mmap_read(self.mmap, img_data)
        rgb_format = options.get("rgb_format", "rgb24")
        if rgb_format=="RGB":
            self.do_paint_rgb24(data, x, y, width, height, rowstride, options, callbacks)
        elif rgb_format=="RGBA":
            self.do_paint_rgb32(data, x, y, width, height, rowstride, options, callbacks)
        else:
            raise Exception("invalid rgb format: %s" % rgb_format)
        return  False


    def draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        """ dispatches the paint to one of the paint_XXXX methods """
        if DRAW_DEBUG:
            log.info("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s, %s)", x, y, width, height, coding, len(img_data), rowstride, options, callbacks)
        coding = strtobytes(coding)
        if coding == "mmap":
            self.idle_add(self.paint_mmap, img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "rgb24":
            if rowstride==0:
                rowstride = width * 3
            self.paint_rgb24(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "rgb32":
            if rowstride==0:
                rowstride = width * 4
            self.paint_rgb32(img_data, x, y, width, height, rowstride, options, callbacks)
        elif coding == "x264":
            self.paint_with_video_decoder(dec_avcodec, "x264", img_data, x, y, width, height, options, callbacks)
        elif coding == "vpx":
            self.paint_with_video_decoder(dec_vpx, "vpx", img_data, x, y, width, height, options, callbacks)
        elif coding == "webp":
            self.paint_webp(img_data, x, y, width, height, options, callbacks)
        elif coding.startswith("png") or coding=="jpeg":
            self.paint_image(coding, img_data, x, y, width, height, options, callbacks)
        else:
            raise Exception("invalid encoding: %s" % coding)
