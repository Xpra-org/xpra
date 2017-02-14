# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import hashlib
from xpra.log import Logger
log = Logger("paint")
deltalog = Logger("delta")

from threading import Lock
from xpra.net.mmap_pipe import mmap_read
from xpra.net import compression
from xpra.util import typedict, csv, envint, envbool
from xpra.codecs.loader import get_codec
from xpra.codecs.video_helper import getVideoHelper
from xpra.os_util import BytesIOClass, bytestostr, _buffer
from xpra.codecs.xor.cyxor import xor_str   #@UnresolvedImport
from xpra.codecs.argb.argb import unpremultiply_argb, unpremultiply_argb_in_place   #@UnresolvedImport

DELTA_BUCKETS = envint("XPRA_DELTA_BUCKETS", 5)
INTEGRITY_HASH = envbool("XPRA_INTEGRITY_HASH", False)

#ie:
#CSC_OPTIONS = { "YUV420P" : {"RGBX" : [swscale.spec], "BGRX" : ...} }
CSC_OPTIONS = None
def load_csc_options():
    global CSC_OPTIONS
    if CSC_OPTIONS is None:
        CSC_OPTIONS = {}
        vh = getVideoHelper()
        for csc_in in vh.get_csc_inputs():
            CSC_OPTIONS[csc_in] = vh.get_csc_specs(csc_in)
    return CSC_OPTIONS

#get the list of video encodings (and the module for each one):
VIDEO_DECODERS = None
def load_video_decoders():
    global VIDEO_DECODERS
    if VIDEO_DECODERS is None:
        VIDEO_DECODERS = {}
        vh = getVideoHelper()
        for encoding in vh.get_decodings():
            specs = vh.get_decoder_specs(encoding)
            for colorspace, decoders in specs.items():
                log("%-5s decoders for %7s: %s", encoding, colorspace, csv([d.get_type() for _,d in decoders]))
                assert len(decoders)>0
                #use the first one:
                _, decoder_module = decoders[0]
                VIDEO_DECODERS[encoding] = decoder_module
        log("video decoders: %s", dict((e,d.get_type()) for e,d in VIDEO_DECODERS.items()))
    return VIDEO_DECODERS


def fire_paint_callbacks(callbacks, success=True, message=""):
    for x in callbacks:
        try:
            x(success, message)
        except KeyboardInterrupt:
            raise
        except:
            log.error("error calling %s(%s)", x, success, exc_info=True)


"""
Generic superclass for all Backing code,
see CairoBacking and GTKWindowBacking for actual implementations
"""
class WindowBackingBase(object):
    def __init__(self, wid, window_alpha, idle_add):
        load_csc_options()
        load_video_decoders()
        self.wid = wid
        self.size = 0, 0
        self.idle_add = idle_add
        self._alpha_enabled = window_alpha
        self._backing = None
        self._delta_pixel_data = [None for _ in range(DELTA_BUCKETS)]
        self._video_decoder = None
        self._csc_decoder = None
        self._decoder_lock = Lock()
        self._PIL_encodings = []
        self.pointer_overlay = None
        PIL = get_codec("dec_pillow")
        if PIL:
            self._PIL_encodings = PIL.get_encodings()
        self.draw_needs_refresh = True
        self.mmap = None
        self.mmap_enabled = False
        self.jpeg_decoder = get_codec("dec_jpeg")

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
        log("close_decoder(%s)", blocking)
        dl = self._decoder_lock
        if dl is None or not dl.acquire(blocking):
            log("close_decoder(%s) lock %s not acquired", blocking, dl)
            return False
        try:
            self.do_clean_video_decoder()
            self.do_clean_csc_decoder()
            return True
        finally:
            dl.release()

    def do_clean_video_decoder(self):
        if self._video_decoder:
            self._video_decoder.clean()
            self._video_decoder = None

    def do_clean_csc_decoder(self):
        if self._csc_decoder:
            self._csc_decoder.clean()
            self._csc_decoder = None


    def get_encoding_properties(self):
        return {
                 "encodings.rgb_formats"    : self.RGB_MODES,
                 "encoding.transparency"    : self._alpha_enabled,
                 "encoding.full_csc_modes"  : self._get_full_csc_modes(self.RGB_MODES),
                 }

    def _get_full_csc_modes(self, rgb_modes):
        #calculate the server CSC modes the server is allowed to use
        #based on the client CSC modes we can convert to in the backing class we use
        #and trim the transparency if we cannot handle it
        target_rgb_modes = list(rgb_modes)
        if not self._alpha_enabled:
            target_rgb_modes = [x for x in target_rgb_modes if x.find("A")<0]
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*target_rgb_modes)
        log("_get_full_csc_modes(%s)=%s (target_rgb_modes=%s)", rgb_modes, full_csc_modes, target_rgb_modes)
        return full_csc_modes


    def unpremultiply(self, img_data):
        if type(img_data) not in (str, _buffer):
            try:
                unpremultiply_argb_in_place(img_data)
                return img_data
            except:
                log.warn("failed to unpremultiply %s (len=%s)" % (type(img_data), len(img_data)))
        return unpremultiply_argb(img_data)


    def process_delta(self, raw_data, width, height, rowstride, options):
        """
            Can be called from any thread, decompresses and xors the rgb raw_data,
            then stores it for later xoring if needed.
        """
        img_data = raw_data
        if options:
            #check for one of the compressors:
            comp = [x for x in compression.ALL_COMPRESSORS if options.intget(x, 0)]
            if comp:
                assert len(comp)==1, "more than one compressor specified: %s" % str(comp)
                img_data = compression.decompress_by_name(raw_data, algo=comp[0])
        if len(img_data)!=rowstride * height:
            deltalog.error("invalid img data length: expected %s but got %s (%s: %s)", rowstride * height, len(img_data), type(img_data), str(img_data)[:256])
            raise Exception("expected %s bytes for %sx%s with rowstride=%s but received %s (%s compressed)" %
                                (rowstride * height, width, height, rowstride, len(img_data), len(raw_data)))
        delta = options.intget("delta", -1)
        bucket = options.intget("bucket", 0)
        rgb_format = options.strget("rgb_format")
        rgb_data = img_data
        if delta>=0:
            assert bucket>=0 and bucket<DELTA_BUCKETS, "invalid delta bucket number: %s" % bucket
            if self._delta_pixel_data[bucket] is None:
                raise Exception("delta region bucket %s references pixmap data we do not have!" % bucket)
            lwidth, lheight, lrgb_format, seq, ldata = self._delta_pixel_data[bucket]
            assert width==lwidth and height==lheight and delta==seq, \
                "delta bucket %s data does not match: expected %s but got %s" % (bucket, (width, height, delta), (lwidth, lheight, seq))
            assert lrgb_format==rgb_format, "delta region uses %s format, was expecting %s" % (rgb_format, lrgb_format)
            deltalog("delta: xoring with bucket %i", bucket)
            rgb_data = xor_str(img_data, ldata)
        #store new pixels for next delta:
        store = options.intget("store", -1)
        if store>=0:
            deltalog("delta: storing sequence %i in bucket %i", store, bucket)
            self._delta_pixel_data[bucket] =  width, height, rgb_format, store, rgb_data
        return rgb_data


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        """ can be called from any thread """
        #log("paint_image(%s, %s bytes, %s, %s, %s, %s, %s, %s)", coding, len(img_data), x, y, width, height, options, callbacks)
        PIL = get_codec("PIL")
        assert PIL.Image, "PIL.Image not found"
        buf = BytesIOClass(img_data)
        img = PIL.Image.open(buf)
        assert img.mode in ("L", "P", "RGB", "RGBA"), "invalid image mode: %s" % img.mode
        transparency = options.get("transparency", -1)
        if img.mode=="P":
            if transparency>=0:
                #this deals with alpha without any extra work
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
        elif img.mode=="L":
            if transparency>=0:
                #why do we have to deal with alpha ourselves??
                def mask_value(a):
                    if a!=transparency:
                        return 255
                    return 0
                mask = PIL.Image.eval(img, mask_value)
                mask = mask.convert("L")
                def nomask_value(a):
                    if a!=transparency:
                        return a
                    return 0
                img = PIL.Image.eval(img, nomask_value)
                img = img.convert("RGBA")
                img.putalpha(mask)
            else:
                img = img.convert("RGB")

        raw_data = img.tobytes("raw", img.mode)
        paint_options = typedict(options)
        rgb_format = img.mode
        if rgb_format=="RGB":
            #PIL flattens the data to a continuous straightforward RGB format:
            rowstride = width*3
            img_data = self.process_delta(raw_data, width, height, rowstride, options)
        elif rgb_format=="RGBA":
            rowstride = width*4
            img_data = self.process_delta(raw_data, width, height, rowstride, options)
        else:
            raise Exception("invalid image mode: %s" % img.mode)
        paint_options["rgb_format"] = rgb_format
        self.idle_add(self.do_paint_rgb, rgb_format, img_data, x, y, width, height, rowstride, paint_options, callbacks)
        return False

    def paint_rgb(self, rgb_format, raw_data, x, y, width, height, rowstride, options, callbacks):
        """ can be called from a non-UI thread
            this method calls process_delta
            before calling _do_paint_rgb from the UI thread via idle_add
        """
        rgb_data = self.process_delta(raw_data, width, height, rowstride, options)
        self.idle_add(self.do_paint_rgb, rgb_format, rgb_data, x, y, width, height, rowstride, options, callbacks)

    def do_paint_rgb(self, rgb_format, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from the UI thread
            this method is only here to ensure that we always fire the callbacks,
            the actual paint code is in _do_paint_rgb[24|32]
        """
        try:
            if not options.get("paint", True):
                fire_paint_callbacks(callbacks)
                return
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "no backing")
                return
            bpp = len(rgb_format)*8
            assert bpp in (24, 32), "invalid rgb format %s" % rgb_format
            paint_fn = getattr(self, "_do_paint_rgb%i" % bpp)
            success = paint_fn(img_data, x, y, width, height, rowstride, options)
            fire_paint_callbacks(callbacks, success)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if not self._backing:
                fire_paint_callbacks(callbacks, -1, "paint error on closed backing ignored")
            else:
                log.error("Error painting rgb%s", bpp, exc_info=True)
                message = "paint rgb%s error: %s" % (bpp, e)
                fire_paint_callbacks(callbacks, False, message)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        raise Exception("override me!")

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        raise Exception("override me!")


    def make_csc(self, src_width, src_height, src_format,
                       dst_width, dst_height, dst_format_options, speed):
        global CSC_OPTIONS
        in_options = CSC_OPTIONS.get(src_format, {})
        assert len(in_options)>0, "no csc options for '%s' input in %s" % (src_format, CSC_OPTIONS)
        for dst_format in dst_format_options:
            specs = in_options.get(dst_format)
            log("make_csc%s specs=%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, speed), specs)
            if not specs:
                continue
            for spec in specs:
                v = self.validate_csc_size(spec, src_width, src_height, dst_width, dst_height)
                if v:
                    continue
                try:
                    csc = spec.make_instance()
                    csc.init_context(src_width, src_height, src_format,
                               dst_width, dst_height, dst_format, speed)
                    return csc
                except Exception as e:
                    log("make_csc%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, speed), exc_info=True)
                    log.error("Error: failed to create csc instance %s", spec.codec_class)
                    log.error(" for %s to %s: %s", src_format, dst_format, e)
        log.error("Error: no matching CSC module found")
        log.error(" for %ix%i %s source format,", src_width, src_height, src_format)
        log.error(" to %ix%i %s", dst_width, dst_height, " or ".join(dst_format_options))
        log.error(" with options=%s, speed=%i", dst_format_options, speed)
        log.error(" tested:")
        for dst_format in dst_format_options:
            specs = in_options.get(dst_format)
            if not specs:
                continue
            log.error(" * %s:", dst_format)
            for spec in specs:
                log.error("   - %s:", spec)
                v = self.validate_csc_size(spec, src_width, src_height, dst_width, dst_height)
                if v:
                    log.error("       "+v[0], *v[1:])
        raise Exception("no csc module found for %s(%sx%s) to %s(%sx%s)" % (src_format, src_width, src_height, " or ".join(dst_format_options), dst_width, dst_height, CSC_OPTIONS))

    def validate_csc_size(self, spec, src_width, src_height, dst_width, dst_height):
        if not spec.can_scale and (src_width!=dst_width or src_height!=dst_height):
            return "scaling not suported"
        elif src_width<spec.min_w:
            return "source width %i is out of range: minimum is %i", src_width, spec.min_w
        elif src_height<spec.min_h:
            return "source height %i is out of range: minimum is %i", src_height, spec.min_h
        elif dst_width<spec.min_w:
            return "target width %i is out of range: minimum is %i", dst_width, spec.min_w
        elif dst_height<spec.min_h:
            return "target height %i is out of range: minimum is %i", dst_height, spec.min_h
        elif src_width>spec.max_w:
            return "source width %i is out of range: maximum is %i", src_width, spec.max_w
        elif src_height>spec.max_h:
            return "source height %i is out of range: maximum is %i", src_height, spec.max_h
        elif dst_width>spec.max_w:
            return "target width %i is out of range: maximum is %i", dst_width, spec.max_w
        elif dst_height>spec.max_h:
            return "target height %i is out of range: maximum is %i", dst_height, spec.max_h
        return None

    def paint_with_video_decoder(self, decoder_module, coding, img_data, x, y, width, height, options, callbacks):
        #log("paint_with_video_decoder%s", (decoder_module, coding, "%s bytes" % len(img_data), x, y, width, height, options, callbacks))
        assert decoder_module, "decoder module not found for %s" % coding
        dl = self._decoder_lock
        if dl is None:
            fire_paint_callbacks(callbacks, False, "no lock - retry")
            return
        with dl:
            if self._backing is None:
                message = "window %s is already gone!" % self.wid
                log(message)
                fire_paint_callbacks(callbacks, -1, message)
                return
            enc_width, enc_height = options.intpair("scaled_size", (width, height))
            input_colorspace = options.strget("csc")
            if not input_colorspace:
                message = "csc mode is missing from the video options!"
                log.error(message)
                fire_paint_callbacks(callbacks, False, message)
                return
            #do we need a prep step for decoders that cannot handle the input_colorspace directly?
            decoder_colorspaces = decoder_module.get_input_colorspaces(coding)
            assert input_colorspace in decoder_colorspaces, "decoder does not support %s for %s" % (input_colorspace, coding)

            vd = self._video_decoder
            if vd:
                if options.get("frame", -1)==0:
                    log("paint_with_video_decoder: first frame of new stream")
                    self.do_clean_video_decoder()
                elif vd.get_encoding()!=coding:
                    log("paint_with_video_decoder: encoding changed from %s to %s", vd.get_encoding(), coding)
                    self.do_clean_video_decoder()
                elif vd.get_width()!=enc_width or vd.get_height()!=enc_height:
                    log("paint_with_video_decoder: video dimensions have changed from %s to %s", (vd.get_width(), vd.get_height()), (enc_width, enc_height))
                    self.do_clean_video_decoder()
                elif vd.get_colorspace()!=input_colorspace:
                    #this should only happen on encoder restart, which means this should be the first frame:
                    log.warn("Warning: colorspace unexpectedly changed from %s to %s", vd.get_colorspace(), input_colorspace)
                    self.do_clean_video_decoder()
            if self._video_decoder is None:
                log("paint_with_video_decoder: new %s(%s,%s,%s)", decoder_module.Decoder, width, height, input_colorspace)
                vd = decoder_module.Decoder()
                vd.init_context(coding, enc_width, enc_height, input_colorspace)
                self._video_decoder = vd
                log("paint_with_video_decoder: info=%s", vd.get_info())

            img = vd.decompress_image(img_data, options)
            if not img:
                if options.get("delayed", 0)>0:
                    #there are further frames queued up,
                    #and this frame references those, so assume all is well:
                    fire_paint_callbacks(callbacks)
                else:
                    fire_paint_callbacks(callbacks, False, "video decoder %s failed to decode %i bytes of %s data" % (vd.get_type(), len(img_data), coding))
                    log.error("Error: decode failed on %s bytes of %s data", len(img_data), coding)
                    log.error(" %sx%s pixels using %s", width, height, vd.get_type())
                    log.error(" frame options:")
                    for k,v in options.items():
                        log.error("   %s=%s", k, v)
                return
            self.do_video_paint(img, x, y, enc_width, enc_height, width, height, options, callbacks)
        if self._backing is None:
            self.close_decoder(True)

    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        target_rgb_formats = self.RGB_MODES
        #as some video formats like vpx can forward transparency
        #also we could skip the csc step in some cases:
        pixel_format = img.get_pixel_format()
        cd = self._csc_decoder
        if cd is not None:
            if cd.get_src_format()!=pixel_format:
                log("do_video_paint csc: switching src format from %s to %s", cd.get_src_format(), pixel_format)
                self.do_clean_csc_decoder()
            elif cd.get_dst_format() not in target_rgb_formats:
                log("do_video_paint csc: switching dst format from %s to %s", cd.get_dst_format(), target_rgb_formats)
                self.do_clean_csc_decoder()
            elif cd.get_src_width()!=enc_width or cd.get_src_height()!=enc_height:
                log("do_video_paint csc: switching src size from %sx%s to %sx%s",
                         enc_width, enc_height, cd.get_src_width(), cd.get_src_height())
                self.do_clean_csc_decoder()
            elif cd.get_dst_width()!=width or cd.get_dst_height()!=height:
                log("do_video_paint csc: switching src size from %sx%s to %sx%s",
                         width, height, cd.get_dst_width(), cd.get_dst_height())
                self.do_clean_csc_decoder()
        if self._csc_decoder is None:
            #use higher quality csc to compensate for lower quality source
            #(which generally means that we downscaled via YUV422P or lower)
            #or when upscaling the video:
            q = options.intget("quality", 50)
            csc_speed = int(min(100, 100-q, 100.0 * (enc_width*enc_height) / (width*height)))
            cd = self.make_csc(enc_width, enc_height, pixel_format,
                                           width, height, target_rgb_formats, csc_speed)
            log("do_video_paint new csc decoder: %s", cd)
            self._csc_decoder = cd
        rgb_format = cd.get_dst_format()
        rgb = cd.convert_image(img)
        log("do_video_paint rgb using %s.convert_image(%s)=%s", cd, img, rgb)
        img.free()
        assert rgb.get_planes()==0, "invalid number of planes for %s: %s" % (rgb_format, rgb.get_planes())
        #make a new options dict and set the rgb format:
        paint_options = typedict(options)
        paint_options["rgb_format"] = rgb_format
        #this will also take care of firing callbacks (from the UI thread):
        def paint():
            data = rgb.get_pixels()
            rowstride = rgb.get_rowstride()
            try:
                self.do_paint_rgb(rgb_format, data, x, y, width, height, rowstride, paint_options, callbacks)
            finally:
                rgb.free()
        self.idle_add(paint)

    def paint_mmap(self, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from UI thread
            see _mmap_send() in server.py for details """
        assert self.mmap_enabled
        data = mmap_read(self.mmap, *img_data)
        rgb_format = options.strget("rgb_format", "RGB")
        #Note: BGR(A) is only handled by gl_window_backing
        self.do_paint_rgb(rgb_format, data, x, y, width, height, rowstride, options, callbacks)

    def paint_scroll(self, *args):
        raise NotImplementedError("no paint scroll on %s" % type(self))


    def draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        """ dispatches the paint to one of the paint_XXXX methods """
        try:
            assert self._backing is not None
            log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s, %s)", x, y, width, height, coding, len(img_data), rowstride, options, callbacks)
            coding = bytestostr(coding)
            options["encoding"] = coding            #used for choosing the color of the paint box
            if INTEGRITY_HASH:
                l = options.get("z.len")
                if l:
                    assert l==len(img_data), "compressed pixel data failed length integrity check: expected %i bytes but got %i" % (l, len(img_data))
                md5 = options.get("z.md5")
                if md5:
                    h = hashlib.md5(img_data)
                    hd = h.hexdigest()
                    assert md5==hd, "pixel data failed compressed md5 integrity check: expected %s but got %s" % (md5, hd)
                deltalog("passed compressed data integrity checks: len=%s, md5=%s (type=%s)", l, md5, type(img_data))
            if coding == "mmap":
                self.idle_add(self.paint_mmap, img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding == "rgb24" or coding == "rgb32":
                #avoid confusion over how many bytes-per-pixel we may have:
                rgb_format = options.get("rgb_format")
                if rgb_format:
                    Bpp = len(rgb_format)
                elif coding=="rgb24":
                    #legacy:
                    rgb_format = "RGB"
                else:
                    #legacy:
                    rgb_format = "RGBX"
                if rowstride==0:
                    rowstride = width * Bpp
                self.paint_rgb(rgb_format, img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding in VIDEO_DECODERS:
                self.paint_with_video_decoder(VIDEO_DECODERS.get(coding), coding, img_data, x, y, width, height, options, callbacks)
            elif self.jpeg_decoder and coding=="jpeg":
                self.paint_jpeg(img_data, x, y, width, height, options, callbacks)
            elif coding in self._PIL_encodings:
                self.paint_image(coding, img_data, x, y, width, height, options, callbacks)
            elif coding == "scroll":
                self.paint_scroll(x, y, width, height, img_data, options, callbacks)
            else:
                self.do_draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)
        except Exception:
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "this backing is closed - retry?")
            else:
                raise

    def do_draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        msg = "invalid encoding: '%s'" % coding
        log.error("Error: %s", msg)
        fire_paint_callbacks(callbacks, False, msg)
