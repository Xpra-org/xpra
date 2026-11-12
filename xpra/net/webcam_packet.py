# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Parsing and validation of the webcam packets:
the peer is not trusted, the frame size, the pixel data and the options are bounded
before they reach the decoders, the csc step or the virtual webcam device.
"""

from typing import NamedTuple
from collections.abc import Sequence

from xpra.common import SizedBuffer
from xpra.net.common import Packet
from xpra.net.packet_values import check_key, check_value, get_mmap_chunks
from xpra.codecs.constants import RGB_FORMAT_BPP, check_image_size, check_rgb_buffer
from xpra.util.env import envint

MAX_WEBCAM_PIXELS: int = envint("XPRA_MAX_WEBCAM_PIXELS", 8192 * 8192)
MAX_WEBCAM_OPTIONS: int = 16
MAX_WEBCAM_MMAP_CHUNKS: int = 256
MAX_WEBCAM_MESSAGE: int = 256
# compressed frames are never this much bigger than the pixels they encode:
MAX_BYTES_PER_PIXEL: int = 8
DATA_SLACK: int = 65536

# the formats the server can accept, `mmap` frames are sent as raw rgb pixels:
WEBCAM_FRAME_ENCODINGS: Sequence[str] = ("mmap", "png", "jpeg", "webp")


class WebcamFrame(NamedTuple):
    """ the fields of a `webcam-frame` packet """
    device_id: int
    frame_no: int
    encoding: str
    width: int
    height: int
    data: SizedBuffer
    options: dict


def check_webcam_size(width: int, height: int) -> None:
    check_image_size(width, height, "webcam frame")
    if width * height > MAX_WEBCAM_PIXELS:
        raise ValueError(f"webcam frame size {width}x{height} exceeds the {MAX_WEBCAM_PIXELS} pixels limit")


def parse_webcam_start_packet(packet: Packet) -> tuple[int, int, int]:
    """ returns the device id and the requested frame size """
    packet.check_len(4, 4)
    device_id = packet.get_i64(1)
    width = packet.get_u16(2)
    height = packet.get_u16(3)
    check_webcam_size(width, height)
    return device_id, width, height


def parse_webcam_stop_packet(packet: Packet) -> tuple[int, str]:
    """ returns the device id and the optional message """
    packet.check_len(2, 3)
    message = packet.get_str(2, MAX_WEBCAM_MESSAGE) if len(packet) > 2 else ""
    return packet.get_i64(1), message


def parse_webcam_ack_packet(packet: Packet) -> tuple[int, int]:
    """ returns the device id and frame number, the server may also specify the frame size """
    packet.check_len(3, 5)
    device_id = packet.get_i64(1)
    frame_no = packet.get_u64(2)
    if len(packet) > 3:
        packet.check_len(5, 5)
        check_webcam_size(packet.get_u16(3), packet.get_u16(4))
    return device_id, frame_no


def validate_webcam_options(options: dict) -> dict:
    validated = {}
    for key, value in options.items():
        check_key(key, "webcam option")
        if key == "chunks":
            value = get_mmap_chunks(value, MAX_WEBCAM_MMAP_CHUNKS, "webcam option")
        elif key == "pixel-format":
            if value not in RGB_FORMAT_BPP:
                raise ValueError(f"invalid webcam pixel format {value!r}")
        else:
            check_value(key, value, "webcam option")
        validated[key] = value
    return validated


def parse_webcam_frame_packet(packet: Packet) -> WebcamFrame:
    """
    parse the fields of a `webcam-frame` packet,
    raises `ValueError` or `TypeError` if the packet is malformed
    """
    packet.check_len(7, 8)
    device_id = packet.get_i64(1)
    frame_no = packet.get_u64(2)
    encoding = packet.get_str(3, 16)
    width = packet.get_u16(4)
    height = packet.get_u16(5)
    check_webcam_size(width, height)
    data = packet.get_buffer(6, width * height * MAX_BYTES_PER_PIXEL + DATA_SLACK)
    options = validate_webcam_options(packet.get_dict(7, MAX_WEBCAM_OPTIONS)) if len(packet) > 7 else {}
    return WebcamFrame(device_id, frame_no, encoding, width, height, data, options)


def check_webcam_frame(frame: WebcamFrame, encodings: Sequence[str] = WEBCAM_FRAME_ENCODINGS) -> str:
    """
    verify that the pixel data is consistent with the frame's size and encoding,
    returns an error message if it is not
    """
    encoding = frame.encoding
    if encoding not in encodings:
        return f"unsupported webcam frame encoding {encoding!r}"
    data_size = len(frame.data)
    if encoding == "mmap":
        if data_size:
            return f"mmap webcam frame with {data_size} bytes of pixel data"
        chunks = frame.options.get("chunks")
        if not chunks:
            return "mmap webcam frame without any chunks"
        pixel_format = frame.options.get("pixel-format", "BGRX")
        mmap_size = sum(length for _offset, length in chunks)
        try:
            check_rgb_buffer(pixel_format, mmap_size, frame.width, frame.height,
                             frame.width * RGB_FORMAT_BPP[pixel_format], "mmap webcam frame")
        except ValueError as e:
            return str(e)
        return ""
    from xpra.codecs.image_type import get_image_type
    image_type = get_image_type(frame.data)
    if image_type != encoding:
        return f"invalid {encoding} webcam frame data, found {image_type or 'unknown'!r}"
    return ""
