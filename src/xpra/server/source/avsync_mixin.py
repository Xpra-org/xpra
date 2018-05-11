# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("av-sync")

from xpra.util import envint
from xpra.server.source.stub_source_mixin import StubSourceMixin

AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA", 0)


class AVSyncMixin(StubSourceMixin):

    def __init__(self):
        self.av_sync = False

    def init_from(self, _protocol, server):
        self.av_sync = server.av_sync

    def cleanup(self):
        self.init_state()

    def init_state(self):
        self.av_sync_enabled = False
        self.av_sync_delay = 0
        self.av_sync_delay_total = 0
        self.av_sync_delta = AV_SYNC_DELTA


    def get_info(self):
        return {
            "av-sync" : {
                ""          : self.av_sync,
                "enabled"   : self.av_sync_enabled,
                "client"    : self.av_sync_delay,
                "total"     : self.av_sync_delay_total,
                "delta"     : self.av_sync_delta,
                },
            }

    def parse_client_caps(self, c):
        av_sync = c.boolget("av-sync")
        self.av_sync_enabled = self.av_sync and av_sync
        self.set_av_sync_delay(int(self.av_sync_enabled) * c.intget("av-sync.delay.default", 150))
        log("av-sync: server=%s, client=%s, total=%s", self.av_sync, av_sync, self.av_sync_delay_total)


    def set_av_sync_delta(self, delta):
        log("set_av_sync_delta(%i)", delta)
        self.av_sync_delta = delta
        self.update_av_sync_delay_total()

    def set_av_sync_delay(self, v):
        #update all window sources with the given delay
        self.av_sync_delay = v
        self.update_av_sync_delay_total()

    def update_av_sync_delay_total(self):
        if self.av_sync:
            encoder_latency = self.get_sound_source_latency()
            self.av_sync_delay_total = min(1000, max(0, int(self.av_sync_delay) + self.av_sync_delta + encoder_latency))
            log("av-sync set to %ims (from client queue latency=%s, encoder latency=%s, delta=%s)", self.av_sync_delay_total, self.av_sync_delay, encoder_latency, self.av_sync_delta)
        else:
            log("av-sync support is disabled, setting it to 0")
            self.av_sync_delay_total = 0
        for ws in self.window_sources.values():
            ws.set_av_sync_delay(self.av_sync_delay_total)
