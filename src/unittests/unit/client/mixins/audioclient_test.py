#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import PYTHON3
from xpra.util import AdHocStruct, typedict
from xpra.gtk_common.gobject_compat import import_glib
from xpra.client.mixins.audio import AudioClient

glib = import_glib()


class AudioClientTest(unittest.TestCase):

	def test_audio(self):
		self.packets = []
		main_loop = glib.MainLoop()
		x = AudioClient()
		opts = AdHocStruct()
		opts.av_sync = True
		opts.speaker = "on"
		opts.microphone = "on"
		opts.sound_source = ""
		opts.speaker_codec = []
		opts.microphone_codec = []
		opts.tray_icon = ""
		x.init(opts)
		x.send = self.send
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"sound.receive" : True,
			"sound.send" : True,
			"sound.encoders" : ["mp3", "opus"],
			"sound.decoders" : ["mp3", "opus"],
			"sound.ogg-latency-fix" : True,
			})
		def stop():
			x.stop_all_sound()
			glib.timeout_add(1000, main_loop.quit)
		glib.timeout_add(5000, stop)
		try:
			x.parse_server_capabilities()
			main_loop.run()
		finally:
			x.stop_all_sound()
		#print("packets=%s" % (self.packets,))
		assert len(self.packets)>2
		assert self.verify_packet(0, ("sound-control", "start")) or self.verify_packet(1, ("sound-control", "start"))
		assert self.verify_packet(1, ("sound-data", )) or self.verify_packet(0, ("sound-data", ))
		assert self.verify_packet(-2, ("sound-control", "stop"))
		assert self.verify_packet(-1, ("sound-control", "new-sequence"))

	def send(self, *args):
		self.packets.append(args)

	def verify_packet(self, index, expected):
		if index<0:
			actual_index = len(self.packets)+index
		else:
			actual_index = index
		assert actual_index>=0
		assert len(self.packets)>actual_index, "not enough packets (%i) to access %i" % (len(self.packets), index)
		packet = self.packets[actual_index]
		pslice = packet[:len(expected)]
		return pslice==expected


def main():
	if PYTHON3:
		unittest.main()


if __name__ == '__main__':
	main()
