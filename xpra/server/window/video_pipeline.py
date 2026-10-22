# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Enumerate video pipelines without creating codecs or owning window state."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any, NamedTuple, Protocol

from xpra.codecs.constants import CSCSpec, VideoSpec
from xpra.codecs.protocols import ColorspaceConverter, VideoEncoder
from xpra.server.window.video_scoring import PipelineScore, get_pipeline_score
from xpra.log import Logger

log = Logger("score")


class PipelineSpecs(Protocol):
    def get_csc_specs(self, src_format: str) -> Mapping[str, Sequence[CSCSpec]]:
        ...

    def get_encoder_specs(self, encoding: str) -> Mapping[str, Sequence[VideoSpec]]:
        ...


@dataclass(frozen=True, slots=True)
class PipelineSettings:
    quality: int
    min_quality: int
    speed: int
    min_speed: int
    max_size: tuple[int, int]
    text_hint: bool
    is_shadow: bool
    force_csc: bool
    force_csc_mode: str
    preferred_encodings: Sequence[str]


class PipelineCodecState(NamedTuple):
    """Live codec references and detection state, read separately for each score."""

    csc: ColorspaceConverter | None = None
    encoder: VideoEncoder | None = None
    detection: bool = False


def get_pipeline_quality(quality: int, min_quality: int, video_fps: int | None) -> int:
    """Adjust a matching subregion's quality; None denotes non-video content."""
    if video_fps is None:
        return int(sqrt(quality / 100.0) * 100)
    reduction = min(90, 2 * video_fps)
    return max(min_quality, int(quality * (100 - reduction) // 100))


def get_pipeline_options(encodings: Iterable[str], width: int, height: int, src_format: str,
                         settings: PipelineSettings, specs: PipelineSpecs,
                         get_client_formats: Callable[[str], Sequence[str]], score_deltas: Mapping[str, Any],
                         calculate_scaling: Callable[[int, int, int, int], tuple[int, int]],
                         is_cancelled: Callable[[], bool], get_codec_state: Callable[[], PipelineCodecState],
                         fps: int) -> tuple[PipelineScore, ...]:
    """Return candidates in stable descending score order, including partial results on cancellation.

    Codec state and runtime factors remain live reads. The caller owns cache publication
    and must check cancellation again before publishing these results.
    """
    max_width, max_height = (16384, 16384) if settings.text_hint else settings.max_size
    cached_w = cached_h = 4096
    cached_scaling = calculate_scaling(width, height, cached_w, cached_h)
    scores = []
    all_no_match = {}
    csc_specs = specs.get_csc_specs(src_format)
    log(f"csc for {src_format} source format: {csc_specs}")
    if settings.force_csc:
        csc_specs = {settings.force_csc_mode: csc_specs.get(settings.force_csc_mode, ())}
        log("forced CSC mode %s: %s", settings.force_csc_mode, csc_specs)
    for encoding in encodings:
        supported_csc_modes = get_client_formats(encoding)
        if not supported_csc_modes:
            log(" no supported csc modes for %s", encoding)
            continue
        encoder_specs = specs.get_encoder_specs(encoding)
        if not encoder_specs:
            log(" no encoder specs for %s", encoding)
            continue
        log(f"encoders({encoding})={encoder_specs}, {supported_csc_modes=}")
        try:
            encoding_score_delta = len(settings.preferred_encodings) // 2 - list(settings.preferred_encodings).index(encoding)
        except ValueError:
            encoding_score_delta = 0
        encoding_score_delta = score_deltas.get(f"{encoding}.score-delta", encoding_score_delta)
        no_match = []

        def add_scores(info: str, csc_spec: CSCSpec | None, enc_in_format: str) -> None:
            colorspace_specs = encoder_specs.get(enc_in_format)
            if not colorspace_specs:
                log(f"no encoders for {enc_in_format}")
                no_match.append(info)
                return
            for encoder_spec in colorspace_specs:
                matches = tuple(x for x in encoder_spec.output_colorspaces if x in supported_csc_modes)
                if not matches or is_cancelled():
                    log(f"output colorspaces {encoder_spec.output_colorspaces} not supported")
                    no_match.append(encoder_spec.codec_type + " " + info)
                    continue
                max_w = min(encoder_spec.max_w, max_width)
                max_h = min(encoder_spec.max_h, max_height)
                if (csc_spec and csc_spec.can_scale) or encoder_spec.can_scale:
                    if width <= max_w and height <= max_h and cached_w >= width and cached_h >= height:
                        scaling = cached_scaling
                    else:
                        scaling = calculate_scaling(width, height, max_w, max_h)
                else:
                    scaling = (1, 1)
                score_delta = encoding_score_delta
                lossy_csc = enc_in_format in ("NV12", "YUV420P", "YUV422P")
                if scaling != (1, 1) or lossy_csc:
                    if settings.text_hint:
                        score_delta -= 500
                    elif settings.quality >= 100:
                        score_delta -= 250
                if settings.is_shadow and lossy_csc and scaling == (1, 1):
                    score_delta -= 40
                state = get_codec_state()
                score_data = get_pipeline_score(enc_in_format, csc_spec, encoder_spec, width, height, scaling,
                                                settings.quality, settings.min_quality, settings.speed, settings.min_speed,
                                                state.csc, state.encoder, score_delta, fps, state.detection)
                if score_data:
                    scores.append(score_data)
                else:
                    log(" no score data for %s", (enc_in_format, csc_spec, encoder_spec, width, height, scaling, ".."))

        if not settings.force_csc or src_format == settings.force_csc_mode:
            add_scores(f"direct (no csc) {src_format}", None, src_format)
        for out_csc, converters in csc_specs.items():
            for csc_spec in converters:
                add_scores(f"via {out_csc}", csc_spec, out_csc)
        all_no_match[encoding] = no_match
    if all_no_match:
        log("no matching colorspace specs for %s", all_no_match)
    return tuple(sorted(scores, key=lambda score: -score[0]))
