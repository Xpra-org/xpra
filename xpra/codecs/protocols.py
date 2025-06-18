# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Protocol, Any

from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict


class VideoCodec(Protocol):
    def init_context(self, encoding: str, width: int, height: int, src_format: str, options: typedict) -> None:
        raise NotImplementedError()

    def get_type(self) -> str:
        raise NotImplementedError()

    def get_info(self) -> dict[str, Any]:
        raise NotImplementedError()

    def get_encoding(self) -> str:
        raise NotImplementedError()

    def get_width(self) -> int:
        raise NotImplementedError()

    def get_height(self) -> int:
        raise NotImplementedError()

    def get_src_format(self) -> str:
        raise NotImplementedError()

    def clean(self) -> None:
        raise NotImplementedError()


class VideoEncoder(VideoCodec):
    def is_closed(self) -> bool:
        raise NotImplementedError()

    def compress_image(self, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        raise NotImplementedError()


class VideoDecoder(VideoCodec):

    def get_colorspace(self) -> str:
        raise NotImplementedError()

    def is_closed(self) -> bool:
        raise NotImplementedError()

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        raise NotImplementedError()


class ColorspaceConverter(Protocol):

    def init_context(self, src_width: int, src_height: int, src_format: str,
                     dst_width: int, dst_height: int, dst_format: str, options: typedict) -> None:
        raise NotImplementedError()

    def get_type(self) -> str:
        raise NotImplementedError()

    def get_info(self) -> dict[str, Any]:
        raise NotImplementedError()

    def get_src_width(self) -> int:
        raise NotImplementedError()

    def get_src_height(self) -> int:
        raise NotImplementedError()

    def get_src_format(self) -> str:
        raise NotImplementedError()

    def get_dst_width(self) -> int:
        raise NotImplementedError()

    def get_dst_height(self) -> int:
        raise NotImplementedError()

    def get_dst_format(self) -> str:
        raise NotImplementedError()

    def convert_image(self, image: ImageWrapper) -> ImageWrapper:
        raise NotImplementedError()
