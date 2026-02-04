# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import torch
import torchvision.transforms.v2 as transforms
import numpy as np
from typing import Any, Sequence

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import CSCSpec
from xpra.log import Logger

log = Logger("csc", "torch")


def get_type() -> str:
    return "torch"


def get_version() -> tuple[int, int]:
    return 6, 5


def get_info() -> dict[str, Any]:
    return {
        "version": get_version(),
    }


def get_specs() -> Sequence[CSCSpec]:
    return (
        CSCSpec(
            input_colorspace="BGRX", output_colorspaces=("BGRX", ),
            codec_class=Filter, codec_type=get_type(),
            setup_cost=0, min_w=2, min_h=2,
            max_w=16*1024, max_h=16*1024,
        ),
    )


MAX_WIDTH = 16384
MAX_HEIGHT = 16384


class Filter:
    __slots__ = ("closed", "width", "height", "transform")

    def __init__(self):
        self.closed = False
        self.width = 0
        self.height = 0
        self.transform = None

    def init_context(self, src_width: int, src_height: int, src_format: str,
                     dst_width: int, dst_height: int, dst_format: str, options: typedict) -> None:
        assert src_width == dst_width and src_height == dst_height, "this module does not handle any scaling"
        assert 0 < src_width <= MAX_WIDTH, f"invalid width {src_width}"
        assert 0 < src_height <= MAX_HEIGHT, f"invalid height {src_height}"
        assert src_format == "BGRX" and dst_format == "BGRX", "this module only handles BGRX"
        self.width = src_width
        self.height = src_height
        self.transform = transforms.RandomInvert(p=0.5)

    def clean(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def get_info(self) -> dict[str,Any]:
        info = get_info()
        info["closed"] = self.closed
        return info

    def __repr__(self):
        return "pytorch filter"

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
        return "torch"

    def convert_image(self, image: ImageWrapper) -> ImageWrapper:
        assert self.width == image.get_width()
        assert self.height == image.get_height()
        bgrx = image.get_pixels()
        bgrx_array = np.frombuffer(bgrx, dtype=np.uint8)
        bgrx_array = bgrx_array.reshape(self.height, self.width, 4)
        # Upload to GPU - convert to tensor (H, W, 4)
        pixels_gpu = torch.from_numpy(bgrx_array).to(self.device)
        # Separate BGR and X channels
        bgr = pixels_gpu[:, :, :3]          # (H, W, 3)
        x_channel = pixels_gpu[:, :, 3:4]   # (H, W, 1)
        # Convert to CHW format for torchvision (C, H, W)
        bgr_chw = bgr.permute(2, 0, 1)  # (3, H, W)
        # Apply transform - RandomInvert works with uint8
        bgr_transformed = self.transform(bgr_chw)
        # Convert back to HWC format
        bgr_hwc = bgr_transformed.permute(1, 2, 0)  # (H, W, 3)
        # Recombine with X channel
        result_gpu = torch.cat([bgr_hwc, x_channel], dim=2)  # (H, W, 4)
        # Download to CPU
        result_cpu = result_gpu.cpu().numpy()
        bgrx = result_cpu.tobytes()
        image.set_pixels(bgrx)
        return image


def selftest(full=False):
    from xpra.codecs.checks import testcsc
    from xpra.codecs.csc_cython import converter
    testcsc(converter, full)


if __name__ == "__main__":
    selftest(True)
