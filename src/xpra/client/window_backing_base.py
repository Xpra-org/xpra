# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import hashlib
from threading import Lock

from xpra.net.mmap_pipe import mmap_read
from xpra.net import compression
from xpra.util import typedict, csv, envint, envbool, repr_ellipsized, first_time
from xpra.codecs.loader import get_codec
from xpra.codecs.video_helper import getVideoHelper
from xpra.os_util import bytestostr, _buffer
try:
    from xpra.codecs.xor.cyxor import xor_str   #@UnresolvedImport
except ImportError:
    from xpra.util import xor as xor_str
from xpra.log import Logger

#X11 constants we use for gravity:
NorthWestGravity = 1
NorthGravity     = 2
NorthEastGravity = 3
WestGravity      = 4
CenterGravity    = 5
EastGravity      = 6
SouthWestGravity = 7
SouthGravity     = 8
SouthEastGravity = 9
StaticGravity    = 10

GRAVITY_STR = {
    NorthWestGravity : "NorthWest",
    NorthGravity     : "North",
    NorthEastGravity : "NorthEast",
    WestGravity      : "West",
    CenterGravity    : "Center",
    EastGravity      : "East",
    SouthWestGravity : "SouthWest",
    SouthGravity     : "South",
    SouthEastGravity : "SouthEast",
    StaticGravity    : "South",
    }

log = Logger("paint")
deltalog = Logger("delta")

DELTA_BUCKETS = envint("XPRA_DELTA_BUCKETS", 5)
INTEGRITY_HASH = envbool("XPRA_INTEGRITY_HASH", False)
PAINT_BOX = envint("XPRA_PAINT_BOX", 0) or envint("XPRA_OPENGL_PAINT_BOX", 0)
WEBP_PILLOW = envbool("XPRA_WEBP_PILLOW", False)
SCROLL_ENCODING = envbool("XPRA_SCROLL_ENCODING", True)
REPAINT_ALL = envbool("XPRA_REPAINT_ALL", False)


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
                assert decoders
                #use the first one:
                _, decoder_module = decoders[0]
                VIDEO_DECODERS[encoding] = decoder_module
        log("video decoders: %s", dict((e,d.get_type()) for e,d in VIDEO_DECODERS.items()))
    return VIDEO_DECODERS


def fire_paint_callbacks(callbacks, success=True, message=""):
    for x in callbacks:
        try:
            x(success, message)
        except Exception:
            log.error("error calling %s(%s)", x, success, exc_info=True)


"""
Generic superclass for all Backing code,
see CairoBackingBase and GTK2WindowBacking subclasses for actual implementations
"""
class WindowBackingBase(object):
    RGB_MODES = ()

    def __init__(self, wid, window_alpha):
        load_csc_options()
        load_video_decoders()
        self.wid = wid
        self.size = 0, 0
        self.render_size = 0, 0
        self.offsets = 0, 0, 0, 0       #top,left,bottom,right
        self.gravity = 0
        self._alpha_enabled = window_alpha
        self._backing = None
        self._delta_pixel_data = [None for _ in range(DELTA_BUCKETS)]
        self._video_decoder = None
        self._csc_decoder = None
        self._decoder_lock = Lock()
        self._PIL_encodings = []
        self.default_paint_box_line_width = PAINT_BOX or 1
        self.paint_box_line_width = PAINT_BOX
        self.pointer_overlay = None
        self.cursor_data = None
        self.default_cursor_data = None
        self.jpeg_decoder = None
        self.webp_decoder = None
        self.pil_decoder = get_codec("dec_pillow")
        if self.pil_decoder:
            self._PIL_encodings = self.pil_decoder.get_encodings()
        self.jpeg_decoder = get_codec("dec_jpeg")
        self.webp_decoder = get_codec("dec_webp")
        self.draw_needs_refresh = True
        self.repaint_all = REPAINT_ALL
        self.mmap = None
        self.mmap_enabled = False

    def idle_add(self, *_args, **_kwargs):
        raise NotImplementedError()

    def enable_mmap(self, mmap_area):
        self.mmap = mmap_area
        self.mmap_enabled = True

    def gravity_copy_coords(self, oldw, oldh, bw, bh):
        sx = sy = dx = dy = 0
        def center_y():
            if bh>=oldh:
                #take the whole source, paste it in the middle
                return 0, (bh-oldh)//2
            #skip the edges of the source, paste all of it
            return (oldh-bh)//2, 0
        def center_x():
            if bw>=oldw:
                return 0, (bw-oldw)//2
            return (oldw-bw)//2, 0
        def east_x():
            if bw>=oldw:
                return 0, bw-oldw
            return oldw-bw, 0
        def west_x():
            return 0, 0
        def north_y():
            return 0, 0
        def south_y():
            if bh>=oldh:
                return 0, bh-oldh
            return oldh-bh, 0
        g = self.gravity
        if not g or g==NorthWestGravity:
            #undefined (or 0), use NW
            sx, dx = west_x()
            sy, dy = north_y()
        elif g==NorthGravity:
            sx, dx = center_x()
            sy, dy = north_y()
        elif g==NorthEastGravity:
            sx, dx = east_x()
            sy, dy = north_y()
        elif g==WestGravity:
            sx, dx = west_x()
            sy, dy = center_y()
        elif g==CenterGravity:
            sx, dx = center_x()
            sy, dy = center_y()
        elif g==EastGravity:
            sx, dx = east_x()
            sy, dy = center_y()
        elif g==SouthWestGravity:
            sx, dx = west_x()
            sy, dy = south_y()
        elif g==SouthGravity:
            sx, dx = center_x()
            sy, dy = south_y()
        elif g==SouthEastGravity:
            sx, dx = east_x()
            sy, dy = south_y()
        elif g==StaticGravity:
            if first_time("StaticGravity-%i" % self.wid):
                log.warn("Warning: static gravity is not handled")
        w = min(bw, oldw)
        h = min(bh, oldh)
        return sx, sy, dx, dy, w, h

    def gravity_adjust(self, x, y, options):
        #if the window size has changed,
        #adjust the coordinates honouring the window gravity:
        window_size = options.intlistget("window-size", None)
        g = self.gravity
        log("gravity_adjust%s window_size=%s, size=%s, gravity=%s",
            (x, y, options), window_size, self.size, GRAVITY_STR.get(g, "unknown"))
        if not window_size:
            return x, y
        window_size = tuple(window_size)
        if window_size==self.size:
            return x, y
        if g==0 or self.gravity==NorthWestGravity:
            return x, y
        oldw, oldh = window_size
        bw, bh = self.size
        def center_y():
            if bh>=oldh:
                return y + (bh-oldh)//2
            return y - (oldh-bh)//2
        def center_x():
            if bw>=oldw:
                return x + (bw-oldw)//2
            return x - (oldw-bw)//2
        def east_x():
            if bw>=oldw:
                return x + (bw-oldw)
            return x - (oldw-bw)
        def west_x():
            return x
        def north_y():
            return y
        def south_y():
            if bh>=oldh:
                return y + (bh-oldh)
            return y - (oldh-bh)
        if g==NorthGravity:
            return center_x(), north_y()
        if g==NorthEastGravity:
            return east_x(), north_y()
        if g==WestGravity:
            return west_x(), center_y()
        if g==CenterGravity:
            return center_x(), center_y()
        if g==EastGravity:
            return east_x(), center_y()
        if g==SouthWestGravity:
            return west_x(), south_y()
        if g==SouthGravity:
            return center_x(), south_y()
        if g==SouthEastGravity:
            return east_x(), south_y()
        #if self.gravity==StaticGravity:
        #    pass
        return x, y


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
                 "encoding.send-window-size" : True,
                 }

    def _get_full_csc_modes(self, rgb_modes):
        #calculate the server CSC modes the server is allowed to use
        #based on the client CSC modes we can convert to in the backing class we use
        #and trim the transparency if we cannot handle it
        target_rgb_modes = tuple(rgb_modes)
        if not self._alpha_enabled:
            target_rgb_modes = tuple(x for x in target_rgb_modes if x.find("A")<0)
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*target_rgb_modes)
        full_csc_modes["webp"] = [x for x in rgb_modes if x in ("BGRX", "BGRA", "RGBX", "RGBA")]
        log("_get_full_csc_modes(%s)=%s (target_rgb_modes=%s)", rgb_modes, full_csc_modes, target_rgb_modes)
        return full_csc_modes


    def unpremultiply(self, img_data):
        from xpra.codecs.argb.argb import unpremultiply_argb, unpremultiply_argb_in_place   #@UnresolvedImport
        if type(img_data) not in (str, _buffer):
            try:
                unpremultiply_argb_in_place(img_data)
                return img_data
            except Exception:
                log.warn("failed to unpremultiply %s (len=%s)" % (type(img_data), len(img_data)))
        return unpremultiply_argb(img_data)


    def set_cursor_data(self, cursor_data):
        self.cursor_data = cursor_data


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
            deltalog.error("Error: invalid img data length: expected %s but got %s (%s: %s)",
                           rowstride * height, len(img_data), type(img_data), repr_ellipsized(img_data))
            raise Exception("expected %s bytes for %sx%s with rowstride=%s but received %s (%s compressed)" %
                                (rowstride * height, width, height, rowstride, len(img_data), len(raw_data)))
        delta = options.intget(b"delta", -1)
        bucket = options.intget(b"bucket", 0)
        rgb_format = options.strget(b"rgb_format")
        rgb_data = img_data
        if delta>=0:
            assert 0<=bucket<DELTA_BUCKETS, "invalid delta bucket number: %s" % bucket
            if self._delta_pixel_data[bucket] is None:
                raise Exception("delta region bucket %s references pixmap data we do not have!" % bucket)
            lwidth, lheight, lrgb_format, seq, ldata = self._delta_pixel_data[bucket]
            assert width==lwidth and height==lheight and delta==seq, \
                "delta bucket %s data does not match: expected %s but got %s" % (
                    bucket, (width, height, delta), (lwidth, lheight, seq))
            assert lrgb_format==rgb_format, "delta region uses %s format, was expecting %s" % (rgb_format, lrgb_format)
            deltalog("delta: xoring with bucket %i", bucket)
            rgb_data = xor_str(img_data, ldata)
        #store new pixels for next delta:
        store = options.intget("store", -1)
        if store>=0:
            deltalog("delta: storing sequence %i in bucket %i", store, bucket)
            self._delta_pixel_data[bucket] =  width, height, rgb_format, store, rgb_data
        return rgb_data


    def paint_jpeg(self, img_data, x, y, width, height, options, callbacks):
        img = self.jpeg_decoder.decompress_to_rgb("RGBX", img_data, width, height, options)
        rgb_format = img.get_pixel_format()
        img_data = img.get_pixels()
        rowstride = img.get_rowstride()
        w = img.get_width()
        h = img.get_height()
        self.idle_add(self.paint_rgb, rgb_format, img_data, x, y, w, h, rowstride, options, callbacks)


    def paint_image(self, coding, img_data, x, y, width, height, options, callbacks):
        # can be called from any thread
        rgb_format, raw_data, rowstride = self.pil_decoder.decompress(coding, img_data, options)
        img_data = self.process_delta(raw_data, width, height, rowstride, options)
        self.idle_add(self.do_paint_rgb, rgb_format, img_data, x, y, width, height, rowstride, options, callbacks)

    def paint_webp(self, img_data, x, y, width, height, options, callbacks):
        if not self.webp_decoder or WEBP_PILLOW:
            #if webp is enabled, then Pillow should be able to take care of it:
            self.paint_image("webp", img_data, x, y, width, height, options, callbacks)
            return
        rgb_format = options.strget("rgb_format")
        has_alpha = options.boolget("has_alpha", False)
        (
            buffer_wrapper,
            width, height, stride, has_alpha,
            rgb_format,
            ) = self.webp_decoder.decompress(img_data, has_alpha, rgb_format, self.RGB_MODES)
        def free_buffer(*_args):
            buffer_wrapper.free()
        callbacks.append(free_buffer)
        data = buffer_wrapper.get_pixels()
        #if the backing can't handle this format,
        #ie: tray only supports RGBA
        if rgb_format not in self.RGB_MODES:
            from xpra.codecs.rgb_transform import rgb_reformat
            from xpra.codecs.image_wrapper import ImageWrapper
            img = ImageWrapper(x, y, width, height, data, rgb_format,
                               len(rgb_format)*8, stride, len(rgb_format), ImageWrapper.PACKED, True, None)
            rgb_reformat(img, self.RGB_MODES, has_alpha and self._alpha_enabled)
            rgb_format = img.get_pixel_format()
            data = img.get_pixels()
            stride = img.get_rowstride()
        #replace with the actual rgb format we get from the decoder:
        options[b"rgb_format"] = rgb_format
        return self.paint_rgb(rgb_format, data, x, y, width, height, stride, options, callbacks)

    def paint_rgb(self, rgb_format, raw_data, x, y, width, height, rowstride, options, callbacks):
        """ can be called from a non-UI thread
            this method calls process_delta
            before calling _do_paint_rgb from the UI thread via idle_add
        """
        rgb_data = self.process_delta(raw_data, width, height, rowstride, options)
        x, y = self.gravity_adjust(x, y, options)
        self.idle_add(self.do_paint_rgb, rgb_format, rgb_data, x, y, width, height, rowstride, options, callbacks)

    def do_paint_rgb(self, rgb_format, img_data, x, y, width, height, rowstride, options, callbacks):
        """ must be called from the UI thread
            this method is only here to ensure that we always fire the callbacks,
            the actual paint code is in _do_paint_rgb[24|32]
        """
        try:
            if not options.boolget("paint", True):
                fire_paint_callbacks(callbacks)
                return
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "no backing")
                return
            bpp = len(rgb_format)*8
            assert bpp in (24, 32), "invalid rgb format '%s'" % rgb_format
            paint_fn = getattr(self, "_do_paint_rgb%i" % bpp)
            options[b"rgb_format"] = rgb_format
            success = paint_fn(img_data, x, y, width, height, rowstride, options)
            fire_paint_callbacks(callbacks, success)
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


    def eos(self):
        dl = self._decoder_lock
        with dl:
            self.do_clean_csc_decoder()
            self.do_clean_video_decoder()


    def make_csc(self, src_width, src_height, src_format,
                       dst_width, dst_height, dst_format_options, speed):
        global CSC_OPTIONS
        in_options = CSC_OPTIONS.get(src_format, {})
        assert in_options, "no csc options for '%s' input in %s" % (src_format, CSC_OPTIONS)
        for dst_format in dst_format_options:
            specs = in_options.get(dst_format)
            log("make_csc%s specs=%s",
                (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, speed), specs)
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
                    log("make_csc%s",
                        (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, speed),
                        exc_info=True)
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
        raise Exception("no csc module found for %s(%sx%s) to %s(%sx%s) in %s" %
                        (src_format, src_width, src_height, " or ".join(dst_format_options),
                         dst_width, dst_height, CSC_OPTIONS))

    def validate_csc_size(self, spec, src_width, src_height, dst_width, dst_height):
        if not spec.can_scale and (src_width!=dst_width or src_height!=dst_height):
            return "scaling not suported"
        if src_width<spec.min_w:
            return "source width %i is out of range: minimum is %i", src_width, spec.min_w
        if src_height<spec.min_h:
            return "source height %i is out of range: minimum is %i", src_height, spec.min_h
        if dst_width<spec.min_w:
            return "target width %i is out of range: minimum is %i", dst_width, spec.min_w
        if dst_height<spec.min_h:
            return "target height %i is out of range: minimum is %i", dst_height, spec.min_h
        if src_width>spec.max_w:
            return "source width %i is out of range: maximum is %i", src_width, spec.max_w
        if src_height>spec.max_h:
            return "source height %i is out of range: maximum is %i", src_height, spec.max_h
        if dst_width>spec.max_w:
            return "target width %i is out of range: maximum is %i", dst_width, spec.max_w
        if dst_height>spec.max_h:
            return "target height %i is out of range: maximum is %i", dst_height, spec.max_h
        return None

    def paint_with_video_decoder(self, decoder_module, coding, img_data, x, y, width, height, options, callbacks):
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
                if options.intget("frame", -1)==0:
                    log("paint_with_video_decoder: first frame of new stream")
                    self.do_clean_video_decoder()
                elif vd.get_encoding()!=coding:
                    log("paint_with_video_decoder: encoding changed from %s to %s", vd.get_encoding(), coding)
                    self.do_clean_video_decoder()
                elif vd.get_width()!=enc_width or vd.get_height()!=enc_height:
                    log("paint_with_video_decoder: video dimensions have changed from %s to %s",
                        (vd.get_width(), vd.get_height()), (enc_width, enc_height))
                    self.do_clean_video_decoder()
                elif vd.get_colorspace()!=input_colorspace:
                    #this should only happen on encoder restart, which means this should be the first frame:
                    log.warn("Warning: colorspace unexpectedly changed from %s to %s",
                             vd.get_colorspace(), input_colorspace)
                    self.do_clean_video_decoder()
            if self._video_decoder is None:
                log("paint_with_video_decoder: new %s(%s,%s,%s)",
                    decoder_module.Decoder, width, height, input_colorspace)
                vd = decoder_module.Decoder()
                vd.init_context(coding, enc_width, enc_height, input_colorspace)
                self._video_decoder = vd
                log("paint_with_video_decoder: info=%s", vd.get_info())

            img = vd.decompress_image(img_data, options)
            if not img:
                if options.intget("delayed", 0)>0:
                    #there are further frames queued up,
                    #and this frame references those, so assume all is well:
                    fire_paint_callbacks(callbacks)
                else:
                    fire_paint_callbacks(callbacks, False,
                                         "video decoder %s failed to decode %i bytes of %s data" % (
                                             vd.get_type(), len(img_data), coding))
                    log.error("Error: decode failed on %s bytes of %s data", len(img_data), coding)
                    log.error(" %sx%s pixels using %s", width, height, vd.get_type())
                    log.error(" frame options:")
                    for k,v in options.items():
                        log.error("   %s=%s", k, v)
                return

            x, y = self.gravity_adjust(x, y, options)
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
        rgb_format = options.strget(b"rgb_format", b"RGB")
        #Note: BGR(A) is only handled by gl_window_backing
        x, y = self.gravity_adjust(x, y, options)
        self.do_paint_rgb(rgb_format, data, x, y, width, height, rowstride, options, callbacks)

    def paint_scroll(self, _img_data, _options, callbacks):
        raise NotImplementedError("no paint scroll on %s" % type(self))


    def draw_region(self, x, y, width, height, coding, img_data, rowstride, options, callbacks):
        """ dispatches the paint to one of the paint_XXXX methods """
        try:
            assert self._backing is not None
            log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s, %s)",
                x, y, width, height, coding, len(img_data), rowstride, options, callbacks)
            coding = bytestostr(coding)
            options["encoding"] = coding            #used for choosing the color of the paint box
            if INTEGRITY_HASH:
                l = options.intget("z.len")
                if l:
                    assert l==len(img_data), "compressed pixel data failed length integrity check: expected %i bytes but got %i" % (l, len(img_data))
                try:
                    chksum = options.get("z.md5")
                    if chksum:
                        h = hashlib.md5(img_data)
                except ValueError:
                    chksum = options.get("z.sha1")
                    if chksum:
                        h = hashlib.sha1(img_data)
                if h:
                    hd = h.hexdigest()
                    assert chksum==hd, "pixel data failed compressed chksum integrity check: expected %s but got %s" % (chksum, hd)
                deltalog("passed compressed data integrity checks: len=%s, chksum=%s (type=%s)", l, chksum, type(img_data))
            if coding == "mmap":
                self.idle_add(self.paint_mmap, img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding in ("rgb24", "rgb32"):
                #avoid confusion over how many bytes-per-pixel we may have:
                rgb_format = options.strget(b"rgb_format")
                if not rgb_format:
                    rgb_format = {
                        "rgb24" : "RGB",
                        "rgb32" : "RGBX",
                        }.get(coding)
                if rowstride==0:
                    rowstride = width * len(rgb_format)
                self.paint_rgb(rgb_format, img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding in VIDEO_DECODERS:
                self.paint_with_video_decoder(VIDEO_DECODERS.get(coding),
                                              coding,
                                              img_data, x, y, width, height, options, callbacks)
            elif self.jpeg_decoder and coding=="jpeg":
                self.paint_jpeg(img_data, x, y, width, height, options, callbacks)
            elif coding == "webp":
                self.paint_webp(img_data, x, y, width, height, options, callbacks)
            elif coding in self._PIL_encodings:
                self.paint_image(coding, img_data, x, y, width, height, options, callbacks)
            elif coding == "scroll":
                self.paint_scroll(img_data, options, callbacks)
            else:
                self.do_draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)
        except Exception:
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "this backing is closed - retry?")
            else:
                raise

    def do_draw_region(self, _x, _y, _width, _height, coding, _img_data, _rowstride, _options, callbacks):
        msg = "invalid encoding: '%s'" % coding
        log.error("Error: %s", msg)
        fire_paint_callbacks(callbacks, False, msg)
