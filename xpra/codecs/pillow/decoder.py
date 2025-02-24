# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from io import BytesIO
import PIL
from PIL import Image
from typing import Any
from collections.abc import Callable, Sequence

from xpra.common import SizedBuffer
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, strtobytes, hexstr, memoryview_to_bytes
from xpra.codecs.debug import may_save_image
from xpra.log import Logger

log = Logger("encoder", "pillow")

Image.init()

DECODE_FORMATS = os.environ.get("XPRA_PILLOW_DECODE_FORMATS", "png,png/L,png/P,jpeg,webp").split(",")

PNG_HEADER = struct.pack("BBBBBBBB", 137, 80, 78, 71, 13, 10, 26, 10)


def is_png(data: bytes) -> bool:
    return data.startswith(PNG_HEADER)


RIFF_HEADER = b"RIFF"
WEBP_HEADER = b"WEBP"


def is_webp(data: bytes) -> bool:
    return data[:4] == RIFF_HEADER and data[8:12] == WEBP_HEADER


JPEG_HEADER = struct.pack("BBB", 0xFF, 0xD8, 0xFF)


def is_jpeg(data: bytes) -> bool:
    # the jpeg header is actually more complicated than this,
    # but in practice all the data we receive from the server
    # will have this type of header
    return data[:3] == JPEG_HEADER


def is_svg(data: bytes) -> bool:
    return strtobytes(data[:5]) == b"<?xml" or strtobytes(data[:4]) == b"<svg"


XPM_HEADER = b"/* XPM */"


def is_xpm(data: bytes) -> bool:
    return data[:9] == XPM_HEADER


def is_tiff(data: bytes) -> bool:
    if data[:2] == b"II":
        return data[2] == 42 and data[3] == 0
    if data[:2] == b"MM":
        return data[2] == 0 and data[3] == 42
    return False


HEADERS: dict[Callable[[bytes], bool], str] = {
    is_png: "png",
    is_webp: "webp",
    is_jpeg: "jpeg",
    is_svg: "svg",
    is_xpm: "xpm",
    is_tiff: "tiff",
}


def get_image_type(data: SizedBuffer) -> str:
    if not data:
        return ""
    if len(data) < 32:
        return ""
    header = memoryview_to_bytes(data[:32])
    for fn, encoding in HEADERS.items():
        if fn(header):
            return encoding
    return ""


def open_only(data: SizedBuffer, types=("png", "jpeg", "webp", "xpm")) -> Image:
    itype = get_image_type(data) or "unknown"
    if itype not in types:
        raise ValueError(f"invalid data: {itype}, not recognized as {csv(types)}, header: " + hexstr(data[:64]))
    buf = BytesIO(data)
    return Image.open(buf)


def get_version() -> str:
    return PIL.__version__


def get_type() -> str:
    return "pillow"


def do_get_encodings() -> list[str]:
    log("PIL.Image.OPEN=%s", Image.OPEN)
    encodings = []
    for encoding in DECODE_FORMATS:
        # strip suffix (so "png/L" -> "png")
        stripped = encoding.split("/")[0].upper()
        if stripped in Image.OPEN:
            encodings.append(encoding)
    log("do_get_encodings()=%s", encodings)
    return encodings


ENCODINGS: Sequence[str] = tuple(do_get_encodings())


def get_encodings() -> Sequence[str]:
    return ENCODINGS


def get_info() -> dict[str, Any]:
    return {
        "version": get_version(),
        "encodings": get_encodings(),
    }


def decompress(coding: str, img_data: bytes, options: typedict) -> tuple[str, bytes, int, int, int]:
    # can be called from any thread
    actual = get_image_type(img_data)
    if not actual or not coding.startswith(actual):
        raise ValueError(f"expected {coding!r} image data but received %r" % (actual or "unknown"))
    buf = BytesIO(img_data)
    img = Image.open(buf)
    assert img.mode in ("L", "LA", "P", "RGB", "RGBA", "RGBX"), f"invalid image mode: {img.mode}"
    transparency = options.intget("transparency", -1)
    if img.mode == "P":
        if transparency >= 0:
            # this deals with alpha without any extra work
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
    elif img.mode == "L":
        if transparency >= 0:
            # why do we have to deal with alpha ourselves??
            def mask_value(a: int) -> int:
                if a != transparency:
                    return 255
                return 0

            mask = Image.eval(img, mask_value)
            mask = mask.convert("L")

            def nomask_value(a: int) -> int:
                if a != transparency:
                    return a
                return 0

            img = Image.eval(img, nomask_value)
            img = img.convert("RGBA")
            img.putalpha(mask)
        else:
            img = img.convert("RGB")
    elif img.mode == "LA":
        img = img.convert("RGBA")

    width, height = img.size
    if img.mode == "RGB":
        # PIL flattens the data to a continuous straightforward RGB format:
        rowstride = width * 3
        rgb_format = options.strget("rgb_format")
        rgb_format = rgb_format.replace("A", "").replace("X", "")
        # the webp encoder only takes BGRX input,
        # so we have to swap things around if it was fed "RGB":
        if rgb_format == "RGB":
            rgb_format = "BGR"
        else:
            rgb_format = "RGB"
    elif img.mode in ("RGBA", "RGBX"):
        rowstride = width * 4
        rgb_format = options.strget("rgb_format", img.mode)
        if coding == "webp":
            # the webp encoder only takes BGRX input,
            # so we have to swap things around if it was fed "RGBA":
            if rgb_format == "RGBA":
                rgb_format = "BGRA"
            elif rgb_format == "RGBX":
                rgb_format = "BGRX"
            elif rgb_format == "BGRA":
                rgb_format = "RGBA"
            elif rgb_format == "BGRX":
                rgb_format = "RGBX"
            else:
                log.warn("Warning: unexpected RGB format '%s'", rgb_format)
    else:
        raise ValueError(f"invalid image mode: {img.mode}")
    raw_data = img.tobytes("raw", img.mode)
    log("pillow decoded %7i bytes of %5s data to %8i bytes of %s", len(img_data), coding, len(raw_data), rgb_format)
    may_save_image(coding, img_data)
    return rgb_format, raw_data, width, height, rowstride


def selftest(_full=False) -> None:
    global ENCODINGS
    from xpra.codecs.checks import TEST_PICTURES  # pylint: disable=import-outside-toplevel
    # test data generated using the encoder:
    for encoding, test_data in TEST_PICTURES.items():
        if encoding not in ENCODINGS:
            # removed already
            continue
        for size, samples in test_data.items():
            log(f"testing {encoding} at size {size} with {len(samples)} samples")
            for i, (cdata, options) in enumerate(samples):
                try:
                    log(f"testing sample {i}: {len(cdata):5} bytes")
                    buf = BytesIO(cdata)
                    img = PIL.Image.open(buf)
                    assert img, "failed to open image data"
                    raw_data = img.tobytes("raw", img.mode)
                    assert raw_data
                    # now try with junk:
                    cdata = b"ABCD" + cdata
                    buf = BytesIO(cdata)
                    try:
                        img = PIL.Image.open(buf)
                        log.warn(f"Pillow failed to generate an error parsing invalid input: {img}, {options=}")
                    except Exception as e:
                        log("correctly raised exception for invalid input: %s", e)
                except Exception as e:
                    log("selftest:", exc_info=True)
                    log.error("Pillow error decoding %s with data:", encoding)
                    log.error(" %r", cdata)
                    log.error(" %s", e, exc_info=True)
                    ENCODINGS = tuple(x for x in ENCODINGS if x != encoding)


if __name__ == "__main__":
    selftest(True)
    print(csv(get_encodings()))
