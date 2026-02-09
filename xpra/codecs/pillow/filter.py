# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Sequence
from PIL import Image, ImageFilter

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import CSCSpec
from xpra.util.str_fn import parse_function_call
from xpra.log import Logger

log = Logger("csc", "pillow")


def get_type() -> str:
    return "pillow"


def get_version() -> tuple[int, int]:
    return 6, 5


def get_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "version": get_version(),
    }
    return info


def get_specs() -> Sequence[CSCSpec]:
    return (
        CSCSpec(
            input_colorspace="BGRX", output_colorspaces=("BGRX", ),
            codec_class=Filter, codec_type=get_type(),
            setup_cost=0, min_w=2, min_h=2,
            max_w=16*1024, max_h=16*1024,
        ),
    )


def get_default_filters() -> Sequence[str]:
    return (
        "BLUR",
        "CONTOUR",
        "DETAIL",
        "EDGE_ENHANCE",
        "EDGE_ENHANCE_MORE",
        "EMBOSS",
        "FIND_EDGES",
        "SHARPEN",
        "SMOOTH",
        "SMOOTH_MORE",
        "BoxBlur(radius=10)",
        "GaussianBlur(radius=10)",
    )


MAX_WIDTH = 16384
MAX_HEIGHT = 16384


class Filter:
    __slots__ = ("closed", "width", "height", "filter")

    def __init__(self):
        self.closed = False
        self.width = 0
        self.height = 0
        self.filter = None

    def init_context(self, src_width: int, src_height: int, src_format: str,
                     dst_width: int, dst_height: int, dst_format: str, options: typedict) -> None:
        assert src_width == dst_width and src_height == dst_height, "this module does not handle any scaling"
        assert 0 < src_width <= MAX_WIDTH, f"invalid width {src_width}"
        assert 0 < src_height <= MAX_HEIGHT, f"invalid height {src_height}"
        assert src_format == "BGRX" and dst_format == "BGRX", "this module only handles BGRX"
        self.width = src_width
        self.height = src_height
        transform_str = options.strget("transform", "BLUR")
        if transform_str.isupper():  # ie: "BLUR"
            self.filter = getattr(ImageFilter, transform_str)
        else:
            function_name, kwargs = parse_function_call(transform_str)
            filter_class = getattr(ImageFilter, function_name)
            self.filter = filter_class(**kwargs)
        log("init_context options=%s, using %r=%s", options, transform_str, self.filter)

    def clean(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def get_info(self) -> dict[str,Any]:
        info = get_info()
        info["closed"] = self.closed
        return info

    def __repr__(self):
        return "pillow filter"

    def get_src_width(self) -> int:
        return self.width

    def get_src_height(self) -> int:
        return self.height

    def get_src_format(self) -> str:
        return "BGRX"

    def get_dst_width(self) -> int:
        return self.width

    def get_dst_height(self) -> int:
        return self.height

    def get_dst_format(self) -> str:
        return "BGRX"

    def get_type(self) -> str:
        return "pillow"

    def convert_image(self, image: ImageWrapper) -> ImageWrapper:
        width = image.get_width()
        height = image.get_height()
        assert width <= self.width, "expected image width smaller than %i got %i" % (self.width, width)
        assert height <= self.height, "expected image height smaller than %i got %i" % (self.height, height)
        bgrx = image.get_pixels()
        img = Image.frombuffer("RGBA", (width, height), bgrx, "raw", "BGRA", image.get_rowstride())
        modified = img.filter(self.filter)
        bgrx = modified.tobytes("raw", "BGRA", 0, 1)
        image.set_pixels(bgrx)
        return image


def selftest(full=False):
    from xpra.codecs.checks import testcsc
    from xpra.codecs.pillow import filter
    filter.Converter = filter.Filter
    testcsc(filter, full)


if __name__ == "__main__":
    selftest(True)
