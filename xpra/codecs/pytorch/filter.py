# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Sequence

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import CSCSpec
from xpra.util.str_fn import parse_function_call
from xpra.log import Logger

log = Logger("csc", "torch")


def get_type() -> str:
    return "torch"


def get_version() -> tuple[int, int]:
    return 6, 5


torch_info: dict[str, Any] = {
    "version": get_version(),
}


def get_info() -> dict[str, Any]:
    return torch_info


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
        #"RandomInvert(p=0.5)",
        #"Grayscale",
        "ColorJitter(brightness=.5, hue=.3)",
        "GaussianNoise(mean=0.0, sigma=0.1, clip=True)",
        #"GaussianBlur(kernel_size=(5, 9), sigma=(0.1, 5.))",
        "functional.vflip",
        "functional.hflip",
        #"functional.gaussian_blur",
        "functional.invert",
        "functional.posterize(bits=4)",
        "functional.solarize(threshold=0.5)",
        #adjust_sharpness
        "functional.autocontrast",
        "functional.equalize",
    )


MAX_WIDTH = 16384
MAX_HEIGHT = 16384


filter_inited = False


def torch_init() -> None:
    global filter_inited
    if filter_inited:
        return
    filter_inited = True
    log.info("pytorch initialization (this may take a few seconds)")
    import torch
    torch_info["pytorch"] = tuple(torch.__version__.split("."))
    log.info(f"pytorch {torch.__version__} initialized")
    if hasattr(torch, "cuda") and torch.cuda.is_available() and not torch.cuda.is_initialized():
        log("initializing cuda")
        torch.cuda.init()
        cuda_info = torch_info.setdefault("cuda", {})
        cuda_info["arch-list"] = torch.cuda.get_arch_list()
        n = torch.cuda.device_count()
        log.info(" with %i devices:", n)
        devices = {}
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            devices[i] = {
                "name": props.name,
                "compute": (props.major, props.minor),
                "memory": props.total_memory,
                "uuid": props.uuid,
                "pci-bus-id": props.pci_bus_id,
                "pci-device-id": props.pci_device_id,
                "pci-domain-id": props.pci_domain_id,
                "multi-processors:": props.multi_processor_count,
            }
            log.info("  + %s %.1fGB memory", props.name, props.total_memory // 1024 // 1024 // 1024)
        if devices:
            cuda_info["devices"] = devices


class Filter:
    __slots__ = ("closed", "width", "height", "device", "transform", "kwargs")

    def __init__(self):
        self.closed = False
        self.width = 0
        self.height = 0
        self.device = ""
        self.transform = None
        self.kwargs = {}

    def init_context(self, src_width: int, src_height: int, src_format: str,
                     dst_width: int, dst_height: int, dst_format: str, options: typedict) -> None:
        assert src_width == dst_width and src_height == dst_height, "this module does not handle any scaling"
        assert 0 < src_width <= MAX_WIDTH, f"invalid width {src_width}"
        assert 0 < src_height <= MAX_HEIGHT, f"invalid height {src_height}"
        assert src_format == "BGRX" and dst_format == "BGRX", "this module only handles BGRX"
        torch_init()
        self.width = src_width
        self.height = src_height
        self.device = "cuda"
        transform_str = options.strget("transform", "RandomInvert(p=0.5)")
        import torchvision.transforms.v2 as transforms
        if transform_str.startswith("functional."):
            functional = transforms.functional
            transform_str = transform_str[len("functional."):]
            function_name, kwargs = parse_function_call(transform_str)
            self.transform = getattr(functional, function_name)
            self.kwargs = kwargs
        else:
            function_name, kwargs = parse_function_call(transform_str)
            function = getattr(transforms, function_name)
            self.transform = function(**kwargs)
            self.kwargs = {}
        log("init_context options=%s, using %r=%s with kwargs=%s", options, transform_str, self.transform, self.kwargs)

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
        width = image.get_width()
        height = image.get_height()
        assert width <= self.width, "expected image width smaller than %i got %i" % (self.width, width)
        assert height <= self.height, "expected image height smaller than %i got %i" % (self.height, height)
        import torch
        import numpy as np
        bgrx = image.get_pixels()
        bgrx_array = np.frombuffer(bgrx, dtype=np.uint8)
        bgrx_array = bgrx_array.reshape(height, width, 4)
        pixels_gpu = torch.tensor(bgrx_array, device=self.device, dtype=torch.uint8)
        # Separate BGR and X channels
        bgr = pixels_gpu[:, :, :3]          # (H, W, 3)
        x_channel = pixels_gpu[:, :, 3:4]   # (H, W, 1)
        # Convert to CHW format for torchvision (C, H, W)
        bgr_chw = bgr.permute(2, 0, 1)  # (3, H, W)
        # Apply transform - RandomInvert works with uint8
        bgr_transformed = self.transform(bgr_chw, **self.kwargs)
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
    from xpra.codecs.pytorch import filter
    filter.Converter = filter.Filter
    testcsc(filter, full)


if __name__ == "__main__":
    selftest(True)
