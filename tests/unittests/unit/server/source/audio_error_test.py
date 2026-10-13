#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.source import audio as audio_source
from xpra.server.source.audio import AudioConnection

DISCONNECTED = "gst-resource-error-quark: Disconnected: Connection terminated (7)"


class FakeGLib:
    def __init__(self):
        self.timers = {}
        self.counter = 0

    def timeout_add(self, delay, callback, *args):
        self.counter += 1
        self.timers[self.counter] = (delay, callback, args)
        return self.counter

    def source_remove(self, timer):
        self.timers.pop(timer, None)

    def fire_timer(self, timer):
        _delay, callback, args = self.timers.pop(timer)
        callback(*args)


class FakeSource(AudioConnection):
    def __init__(self):
        self.init_state()

    def send_more(self, *_args):
        """ no client connection """


class TestAudioSourceError(unittest.TestCase):

    def setUp(self):
        self.glib = FakeGLib()
        patcher = patch.object(audio_source, "GLib", self.glib)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.connection = FakeSource()
        self.audio = object()
        self.connection.audio_source = self.audio

    def test_disconnect_is_reported_later(self):
        self.connection.audio_source_error(self.audio, DISCONNECTED)
        timer = self.connection.audio_source_error_timer
        assert timer in self.glib.timers
        with patch.object(audio_source, "log") as log:
            self.glib.fire_timer(timer)
        log.warn.assert_called_once()
        assert not self.connection.audio_source_error_timer

    def test_disconnect_during_shutdown_is_silent(self):
        self.connection.audio_source_error(self.audio, DISCONNECTED)
        timer = self.connection.audio_source_error_timer
        self.connection.audio_source = None
        self.connection.cleanup()
        assert not self.connection.audio_source_error_timer
        assert timer not in self.glib.timers

    def test_other_errors_are_not_deferred(self):
        self.connection.audio_source_error(self.audio, "some other problem")
        assert not self.connection.audio_source_error_timer
        assert not self.glib.timers

    def test_stale_source_is_ignored(self):
        self.connection.audio_source_error(object(), DISCONNECTED)
        assert not self.connection.audio_source_error_timer


def main():
    unittest.main()


if __name__ == '__main__':
    main()
