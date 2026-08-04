# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Colourspace descriptors.

A colourspace is described by four independent code points rather than by an ICC profile:
primaries, transfer function, matrix coefficients and range.
The numbering is the one from ITU-T H.273 (ISO/IEC 23091-2),
which is what x264, libvpx, aom, avif and ffmpeg already use,
so these values can be handed to the encoders without a translation table.

A virtual framebuffer has no colourimetry of its own
(no EDID, no ICC profile, and the X11 core protocol cannot express primaries at all),
so `SRGB` is the only sensible interpretation of its contents,
and it is what every toolkit assumes in the absence of any metadata.
"""

from enum import IntEnum
from typing import Any
from dataclasses import dataclass, fields


class Primaries(IntEnum):
    BT709 = 1               # also sRGB
    UNSPECIFIED = 2
    BT2020 = 9
    DISPLAY_P3 = 12         # SMPTE EG 432-1


class TransferFunction(IntEnum):
    BT709 = 1
    UNSPECIFIED = 2
    LINEAR = 8
    SRGB = 13               # IEC 61966-2-1
    BT2020 = 14
    PQ = 16                 # SMPTE ST 2084
    HLG = 18                # ARIB STD-B67


class MatrixCoefficients(IntEnum):
    IDENTITY = 0            # RGB / GBR: no matrix applied
    BT709 = 1
    UNSPECIFIED = 2
    BT2020_NCL = 9          # non-constant luminance


class Range(IntEnum):
    LIMITED = 0
    FULL = 1


def _parse(enum_class, value, default):
    try:
        return enum_class(int(value))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True, kw_only=True)
class Colourspace:
    primaries: Primaries = Primaries.BT709
    transfer: TransferFunction = TransferFunction.SRGB
    # `matrix` describes how the stored samples relate to RGB:
    # framebuffers are RGB, so `IDENTITY`.
    # (the video encoders choose their own matrix for the RGB to YUV conversion, per frame)
    matrix: MatrixCoefficients = MatrixCoefficients.IDENTITY
    range: Range = Range.FULL

    def to_dict(self) -> dict[str, int]:
        return {f.name: int(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, value: Any, default: "Colourspace | None" = None) -> "Colourspace":
        """
        Parse a colourspace from its dictionary form,
        falling back to `default` for anything missing, unknown or malformed
        (ie: values from a newer version, or no data at all from an older one)
        """
        default = default or SRGB
        if not isinstance(value, dict):
            return default
        return cls(
            primaries=_parse(Primaries, value.get("primaries"), default.primaries),
            transfer=_parse(TransferFunction, value.get("transfer"), default.transfer),
            matrix=_parse(MatrixCoefficients, value.get("matrix"), default.matrix),
            range=_parse(Range, value.get("range"), default.range),
        )

    def __str__(self):
        return "Colourspace(%s)" % ", ".join(f"{f.name}={getattr(self, f.name).name}" for f in fields(self))


SRGB: Colourspace = Colourspace()
