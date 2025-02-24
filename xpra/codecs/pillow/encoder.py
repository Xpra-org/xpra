# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from math import sqrt
from io import BytesIO
from typing import Any
from collections.abc import Sequence

import PIL
from PIL import Image, ImagePalette, __version__ as pil_version

from xpra.common import roundup
from xpra.codecs.debug import may_save_image
from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, hexstr
from xpra.net.compression import Compressed
from xpra.log import Logger

log = Logger("encoder", "pillow")

ENCODE_FORMATS = os.environ.get("XPRA_PILLOW_ENCODE_FORMATS", "png,png/L,png/P,jpeg,webp").split(",")

Image.init()

try:
    pil_major = int(pil_version.split(".")[0])
except ValueError:
    pil_major = 0


try:
    # pylint: disable=ungrouped-imports
    from PIL.Image import Palette, Resampling

    ADAPTIVE = Palette.ADAPTIVE
    WEB = Palette.WEB
    NEAREST = Resampling.NEAREST
    BILINEAR = Resampling.BILINEAR
    BICUBIC = Resampling.BICUBIC
    LANCZOS = Resampling.LANCZOS
except ImportError:
    # location for older versions:
    from PIL.Image import ADAPTIVE, WEB  # type: ignore
    from PIL.Image import NEAREST, BILINEAR, BICUBIC, LANCZOS  # type: ignore


def get_version() -> str:
    return PIL.__version__


def get_type() -> str:
    return "pillow"


def do_get_encodings() -> Sequence[str]:
    log("PIL.Image.SAVE=%s", Image.SAVE)
    encodings: list[str] = []
    for encoding in ENCODE_FORMATS:
        # strip suffix (so "png/L" -> "png")
        stripped = encoding.split("/")[0].upper()
        if stripped in Image.SAVE:
            encodings.append(encoding)
    log("do_get_encodings()=%s", encodings)
    return tuple(encodings)


def get_encodings() -> Sequence[str]:
    return ENCODINGS


ENCODINGS: Sequence[str] = do_get_encodings()


def get_info() -> dict[str, Any]:
    return {
        "version": get_version(),
        "encodings": get_encodings(),
    }


def encode(coding: str, image: ImageWrapper, options: typedict) -> tuple[str, Compressed, dict[str, Any], int, int, int, int]:
    if coding not in ("jpeg", "webp", "png", "png/P", "png/L"):
        raise ValueError(f"unsupported encoding: {coding!r}")
    log("pillow.encode%s", (coding, image, options))
    quality = options.intget("quality", 50)
    speed = options.intget("speed", 50)
    supports_transparency = options.boolget("alpha", True)
    grayscale = options.boolget("grayscale", False)
    pixel_format: str = image.get_pixel_format()
    palette: list[int] = []
    w: int = image.get_width()
    h: int = image.get_height()
    bpp = 32
    in_stride = image.get_rowstride()
    rowstride = in_stride
    pixels = image.get_pixels()
    if not pixels:
        raise RuntimeError(f"failed to get pixels from {image}")
    # remove transparency if it cannot be handled,
    # and deal with non-24-bit formats:
    if pixel_format == "r210":
        from xpra.codecs.argb.argb import r210_to_rgba, r210_to_rgb  # pylint: disable=import-outside-toplevel
        has_alpha = options.intget("depth", 24) == 32
        if has_alpha and supports_transparency:
            rowstride = w * 4
            pixels = r210_to_rgba(pixels, w, h, in_stride, w * 4)
            pixel_format = "RGBA"
        else:
            rowstride = roundup(w * 3, 2)
            pixels = r210_to_rgb(pixels, w, h, in_stride, rowstride)
            pixel_format = "RGB"
            bpp = 24
    elif pixel_format == "BGR565":
        from xpra.codecs.argb.argb import bgr565_to_rgbx, bgr565_to_rgb  # pylint: disable=import-outside-toplevel
        if supports_transparency:
            rowstride = in_stride * 2
            pixels = bgr565_to_rgbx(pixels)
            pixel_format = "RGBA"
        else:
            rowstride = in_stride * 3 // 2
            pixels = bgr565_to_rgb(pixels)
            pixel_format = "RGB"
            bpp = 24
    elif pixel_format == "RLE8":
        pixel_format = "P"
        palette = []
        # pillow requires 8 bit palette values,
        # but we get 16-bit values from the image wrapper (X11 palettes are 16-bit):
        for r, g, b in image.get_palette():
            palette.append((r >> 8) & 0xFF)
            palette.append((g >> 8) & 0xFF)
            palette.append((b >> 8) & 0xFF)
        bpp = 8
    else:
        if pixel_format not in ("RGBA", "RGBX", "BGRA", "BGRX", "BGR", "RGB"):
            raise ValueError(f"invalid pixel format {pixel_format!r}")
    rgb: str = {
        "XRGB": "RGB",
        "BGRX": "RGB",
        "RGBX": "RGB",
        "RGBA": "RGBA",
        "BGRA": "RGBA",
        "BGR": "RGB",
    }.get(pixel_format, pixel_format)
    pil_import_format = pixel_format.replace("A", "a")
    try:
        # older versions cannot use the memoryview directly:
        if pil_major < 10 and isinstance(pixels, memoryview):
            pixels = pixels.tobytes()
        # it is safe to use frombuffer() here since the convert()
        # calls below will not convert and modify the data in place,
        # and we save the compressed data then discard the image
        im = Image.frombuffer(rgb, (w, h), pixels, "raw", pil_import_format, rowstride, 1)
    except Exception as e:
        log("Image.frombuffer%s", (
            rgb, (w, h), len(pixels),
            "raw", pil_import_format, rowstride, 1),
            exc_info=True)
        log.error(f"Error: pillow failed to import image as {pil_import_format!r}:")
        log.estr(e)
        log.error(" for %s", image)
        log.error(f" pixel data: %i %s, with {rowstride=}", len(pixels), type(pixels))
        raise
    try:
        if palette:
            im.putpalette(palette)
            im.palette = ImagePalette.ImagePalette("RGB", palette=palette)
        if coding != "png/L" and grayscale:
            if rgb.find("A") >= 0 and supports_transparency and coding != "jpeg":
                im = im.convert("LA")
            else:
                im = im.convert("L")
            rgb = "L"
            bpp = 8
        elif coding.startswith("png") and not supports_transparency and rgb == "RGBA":
            im = im.convert("RGB")
            rgb = "RGB"
            bpp = 24
    except Exception as e:
        log.error("Error: pillow failed to convert image")
        log.estr(e)
        log.error(" for %s", im)
        raise
    scaled_width = options.intget("scaled-width", w)
    scaled_height = options.intget("scaled-height", h)
    client_options: dict[str, Any] = {}
    if scaled_width != w or scaled_height != h:
        if speed >= 95:
            resample = NEAREST
        elif speed > 80:
            resample = BILINEAR
        elif speed >= 30:
            resample = BICUBIC
        else:
            resample = LANCZOS
        im = im.resize((scaled_width, scaled_height), resample=resample)
        client_options["resample"] = getattr(resample, "name", str(resample))
    if coding in ("jpeg", "webp"):
        # newer versions of pillow require explicit conversion to non-alpha:
        if pixel_format.find("A") >= 0 and coding == "jpeg":
            im = im.convert("RGB")
        q = int(min(100, max(1, quality)))
        kwargs = dict(im.info)
        kwargs["quality"] = q
        if coding == "webp":
            kwargs["method"] = int(speed < 10)
            client_options["quality"] = min(100, max(0, 10 + round(sqrt(sqrt(q * 100) * 100))))
        else:
            client_options["quality"] = min(99, q)
        if coding == "jpeg" and speed < 50:
            # (optimizing jpeg is pretty cheap and worth doing)
            kwargs["optimize"] = True
        elif coding == "webp" and q >= 100:
            kwargs["lossless"] = True
            kwargs["quality"] = 0
        pil_fmt = coding.upper()
    else:
        assert coding in ("png", "png/P", "png/L"), "unsupported encoding: %r" % coding
        if coding in ("png/L", "png/P") and supports_transparency and rgb == "RGBA":
            # grab alpha channel (the last one):
            # we use the last channel because we know it is RGBA,
            # otherwise we should do: alpha_index= image.getbands().index('A')
            alpha = im.split()[-1]

            # convert to simple on or off mask:
            # set all pixel values below 128 to 255, and the rest to 0

            def mask_value(a) -> int:
                # without branch, same as:
                # return 255 if a <= 128 else 0
                return int(a <= 128) * 255

            mask = Image.eval(alpha, mask_value)
        else:
            # no transparency
            mask = None
        if coding == "png/L":
            im = im.convert("L", palette=ADAPTIVE, colors=255)
            bpp = 8
        elif coding == "png/P":
            # convert to 255 indexed colour if:
            # * we're not in palette mode yet (source is >8bpp)
            # * we need space for the mask (256 -> 255)
            if mask or not palette:
                # I wanted to use the "better" adaptive method,
                # but this does NOT work (produces a black image instead):
                # im.convert("P", palette=Image.ADAPTIVE)
                im = im.convert("P", palette=WEB, colors=255)
            bpp = 8
        kwargs = im.info
        if mask:
            # paste the alpha mask to the color of index 255
            im.paste(255, mask)
            client_options["transparency"] = 255
            kwargs["transparency"] = 255
        if speed == 0:
            # optimizing png is very rarely worth doing
            kwargs["optimize"] = True
        # level can range from 0 to 9, but anything above 5 is way too slow for small gains:
        # 76-100   -> 1
        # 51-76    -> 2
        # etc
        level = max(1, min(5, (100 - speed) // 25))
        kwargs["compress_level"] = level
        # no need to expose to the client:
        # client_options["compress_level"] = level
        # default is good enough, no need to override, other options:
        # DEFAULT_STRATEGY, FILTERED, HUFFMAN_ONLY, RLE, FIXED
        # kwargs["compress_type"] = Image.DEFAULT_STRATEGY
        pil_fmt = "PNG"
    buf = BytesIO()
    im.save(buf, pil_fmt, **kwargs)
    data = buf.getvalue()
    may_save_image(pil_fmt, data)
    log("sending %sx%s %s as %s, mode=%s, options=%s", w, h, pixel_format, coding, im.mode, kwargs)
    buf.close()
    return coding, Compressed(coding, data), client_options, image.get_width(), image.get_height(), 0, bpp


def selftest(full=False) -> None:
    global ENCODINGS
    # pylint: disable=import-outside-toplevel
    from xpra.codecs.checks import make_test_image
    img = make_test_image("BGRA", 128, 128)
    vrange: Sequence[int] = (50,)
    if full:
        vrange = (0, 50, 100)
    for encoding in tuple(ENCODINGS):
        q = s = 0
        alpha = False
        try:
            for q in vrange:
                for s in vrange:
                    for alpha in (True, False):
                        v = encode(encoding, img, typedict({
                            "quality": q,
                            "speed": s,
                            "alpha": alpha,
                        }))
                        assert v, "encode output was empty!"
                        cdata = v[1].data
                        log("encode(%s)=%s", (encoding, img, q, s, alpha), hexstr(cdata))
        except Exception as e:  # pragma: no cover
            log_fn = log.warn
            log_fn("Pillow error saving %s with quality=%s, speed=%s, alpha=%s", encoding, q, s, alpha)
            log_fn(" %s", e, exc_info=True)
            encs: list[str] = list(ENCODINGS)
            encs.remove(encoding)
            ENCODINGS = tuple(encs)


if __name__ == "__main__":
    selftest(True)
    print(csv(get_encodings()))
