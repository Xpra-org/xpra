# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Parsing and validation of the audio packets, which both the client and the server receive:
the peer is not trusted, everything is bounded before it reaches the audio pipelines,
or the audio subprocesses we forward the data and metadata to.
"""

from typing import NamedTuple, Any
from collections.abc import Sequence

from xpra.common import SizedBuffer
from xpra.net.common import Packet
from xpra.net.packet_values import check_key, check_value, get_int
from xpra.util.env import envint

MAX_AUDIO_CODEC: int = 64
MAX_AUDIO_DATA: int = envint("XPRA_MAX_AUDIO_DATA", 4 * 1024 * 1024)
MAX_AUDIO_METADATA: int = 32
# the audio source bundles at most 10 buffers of "packet metadata" (ie: stream headers):
MAX_PACKET_METADATA: int = 16
MAX_AUDIO_CAPS: int = 256
MAX_AUDIO_CONTROL_ARGS: int = 4
MAX_AUDIO_CONTROL_ARG: int = 64
MAX_AUDIO_STREAM_EVENT: int = 16

# the metadata the audio sources set, see `xpra.audio.src`:
NUMERIC_METADATA: Sequence[str] = ("timestamp", "duration", "time", "ts", "latency", "sequence")
# the only stream compression the sinks support, see `xpra.audio.sink.uncompress_data`:
STREAM_COMPRESSORS: Sequence[str] = ("", "lz4")


class AudioData(NamedTuple):
    """ the fields of an `audio-data` packet """
    codec: str
    data: SizedBuffer
    metadata: dict
    packet_metadata: Sequence[bytes]


def validate_audio_metadata(metadata: dict) -> dict:
    """ raises `ValueError` or `TypeError` if the metadata is not acceptable """
    for key, value in metadata.items():
        check_key(key, "audio metadata")
        if key in NUMERIC_METADATA:
            if isinstance(value, float):
                continue
            get_int(value, key, what="audio metadata")
        elif key == "compress":
            if value not in STREAM_COMPRESSORS:
                raise ValueError(f"unsupported audio stream compression {value!r}")
        else:
            check_value(key, value, "audio metadata", max_depth=1)
    return metadata


def parse_audio_data_packet(packet: Packet) -> AudioData:
    """
    parse the fields of an `audio-data` packet,
    raises `ValueError` or `TypeError` if the packet is malformed
    """
    packet.check_len(4, 5)
    codec = packet.get_str(1, MAX_AUDIO_CODEC)
    # the legacy start-of-stream marker uses an empty tuple instead of a buffer:
    data = packet.get_buffer(2, MAX_AUDIO_DATA)
    metadata = validate_audio_metadata(packet.get_dict(3, MAX_AUDIO_METADATA))
    packet_metadata: Sequence[bytes] = ()
    if len(packet) > 4:
        packet_metadata = packet.get_bytes_seq(4, MAX_PACKET_METADATA, MAX_AUDIO_DATA)
    return AudioData(codec, data, metadata, packet_metadata)


def parse_audio_stream_packet(packet: Packet) -> tuple[str, str, int]:
    """ returns the event, codec and sequence of an `audio-stream` packet """
    packet.check_len(4, 4)
    return packet.get_str(1, MAX_AUDIO_STREAM_EVENT), packet.get_str(2, MAX_AUDIO_CODEC), packet.get_i64(3)


def parse_audio_control_packet(packet: Packet) -> tuple[str, list[Any]]:
    """
    returns the action and the arguments of an `audio-control` packet,
    the arguments are strings or integers
    """
    packet.check_len(2, 2 + MAX_AUDIO_CONTROL_ARGS)
    action = packet.get_str(1, 32)
    args: list[Any] = []
    for i in range(2, len(packet)):
        value = packet[i]
        if isinstance(value, int) and not isinstance(value, bool):
            args.append(get_int(value, action, what="audio-control argument"))
        elif isinstance(value, (str, bytes)):
            args.append(packet.get_str(i, MAX_AUDIO_CONTROL_ARG))
        else:
            raise TypeError(f"invalid type for audio-control {action!r} argument: {type(value)}")
    return action, args


def parse_audio_capabilities_packet(packet: Packet) -> dict:
    packet.check_len(2, 2)
    return packet.get_dict(1, MAX_AUDIO_CAPS)


def parse_audio_keepalive_packet(packet: Packet) -> int:
    packet.check_len(2, 2)
    return packet.get_u64(1)
