#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.audio.keepalive import AudioKeepaliveMixin


class FakeKeepalive(AudioKeepaliveMixin):
    """ minimal implementation of the transport specific hooks """

    def __init__(self):
        self.init_audio_keepalive_state()
        # pretend that the peer has told us that it supports keepalive:
        self.audio_remote_keepalive = True
        self.stopped = 0
        self.sent: list[int] = []
        self.timers: dict[int, tuple] = {}
        self.timer_seq = 0

    def stop_sending_audio(self) -> None:
        self.stopped += 1

    def send_audio_keepalive_packet(self, timestamp: int) -> None:
        self.sent.append(timestamp)

    def audio_keepalive_timer_add(self, delay: int, fn) -> int:
        self.timer_seq += 1
        self.timers[self.timer_seq] = (delay, fn)
        return self.timer_seq

    def audio_keepalive_timer_remove(self, timer: int) -> None:
        self.timers.pop(timer, None)


class TestAudioKeepalive(unittest.TestCase):
    """
    The audio timestamps exchanged with the peer come from the capture pipeline,
    they are only comparable with `monotonic()` because they use the same clock:
    what matters is *when* the echo was received, not how old the audio is.
    """

    def setUp(self):
        # a `monotonic()` we can move forwards, in seconds:
        self.clock = [1000.0]
        patcher = patch("xpra.audio.keepalive.monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ka = FakeKeepalive()

    def tick(self, seconds: float) -> None:
        self.clock[0] += seconds

    def send(self) -> bool:
        """ send an audio buffer captured right now, return False if it was blocked """
        timestamp = int(self.clock[0] * 1000)
        return self.ka.audio_keepalive_may_send("opus", {"time": timestamp})

    def test_no_keepalive_without_peer_support(self):
        self.ka.audio_remote_keepalive = False
        assert self.send()
        self.tick(3600)
        assert not self.ka.audio_keepalive_stale()
        assert self.send()
        assert self.ka.stopped == 0

    def test_not_stale_when_echoed(self):
        assert self.send()
        self.ka.audio_keepalive(self.ka.latest_sent_audio_timestamp)
        self.tick(300)
        assert not self.ka.audio_keepalive_stale()
        assert self.ka.stopped == 0

    def test_stale_without_echo(self):
        assert self.send()
        self.tick(11)
        assert self.ka.audio_keepalive_stale()
        assert not self.send()
        assert self.ka.stopped == 1

    def test_silence_gap_does_not_stop_the_stream(self):
        # the `cutter` element removes silence from the stream,
        # so there can be long gaps between two audio buffers:
        assert self.send()
        self.ka.audio_keepalive(self.ka.latest_sent_audio_timestamp)
        self.tick(60)
        # the audio resumes: the timestamp of this buffer is 60 seconds newer
        # than the one the peer last echoed, but the connection is perfectly healthy
        assert self.send()
        assert self.ka.stopped == 0

    def test_partial_echo_restarts_the_timeout(self):
        assert self.send()
        self.tick(3)
        assert self.send()
        # the peer only echoes the first buffer:
        self.ka.audio_keepalive(int((self.clock[0] - 3) * 1000))
        assert not self.ka.audio_keepalive_stale()
        # the timeout now runs from the time this echo was received:
        self.tick(9)
        assert not self.ka.audio_keepalive_stale()
        self.tick(2)
        assert self.ka.audio_keepalive_stale()

    def test_stale_warning_is_only_logged_once(self):
        assert self.send()
        self.tick(11)
        with patch("xpra.audio.keepalive.log") as klog:
            assert self.ka.handle_audio_keepalive_stale("opus")
            assert self.ka.handle_audio_keepalive_stale("opus")
        assert klog.warn.call_count == 2, f"expected a single 2 line warning, got {klog.warn.call_args_list}"
        assert self.ka.stopped == 2

    def test_echo_clears_the_stale_warning(self):
        assert self.send()
        self.tick(11)
        assert self.ka.handle_audio_keepalive_stale("opus")
        assert self.ka.audio_keepalive_stale_warning
        self.ka.audio_keepalive(self.ka.latest_sent_audio_timestamp)
        assert not self.ka.audio_keepalive_stale_warning
        assert not self.ka.audio_keepalive_stale()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
