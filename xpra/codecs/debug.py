# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.codecs.image import ImageWrapper
from xpra.util.str_fn import memoryview_to_bytes
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("codec")

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")


def may_save_image(coding: str, data: memoryview | bytes | bytearray, now: float = 0):
    if SAVE_TO_FILE:  # pragma: no cover
        now = now or monotonic()
        ext = coding.lower().replace("/", "-")
        filename = f"./{now}.{ext}"
        bdata = memoryview_to_bytes(data)
        with open(filename, "wb") as f:
            f.write(bdata)
        log.info("saved %7i bytes to %s", len(data), filename)


def save_imagewrapper(image: ImageWrapper, filename: str) -> None:
    import os.path
    from xpra.util.objects import typedict
    from xpra.codecs.pillow.encoder import encode
    ext = os.path.splitext(filename)[1].lstrip(".")
    cdata = encode(ext, image, typedict())[1]
    w = image.get_width()
    h = image.get_height()
    stride = image.get_rowstride()
    log("save_image: saving %4ix%-4i pixels, %7i bytes to %s", w, h, (stride * h), filename)
    with open(filename, "wb") as f:
        f.write(cdata.data)
