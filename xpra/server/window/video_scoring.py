# This file is part of Xpra.
# Copyright (C) 2013-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envint
from xpra.codecs.constants import LOSSY_PIXEL_FORMATS, CSCSpec, VideoSpec
from xpra.log import Logger

log = Logger("score")

GPU_BIAS = envint("XPRA_GPU_BIAS", 100)
MIN_FPS_COST = envint("XPRA_MIN_FPS_COST", 4)

# any colourspace conversion will lose at least some quality (due to rounding)
# (so add 0.2 to the value we get from calculating the degradation using get_subsampling_divs)
SUBSAMPLING_QUALITY_LOSS = {
    "NV12": 186,
    "YUV420P": 186,  # 1.66 + 0.2
    "YUV422P": 153,  # 1.33 + 0.2
    "YUV444P": 120,  # 1.00 + 0.2
}

LOSSY_CSC = ("NV12", "YUV420P", "YUV422P")


def clamp(value: int) -> int:
    return max(0, min(100, value))


def get_quality_score(csc_format: str, csc_spec: CSCSpec | None, encoder_spec: VideoSpec, scaling: tuple[int, int],
                      target_quality: int = 100, min_quality: int = 0) -> int:
    quality = encoder_spec.quality
    div = SUBSAMPLING_QUALITY_LOSS.get(csc_format, 100)
    quality = quality * 100 // div

    if csc_spec:
        # csc_spec.quality is the upper limit (up to 100):
        quality += csc_spec.quality
        quality /= 2.0

    if scaling == (1, 1) and csc_format not in LOSSY_CSC and target_quality == 100 and encoder_spec.has_lossless_mode:
        # we want lossless!
        qscore = quality + 80
    else:
        # how far are we from the current quality heuristics?
        qscore = 100 - abs(target_quality - quality)
        if min_quality >= quality:
            # if this encoder's quality is lower than the min_quality
            # then it isn't very suitable, discount its score:
            mqs = (min_quality - quality) // 2
            qscore = max(0, qscore - mqs)
        # when downscaling, YUV420P should always win:
        if csc_format in ("YUV420P", "NV12") and scaling != (1, 1):
            qscore *= 2.0
    return round(qscore)


def get_speed_score(csc_format: str, csc_spec: CSCSpec | None, encoder_spec: VideoSpec, scaling: tuple[int, int],
                    target_speed: int = 100, min_speed: int = 0) -> int:
    # when subsampling, add the speed gains to the video encoder
    # which now has less work to do:
    mult = {
        "NV12": 100,
        "YUV420P": 100,
        "YUV422P": 80,
    }.get(csc_format, 60)
    # score based on speed:
    speed = round(encoder_spec.speed * mult // 100)
    # the encoder speed matters less
    # when the target speed is low:
    ts = clamp(target_speed)
    sscore = speed * 100 // (200 - ts)
    if csc_spec:
        # if there is a csc step,
        # then we lose some performance,
        # but less if the csc is fast
        sscore = sscore - 20 - (100 - csc_spec.speed) // 2
    # when already downscaling, favour YUV420P subsampling:
    if csc_format in ("YUV420P", "NV12") and scaling != (1, 1):
        sscore += 25
    if min_speed >= speed:
        # if this encoder's speed is lower than the min_speed
        # then it isn't very suitable, discount its score:
        mss = (min_speed - speed) // 2
        sscore -= mss
    return round(sscore)


def get_pipeline_score(enc_in_format: str, csc_spec: CSCSpec | None, encoder_spec: VideoSpec,
                       width: int, height: int, scaling: tuple[int, int],
                       target_quality: int, min_quality: int,
                       target_speed: int, min_speed: int,
                       current_csce, current_ve,
                       score_delta: int, ffps: int, detection=True) -> tuple | None:
    """
        Given an optional csc step (csc_format and csc_spec),
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

    qscore = clamp(get_quality_score(enc_in_format, csc_spec, encoder_spec, scaling, target_quality, min_quality))
    sscore = get_speed_score(enc_in_format, csc_spec, encoder_spec, scaling, target_speed, min_speed)

    # multiplier for setup_cost:
    # (lose points if we have less than N fps)
    setup_cost_mult = int(detection) * (1 + max(0, MIN_FPS_COST - ffps))

    # how well the codec deals with larger screen sizes:
    sizescore = 100
    pixels = width * height
    if scaling != (1, 1):
        n, d = scaling
        pixels = pixels * n * n // d // d
    if pixels >= 1048576:
        # high size efficiency means sizescore stays high even with high number of mpixels,
        # ie: 1MPixels -> sizescore = 100
        # ie: 8MPixels -> sizescore = size_efficiency
        sdisc = 100 - encoder_spec.size_efficiency
        sizescore = max(0, 100 - pixels * sdisc // 1048576 // 4)

    # runtime codec adjustments:
    runtime_score = 100
    # score for "edge resistance" via setup cost:

    csc_width = 0
    csc_height = 0
    if csc_spec:
        # OR the masks, so we have a chance of making it work
        width_mask = csc_spec.width_mask & encoder_spec.width_mask
        height_mask = csc_spec.height_mask & encoder_spec.height_mask
        csc_width = width & width_mask
        csc_height = height & height_mask
        if enc_in_format == "RGB":
            # converting to "RGB" is often a waste of CPU
            # (can only get selected because the csc step will do scaling,
            # but even then, the YUV subsampling are better options)
            ecsc_score = 1
        else:
            ecsc_score = 80

            # if anything is different, account for setup cost:

            def is_csc_changed() -> bool:
                if current_csce is None:
                    return True
                if current_csce.get_dst_format() != enc_in_format:
                    return True
                if current_csce.get_type() != csc_spec.codec_type:
                    return True
                if current_csce.get_src_width() != csc_width or current_csce.get_src_height() != csc_height:
                    return True
                return False

            if is_csc_changed():
                # if we have to change csc, account for new csc setup cost:
                ecsc_score = max(0, 80 - round(csc_spec.setup_cost * setup_cost_mult * 80 // 100))
        ecsc_score += csc_spec.score_boost
        runtime_score *= csc_spec.get_runtime_factor()

        csc_scaling = scaling
        encoder_scaling = (1, 1)
        if scaling != (1, 1) and not csc_spec.can_scale:
            # csc cannot take care of scaling, so encoder will have to:
            encoder_scaling = scaling
            csc_scaling = (1, 1)
        if scaling != (1, 1):
            # if we are (down)scaling, we should prefer lossy pixel formats:
            v = LOSSY_PIXEL_FORMATS.get(enc_in_format, 1)
            qscore *= (v / 2)
        enc_width, enc_height = get_encoder_dimensions(encoder_spec, csc_width, csc_height, scaling)
    else:
        # not using csc at all!
        ecsc_score = 100
        width_mask = encoder_spec.width_mask
        height_mask = encoder_spec.height_mask
        enc_width = width & width_mask
        enc_height = height & height_mask
        csc_scaling = None
        encoder_scaling = scaling

    if encoder_scaling != (1, 1) and not encoder_spec.can_scale:
        # we need the encoder to scale but it cannot do it, fail it:
        log("scaling (%s) not supported by %s", encoder_scaling, encoder_spec)
        return None

    if enc_width < encoder_spec.min_w or enc_height < encoder_spec.min_h:
        log("video size %ix%i out of range for %s, min %ix%i",
            enc_width, enc_height, encoder_spec.codec_type, encoder_spec.min_w, encoder_spec.min_h)
        return None
    elif enc_width > encoder_spec.max_w or enc_height > encoder_spec.max_h:
        log("video size %ix%i out of range for %s, max %ix%i",
            enc_width, enc_height, encoder_spec.codec_type, encoder_spec.max_w, encoder_spec.max_h)
        return None

    ee_score = 100
    if current_ve is None or current_ve.get_type() != encoder_spec.codec_type or \
            current_ve.get_src_format() != enc_in_format or \
            current_ve.get_width() != enc_width or current_ve.get_height() != enc_height:
        # account for new encoder setup cost:
        ee_score = 100 - round(encoder_spec.setup_cost * setup_cost_mult)
        ee_score += encoder_spec.score_boost
    # edge resistance score: average of csc and encoder score:
    er_score = (ecsc_score + ee_score) // 2
    # gpu vs cpu
    gpu_score = max(0, GPU_BIAS - 50) * encoder_spec.gpu_cost // 50
    cpu_score = max(0, 50 - GPU_BIAS) * encoder_spec.cpu_cost // 50
    runtime_score *= encoder_spec.get_runtime_factor()
    score = round(
        (qscore + sscore + er_score + sizescore + score_delta + gpu_score + cpu_score) * runtime_score / 100)
    log(
        "get_pipeline_score(%-7s, %-24r, %-42r, %5i, %5i) quality: %3i, speed: %3i, setup: %4i - %4i runtime: %3i scaling: %s / %s, encoder dimensions=%sx%s, sizescore=%3i, client score delta=%3i, cpu score=%3i, gpu score=%3i, score=%3i",
        # noqa: E501
        enc_in_format, csc_spec, encoder_spec, width, height,
        qscore, sscore, ecsc_score, ee_score, runtime_score, scaling,
        encoder_scaling, enc_width, enc_height, sizescore, score_delta,
        cpu_score, gpu_score, score)
    return (
        score, scaling, csc_scaling, csc_width, csc_height, csc_spec, enc_in_format,
        encoder_scaling, enc_width, enc_height, encoder_spec,
    )


def get_encoder_dimensions(encoder_spec: VideoSpec, width: int, height: int, scaling=(1, 1)) -> tuple[int, int]:
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
