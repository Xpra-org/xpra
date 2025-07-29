#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.util.objects import AdHocStruct

from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class AudioMixinTest(ServerMixinTest):

    @classmethod
    def setUpClass(cls):
        ServerMixinTest.setUpClass()
        from xpra.net import packet_encoding
        packet_encoding.init_all()
        from xpra.net import compression
        compression.init_all()

    def test_audio(self):
        from xpra.server.subsystem import audio
        from xpra.server.source.audio import AudioConnection
        from xpra.audio import gstreamer_util
        opts = AdHocStruct()
        opts.audio_source = ""
        opts.speaker = "on"
        opts.speaker_codec = gstreamer_util.CODEC_ORDER
        opts.microphone = "on"
        opts.microphone_codec = ["mp3"]
        opts.audio = True
        opts.pulseaudio = False
        opts.pulseaudio_command = "/bin/true"
        opts.pulseaudio_configure_commands = []
        opts.av_sync = True
        with silence_info(audio, "log"):
            self._test_mixin_class(audio.AudioServer, opts, {
                "audio": {
                    "receive": True,
                    "decoders": gstreamer_util.CODEC_ORDER,
                },
            }, AudioConnection)
            #init runs in a thread, give it time:
            time.sleep(2)
        if not self.mixin.speaker_codecs:
            print("no speaker codecs available, test skipped")
            return
        codec = self.mixin.speaker_codecs[0]
        with silence_info(gstreamer_util):
            self.handle_packet(("audio-control", "start", codec))
        time.sleep(1)
        self.handle_packet(("audio-control", "fadeout"))
        time.sleep(1)
        self.handle_packet(("audio-control", "stop"))


def main():
    from xpra.os_util import POSIX, OSX
    if POSIX and not OSX:
        #verify that pulseaudio is running:
        #otherwise the tests will fail
        #ie: during rpmbuild
        from subprocess import getstatusoutput
        if getstatusoutput("pactl info")[0]!=0:
            return
        unittest.main()


if __name__ == '__main__':
    main()
