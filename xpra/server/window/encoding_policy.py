# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Encoding selection over explicit window state and ordered encoding choices."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto

DEFAULT_TRANSPARENCY_ENCODINGS = "webp", "png", "rgb32", "jpega"


class EncodingStrategy(Enum):
    DEFAULT = auto()
    HARDCODED = auto()
    HINT = auto()
    MMAP = auto()
    PNG_L = auto()
    PNG_P = auto()
    RGB32 = auto()
    RGB24 = auto()
    STRICT = auto()
    GRAYSCALE = auto()
    TRANSPARENT = auto()


@dataclass(frozen=True, slots=True)
class EncodingStrategyState:
    encoding: str = "auto"
    common_encodings: tuple[str, ...] = ()
    image_depth: int = 24
    want_alpha: bool = False
    is_tray: bool = False
    has_shape: bool = False
    strict: bool = False
    using_mmap: bool = False
    hint_available: bool = False
    hardcoded: bool = False


@dataclass(frozen=True, slots=True)
class EncodingState:
    encoding: str = "auto"
    image_depth: int = 24
    client_bit_depth: int = 24
    want_alpha: bool = False
    is_tray: bool = False
    has_shape: bool = False
    rgb_auto_threshold: int = 0
    natural_content: bool = False


def select_encoding_strategy(state: EncodingStrategyState) -> EncodingStrategy:
    if state.hardcoded:
        return EncodingStrategy.HARDCODED
    if state.hint_available:
        return EncodingStrategy.HINT
    if state.using_mmap and state.encoding != "grayscale":
        return EncodingStrategy.MMAP
    if state.encoding == "png/L":
        return EncodingStrategy.PNG_L
    if state.image_depth == 8 or state.encoding == "png/P":
        if state.encoding == "grayscale":
            assert "png/L" in state.common_encodings
            return EncodingStrategy.PNG_L
        assert "png/P" in state.common_encodings
        return EncodingStrategy.PNG_P
    if state.strict and state.encoding not in ("auto", "stream"):
        if state.encoding == "rgb":
            if state.want_alpha and "rgb32" in state.common_encodings:
                return EncodingStrategy.RGB32
            assert "rgb24" in state.common_encodings
            return EncodingStrategy.RGB24
        return EncodingStrategy.STRICT
    if state.want_alpha or state.is_tray:
        if state.encoding in ("rgb", "rgb32") and "rgb32" in state.common_encodings:
            return EncodingStrategy.RGB32
        if state.encoding in ("png", "png/P", "png/L"):
            return EncodingStrategy.STRICT
        if state.encoding == "grayscale":
            return EncodingStrategy.GRAYSCALE
        return EncodingStrategy.TRANSPARENT
    if state.encoding == "rgb" and not state.has_shape:
        if "rgb24" in state.common_encodings:
            return EncodingStrategy.RGB24
        if "rgb32" in state.common_encodings:
            return EncodingStrategy.RGB32
    # The source owns this hook: a video source can supply its own default.
    return EncodingStrategy.DEFAULT


def select_auto_encoding(state: EncodingState, width: int, height: int, encodings: Sequence[str], *,
                         quality: int = 0, speed: int = 50, current_encoding: str = "",
                         webp_efficiency_cutoff: int = 512*1024) -> str:
    if not encodings:
        raise ValueError("no options to choose from")
    depth = state.image_depth
    grayscale = state.encoding == "grayscale"
    alpha = state.want_alpha or state.is_tray
    if width*height < state.rgb_auto_threshold and not grayscale and not state.has_shape:
        if depth > 24 and state.client_bit_depth > 24 and "rgb32" in encodings:
            return "rgb32"
        if "rgb24" in encodings:
            return "rgb24"
    jpeg = "jpeg" in encodings and width >= 2 and height >= 2
    jpega = "jpega" in encodings and width >= 2 and height >= 2
    webp = "webp" in encodings and 16383 >= width >= 2 and 16383 >= height >= 2 and not grayscale
    jph = "jph" in encodings and not grayscale
    avif = "avif" in encodings
    lossy = quality < 100
    if depth in (24, 32) and (jpeg or jpega or webp or avif or jph):
        if state.natural_content and quality <= 50 and jph and not alpha and speed < 50:
            return "jph"
        if webp and (not lossy or width*height <= webp_efficiency_cutoff):
            return "webp"
        if lossy:
            if jpeg and not alpha:
                return "jpeg"
            if jpega and alpha:
                return "jpega"
        if webp:
            return "webp"
        if avif:
            return "avif"
        if jph:
            return "jph"
    elif depth > 24 and "rgb32" in encodings and state.client_bit_depth > 24 and state.client_bit_depth != 32:
        return "rgb32"
    if "png" in encodings and (not lossy or depth <= 16):
        return "png"
    if jpeg and lossy:
        return "jpeg"
    if avif:
        return "avif"
    if current_encoding in encodings:
        return current_encoding
    try:
        return next(encoding for encoding in encodings if encoding != "rgb")
    except StopIteration:
        return encodings[0]


def select_transparent_encoding(state: EncodingState, width: int, height: int, encodings: Sequence[str], *,
                                quality: int, current_encoding: str = "",
                                transparency_encodings: Sequence[str] = DEFAULT_TRANSPARENCY_ENCODINGS,
                                webp_efficiency_cutoff: int = 512*1024) -> str | None:
    """Return None when the source should delegate to its automatic selector."""
    if current_encoding in transparency_encodings:
        return current_encoding
    common = tuple(encoding for encoding in encodings if encoding in transparency_encodings)
    if not common and current_encoding:
        return current_encoding
    lossy = quality < 100
    if "rgb32" in common and not state.has_shape:
        if width*height < state.rgb_auto_threshold:
            return "rgb32"
        if not lossy and state.image_depth > 24 and state.client_bit_depth > 24:
            return "rgb32"
    grayscale = state.encoding == "grayscale"
    webp = "webp" in common and 16383 >= width >= 2 and 16383 >= height >= 2 and not grayscale
    if webp and state.image_depth in (24, 32) and (not lossy or width*height <= webp_efficiency_cutoff):
        return "webp"
    if "jpega" in common and width >= 2 and height >= 2 and lossy:
        return "jpega"
    if webp:
        return "webp"
    for encoding in ("png", "rgb32"):
        if encoding in common:
            return encoding
    return None
