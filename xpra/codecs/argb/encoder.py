# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.codecs.rgb_transform import rgb_reformat
from xpra.codecs import rgb_transform
from xpra.codecs.debug import SAVE_TO_FILE, may_save_image
from xpra.net.compression import Compressed, LevelCompressed, compressed_wrapper
from xpra.log import Logger

log = Logger("encoder", "argb")


def get_version() -> tuple[int, int]:
    return 6, 0


def get_type() -> str:
    return "rgb"


def get_encodings() -> Sequence[str]:
    return "rgb24", "rgb32"


def get_info() -> dict[str, Any]:
    return {
        "version": get_version(),
        "encodings": get_encodings(),
    }


def encode(coding: str, image, options: dict) -> tuple[str, Compressed, dict[str, Any], int, int, int, int]:
    pixel_format = image.get_pixel_format()
    # log("rgb_encode%s pixel_format=%s, rgb_formats=%s",
    #    (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4), pixel_format, rgb_formats)
    if pixel_format in ("BGRX", "BGRA", "RGBA", "RGBX"):
        rgb_formats = options.get("rgb_formats", ("BGRX", "BGRA", "RGBA", "RGBX"))
    elif pixel_format in ("RGB", "BGR"):
        rgb_formats = options.get("rgb_formats", ("RGB", "BGR"))
    elif pixel_format in ("r210", "BGR565"):
        rgb_formats = options.get("rgb_formats", (pixel_format, ))
    else:
        raise ValueError(f"unsupported pixel format {pixel_format!r}")
    supports_transparency = options.get("alpha", True)
    if not rgb_formats:
        raise ValueError(f"no rgb formats for {pixel_format!r} input")
    if pixel_format not in rgb_formats:
        log("rgb_encode reformatting because %s not in %s, supports_transparency=%s",
            pixel_format, rgb_formats, supports_transparency)
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            raise ValueError(f"no compatible rgb format for {pixel_format!r}! (only: {rgb_formats})")
        # get the new format:
        pixel_format = image.get_pixel_format()
        # switch encoding if necessary:
        if len(pixel_format) == 4:
            coding = "rgb32"
        elif len(pixel_format) == 3:
            coding = "rgb24"
        else:
            raise ValueError(f"invalid pixel format {pixel_format!r}")
    # we may still want to re-stride:
    image.may_restride()
    # always tell client which pixel format we are sending:
    client_options = {"rgb_format": pixel_format}

    # compress here and return a wrapper so network code knows it is already zlib compressed:
    pixels = image.get_pixels()
    if not pixels:
        raise RuntimeError(f"failed to get pixels from {image}")
    width = image.get_width()
    height = image.get_height()
    stride = image.get_rowstride()
    speed = options.get("speed", 50)

    # compression stage:
    level = 0
    size = len(pixels)
    lz4 = options.get("lz4", False)
    if lz4 and size >= 512 and speed < 100:
        if size >= 4096:
            level = 1 + max(0, min(7, int(100 - speed) // 14))
        else:
            # fewer pixels, make it more likely we won't bother compressing
            # and use a lower level (max=3)
            level = max(0, min(3, int(125 - speed) // 35))
    if level > 0:
        algo = "lz4"
        can_inline = size <= 32768
        cwrapper = compressed_wrapper(coding, pixels, level=level,
                                      lz4=lz4,
                                      can_inline=can_inline)
        if isinstance(cwrapper, LevelCompressed):
            # add compressed marker:
            client_options[cwrapper.algorithm] = cwrapper.level & 0xF
            # remove network layer compression marker
            # so that this data will be decompressed by the decode thread client side:
            cwrapper.level = 0
        elif can_inline and isinstance(pixels, memoryview):
            assert isinstance(cwrapper, Compressed)
            assert cwrapper.data == pixels
            # compression either did not work or was not enabled
            # and `memoryview` pixel data cannot be handled by the packet encoders,
            # so we have to convert it to bytes:
            cwrapper.data = rgb_transform.pixels_to_bytes(pixels)
            algo = "inlined lz4"
    else:
        # can't pass a raw buffer to rencodeplus,
        # and even if we could, the image containing those pixels may be freed by the time we get to the encoder
        algo = "not"
        cwrapper = Compressed(coding, rgb_transform.pixels_to_bytes(pixels))
    if pixel_format.find("A") >= 0 or pixel_format.find("X") >= 0:
        bpp = 32
    else:
        bpp = 24
    log("rgb_encode using level=%s for %5i bytes at %3i speed, %s compressed %4sx%-4s in %s/%s: %5s bytes down to %5s",
        level, size, speed, algo, width, height, coding, pixel_format, len(pixels), len(cwrapper.data))
    if SAVE_TO_FILE and pixel_format in ("BGRX", "BGRA", ):
        may_save_image(coding, pixels)
        from io import BytesIO
        from PIL import Image
        img = Image.frombuffer("RGB" if pixel_format == "BGRX" else "BGRA",
                               (width, height), pixels, "raw", pixel_format, stride)
        buf = BytesIO()
        img.save(buf, "png")
        data = buf.getvalue()
        may_save_image("png", data)

    # wrap it using "Compressed" so the network layer receiving it
    # won't decompress it (leave it to the client's draw thread)
    return coding, cwrapper, client_options, width, height, stride, bpp
