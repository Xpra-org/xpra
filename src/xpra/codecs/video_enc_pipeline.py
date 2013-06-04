# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from threading import Lock

from xpra.log import Logger, debug_if_env
log = Logger()

from xpra.net.protocol import Compressed
from xpra.codecs.codec_constants import get_avutil_enum_from_colorspace, get_subsampling_divs

debug = debug_if_env(log, "XPRA_VIDEO_DEBUG")
score_debug = debug_if_env(log, "XPRA_SCORE_DEBUG")


class VideoEncoderPipeline(object):
    """
    """

    _video_encoder_specs = {}
    _csc_encoder_specs = {}

    def __init__(self, client_encodings, encoding_options):
        self.encodings = client_encodings
        self.uses_swscale = encoding_options.get("uses_swscale", True)
                                                        #client uses uses_swscale (has extra limits on sizes)
                                                        #unused since we still use swscale on the server...
        self.encoding_options = encoding_options        #extra options which may be specific to the encoder (ie: x264)
        self.encoding_client_options = encoding_options.get("client_options", False)
                                                        #does the client support encoding options?
        self.uses_csc_atoms = encoding_options.get("csc_atoms", False)
        self.video_scaling = encoding_options.get("video_scaling", False)       #support video scaling
        if not self.encoding_client_options:
            #cannot use anything but 420P, so filter everything else out:
            #(though I think we ought to allow other modes that
            #can be decompressed to YUV420P... if any?)
            def_csc_modes = ("YUV420P")
        else:
            def_csc_modes = ("YUV420P", "YUV422P", "YUV444P")
        self.csc_modes = encoding_options.get("csc_modes", def_csc_modes)

        from xpra.server.server_base import SERVER_CORE_ENCODINGS
        self.SERVER_CORE_ENCODINGS = SERVER_CORE_ENCODINGS

        self._csc_encoder = None
        self._video_encoder = None
        self._lock = Lock()               #to ensure we serialize access to the encoder and its internals

        if len(self._video_encoder_specs)==0:
            self.init_video_encoders_options()
        if len(self._csc_encoder_specs)==0:
            self.init_csc_options()

    def add_stats(self, info, prefix, suffix):
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

    def update_video_encoder(self, fullscreen, scaling, quality, speed, force_reload=False):
        debug("update_video_encoder%s csc_encoder=%s, video_encoder=%s", (fullscreen, scaling, quality, speed, force_reload), self._csc_encoder, self._video_encoder)
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
            csc_format = None
            enc_format = ve.get_src_format()
            if self._csc_encoder:
                csc_format = self._csc_encoder.get_src_format()
            encoding = ve.get_type()
            width = ve.get_width()
            height = ve.get_height()
            min_speed = self.encoding_options.get("min-speed", 0)
            min_quality = self.encoding_options.get("min-quality", 0)

            scores = self.get_encoding_paths_options(encoding, width, height, csc_format or enc_format,
                               fullscreen, scaling, min_quality, quality, min_speed, speed)
            if len(scores)>0:
                debug("update_video_encoder(..) best=%s", scores[0])
                _, csc_spec, enc_in_format, encoder_spec = scores[0]
                if self._csc_encoder:
                    if csc_spec is None or \
                       type(self._csc_encoder)!=csc_spec.codec_class or \
                       self._csc_encoder.get_dst_format()!=enc_in_format:
                        debug("update_video_encoder(..) found better csc encoder: %s", scores[0])
                        self.do_csc_encoder_cleanup()
                if type(self._video_encoder)!=encoder_spec.codec_class or \
                   self._video_encoder.get_src_format()!=enc_in_format:
                    debug("update_video_encoder(..) found better video encoder: %s", scores[0])
                    self.do_video_encoder_cleanup()

            if self._video_encoder is None:
                self.setup_pipeline(scores, width, height, csc_format or enc_format, fullscreen, scaling, quality, speed, {})

            if self._video_encoder:
                self._video_encoder.set_encoding_speed(quality)
                self._video_encoder.set_encoding_quality(speed)
        finally:
            self._lock.release()


    def init_video_options(self):
        self.init_video_encoders_options()
        self.init_csc_options()

    def init_video_encoders_options(self):
        from xpra.server.server_base import SERVER_ENCODINGS
        common = [x for x in SERVER_ENCODINGS if x in self.encodings]
        if "vpx" in common:
            try:
                from xpra.codecs.vpx import encoder
                self.init_video_encoder_option("vpx", encoder)
            except Exception, e:
                log.warn("init_video_encoders_options() cannot add vpx encoder: %s" % e)
        if "x264" in common:
            try:
                from xpra.codecs.enc_x264 import encoder        #@Reimport
                self.init_video_encoder_option("x264", encoder)
            except Exception, e:
                log.warn("init_video_encoders_options() cannot add x264 encoder: %s" % e)
            try:
                from xpra.codecs.nvenc import encoder           #@Reimport
                self.init_video_encoder_option("x264", encoder)
            except Exception, e:
                log.warn("init_video_encoders_options() cannot add nvenc encoder: %s" % e)
        debug("init_video_encoders_options() video encoder specs: %s", self._video_encoder_specs)

    def init_video_encoder_option(self, encoding, encoder_module):
        colorspaces = encoder_module.get_colorspaces()
        debug("init_video_encoder_option(%s, %s) colorspaces=%s", encoding, encoder_module, colorspaces)
        encoder_specs = VideoEncoderPipeline._video_encoder_specs.setdefault(encoding, {})
        for colorspace in colorspaces:
            colorspace_specs = encoder_specs.setdefault(colorspace, [])
            spec = encoder_module.get_spec(colorspace)
            colorspace_specs.append(spec)

    def init_csc_options(self):
        try:
            from xpra.codecs.csc_swscale import colorspace_converter
            self.init_csc_option(colorspace_converter)
        except Exception, e:
            log.warn("init_csc_options() cannot add swscale csc: %s" % e)
        try:
            from xpra.codecs.csc_nvcuda import colorspace_converter #@Reimport
            self.init_csc_option(colorspace_converter)
        except Exception, e:
            log.warn("init_csc_options() cannot add nvcuda csc: %s" % e)

    def init_csc_option(self, csc_module):
        in_cscs = csc_module.get_input_colorspaces()
        debug("init_csc_option(%s)", csc_module)
        for in_csc in in_cscs:
            csc_specs = VideoEncoderPipeline._csc_encoder_specs.setdefault(in_csc, [])
            out_cscs = csc_module.get_output_colorspaces(in_csc)
            for out_csc in out_cscs:
                spec = csc_module.get_spec(in_csc, out_csc)
                item = out_csc, spec
                csc_specs.append(item)


    def get_encoding_paths_options(self, encoding, width, height, pixel_format,
                                   fullscreen, scaling, min_quality, quality, min_speed, speed):
        encoder_specs = self._video_encoder_specs.get(encoding, [])
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
                                           width, height,
                                           fullscreen, scaling, min_quality, quality, min_speed, speed)
                    if score>=0:
                        item = score, csc_spec, enc_in_format, encoder_spec
                        scores.append(item)
        if pixel_format in self.csc_modes:
            add_scores("direct (no csc)", None, pixel_format)
        #now add those that require a csc step:
        csc_specs = self._csc_encoder_specs.get(pixel_format)
        if csc_specs:
            #debug("%s can also be converted to %s using %s", pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
            #we have csc module(s) that can get us from pixel_format to out_csc:
            for out_csc, csc_spec in csc_specs:
                if out_csc in self.csc_modes:
                    add_scores("via %s" % out_csc, csc_spec, out_csc)
        s = sorted(scores, key=lambda x : -x[0])
        score_debug("get_encoding_paths_options%s scores=%s", (encoding, width, height, pixel_format,
                                   fullscreen, scaling, min_quality, quality, min_speed, speed), s)
        return s

    def get_score(self, csc_format, csc_spec, encoder_spec,
                  width, height,
                  fullscreen, scaling, min_quality, target_quality, min_speed, target_speed):
        #first discard if we cannot handle this size:
        if csc_spec and not csc_spec.can_handle(width, height):
            return -1, ""
        if not encoder_spec.can_handle(width, height):
            return -1, ""
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
        if quality<min_quality:
            qscore = 0
        else:
            qscore = 100-abs(quality-target_quality)

        #score based on speed:
        speed = clamp(encoder_spec.speed)
        if csc_spec:
            speed *= csc_spec.speed/100.0
        if speed<min_speed:
            sscore = 0
        else:
            sscore = 100-abs(speed-target_speed)

        #score for "edge resistance":
        ecsc_score = 100
        csce = self._csc_encoder
        if csc_spec:
            if csce is None or csce.get_dst_format()!=csc_format or \
               type(csce)!=csc_spec.codec_class or \
               csce.get_src_width()!=width or csce.get_src_height()!=height:
                #if we have to change csc, account for new csc setup cost:
                ecsc_score = 100 - csc_spec.setup_cost
        enc_width, enc_height = self.get_encoder_dimensions(csc_spec, width, height, fullscreen, scaling, quality, speed)
        ee_score = 100
        ve = self._video_encoder
        if ve is None or type(ve)!=encoder_spec.codec_class or \
           ve.get_src_format()!=csc_format or \
           ve.get_width()!=enc_width or ve.get_height()!=enc_height:
            #account for new encoder setup cost:
            ee_score = 100 - encoder_spec.setup_cost
        #edge resistance score: average of csc and encoder score:
        er_score = (ecsc_score + ee_score) / 2.0
        score_debug("get_score%s %s/%s/%s", (csc_format, csc_spec, encoder_spec,
                  width, height,
                  fullscreen, scaling, min_quality, target_quality, min_speed, target_speed), int(qscore), int(sscore), int(er_score))
        return int((qscore+sscore+er_score)/3.0)

    def setup_pipeline(self, scores, width, height, src_format, fullscreen, scaling, quality, speed, options):
        start = time.time()
        debug("setup_pipeline%s", (scores, width, height, src_format, fullscreen, scaling, quality, speed, options))
        for option in scores:
            try:
                _, csc_spec, enc_in_format, encoder_spec = option
                debug("setup_pipeline: trying %s", option)
                if csc_spec:
                    enc_width, enc_height = self.get_encoder_dimensions(csc_spec, width, height, fullscreen, scaling, quality, speed)
                    #csc speed is not very important compared to encoding speed,
                    #so make sure it never degrades quality
                    #and reduce our requirements when scaling (since this will increase speed already):
                    csc_speed = min(speed, 100-quality)
                    csc_speed = csc_speed * (enc_width * enc_height) / (width * height)
                    csc_start = time.time()
                    self._csc_encoder = csc_spec.codec_class()
                    self._csc_encoder.init_context(width, height, src_format,
                                                          enc_width, enc_height, enc_in_format, csc_speed)
                    csc_end = time.time()
                    debug("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
                          self._csc_encoder, self._csc_encoder.get_info(), (csc_end-csc_start)*1000.0)
                else:
                    enc_width = width
                    enc_height = height
                enc_start = time.time()
                self._video_encoder = encoder_spec.codec_class()
                self._video_encoder.init_context(enc_width, enc_height, enc_in_format, quality, speed, options)
                enc_end = time.time()
                debug("setup_pipeline: video encoder=%s, info: %s, setup took %.2fms",
                        self._video_encoder, self._video_encoder.get_info(), (enc_end-enc_start)*1000.0)
                return  True
            except:
                log.warn("setup_pipeline failed for %s", option, exc_info=True)
        end = time.time()
        debug("setup_pipeline(..) took %.2fms", (end-start)*1000.0)
        return False

    def get_encoder_dimensions(self, csc_spec, width, height, fullscreen, scaling, quality, speed):
        if not csc_spec or not self.video_scaling:
            return width, height
        #FIXME: take screensize into account,
        #we want to scale more when speed is high and min-quality is low
        #also framerate?
        if scaling is None:
            if width>1024 and height>768 and quality<30:
                scaling = 2,3
            if fullscreen and quality<50:
                scaling = 1,2
        if scaling is None:
            return width, height
        v, u = scaling
        if v/u>1.0:         #never upscale before encoding!
            return width, height
        if v/u<0.1:         #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            v, u = 1, 10
        enc_width = int(width * v / u)
        enc_height = int(height * v / u)
        return enc_width, enc_height


    def check_pipeline(self, wid, encoding, width, height, src_format, fullscreen, scaling, quality, speed, options):
        if self.do_check_pipeline(wid, encoding, width, height, src_format):
            return True #OK!
        min_speed = self.encoding_options.get("min-speed", 0)
        min_quality = self.encoding_options.get("min-quality", 0)
        scores = self.get_encoding_paths_options(encoding, width, height, src_format,
                                        fullscreen, scaling, min_quality, quality, min_speed, speed)
        return self.setup_pipeline(scores, width, height, src_format, fullscreen, scaling, quality, speed, options)

    def do_check_pipeline(self, wid, encoding, width, height, src_format):
        def err():
            if self._csc_encoder:
                self.do_csc_encoder_cleanup()
            if self._video_encoder:
                self.do_video_encoder_cleanup()
            return False

        if self._video_encoder is None:
            return err()
            
        #must be called with video lock held
        if self._csc_encoder:
            if self._csc_encoder.get_src_format()!=src_format:
                debug("check_pipeline csc: wid=%s, switching source format from %s to %s",
                                            wid, self._csc_encoder.get_src_format(), src_format)
                return err()
            elif self._csc_encoder.get_src_width()!=width or self._csc_encoder.get_src_height()!=height:
                debug("check_pipeline csc: window dimensions have changed from %sx%s to %sx%s",
                                            self._csc_encoder.get_src_width(), self._csc_encoder.get_src_height(), width, height)
                return err()
            elif self._csc_encoder.get_dst_format()!=self._video_encoder.get_src_format():
                log.warn("check_pipeline csc: intermediate format mismatch: %s vs %s",
                                            wid, self._csc_encoder.get_dst_format(), self._video_encoder.get_src_format())
                return err()
            else:
                encoder_src_format = self._csc_encoder.get_dst_format()
                encoder_src_width = self._csc_encoder.get_dst_width()
                encoder_src_height = self._csc_encoder.get_dst_height()
        else:
            #direct!
            encoder_src_format = src_format
            encoder_src_width = width
            encoder_src_height = height

        if self._video_encoder.get_src_format()!=encoder_src_format:
            debug("check_pipeline video: invalid source format %s, expected %s",
                                            self._video_encoder.get_src_format(), encoder_src_format)
            return err()
        elif self._video_encoder.get_type()!=encoding:
            debug("check_pipeline video: invalid encoding %s, expected %s",
                                            self._video_encoder.get_type(), encoding)
            return err()
        elif self._video_encoder.get_width()!=encoder_src_width or self._video_encoder.get_height()!=encoder_src_height:
            debug("check_pipeline video: window dimensions have changed from %sx%s to %sx%s",
                                            self._video_encoder.get_width(), self._video_encoder.get_height(), encoder_src_width, encoder_src_height)
            return err()
        return True

    def video_encode(self, wid, encoding, image, fullscreen, scaling, quality, speed, options):
        """
            This method is used by make_data_packet to encode frames using x264 or vpx.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the '_lock' to prevent races.
        """
        debug("video_encode%s", (wid, encoding, image, fullscreen, scaling, quality, speed, options))
        x, y, w, h = image.get_geometry()[:4]
        width = w & 0xFFFE
        height = h & 0xFFFE
        assert x==0 and y==0, "invalid position: %s,%s" % (x,y)
        src_format = image.get_pixel_format()
        try:
            self._lock.acquire()
            if not self.check_pipeline(wid, encoding, width, height, src_format, fullscreen, scaling, quality, speed, options):
                raise Exception("failed to setup a pipeline for %s encoding!" % encoding)

            if self._csc_encoder:
                start = time.time()
                csc_image = self._csc_encoder.convert_image(image)
                end = time.time()
                image.free()
                debug("video_encode csc: converted %s to %s in %.1fms (%.1f MPixels/s)",
                                image, csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
                if not csc_image:
                    log.error("video_encode csc: ouch, %s conversion failed", self._csc_encoder.get_dst_format())
                    return None, None
                assert self._csc_encoder.get_dst_format()==csc_image.get_pixel_format()
                csc = self._csc_encoder.get_dst_format()
                enc_width = self._csc_encoder.get_dst_width()
                enc_height = self._csc_encoder.get_dst_height()
            else:
                csc_image = image
                csc = src_format
                enc_width = width
                enc_height = height

            start = time.time()
            data, client_options = self._video_encoder.compress_image(csc_image, options)
            end = time.time()

            csc_image.free()
            del csc_image
            if data is None:
                log.error("video_encode: ouch, %s compression failed", encoding)
                return None, None
            if self.encoding_client_options:
                #tell the client which pixel encoding we used:
                if self.uses_csc_atoms:
                    client_options["csc"] = csc
                else:
                    #ugly hack: expose internal ffmpeg/libav constant
                    #for old versions without the "csc_atoms" feature:
                    client_options["csc_pixel_format"] = get_avutil_enum_from_colorspace(csc)
                #tell the client about scaling:
                if self._csc_encoder and (self._csc_encoder.get_dst_width()!=width or self._csc_encoder.get_dst_height()!=height):
                    client_options["scaled_size"] = self._csc_encoder.get_dst_width(), self._csc_encoder.get_dst_height()
            debug("video_encode encoder: %s wid=%s, %sx%s result is %s bytes (%.1f MPixels/s), client options=%s",
                                encoding, wid, enc_width, enc_height, len(data), (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
            return Compressed(encoding, data), client_options
        finally:
            self._lock.release()
