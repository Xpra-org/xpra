# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.codec_constants import get_subsampling_divs, LOSSY_PIXEL_FORMATS

from xpra.log import Logger
scorelog = Logger("score")


def get_quality_score(csc_format, csc_spec, encoder_spec, scaling, target_quality=100, min_quality=0):
    quality = encoder_spec.quality
    if csc_format in ("YUV420P", "YUV422P", "YUV444P"):
        #account for subsampling: reduces quality
        y,u,v = get_subsampling_divs(csc_format)
        div = 0.5   #any colourspace convertion will lose at least some quality (due to rounding)
        for div_x, div_y in (y, u, v):
            div += (div_x+div_y)/2.0/3.0
        quality /= div

    if csc_spec:
        #csc_spec.quality is the upper limit (up to 100):
        quality += csc_spec.quality
        quality /= 2.0

    if scaling==(1, 1) and csc_format not in ("YUV420P", "YUV422P") and target_quality==100 and encoder_spec.has_lossless_mode:
        #we want lossless!
        qscore = quality + 80
    else:
        #how far are we from the current quality heuristics?
        qscore = 100-abs(target_quality - quality)
        if min_quality>=quality:
            #if this encoder's quality is lower than the min_quality
            #then it isn't very suitable, discount its score:
            mqs = (min_quality - quality) // 2
            qscore = max(0, qscore - mqs)
        #when downscaling, YUV420P should always win:
        if csc_format=="YUV420P" and scaling!=(1, 1):
            qscore *= 2.0
    return int(qscore)

def get_speed_score(csc_format, csc_spec, encoder_spec, scaling, target_speed=100, min_speed=0):
    #score based on speed:
    speed = encoder_spec.speed
    if csc_spec:
        #when subsampling, add the speed gains to the video encoder
        #which now has less work to do:
        mult = 1.0
        if csc_format and csc_format in ("YUV420P", "YUV422P", "YUV444P"):
            #account for subsampling: increases encoding speed
            y,u,v = get_subsampling_divs(csc_format)
            mult = 0.0
            for div_x, div_y in (y, u, v):
                mult += (div_x+div_y)/2.0/3.0
        #average and add 0.25 for the extra cost of doing the csc step:
        speed = (encoder_spec.speed * mult + csc_spec.speed) / 2.25

    #the lower the current speed
    #the more we need a fast encoder/csc to cancel it out:
    sscore = max(0, (100.0-target_speed) * speed/100.0)
    if min_speed>=0:
        #if the encoder speed is lower or close to min_speed
        #then it isn't very suitable:
        mss = max(0, speed - min_speed)*100/max(1, 100-min_speed)
        sscore = (sscore + mss)/2.0
    #then always favour fast encoders:
    sscore += speed
    sscore /= 2
    return int(sscore)

def get_pipeline_score(enc_in_format, csc_spec, encoder_spec, width, height, scaling,
                       target_quality, min_quality,
                       target_speed, min_speed,
                       current_csce, current_ve,
                       client_score_delta):
    """
        Given an optional csc step (csc_format and csc_spec), and
        and a required encoding step (encoder_spec and width/height),
        we calculate a score of how well this matches our requirements:
        * our quality target "self._currend_quality"
        * our speed target "self._current_speed"
        * how expensive it would be to switch to this pipeline option
        Note: we know the current pipeline settings, so the "switching
        cost" will be lower for pipelines that share components with the
        current one.

        Can be called from any thread.
    """
    def clamp(v):
        return max(0, min(100, v))
    qscore = clamp(get_quality_score(enc_in_format, csc_spec, encoder_spec, scaling, target_quality, min_quality))
    sscore = clamp(get_speed_score(enc_in_format, csc_spec, encoder_spec, scaling, target_speed, min_speed))

    #how well the codec deals with larger screen sizes:
    sizescore = 100
    mpixels = width*height/(1024.0*1024.0)
    if mpixels>1.0:
        #high size efficiency means sizescore stays high even with high number of mpixels,
        #ie: 1MPixels -> sizescore = 100
        #ie: 8MPixels -> sizescore = size_efficiency
        sdisc = (100-encoder_spec.size_efficiency)
        sizescore = max(0, 100-(mpixels-1)/7.0*sdisc)

    #runtime codec adjustements:
    runtime_score = 100
    #score for "edge resistance" via setup cost:
    ecsc_score = 100

    csc_width = 0
    csc_height = 0
    if csc_spec:
        #OR the masks so we have a chance of making it work
        width_mask = csc_spec.width_mask & encoder_spec.width_mask
        height_mask = csc_spec.height_mask & encoder_spec.height_mask
        csc_width = width & width_mask
        csc_height = height & height_mask
        if enc_in_format=="RGB":
            #converting to "RGB" is often a waste of CPU
            #(can only get selected because the csc step will do scaling,
            # but even then, the YUV subsampling are better options)
            ecsc_score = 1
        elif current_csce is None or current_csce.get_dst_format()!=enc_in_format or \
           type(current_csce)!=csc_spec.codec_class or \
           current_csce.get_src_width()!=csc_width or current_csce.get_src_height()!=csc_height:
            #if we have to change csc, account for new csc setup cost:
            ecsc_score = max(0, 80 - csc_spec.setup_cost*80.0/100.0)
        else:
            ecsc_score = 80
        ecsc_score += csc_spec.score_boost
        runtime_score *= csc_spec.get_runtime_factor()

        csc_scaling = scaling
        encoder_scaling = (1, 1)
        if scaling!=(1,1) and not csc_spec.can_scale:
            #csc cannot take care of scaling, so encoder will have to:
            encoder_scaling = scaling
            csc_scaling = (1, 1)
        if scaling!=(1, 1):
            #if we are (down)scaling, we should prefer lossy pixel formats:
            v = LOSSY_PIXEL_FORMATS.get(enc_in_format, 1)
            qscore *= (v/2)
        enc_width, enc_height = get_encoder_dimensions(encoder_spec, csc_width, csc_height, scaling)
    else:
        #not using csc at all!
        ecsc_score = 100
        width_mask = encoder_spec.width_mask
        height_mask = encoder_spec.height_mask
        enc_width = width & width_mask
        enc_height = height & height_mask
        csc_scaling = None
        encoder_scaling = scaling

    if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
        #we need the encoder to scale but it cannot do it, fail it:
        scorelog("scaling (%s) not supported by %s", encoder_scaling, encoder_spec)
        return None

    ee_score = 100
    if current_ve is None or current_ve.get_type()!=encoder_spec.codec_type or \
       current_ve.get_src_format()!=enc_in_format or \
       current_ve.get_width()!=enc_width or current_ve.get_height()!=enc_height:
        #account for new encoder setup cost:
        ee_score = 100 - encoder_spec.setup_cost
        ee_score += encoder_spec.score_boost
    #edge resistance score: average of csc and encoder score:
    er_score = (ecsc_score + ee_score) / 2.0
    score = int((qscore+sscore+er_score+sizescore+client_score_delta)*runtime_score/100.0/4.0)
    scorelog("get_score(%-7s, %-24r, %-24r, %5i, %5i) quality: %2i, speed: %2i, setup: %2i runtime: %2i scaling: %s / %s, encoder dimensions=%sx%s, sizescore=%3i, client score delta=%3i, score=%2i",
             enc_in_format, csc_spec, encoder_spec, width, height,
             qscore, sscore, er_score, runtime_score, scaling, encoder_scaling, enc_width, enc_height, sizescore, client_score_delta, score)
    return score, scaling, csc_scaling, csc_width, csc_height, csc_spec, enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec

def get_encoder_dimensions(encoder_spec, width, height, scaling=(1,1)):
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
