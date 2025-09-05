# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True, always_allow_keywords=False

from typing import Any, Dict, Tuple
from collections.abc import Sequence

# libaom 3.3 as found in Ubuntu 22.04 doesn't define `AOM_IMG_FMT_NV12`,
# so we just duplicate the definition here instead:
cdef aom_img_fmt_t AOM_IMG_FMT_NV12 = <aom_img_fmt_t> (AOM_IMG_FMT_PLANAR | 7)


FORMAT_STRS: Dict[aom_img_fmt_t, str] = {
    AOM_IMG_FMT_NONE: "None",
    AOM_IMG_FMT_I420: "YUV420P",
    AOM_IMG_FMT_I422: "YUV422P",
    AOM_IMG_FMT_I444: "YUV444P",
    AOM_IMG_FMT_YV12: "YV12",
    AOM_IMG_FMT_NV12: "NV12",
    AOM_IMG_FMT_AOMYV12: "AOMYV12",
    AOM_IMG_FMT_AOMI420: "AOMI420",
    AOM_IMG_FMT_I42016: "YUV420P16",
    AOM_IMG_FMT_YV1216: "YV12P16",
    AOM_IMG_FMT_I42216: "YUV422P16",
    AOM_IMG_FMT_I44416: "YUV444P16",
}


cdef str get_format_str(aom_img_fmt_t fmt):
    """Return the string representation of the image format."""
    return FORMAT_STRS.get(fmt, f"Unknown({fmt})")