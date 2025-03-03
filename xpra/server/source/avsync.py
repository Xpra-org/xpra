# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("av-sync")

AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA", 0)
DEFAULT_AV_SYNC_DELAY = envint("XPRA_DEFAULT_AV_SYNC_DELAY", 150)


class AVSyncMixin(StubSourceMixin):
    PREFIX = "av-sync"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        audio = caps.get("audio")
        if not isinstance(audio, dict):
            return False
        audio = typedict(audio)
        if not (audio.boolget("send") or audio.boolget("receive")):
            return False
        return caps.boolget("av-sync") and caps.boolget("windows")

    def __init__(self):
        self.av_sync = False

    def init_from(self, _protocol, server) -> None:
        self.av_sync = server.av_sync

    def cleanup(self) -> None:
        self.init_state()

    def init_state(self) -> None:
        self.av_sync_enabled = False
        self.av_sync_delay = 0
        self.av_sync_delay_total = 0
        self.av_sync_delta = AV_SYNC_DELTA

    def get_info(self) -> dict[str, Any]:
        return {
            AVSyncMixin.PREFIX: {
                "": self.av_sync,
                "enabled": self.av_sync_enabled,
                "client": self.av_sync_delay,
                "total": self.av_sync_delay_total,
                "delta": self.av_sync_delta,
            },
        }

    def parse_client_caps(self, c: typedict) -> None:
        av_sync = c.get(AVSyncMixin.PREFIX)
        if isinstance(av_sync, dict):
            av_sync = typedict(av_sync)
            enabled = av_sync.boolget("enabled")
            default_delay = av_sync.intget("delay.default", DEFAULT_AV_SYNC_DELAY)
            delay = av_sync.intget("delay", default_delay)
        else:
            enabled = bool(av_sync)
            delay = c.intget("av-sync.delay.default", DEFAULT_AV_SYNC_DELAY)
        self.av_sync_enabled = self.av_sync and enabled
        self.set_av_sync_delay(int(self.av_sync_enabled) * delay)
        log("av-sync: server=%s, client=%s, enabled=%s, total=%s",
            self.av_sync, enabled, self.av_sync_enabled, self.av_sync_delay_total)

    def set_av_sync_delta(self, delta: int) -> None:
        log("set_av_sync_delta(%i)", delta)
        self.av_sync_delta = delta
        self.update_av_sync_delay_total()

    def set_av_sync_delay(self, v: int) -> None:
        # update all window sources with the given delay
        self.av_sync_delay = v
        self.update_av_sync_delay_total()

    def update_av_sync_delay_total(self) -> None:
        enabled = self.av_sync and bool(getattr(self, "audio_source", None))
        if enabled:
            encoder_latency = self.get_audio_source_latency()
            self.av_sync_delay_total = min(1000, max(0, int(self.av_sync_delay) + self.av_sync_delta + encoder_latency))
            log("av-sync set to %ims (from client queue latency=%s, encoder latency=%s, delta=%s)",
                self.av_sync_delay_total, self.av_sync_delay, encoder_latency, self.av_sync_delta)
        else:
            log("av-sync support is disabled, setting it to 0")
            self.av_sync_delay_total = 0
        for ws in self.window_sources.values():
            ws.set_av_sync(enabled)
            ws.set_av_sync_delay(self.av_sync_delay_total)
            ws.may_update_av_sync_delay()

    ##########################################################################
    # audio control commands:
    def audio_control_sync(self, delay_str) -> str:
        assert self.av_sync, "av-sync is not enabled"
        self.set_av_sync_delay(int(delay_str))
        return "av-sync delay set to %ims" % self.av_sync_delay

    def audio_control_av_sync_delta(self, delta_str) -> str:
        assert self.av_sync, "av-sync is not enabled"
        self.set_av_sync_delta(int(delta_str))
        return "av-sync delta set to %ims" % self.av_sync_delta
