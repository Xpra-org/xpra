#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class AudioMixinTest(ServerMixinTest):

    def test_audio(self):
        from xpra.server.mixins.audio_server import AudioServer
        x = AudioServer()
        self.mixin = x
        opts = AdHocStruct()
        opts.sound_source = ""
        opts.speaker = "on"
        opts.speaker_codec = ["mp3"]
        opts.microphone = "on"
        opts.microphone_codec = ["mp3"]
        opts.pulseaudio = True
        opts.pulseaudio_command = ""
        opts.pulseaudio_configure_commands = []
        x.init(opts)
        x.setup()
        x.get_info(None)
        x.get_caps(None)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
