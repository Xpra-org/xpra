#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Any

from xpra.audio.common import AUDIO_KEEPALIVE_INTERVAL, AUDIO_KEEPALIVE_TIMEOUT
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("audio")

AUDIO_KEEPALIVE_DROP_CODECS = tuple(
    x.strip().lower() for x in os.environ.get("XPRA_AUDIO_KEEPALIVE_DROP_CODECS", "").split(",") if x.strip()
)


class AudioKeepaliveMixin:
    """
    Shared audio keepalive state.

    Subclasses provide the transport-specific timer and packet send hooks.
    """

    def init_audio_keepalive_state(self) -> None:
        self.audio_remote_keepalive: bool = False
        self.latest_audio_timestamp: int = 0
        self.latest_echoed_audio_timestamp: int = 0
        self.latest_sent_audio_timestamp: int = 0
        self.audio_echo_timeout_start: float = 0
        self.audio_keepalive_timer: int = 0
        self.audio_keepalive_check_timer: int = 0
        self.audio_keepalive_stale_warning: bool = False

    @staticmethod
    def audio_keepalive_supported() -> bool:
        return AUDIO_KEEPALIVE_INTERVAL > 0 and AUDIO_KEEPALIVE_TIMEOUT > 0

    def get_audio_keepalive_caps(self) -> dict[str, Any]:
        return {
            "keepalive": self.audio_keepalive_supported(),
            "keepalive.interval": AUDIO_KEEPALIVE_INTERVAL,
            "keepalive.timeout": AUDIO_KEEPALIVE_TIMEOUT,
        }

    def parse_audio_keepalive_caps(self, audio: typedict) -> bool:
        self.audio_remote_keepalive = audio.boolget("keepalive") and self.audio_keepalive_supported()
        return self.audio_remote_keepalive

    def audio_keepalive_enabled(self) -> bool:
        return self.audio_remote_keepalive and self.audio_keepalive_supported()

    def cancel_audio_keepalive_timers(self) -> None:
        if self.audio_keepalive_timer:
            self.audio_keepalive_timer_remove(self.audio_keepalive_timer)
            self.audio_keepalive_timer = 0
        if self.audio_keepalive_check_timer:
            self.audio_keepalive_timer_remove(self.audio_keepalive_check_timer)
            self.audio_keepalive_check_timer = 0

    def update_latest_received_audio_timestamp(self, metadata: typedict | dict) -> None:
        timestamp = int(metadata.get("time", metadata.get(b"time", 0)) or 0)
        if timestamp > self.latest_audio_timestamp:
            self.latest_audio_timestamp = timestamp
            self.schedule_audio_keepalive()

    def update_latest_sent_audio_timestamp(self, metadata: dict) -> None:
        timestamp = max(int(metadata.get("time", 0) or 0), int(metadata.get(b"time", 0) or 0))
        if timestamp > self.latest_sent_audio_timestamp:
            self.latest_sent_audio_timestamp = timestamp
            if not self.audio_echo_timeout_start:
                self.audio_echo_timeout_start = monotonic() * 1000

    def schedule_audio_keepalive(self) -> None:
        if not self.audio_keepalive_enabled() or self.audio_keepalive_timer or not self.latest_audio_timestamp:
            return
        self.audio_keepalive_timer = self.audio_keepalive_timer_add(
            AUDIO_KEEPALIVE_INTERVAL * 1000, self.send_audio_keepalive,
        )

    def send_audio_keepalive(self) -> bool:
        self.audio_keepalive_timer = 0
        if not self.audio_keepalive_enabled() or not self.latest_audio_timestamp:
            return False
        self.send_audio_keepalive_packet(self.latest_audio_timestamp)
        if self.audio_keepalive_active():
            self.schedule_audio_keepalive()
        return False

    def schedule_audio_keepalive_check(self) -> None:
        if not self.audio_keepalive_enabled() or self.audio_keepalive_check_timer:
            return
        self.audio_keepalive_check_timer = self.audio_keepalive_timer_add(1000, self.check_audio_keepalive)

    def check_audio_keepalive(self) -> bool:
        self.audio_keepalive_check_timer = 0
        self.handle_audio_keepalive_stale(self.get_audio_keepalive_codec())
        if getattr(self, "audio_source", None):
            self.schedule_audio_keepalive_check()
        return False

    def audio_keepalive_stale(self) -> bool:
        if not self.audio_keepalive_enabled() or not self.latest_sent_audio_timestamp:
            return False
        if self.latest_echoed_audio_timestamp >= self.latest_sent_audio_timestamp:
            return False
        echoed = self.latest_echoed_audio_timestamp or self.audio_echo_timeout_start
        if not echoed:
            return False
        return monotonic() * 1000 - echoed > AUDIO_KEEPALIVE_TIMEOUT * 1000

    def can_drop_audio_data(self, codec: str) -> bool:
        if not AUDIO_KEEPALIVE_DROP_CODECS:
            return False
        codec = (codec or "").lower()
        if codec in AUDIO_KEEPALIVE_DROP_CODECS:
            return True
        parts = codec.split("+", 1)
        return any(part in AUDIO_KEEPALIVE_DROP_CODECS for part in parts)

    def audio_keepalive_may_send(self, codec: str, metadata: dict) -> bool:
        self.update_latest_sent_audio_timestamp(metadata)
        if not self.handle_audio_keepalive_stale(codec):
            return True
        return False

    def handle_audio_keepalive_stale(self, codec: str) -> bool:
        if not self.audio_keepalive_stale():
            return False
        if self.can_drop_audio_data(codec):
            if not self.audio_keepalive_stale_warning:
                self.audio_keepalive_stale_warning = True
                log.warn("Warning: audio keepalive echo is stale")
                log.warn(" dropping %s audio packets until the connection recovers", codec or "unknown")
            return True
        if not self.audio_keepalive_stale_warning:
            self.audio_keepalive_stale_warning = True
            log.warn("Warning: audio keepalive echo is stale")
            log.warn(" stopping %s audio forwarding", codec or "unknown")
        self.stop_sending_audio()
        return True

    def audio_keepalive(self, timestamp: int) -> None:
        if timestamp > self.latest_echoed_audio_timestamp:
            self.latest_echoed_audio_timestamp = timestamp
            self.audio_echo_timeout_start = 0
            self.audio_keepalive_stale_warning = False

    def audio_keepalive_active(self) -> bool:
        return bool(getattr(self, "audio_source", None) or getattr(self, "audio_sink", None))

    def get_audio_keepalive_codec(self) -> str:
        audio_source = getattr(self, "audio_source", None)
        return getattr(audio_source, "codec", "")

    def send_audio_keepalive_packet(self, timestamp: int) -> None:
        raise NotImplementedError()

    def audio_keepalive_timer_add(self, delay: int, fn) -> int:
        raise NotImplementedError()

    def audio_keepalive_timer_remove(self, timer: int) -> None:
        raise NotImplementedError()
