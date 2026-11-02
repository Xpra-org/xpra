# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envint
from xpra.codecs.constants import VideoSpec


# With rate control disabled, low QPs can overflow OpenH264's fixed bitstream
# buffers even on small noisy images. Larger frames can also exceed the decoder's
# access-unit limit. Keep some headroom for both CABAC and CAVLC streams.
MAX_QUALITY = max(0, min(100, envint("XPRA_OPENH264_MAX_QUALITY", 45)))
LARGE_FRAME_PIXELS = max(1, envint("XPRA_OPENH264_LARGE_FRAME_PIXELS", 1920 * 1080))
LARGE_FRAME_MAX_QUALITY = max(0, min(MAX_QUALITY, envint("XPRA_OPENH264_LARGE_FRAME_MAX_QUALITY", 35)))


def get_effective_quality(quality: int, width: int, height: int) -> int:
    """Bound the quality using the dimensions actually passed to the encoder."""
    if quality < 0:
        quality = 50
    limit = LARGE_FRAME_MAX_QUALITY if width * height > LARGE_FRAME_PIXELS else MAX_QUALITY
    return min(quality, limit)


class OpenH264Spec(VideoSpec):

    def get_effective_quality(self, quality: int, width: int, height: int) -> int:
        return get_effective_quality(quality, width, height)
