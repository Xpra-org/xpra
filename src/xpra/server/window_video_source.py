# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from threading import Lock

from xpra.net.protocol import Compressed
from xpra.codecs.codec_constants import get_avutil_enum_from_colorspace, get_subsampling_divs, TransientCodecException
from xpra.codecs.video_helper import getVideoHelper
from xpra.server.window_source import WindowSource, log
from xpra.server.background_worker import add_work_item
from xpra.log import debug_if_env

debug = debug_if_env(log, "XPRA_VIDEO_DEBUG")


def envint(name, d):
    try:
        return int(os.environ.get(name, d))
    except:
        return d

MAX_NONVIDEO_PIXELS = envint("XPRA_MAX_NONVIDEO_PIXELS", 2048)
MAX_NONVIDEO_OR_INITIAL_PIXELS = envint("XPRA_MAX_NONVIDEO_OR_INITIAL_PIXELS", 1024*64)

ENCODER_TYPE = os.environ.get("XPRA_ENCODER_TYPE", "")  #ie: "x264" or "nvenc"
CSC_TYPE = os.environ.get("XPRA_CSC_TYPE", "")          #ie: "swscale" or "opencl"
FORCE_CSC_MODE = os.environ.get("XPRA_FORCE_CSC_MODE", "")   #ie: "YUV444P"
FORCE_CSC = bool(FORCE_CSC_MODE) or  os.environ.get("XPRA_FORCE_CSC", "0")=="1"
SCALING = os.environ.get("XPRA_SCALING", "1")=="1"
def parse_scaling_value(v):
    if not v:
        return None
    values = v.split(":", 1)
    values = [int(x) for x in values]
    for x in values:
        assert x>0, "invalid scaling value %s" % x
    if len(values)==1:
        return 1, values[0]
    assert values[0]<=values[1], "cannot upscale"
    return values[0], values[1]
SCALING_HARDCODED = parse_scaling_value(os.environ.get("XPRA_SCALING_HARDCODED", ""))


class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    _video_helper = getVideoHelper()

    def __init__(self, *args):
        WindowSource.__init__(self, *args)
        #client uses uses_swscale (has extra limits on sizes)
        self.uses_swscale = self.encoding_options.get("uses_swscale", True)
        self.uses_csc_atoms = self.encoding_options.get("csc_atoms", False)
        self.video_scaling = self.encoding_options.get("video_scaling", False)
        self.video_reinit = self.encoding_options.get("video_reinit", False)
        if not self.encoding_client_options:
            #old clients can only use 420P:
            def_csc_modes = ("YUV420P")
        else:
            #default for newer clients that don't specify "csc_modes":
            def_csc_modes = ("YUV420P", "YUV422P", "YUV444P")
        #0.10 onwards should have specified csc_modes:
        self.csc_modes = self.encoding_options.get("csc_modes", def_csc_modes)

        self.video_encodings = ("vp8", "vp9", "h264")
        for x in self.video_encodings:
            if x in self.server_core_encodings:
                self._encoders[x] = self.video_encode

        #these constraints get updated with real values
        #when we construct the video pipeline:
        self.min_w = 1
        self.min_h = 1
        self.max_w = 16384
        self.max_h = 16384
        self.width_mask = 0xFFFF
        self.height_mask = 0xFFFF
        self.actual_scaling = (1, 1)

        self._csc_encoder = None
        self._video_encoder = None
        self._lock = Lock()               #to ensure we serialize access to the encoder and its internals

        self.last_pipeline_params = None
        self.last_pipeline_scores = []
        WindowVideoSource._video_helper.may_init()

    def add_stats(self, info, suffix=""):
        WindowSource.add_stats(self, info, suffix)
        prefix = "window[%s]." % self.wid
        info[prefix+"client.csc_modes"] = self.csc_modes
        info[prefix+"client.uses_swscale"] = self.uses_swscale
        info[prefix+"client.uses_csc_atoms"] = self.uses_csc_atoms
        info[prefix+"client.supports_scaling"] = self.video_scaling
        info[prefix+"scaling"] = self.actual_scaling
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
        if self.last_pipeline_params:
            encoding, width, height, src_format = self.last_pipeline_params
            info[prefix+"encoding.pipeline_param.encoding"+suffix] = encoding
            info[prefix+"encoding.pipeline_param.dimensions"+suffix] = width, height
            info[prefix+"encoding.pipeline_param.src_format"+suffix] = src_format
        if self.last_pipeline_scores:
            i = 0
            for score, csc_spec, enc_in_format, encoder_spec in self.last_pipeline_scores:
                info[prefix+("encoding.pipeline_option[%s].score" % i)+suffix] = score
                info[prefix+("encoding.pipeline_option[%s].csc" % i)+suffix] = repr(csc_spec)
                info[prefix+("encoding.pipeline_option[%s].format" % i)+suffix] = str(enc_in_format)
                info[prefix+("encoding.pipeline_option[%s].encoder" % i)+suffix] = repr(encoder_spec)
                i += 1

    def cleanup(self):
        WindowSource.cleanup(self)
        self.cleanup_codecs()

    def cleanup_codecs(self):
        """ Video encoders (x264, nvenc and vpx) and their csc helpers
            require us to run cleanup code to free the memory they use.
            But some cleanups may be slow, so run them in a worker thread.
        """
        if self._csc_encoder is None and self._video_encoder is None:
            return
        try:
            self._lock.acquire()
            self.do_csc_encoder_cleanup()
            self.do_video_encoder_cleanup()
        finally:
            self._lock.release()

    def do_csc_encoder_cleanup(self):
        #MUST be called with video lock held!
        if self._csc_encoder is None:
            return
        add_work_item(self._csc_encoder.clean)
        self._csc_encoder = None

    def do_video_encoder_cleanup(self):
        #MUST be called with video lock held!
        if self._video_encoder is None:
            return
        add_work_item(self._video_encoder.clean)
        self._video_encoder = None

    def set_new_encoding(self, encoding):
        if self.encoding!=encoding:
            #ensure we re-init the codecs asap:
            self.cleanup_codecs()
        WindowSource.set_new_encoding(self, encoding)

    def set_client_properties(self, properties):
        #client may restrict csc modes for specific windows
        self.csc_modes = properties.get("encoding.csc_modes", self.csc_modes)
        self.video_scaling = properties.get("encoding.video_scaling", self.video_scaling)
        self.uses_swscale = properties.get("encoding.uses_swscale", self.uses_swscale)
        WindowSource.set_client_properties(self, properties)
        debug("set_client_properties(%s) csc_modes=%s, video_scaling=%s, uses_swscale=%s", properties, self.csc_modes, self.video_scaling, self.uses_swscale)

    def unmap(self):
        WindowSource.cancel_damage(self)
        self.cleanup_codecs()

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
        if coding in self.video_encodings and (dw>0 or dh>0):
            if dw>0:
                lossless = self.find_common_lossless_encoder(window.has_alpha(), coding, dw*h)
                WindowSource.process_damage_region(self, damage_time, window, x+w-dw, y, dw, h, lossless, options)
            if dh>0:
                lossless = self.find_common_lossless_encoder(window.has_alpha(), coding, w*dh)
                WindowSource.process_damage_region(self, damage_time, window, x, y+h-dh, x+w, dh, lossless, options)


    def must_encode_full_frame(self, window, encoding):
        return WindowSource.must_encode_full_frame(self, window, encoding) or (encoding in self.video_encodings)

    def do_get_best_encoding(self, batching, has_alpha, is_tray, is_OR, pixel_count, ww, wh, current_encoding):
        """
            decide whether we send a full window update
            using the video encoder or if a small lossless region(s) is a better choice
        """
        encoding = WindowSource.do_get_best_encoding(self, batching, has_alpha, is_tray, is_OR, pixel_count, ww, wh, current_encoding)
        if encoding is not None:
            #superclass knows best (usually a tray or transparent window):
            return encoding
        if current_encoding not in self.video_encodings:
            return None
        if ww<self.min_w or ww>self.max_w or wh<self.min_h or wh>self.max_h:
            #video encoder cannot handle this size!
            #(maybe this should be an 'assert' statement here?)
            return None

        def switch_to_lossless(reason):
            coding = self.find_common_lossless_encoder(has_alpha, current_encoding, ww*wh)
            debug("do_get_best_encoding(..) temporarily switching to %s encoder for %s pixels: %s", coding, pixel_count, reason)
            return  coding

        max_nvoip = MAX_NONVIDEO_OR_INITIAL_PIXELS
        max_nvp = MAX_NONVIDEO_PIXELS
        if not batching:
            max_nvoip *= 128
            max_nvp *= 128
        if self._sequence==1 and is_OR and pixel_count<max_nvoip:
            #first frame of a small-ish OR window, those are generally short lived
            #so delay using a video encoder until the next frame:
            return switch_to_lossless("first small frame of an OR window")
        #ensure the dimensions we use for decision making are the ones actually used:
        ww = ww & self.width_mask
        wh = wh & self.height_mask
        if ww<self.min_w or ww>self.max_w or wh<self.min_h or wh>self.max_h:
            return switch_to_lossless("window dimensions are unsuitable for this encoder/csc")
        if pixel_count<ww*wh*0.01:
            #less than one percent of total area
            return switch_to_lossless("few pixels (%.2f%% of window)" % (100.0*pixel_count/ww/wh))
        if pixel_count>max_nvp:
            #too many pixels, use current video encoder
            return self.get_core_encoding(has_alpha, current_encoding)
        if pixel_count<0.5*ww*wh and not batching:
            #less than 50% of the full window and we're not batching
            return switch_to_lossless("%i%% of image, not batching" % (100.0*pixel_count/ww/wh))
        return self.get_core_encoding(has_alpha, current_encoding)


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
                if self._csc_encoder:
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

            scores = self.get_video_pipeline_options(ve.get_encoding(), width, height, pixel_format)
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
        encoder_specs = WindowVideoSource._video_helper.get_encoder_specs(encoding)
        assert len(encoder_specs)>0, "no encoders found for '%s'" % encoding
        scores = []
        debug("get_video_pipeline_options%s speed: %s (min %s), quality: %s (min %s)", (encoding, width, height, src_format), int(self.get_current_speed()), self.get_min_speed(), int(self.get_current_quality()), self.get_min_quality())
        def add_scores(info, csc_spec, enc_in_format):
            if bool(CSC_TYPE) and (csc_spec and csc_spec.codec_type!=CSC_TYPE):
                debug("add_scores: ignoring %s", csc_spec.codec_type)
                return
            colorspace_specs = encoder_specs.get(enc_in_format)
            debug("add_scores(%s, %s, %s) colorspace_specs=%s", info, csc_spec, enc_in_format, colorspace_specs)
            if not colorspace_specs:
                return
            #debug("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
            for encoder_spec in colorspace_specs:
                if bool(ENCODER_TYPE) and encoder_spec.codec_type!=ENCODER_TYPE:
                    debug("add_scores: ignoring %s: %s", encoder_spec.codec_type, encoder_spec)
                    continue
                score = self.get_score(enc_in_format,
                                       csc_spec, encoder_spec,
                                       width, height)
                debug("add_scores: score(%s)=%s", (enc_in_format, csc_spec, encoder_spec, width, height), score)
                if score>=0:
                    item = score, csc_spec, enc_in_format, encoder_spec
                    scores.append(item)
        if src_format in self.csc_modes and (not FORCE_CSC or src_format==FORCE_CSC_MODE):
            add_scores("direct (no csc)", None, src_format)
        #now add those that require a csc step:
        csc_specs = WindowVideoSource._video_helper.get_csc_specs(src_format)
        if csc_specs:
            #debug("%s can also be converted to %s using %s", pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
            #we have csc module(s) that can get us from pixel_format to out_csc:
            for out_csc, csc_spec in csc_specs:
                actual_csc = self.csc_equiv(out_csc)
                if actual_csc in self.csc_modes and (not bool(FORCE_CSC_MODE) or FORCE_CSC_MODE==out_csc):
                    add_scores("via %s" % out_csc, csc_spec, out_csc)
        s = sorted(scores, key=lambda x : -x[0])
        debug("get_video_pipeline_options%s scores=%s", (encoding, width, height, src_format), s)
        return s

    def csc_equiv(self, csc_mode):
        #in some places, we want to check against the subsampling used
        #and not the colorspace itself.
        #and NV12 uses the same subsampling as YUV420P...
        return {"NV12" : "YUV420P"}.get(csc_mode, csc_mode)


    def get_quality_score(self, csc_format, csc_spec, encoder_spec):
        quality = encoder_spec.quality
        if csc_format and csc_format in ("YUV420P", "YUV422P", "YUV444P"):
            #account for subsampling (reduces quality):
            y,u,v = get_subsampling_divs(csc_format)
            div = 0.5   #any colourspace convertion will lose at least some quality (due to rounding)
            for div_x, div_y in (y, u, v):
                div += (div_x+div_y)/2.0/3.0
            quality = quality / div

        if csc_spec:
            #csc_spec.quality is the upper limit (up to 100):
            quality += csc_spec.quality
            quality /= 2.0

        #the lower the current quality
        #the more we need an HQ encoder/csc to improve things:
        qscore = max(0, (100.0-self.get_current_quality()) * quality/100.0)
        mq = self.get_min_quality()
        if mq>=0:
            #if the encoder quality is lower or close to min_quality
            #then it isn't very suitable:
            mqs = max(0, quality - mq)*100/max(1, 100-mq)
            qscore = (qscore + mqs)/2.0
        return qscore

    def get_speed_score(self, csc_spec, encoder_spec):
        #score based on speed:
        speed = encoder_spec.speed
        if csc_spec:
            speed += csc_spec.speed
            speed /= 2.0
        #the lower the current speed
        #the more we need a fast encoder/csc to cancel it out:
        sscore = max(0, (100.0-self.get_current_speed()) * speed/100.0)
        ms = self.get_min_speed()
        if ms>=0:
            #if the encoder speed is lower or close to min_speed
            #then it isn't very suitable:
            mss = max(0, speed - ms)*100/max(1, 100-ms)
            sscore = (sscore + mss)/2.0
        return sscore

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
        if self._video_encoder is not None and not self.video_reinit \
            and self._video_encoder.get_encoding()==encoder_spec.encoding \
            and self._video_encoder.get_type()!=encoder_spec.codec_type:
            #client does not support video decoder reinit,
            #so we cannot swap for another encoder of the same type
            #(which would generate a new stream)
            return -1
        def clamp(v):
            return max(0, min(100, v))
        qscore = clamp(self.get_quality_score(csc_format, csc_spec, encoder_spec))
        sscore = clamp(self.get_speed_score(csc_spec, encoder_spec))

        scaling = self.calculate_scaling(width, height, encoder_spec.max_w, encoder_spec.max_h)
        #runtime codec adjustements:
        runtime_score = 100
        #score for "edge resistance" via setup cost:
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
                ecsc_score = max(0, 80 - csc_spec.setup_cost*80.0/100.0)
            else:
                ecsc_score = 80
            runtime_score *= csc_spec.get_runtime_factor()
            enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height, scaling)
            encoder_scaling = (1, 1)
        else:
            #not using csc at all!
            ecsc_score = 100
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            enc_width = width & width_mask
            enc_height = height & height_mask
            encoder_scaling = scaling
        ee_score = 100
        if self._video_encoder is None or self._video_encoder.get_type()!=encoder_spec.codec_type or \
           self._video_encoder.get_src_format()!=csc_format or \
           self._video_encoder.get_width()!=enc_width or self._video_encoder.get_height()!=enc_height:
            #account for new encoder setup cost:
            ee_score = 100 - encoder_spec.setup_cost
        #edge resistance score: average of csc and encoder score:
        er_score = (ecsc_score + ee_score) / 2.0
        score = int((qscore+sscore+er_score)*runtime_score/100.0/3.0)
        if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
            #slash score if we want scaling but this encoder cannot do it:
            score /= 5
        debug("get_score%s quality:%.1f, speed:%.1f, setup:%.1f runtime:%.1f score=%s", (csc_format, csc_spec, encoder_spec,
                  width, height), qscore, sscore, er_score, runtime_score, score)
        return score

    def get_encoder_dimensions(self, csc_spec, encoder_spec, width, height, scaling=(1,1)):
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
        v, u = scaling
        enc_width = int(width * v / u) & encoder_spec.width_mask
        enc_height = int(height * v / u) & encoder_spec.height_mask
        return enc_width, enc_height

    def calculate_scaling(self, width, height, max_w=4096, max_h=4096):
        actual_scaling = self.scaling
        if not SCALING or not self.video_scaling:
            #not supported by client or disabled by env:
            actual_scaling = 1, 1
        elif SCALING_HARDCODED:
            actual_scaling = tuple(SCALING_HARDCODED)
            debug("using hardcoded scaling: %s", actual_scaling)
        elif actual_scaling is None:
            #no scaling window attribute defined, so use heuristics to enable:
            quality = self.get_current_quality()
            speed = self.get_current_speed()
            if width>max_w or height>max_h:
                #most encoders can't deal with that!
                d = 1
                while width/d>max_w or height/d>max_h:
                    d += 1
                actual_scaling = 1,d
            elif width*height>=2560*1440 and quality<60 and speed>70:
                actual_scaling = 1,3
            elif width*height>=1024*1024 and quality<40 and speed>80:
                actual_scaling = 1,2
            elif self.maximized and quality<50 and speed>80:
                actual_scaling = 2,3
            elif self.fullscreen and quality<60 and speed>70:
                actual_scaling = 1,2
        if actual_scaling is None:
            actual_scaling = 1, 1
        v, u = actual_scaling
        if v/u>1.0:
            #never upscale before encoding!
            actual_scaling = 1, 1
        elif float(v)/float(u)<0.1:
            #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            actual_scaling = 1, 10
        return actual_scaling


    def check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
        #must be called with video lock held!
        if self.do_check_pipeline(encoding, width, height, src_format):
            return True  #OK!

        #cleanup existing one if needed:
        if self._csc_encoder:
            self.do_csc_encoder_cleanup()
        if self._video_encoder:
            self.do_video_encoder_cleanup()
        #and make a new one:
        self.last_pipeline_params = encoding, width, height, src_format
        self.last_pipeline_scores = self.get_video_pipeline_options(encoding, width, height, src_format)
        return self.setup_pipeline(self.last_pipeline_scores, width, height, src_format)

    def do_check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
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

            #encoder will take its input from csc:
            encoder_src_width = self._csc_encoder.get_dst_width()
            encoder_src_height = self._csc_encoder.get_dst_height()
        else:
            #direct to video encoder without csc:
            encoder_src_width = width & self.width_mask
            encoder_src_height = height & self.height_mask

            if self._video_encoder.get_src_format()!=src_format:
                debug("check_pipeline video: invalid source format %s, expected %s",
                                                self._video_encoder.get_src_format(), src_format)
                return False

        if self._video_encoder.get_encoding()!=encoding:
            debug("check_pipeline video: invalid encoding %s, expected %s",
                                            self._video_encoder.get_encoding(), encoding)
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
        assert width>0 and height>0, "invalid dimensions: %sx%s" % (width, height)
        start = time.time()
        debug("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                _, csc_spec, enc_in_format, encoder_spec = option
                debug("setup_pipeline: trying %s", option)
                scaling = self.calculate_scaling(width, height, encoder_spec.max_w, encoder_spec.max_h)
                encoder_scaling = scaling
                speed = self.get_current_speed()
                quality = self.get_current_quality()
                min_w = 1
                min_h = 1
                max_w = 16384
                max_h = 16384
                if csc_spec:
                    #TODO: no need to OR encoder mask if we are scaling...
                    self.width_mask = csc_spec.width_mask & encoder_spec.width_mask
                    self.height_mask = csc_spec.height_mask & encoder_spec.height_mask
                    min_w = max(min_w, csc_spec.min_w)
                    min_h = max(min_h, csc_spec.min_h)
                    max_w = min(max_w, csc_spec.max_w)
                    max_h = min(max_h, csc_spec.max_h)
                    csc_width = width & self.width_mask
                    csc_height = height & self.height_mask
                    enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height, scaling)
                    encoder_scaling = (1, 1)
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
                    #restrict limits:
                    min_w = max(min_w, encoder_spec.min_w)
                    min_h = max(min_h, encoder_spec.min_h)
                    max_w = min(max_w, encoder_spec.max_w)
                    max_h = min(max_h, encoder_spec.max_h)
                    enc_width = width & self.width_mask
                    enc_height = height & self.height_mask
                    if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
                        debug("scaling is now enabled, so skipping %s", encoder_spec)
                        continue
                if width<=0 or height<=0:
                    #log.warn("skipping invalid dimensions..")
                    continue
                enc_start = time.time()
                self._video_encoder = encoder_spec.codec_class()
                self._video_encoder.init_context(enc_width, enc_height, enc_in_format, encoder_spec.encoding, quality, speed, encoder_scaling, self.encoding_options)
                #record new actual limits:
                self.actual_scaling = scaling
                self.min_w = min_w
                self.min_h = min_h
                self.max_w = max_w
                self.max_h = max_h
                enc_end = time.time()
                debug("setup_pipeline: video encoder=%s, info: %s, setup took %.2fms",
                        self._video_encoder, self._video_encoder.get_info(), (enc_end-enc_start)*1000.0)
                return  True
            except TransientCodecException, e:
                log.warn("setup_pipeline failed for %s: %s", option, e)
                self.cleanup_codecs()
            except:
                log.warn("setup_pipeline failed for %s", option, exc_info=True)
                self.cleanup_codecs()
        end = time.time()
        debug("setup_pipeline(..) failed! took %.2fms", (end-start)*1000.0)
        return False


    def video_encode(self, encoding, image, options):
        """
            This method is used by make_data_packet to encode frames using video encoders.
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
                raise Exception("failed to setup a video pipeline for %s encoding with source format %s" % (encoding, src_format))

            #dw and dh are the edges we don't handle here
            width = w & self.width_mask
            height = h & self.height_mask
            debug("video_encode%s wxh=%s-%s, widthxheight=%sx%s", (encoding, image, options), w, h, width, height)

            csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

            start = time.time()
            data, client_options = self._video_encoder.compress_image(csc_image, options)
            end = time.time()

            if csc_image is image:
                #no csc step, so the image comes from the UI server
                #and must be freed in the UI thread:
                self.idle_add(csc_image.free)
            else:
                #csc temporary images can be freed at will
                csc_image.free()
            del csc_image

            if data is None:
                log.error("video_encode: ouch, %s compression failed", encoding)
                return None, None, 0
            if self.encoding_client_options:
                #tell the client which colour subsampling we used:
                #(note: see csc_equiv!)
                if self.uses_csc_atoms:
                    client_options["csc"] = self.csc_equiv(csc)
                else:
                    #ugly hack: expose internal ffmpeg/libav constant
                    #for old versions without the "csc_atoms" feature:
                    client_options["csc_pixel_format"] = get_avutil_enum_from_colorspace(csc)
                #tell the client about scaling (the size of the encoded picture):
                #(unless the video encoder has already done so):
                if self._csc_encoder and ("scaled_size" not in client_options) and (enc_width!=width or enc_height!=height):
                    client_options["scaled_size"] = enc_width, enc_height
            debug("video_encode encoder: %s %sx%s result is %s bytes (%.1f MPixels/s), client options=%s",
                                encoding, enc_width, enc_height, len(data), (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
            return self._video_encoder.get_type(), Compressed(encoding, data), client_options, width, height, 0, 24
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
        #the image comes from the UI server, free it in the UI thread:
        self.idle_add(image.free)
        debug("csc_image(%s, %s, %s) converted to %s in %.1fms (%.1f MPixels/s)",
                        image, width, height,
                        csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise Exception("csc_image: conversion of %s to %s failed" % (image, self._csc_encoder.get_dst_format()))
        assert self._csc_encoder.get_dst_format()==csc_image.get_pixel_format()
        return csc_image, self._csc_encoder.get_dst_format(), self._csc_encoder.get_dst_width(), self._csc_encoder.get_dst_height()
