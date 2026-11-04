#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from threading import Lock
from collections import deque
from typing import Any
from collections.abc import Iterable, Sequence
from xpra.util.env import envint
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.str_fn import csv
from xpra.log import Logger

log = Logger("audio")

VORBIS = "vorbis"
AAC = "aac"
FLAC = "flac"
MP3 = "mp3"
WAV = "wav"
OPUS = "opus"
WAVPACK = "wavpack"

OGG = "ogg"
MKA = "mka"
MPEG4 = "mpeg4"
ID3V2 = "id3v2"
RTP = "rtp"
RAW = "raw"

# stream compression
LZ4 = "lz4"
# LZO = "lzo"

FLAC_OGG = FLAC + "+" + OGG
OPUS_OGG = OPUS + "+" + OGG
VORBIS_OGG = VORBIS + "+" + OGG
OPUS_MKA = OPUS + "+" + MKA
OPUS_RTP = OPUS + "+" + RTP
VORBIS_MKA = VORBIS + "+" + MKA
AAC_MPEG4 = AAC + "+" + MPEG4
WAV_LZ4 = WAV + "+" + LZ4
# WAV_LZO     = WAV+"+"+LZO
MP3_MPEG4 = MP3 + "+" + MPEG4
MP3_ID3V2 = MP3 + "+" + ID3V2


# codecs whose pipelines keep playing through packet loss (see `xpra.audio.sink`):
LOSS_TOLERANT_CODECS: Sequence[str] = (OPUS_RTP, )


def get_matching_codecs(local_codecs: Sequence[str], remote_codecs: Sequence[str], lossy=False) -> Sequence[str]:
    """
    The codecs found in both lists, in the order of `local_codecs`.
    When the connection can lose packets, the loss-tolerant codecs are moved to the front.
    """
    matching_codecs = tuple(x for x in local_codecs if x in remote_codecs)
    if lossy:
        # stable sort, so the preference order is preserved otherwise:
        matching_codecs = tuple(sorted(matching_codecs, key=lambda codec: codec not in LOSS_TOLERANT_CODECS))
    log("get_matching_codecs(%s, %s, %s)=%s", local_codecs, remote_codecs, lossy, matching_codecs)
    return matching_codecs


AUDIO_DATA_PACKET = "audio-data"
AUDIO_CONTROL_PACKET = "audio-control"
# marks the start and end of an audio stream, in either direction:
AUDIO_STREAM_PACKET = "audio-stream"
AUDIO_STREAM_START = "start"
AUDIO_STREAM_END = "end"
AUDIO_KEEPALIVE_PACKET = "audio-keepalive"
AUDIO_LEVEL_PACKET = "audio-level"
AUDIO_SIGNAL_PACKET = "audio-signal"
AUDIO_KEEPALIVE_INTERVAL = envint("XPRA_AUDIO_KEEPALIVE_INTERVAL", 5)
AUDIO_KEEPALIVE_TIMEOUT = envint("XPRA_AUDIO_KEEPALIVE_TIMEOUT", 10)
SILENCE_FLOOR_DB = -120
# how long to hold on to `audio-data` packets that arrive before the stream has started:
PENDING_AUDIO_DELAY = envint("XPRA_AUDIO_PENDING_DELAY", 200)
PENDING_AUDIO_MAX = envint("XPRA_AUDIO_PENDING_MAX", 50)


def audio_stream_packet(remote_stream_packet: bool, event: str, codec: str, sequence: int) -> tuple[Any, ...]:
    """
    The packet to send to mark the start or end of an audio stream.
    Peers that do not advertise `stream-packet` in their audio capabilities
    expect an `audio-data` packet without any data, using metadata flags instead.
    """
    if remote_stream_packet or not BACKWARDS_COMPATIBLE:
        return AUDIO_STREAM_PACKET, event, codec, sequence
    metadata: dict[str, Any] = {f"{event}-of-stream": True, "sequence": sequence}
    if event == AUDIO_STREAM_START:
        metadata["codec"] = codec
    return AUDIO_DATA_PACKET, codec, (), metadata


class PendingAudio:
    """
    `audio-data` packets sent as datagrams may overtake the `audio-stream` start packet,
    which is sent on the regular stream:
    hold on to them for a short while, and replay them once the stream has started.
    Packets can be added from one thread (ie: the asyncio loop receiving datagrams)
    while the stream is started from another (ie: the network parse thread).
    """

    def __init__(self, delay: int = PENDING_AUDIO_DELAY, max_items: int = PENDING_AUDIO_MAX):
        self.delay = delay / 1000
        self.max_items = max_items
        self.lock = Lock()
        self.items: deque[tuple[float, Any]] = deque()
        self.active = False
        self.dropped = 0

    def _expire(self, now: float) -> None:
        while self.items and now - self.items[0][0] > self.delay:
            self.items.popleft()
            self.dropped += 1

    def add(self, item: Any) -> bool:
        """ returns False if the stream has already started, the item must be processed instead """
        now = monotonic()
        with self.lock:
            if self.active:
                return False
            self._expire(now)
            if len(self.items) >= self.max_items:
                self.items.popleft()
                self.dropped += 1
            self.items.append((now, item))
        return True

    def start(self) -> list[Any]:
        """ the stream has started: returns the items still pending, in the order they were received """
        with self.lock:
            self.active = True
            self._expire(monotonic())
            items = [item for _, item in self.items]
            self.items.clear()
        return items

    def stop(self) -> None:
        with self.lock:
            self.active = False
            self.dropped += len(self.items)
            self.items.clear()

    def get_info(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "pending": len(self.items),
            "dropped": self.dropped,
        }


# PulseAudio receives the server's terminal signal directly (ie: Ctrl-C) and may exit
# before our audio subprocesses process their cleanup request:
PULSEAUDIO_DISCONNECTED = "Disconnected: Connection terminated"


# used for parsing codec names specified on the command line:
def audio_option_or_all(name: str, options: Sequence[str], all_values: Iterable[str]) -> Sequence[str]:
    log("audio_option_or_all%s", (name, options, all_values))
    if not options:
        v = list(all_values)  # not specified on command line: use default
    else:
        v = []
        invalid_options = []
        for x in options:
            # options is a list, but it may have csv embedded:
            for o in x.split(","):
                o = o.strip()
                if o not in all_values:
                    invalid_options.append(o)
                else:
                    v.append(o)
        if invalid_options:
            if all_values:
                log.warn(f"Warning: invalid values for {name!r}: " + csv(invalid_options))
                log.warn(" valid options: " + csv(all_values))
            else:
                log.warn(f"Warning: no {name!r} available")
    log("%s=%s", name, csv(v))
    return tuple(v)
