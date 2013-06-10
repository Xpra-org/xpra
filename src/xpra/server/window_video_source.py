# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from threading import Lock

from xpra.net.protocol import Compressed
from xpra.codecs.codec_constants import get_avutil_enum_from_colorspace, get_subsampling_divs
from xpra.codecs.video_enc_pipeline import VideoPipelineHelper
from xpra.server.window_source import WindowSource, debug, log

SCALING = os.environ.get("XPRA_SCALING", "1")=="1"


class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    _video_pipeline_helper = VideoPipelineHelper()

    def __init__(self, *args):
        WindowSource.__init__(self, *args)
        #client uses uses_swscale (has extra limits on sizes)
        self.uses_swscale = self.encoding_options.get("uses_swscale", True)
        self.uses_csc_atoms = self.encoding_options.get("csc_atoms", False)
        self.video_scaling = self.encoding_options.get("video_scaling", False)
        if not self.encoding_client_options:
            #old clients can only use 420P:
            def_csc_modes = ("YUV420P")
        else:
            #default for newer clients that don't specify "csc_modes":
            def_csc_modes = ("YUV420P", "YUV422P", "YUV444P")
        #0.10 onwards should have specified csc_modes:
        self.csc_modes = self.encoding_options.get("csc_modes", def_csc_modes)

        for x in ("vpx", "x264"):
            if x in self.SERVER_CORE_ENCODINGS:
                self._encoders[x] = self.video_encode

        self.width_mask = 0xFFFF
        self.height_mask = 0xFFFF

        self._csc_encoder = None
        self._video_encoder = None
        self._lock = Lock()               #to ensure we serialize access to the encoder and its internals

        self._video_pipeline_helper.may_init()

    def add_stats(self, info, metadata, suffix=""):
        WindowSource.add_stats(self, info, metadata, suffix)
        prefix = "window[%s]." % self.wid
        if self._csc_encoder:
            info[prefix+"csc"+suffix] = self._csc_encoder.get_type()
            ci = self._csc_encoder.get_info()
            for k,v in ci.items():
                info[prefix+"csc."+k+suffix] = v
        if self._video_encoder:
            info[prefix+"encoder"+suffix] = self._video_encoder.get_type()
            vi = self._video_encoder.get_info()
            for k,v in vi.items():
                info[prefix+"encoder."+k+suffix] = v

    def cleanup(self):
        WindowSource.cleanup(self)
        self.cleanup_codecs()

    def cleanup_codecs(self):
        """ Video encoders (x264 and vpx) require us to run
            cleanup code to free the memory they use.
        """
        try:
            self._lock.acquire()
            if self._csc_encoder:
                self.do_csc_encoder_cleanup()
            if self._video_encoder:
                self.do_video_encoder_cleanup()
        finally:
            self._lock.release()

    def do_csc_encoder_cleanup(self):
        self._csc_encoder.clean()
        self._csc_encoder = None

    def do_video_encoder_cleanup(self):
        self._video_encoder.clean()
        self._video_encoder = None

    def set_new_encoding(self, encoding):
        if self.encoding!=encoding:
            #ensure we re-init the codecs asap:
            self.cleanup_codecs()
        WindowSource.set_new_encoding(self, encoding)


    def cancel_damage(self):
        WindowSource.cancel_damage(self)
        if self._last_sequence_queued<self._sequence:
            #we must clean the video encoder to ensure
            #we will resend a key frame because it looks like we will
            #drop a frame which is being processed
            self.cleanup_codecs()

    def process_damage_region(self, damage_time, window, x, y, w, h, coding, options):
        WindowSource.process_damage_region(self, damage_time, window, x, y, w, h, coding, options)
        #now figure out if we need to send edges separately:
        dw = w - (w & self.width_mask)
        dh = h - (h & self.height_mask)
        if coding in ("vpx", "x264") and (dw>0 or dh>0):
            if dw>0:
                lossless = self.find_common_lossless_encoder(window.has_alpha(), coding, dw*h)
                WindowSource.process_damage_region(self, damage_time, window, x+w-dw, y, dw, h, lossless, options)
            if dh>0:
                lossless = self.find_common_lossless_encoder(window.has_alpha(), coding, w*dh)
                WindowSource.process_damage_region(self, damage_time, window, x, y+h-dh, x+w, dh, lossless, options)


    def reconfigure(self, force_reload=False):
        """
            This is called when we want to force a full re-init (force_reload=True)
            or from the timer that allows to tune the quality and speed.
            (this tuning is done in WindowSource.reconfigure)
            Here we re-evaluate if the pipeline we are currently using
            is really the best one, and if not we switch to the best one.
            This uses get_video_pipeline_options() to get a list of pipeline
            options with a score for each.
        """
        debug("reconfigure(%s) csc_encoder=%s, video_encoder=%s", force_reload, self._csc_encoder, self._video_encoder)
        WindowSource.reconfigure(self, force_reload)
        if not self._video_encoder:
            return
        try:
            self._lock.acquire()
            ve = self._video_encoder
            if not ve or ve.is_closed():
                #could have been freed since we got the lock!
                return
            if force_reload:
                self.do_csc_encoder_cleanup()
                self.do_video_encoder_cleanup()
                return

            pixel_format = None
            if self._csc_encoder:
                pixel_format = self._csc_encoder.get_src_format()
            else:
                pixel_format = ve.get_src_format()
            width = ve.get_width()
            height = ve.get_height()
            quality = self.get_current_quality()
            speed = self.get_current_speed()

            scores = self.get_video_pipeline_options(ve.get_type(), width, height, pixel_format)
            if len(scores)>0:
                debug("reconfigure(%s) best=%s", force_reload, scores[0])
                _, csc_spec, enc_in_format, encoder_spec = scores[0]
                if self._csc_encoder:
                    if csc_spec is None or \
                       type(self._csc_encoder)!=csc_spec.codec_class or \
                       self._csc_encoder.get_dst_format()!=enc_in_format:
                        debug("reconfigure(%s) found better csc encoder: %s", force_reload, scores[0])
                        self.do_csc_encoder_cleanup()
                if type(self._video_encoder)!=encoder_spec.codec_class or \
                   self._video_encoder.get_src_format()!=enc_in_format:
                    debug("reconfigure(%s) found better video encoder: %s", force_reload, scores[0])
                    self.do_video_encoder_cleanup()

            if self._video_encoder is None:
                self.setup_pipeline(scores, width, height, pixel_format)

            if self._video_encoder:
                self._video_encoder.set_encoding_speed(speed)
                self._video_encoder.set_encoding_quality(quality)
        finally:
            self._lock.release()


    def get_video_pipeline_options(self, encoding, width, height, src_format):
        """
            Given a picture format (width, height and src pixel format),
            we find all the pipeline options that will allow us to compress
            it using the given encoding.
            First, we try with direct encoders (for those that support the
            source pixel format natively), then we try all the combinations
            using csc encoders to convert to an intermediary format.
            Each solution is rated and we return all of them in descending
            score (best solution comes first).
        """
        encoder_specs = self._video_pipeline_helper.get_encoder_specs(encoding)
        assert len(encoder_specs)>0, "cannot handle %s encoding!" % encoding
        scores = []
        def add_scores(info, csc_spec, enc_in_format):
            colorspace_specs = encoder_specs.get(enc_in_format)
            #first, add the direct matches (no csc needed) - if any:
            if colorspace_specs:
                #debug("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
                for encoder_spec in colorspace_specs:
                    score = self.get_score(enc_in_format,
                                           csc_spec, encoder_spec,
                                           width, height)
                    if score>=0:
                        item = score, csc_spec, enc_in_format, encoder_spec
                        scores.append(item)
        if src_format in self.csc_modes:
            add_scores("direct (no csc)", None, src_format)
        #now add those that require a csc step:
        csc_specs = self._video_pipeline_helper.get_csc_specs(src_format)
        if csc_specs:
            #debug("%s can also be converted to %s using %s", pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
            #we have csc module(s) that can get us from pixel_format to out_csc:
            for out_csc, csc_spec in csc_specs:
                if out_csc in self.csc_modes:
                    add_scores("via %s" % out_csc, csc_spec, out_csc)
        s = sorted(scores, key=lambda x : -x[0])
        debug("get_video_pipeline_options%s scores=%s", (encoding, width, height, src_format), s)
        return s

    def get_score(self, csc_format, csc_spec, encoder_spec, width, height):
        """
            Given an optional csc step (csc_format and csc_spec), and
            and a required encoding step (encoder_spec and width/height),
            we calculate a score of how well this matches our requirements:
            * our quality target (as per get_currend_quality)
            * our speed target (as per get_current_speed)
            * how expensive it would be to switch to this pipeline option
            Note: we know the current pipeline settings, so the "switching
            cost" will be lower for pipelines that share components with the
            current one.
        """
        #first discard if we cannot handle this size:
        if csc_spec and not csc_spec.can_handle(width, height):
            return -1
        if not encoder_spec.can_handle(width, height):
            return -1
        #debug("get_score%s", (csc_format, csc_spec, encoder_spec,
        #          width, height, min_quality, target_quality, min_speed, target_speed))
        def clamp(v):
            return max(0, min(100, v))
        #evaluate output quality:
        quality = clamp(encoder_spec.quality)
        if csc_format and csc_format in ("YUV420P", "YUV422P", "YUV444P"):
            #account for subsampling (reduces quality):
            y,u,v = get_subsampling_divs(csc_format)
            div = 0.5   #any colourspace convertion will lose at least some quality (due to rounding)
            for div_x, div_y in (y, u, v):
                div += (div_x+div_y)/2.0/3.0
            quality = quality / div
        if csc_spec and csc_spec.quality<100:
            #csc_spec.quality is the upper limit (up to 100):
            quality *= csc_spec.quality/100.0
        #score based on how far we are:
        if quality<self.get_min_quality():
            qscore = 0
        else:
            qscore = 100-abs(quality-self.get_current_quality())

        #score based on speed:
        speed = clamp(encoder_spec.speed)
        if csc_spec:
            speed *= csc_spec.speed/100.0
        if speed<self.get_min_speed():
            sscore = 0
        else:
            sscore = 100-abs(speed-self.get_current_speed())

        #score for "edge resistance":
        ecsc_score = 100
        if csc_spec:
            #OR the masks so we have a chance of making it work
            width_mask = csc_spec.width_mask & encoder_spec.width_mask
            height_mask = csc_spec.height_mask & encoder_spec.height_mask
            csc_width = width & width_mask
            csc_height = height & height_mask
            if self._csc_encoder is None or self._csc_encoder.get_dst_format()!=csc_format or \
               type(self._csc_encoder)!=csc_spec.codec_class or \
               self._csc_encoder.get_src_width()!=csc_width or self._csc_encoder.get_src_height()!=csc_height:
                #if we have to change csc, account for new csc setup cost:
                ecsc_score = 100 - csc_spec.setup_cost
            enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height)
        else:
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            enc_width = width & width_mask
            enc_height = height & height_mask
        ee_score = 100
        if self._video_encoder is None or type(self._video_encoder)!=encoder_spec.codec_class or \
           self._video_encoder.get_src_format()!=csc_format or \
           self._video_encoder.get_width()!=enc_width or self._video_encoder.get_height()!=enc_height:
            #account for new encoder setup cost:
            ee_score = 100 - encoder_spec.setup_cost
        #edge resistance score: average of csc and encoder score:
        er_score = (ecsc_score + ee_score) / 2.0
        debug("get_score%s %s/%s/%s", (csc_format, csc_spec, encoder_spec,
                  width, height), int(qscore), int(sscore), int(er_score))
        return int((qscore+sscore+er_score)/3.0)

    def get_encoder_dimensions(self, csc_spec, encoder_spec, width, height):
        """
            Given a csc and encoder specs and dimensions, we calculate
            the dimensions that we would use as output.
            Taking into account:
            * applications can require scaling (see "scaling" attribute)
            * we scale fullscreen and maximize windows when at high speed
              and low quality.
            * we do not bother scaling small dimensions
            * the encoder may not support all dimensions
              (see width and height masks)
        """
        #TODO: framerate is relevant, probably
        if not SCALING:
            return width, height
        scaling = self.scaling
        if not self.video_scaling:
            scaling = None
        if scaling is None:
            quality = self.get_current_quality()
            speed = self.get_current_speed()
            if width*height>=1024*1024 and quality<30 and speed>90:
                scaling = 2,3
            elif self.maximized and quality<50 and speed>80:
                scaling = 2,3
            elif self.fullscreen and quality<60 and speed>70:
                scaling = 1,2
        if scaling is None:
            return width, height
        v, u = scaling
        if v/u>1.0:         #never upscale before encoding!
            return width, height
        if float(v)/float(u)<0.1:         #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            v, u = 1, 10
        enc_width = int(width * v / u) & encoder_spec.width_mask
        enc_height = int(height * v / u) & encoder_spec.height_mask
        if not encoder_spec.can_handle(enc_width, enc_height):
            return width, height
        return enc_width, enc_height


    def check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
        debug("check_pipeline%s", (encoding, width, height, src_format))
        #must be called with video lock held!
        if self.do_check_pipeline(encoding, width, height, src_format):
            return True  #OK!

        #cleanup existing one if needed:
        if self._csc_encoder:
            self.do_csc_encoder_cleanup()
        if self._video_encoder:
            self.do_video_encoder_cleanup()
        #and make a new one:
        scores = self.get_video_pipeline_options(encoding, width, height, src_format)
        return self.setup_pipeline(scores, width, height, src_format)

    def do_check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
        debug("do_check_pipeline%s", (encoding, width, height, src_format))
        #must be called with video lock held!
        if self._video_encoder is None:
            return False

        if self._csc_encoder:
            csc_width = width & self.width_mask
            csc_height = height & self.height_mask
            if self._csc_encoder.get_src_format()!=src_format:
                debug("check_pipeline csc: switching source format from %s to %s",
                                            self._csc_encoder.get_src_format(), src_format)
                return False
            elif self._csc_encoder.get_src_width()!=csc_width or self._csc_encoder.get_src_height()!=csc_height:
                debug("check_pipeline csc: window dimensions have changed from %sx%s to %sx%s, csc info=%s",
                                            self._csc_encoder.get_src_width(), self._csc_encoder.get_src_height(), csc_width, csc_height, self._csc_encoder.get_info())
                return False
            elif self._csc_encoder.get_dst_format()!=self._video_encoder.get_src_format():
                log.warn("check_pipeline csc: intermediate format mismatch: %s vs %s, csc info=%s",
                                            self._csc_encoder.get_dst_format(), self._video_encoder.get_src_format(), self._csc_encoder.get_info())
                return False

            encoder_src_format = self._csc_encoder.get_dst_format()
            encoder_src_width = self._csc_encoder.get_dst_width()
            encoder_src_height = self._csc_encoder.get_dst_height()
        else:
            #direct to video encoder without csc:
            encoder_src_format = src_format
            encoder_src_width = width & self.width_mask
            encoder_src_height = height & self.height_mask

        if self._video_encoder.get_src_format()!=encoder_src_format:
            debug("check_pipeline video: invalid source format %s, expected %s",
                                            self._video_encoder.get_src_format(), encoder_src_format)
            return False
        elif self._video_encoder.get_type()!=encoding:
            debug("check_pipeline video: invalid encoding %s, expected %s",
                                            self._video_encoder.get_type(), encoding)
            return False
        elif self._video_encoder.get_width()!=encoder_src_width or self._video_encoder.get_height()!=encoder_src_height:
            debug("check_pipeline video: window dimensions have changed from %sx%s to %sx%s",
                                            self._video_encoder.get_width(), self._video_encoder.get_height(), encoder_src_width, encoder_src_height)
            return False
        return True


    def setup_pipeline(self, scores, width, height, src_format):
        """
            Given a list of pipeline options ordered by their score
            and an input format (width, height and source pixel format),
            we try to create a working pipeline, trying each option
            until one succeeds.
        """
        start = time.time()
        debug("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                _, csc_spec, enc_in_format, encoder_spec = option
                debug("setup_pipeline: trying %s", option)
                speed = self.get_current_speed()
                quality = self.get_current_quality()
                if csc_spec:
                    #TODO: no need to OR encoder mask if we are scaling...
                    self.width_mask = csc_spec.width_mask & encoder_spec.width_mask
                    self.height_mask = csc_spec.height_mask & encoder_spec.height_mask
                    csc_width = width & self.width_mask
                    csc_height = height & self.height_mask
                    enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height)
                    #csc speed is not very important compared to encoding speed,
                    #so make sure it never degrades quality
                    csc_speed = min(speed, 100-quality/2.0)
                    csc_start = time.time()
                    self._csc_encoder = csc_spec.codec_class()
                    self._csc_encoder.init_context(csc_width, csc_height, src_format,
                                                          enc_width, enc_height, enc_in_format, csc_speed)
                    csc_end = time.time()
                    debug("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
                          self._csc_encoder, self._csc_encoder.get_info(), (csc_end-csc_start)*1000.0)
                else:
                    #use the encoder's mask directly since that's all we have to worry about!
                    self.width_mask = encoder_spec.width_mask
                    self.height_mask = encoder_spec.height_mask
                    enc_width = width & self.width_mask
                    enc_height = height & self.height_mask
                enc_start = time.time()
                self._video_encoder = encoder_spec.codec_class()
                self._video_encoder.init_context(enc_width, enc_height, enc_in_format, quality, speed, self.encoding_options)
                enc_end = time.time()
                debug("setup_pipeline: video encoder=%s, info: %s, setup took %.2fms",
                        self._video_encoder, self._video_encoder.get_info(), (enc_end-enc_start)*1000.0)
                return  True
            except:
                log.warn("setup_pipeline failed for %s", option, exc_info=True)
        end = time.time()
        debug("setup_pipeline(..) failed! took %.2fms", (end-start)*1000.0)
        return False


    def video_encode(self, encoding, image, options):
        """
            This method is used by make_data_packet to encode frames using x264 or vpx.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the '_lock' to prevent races.
        """
        debug("video_encode%s", (encoding, image, options))
        x, y, w, h = image.get_geometry()[:4]
        assert x==0 and y==0, "invalid position: %s,%s" % (x,y)
        src_format = image.get_pixel_format()
        try:
            self._lock.acquire()
            if not self.check_pipeline(encoding, w, h, src_format):
                raise Exception("failed to setup a pipeline for %s encoding!" % encoding)

            #dw and dh are the edges we don't handle here
            width = w & self.width_mask
            height = h & self.height_mask
            debug("video_encode%s w-h=%s-%s, width-height=%s-%s", (encoding, image, options), w, h, width, height)

            csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

            start = time.time()
            data, client_options = self._video_encoder.compress_image(csc_image, options)
            end = time.time()

            csc_image.free()
            del csc_image
            if data is None:
                log.error("video_encode: ouch, %s compression failed", encoding)
                return None, None, 0
            if self.encoding_client_options:
                #tell the client which pixel encoding we used:
                if self.uses_csc_atoms:
                    client_options["csc"] = csc
                else:
                    #ugly hack: expose internal ffmpeg/libav constant
                    #for old versions without the "csc_atoms" feature:
                    client_options["csc_pixel_format"] = get_avutil_enum_from_colorspace(csc)
                #tell the client about scaling:
                if self._csc_encoder and (enc_width!=width or enc_height!=height):
                    client_options["scaled_size"] = enc_width, enc_height
            debug("video_encode encoder: %s %sx%s result is %s bytes (%.1f MPixels/s), client options=%s",
                                encoding, enc_width, enc_height, len(data), (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
            return Compressed(encoding, data), client_options, width, height, 0
        finally:
            self._lock.release()

    def csc_image(self, image, width, height):
        """
            Takes a source image and converts it
            using the current csc_encoder.
            If there are no csc_encoders (because the video
            encoder can process the source format directly)
            then the image is returned unchanged.
        """
        if self._csc_encoder is None:
            #no csc step!
            return image, image.get_pixel_format(), width, height

        start = time.time()
        csc_image = self._csc_encoder.convert_image(image)
        end = time.time()
        image.free()
        debug("csc_image(%s, %s, %s) converted to %s in %.1fms (%.1f MPixels/s)",
                        image, width, height,
                        csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise Exception("csc_image: conversion of %s to %s failed" % (image, self._csc_encoder.get_dst_format()))
        assert self._csc_encoder.get_dst_format()==csc_image.get_pixel_format()
        return csc_image, self._csc_encoder.get_dst_format(), self._csc_encoder.get_dst_width(), self._csc_encoder.get_dst_height()
