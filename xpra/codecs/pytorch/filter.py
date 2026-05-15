# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib
import os
from typing import Any, Sequence

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import CSCSpec
from xpra.util.str_fn import parse_function_call
from xpra.log import Logger

log = Logger("filter", "torch")


def get_type() -> str:
    return "torch"


def get_version() -> tuple[int, int]:
    return 6, 5


torch_info: dict[str, Any] = {
    "type": get_type(),
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
                "uuid": str(props.uuid),
                "pci-bus-id": props.pci_bus_id,
                "pci-device-id": props.pci_device_id,
                "pci-domain-id": props.pci_domain_id,
                "multi-processors:": props.multi_processor_count,
            }
            log.info("  + %s %.1fGB memory", props.name, props.total_memory // 1024 // 1024 // 1024)
        if devices:
            cuda_info["devices"] = devices


def _load_py_transform(transform_str: str) -> tuple[Any, dict]:
    """Load an external callable via 'py:<module>:<Class>(kwargs...)'."""
    rest = transform_str[len("py:"):]
    if ":" not in rest:
        raise ValueError(
            f"Invalid py: transform {transform_str!r}. "
            "Expected format: py:<module>:<callable>(kwargs...)"
        )
    module_path, callable_part = rest.split(":", 1)
    callable_name, kwargs = parse_function_call(callable_part)
    log.info("py: loader: importing %r.%r kwargs=%s", module_path, callable_name, kwargs)
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import {module_path!r} for py: transform. "
            f"Install the package or set PYTHONPATH. Error: {exc}"
        ) from exc
    factory = getattr(mod, callable_name)
    return factory(**kwargs), {}


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
        transform_str = (
            options.strget("transform")
            or os.environ.get("XPRA_IMAGEFILTER_TRANSFORM", "functional.invert")
        )
        if transform_str.startswith("py:"):
            self.transform, self.kwargs = _load_py_transform(transform_str)
            log("init_context: loaded py: transform %r", self.transform)
            return
        import torchvision.transforms.v2 as transforms
        if transform_str.startswith("functional."):
            functional = transforms.functional
            transform_str = transform_str.removeprefix("functional.")
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

    def convert_image(self, image: ImageWrapper, last_scroll_event: float = 0) -> ImageWrapper:
        width = image.get_width()
        height = image.get_height()
        assert width <= self.width, "expected image width smaller than %i got %i" % (self.width, width)
        assert height <= self.height, "expected image height smaller than %i got %i" % (self.height, height)
        import numpy as np
        rowstride = image.get_rowstride()
        bgrx = image.get_pixels()
        log("convert_image(%s) stride=%i, pixels=%i", image, rowstride, len(bgrx))
        bgrx_array = np.frombuffer(bgrx, dtype=np.uint8)
        bgrx_array = bgrx_array.reshape(height, rowstride)
        bgrx_array = bgrx_array[:, :width * 4].reshape(height, width, 4)

        if getattr(self.transform, "supports_numpy", False):
            bgr_np = bgrx_array[:, :, :3].copy()
            bgr_result = self.transform.process_numpy(
                bgr_np,
                target_x=getattr(image, "get_target_x", lambda: 0)(),
                target_y=getattr(image, "get_target_y", lambda: 0)(),
                window_width=self.width,
                window_height=self.height,
                scroll_event_time=last_scroll_event,
                last_scroll_event=last_scroll_event,
            )
            result = np.concatenate([bgr_result, bgrx_array[:, :, 3:4]], axis=2)
            bgrx_out = np.ascontiguousarray(result).tobytes()
            filtered = ImageWrapper(
                image.get_x(), image.get_y(), width, height,
                bgrx_out, image.get_pixel_format(), image.get_depth(),
                width * 4, 4, planes=ImageWrapper.PACKED, thread_safe=True,
            )
            filtered.set_target_x(image.get_target_x())
            filtered.set_target_y(image.get_target_y())
            return filtered

        import torch
        pixels_gpu = torch.tensor(bgrx_array, device=self.device, dtype=torch.uint8)
        bgr = pixels_gpu[:, :, :3]
        x_channel = pixels_gpu[:, :, 3:4]
        bgr_chw = bgr.permute(2, 0, 1)
        bgr_transformed = self.transform(bgr_chw, **self.kwargs)
        bgr_hwc = bgr_transformed.permute(1, 2, 0)
        result_gpu = torch.cat([bgr_hwc, x_channel], dim=2)
        result_cpu = result_gpu.cpu().numpy()
        bgrx_out = np.ascontiguousarray(result_cpu).tobytes()
        filtered = ImageWrapper(
            image.get_x(), image.get_y(), width, height,
            bgrx_out, image.get_pixel_format(), image.get_depth(),
            width * 4, 4, planes=ImageWrapper.PACKED, thread_safe=True,
        )
        filtered.set_target_x(image.get_target_x())
        filtered.set_target_y(image.get_target_y())
        return filtered


def selftest(full=False):
    from xpra.codecs.checks import testcsc
    from xpra.codecs.pytorch import filter
    filter.Converter = filter.Filter
    testcsc(filter, full)


if __name__ == "__main__":
    selftest(True)
