#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import unittest

from xpra.os_util import WIN32, POSIX, OSX
from xpra.util import AdHocStruct
from xpra.client.mixins.audio import AudioClient
from xpra.sound.gstreamer_util import CODEC_ORDER
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class AudioClientTestUtil(ClientMixinTest):

	def _default_opts(self):
		opts = AdHocStruct()
		opts.av_sync = True
		opts.speaker = "no"
		opts.microphone = "no"
		opts.sound_source = ""
		opts.speaker_codec = []
		opts.microphone_codec = []
		opts.tray_icon = ""
		return opts

	def _test_audio(self, opts, caps):
		return self._test_mixin_class(AudioClient, opts, caps)


class AudioClientSendTestUtil(AudioClientTestUtil):

	def do_test_audio_send(self, auto_start=True):
		opts = self._default_opts()
		opts.microphone = "on" if auto_start else "off"
		self._test_audio(opts, {
			"sound.receive" : True,
			"sound.decoders" : CODEC_ORDER,
			})
		if not self.mixin.microphone_codecs:
			print("no microphone codecs, test skipped")
			return
		def check_packets():
			if len(self.packets)<5:
				return True
			self.mixin.stop_sending_sound()
			self.main_loop.quit()
			return False
		if not auto_start:
			def request_start():
				self.mixin.start_sending_sound()
			self.glib.timeout_add(500, request_start)
		self.glib.timeout_add(100, check_packets)
		self.glib.timeout_add(5000, self.main_loop.quit)
		self.main_loop.run()
		assert len(self.packets)>2
		self.verify_packet(0, ("sound-data", ))
		assert self.packets[0][3].get("start-of-stream"), "start-of-stream not found"
		self.verify_packet(-1, ("sound-data", ))
		assert self.packets[-1][3].get("end-of-stream"), "end-of-stream not found"


class AudioClientSendAuto(AudioClientSendTestUtil):

	def test_audio_send_auto(self):
		self.do_test_audio_send(True)

class AudioClientSendRequest(AudioClientSendTestUtil):

	def test_audio_send_request(self):
		self.do_test_audio_send(False)


class AudioClientReceiveTest(AudioClientTestUtil):

	def test_audio_receive(self):
		opts = self._default_opts()
		opts.speaker = "yes"
		x = self._test_audio(opts, {
			"sound.send" : True,
			"sound.encoders" : CODEC_ORDER,
			})
		def stop():
			x.stop_receiving_sound()
			self.stop()
		if not self.mixin.speaker_codecs:
			stop()
			print("no speaker codecs, test skipped")
		if "opus" not in self.mixin.speaker_codecs:
			stop()
			print("'opus' speaker codec missing, test skipped")
			return
		packet_data = [
				('sound-data', b'opus', '', {'start-of-stream': True, 'codec': b'opus'}),
				('sound-data', b'opus', b'fc60fddad634b19a5baa6dd0ae26e05d15106df1135c84590fa2ab85d9945dd504a1d7b54d3ea189b276b36909ee33d34f038fd0d4aa25baa6abd1cd6b896bbfab52e02b9b18bc260fc4441bc44a65b2e0428431aafeabc3cc4974c9a4afe02df92638c51c1eb36292662b710ee971fb16361692e6fb819a1ef7bc66a6badd04d71160c16b249aaf497e79cf56c622cffeb6bcfd83027954132d5d90500104a4', {b'duration': 13500000, b'timestamp': 0, b'time': 159963539, 'sequence': 0}),
				('sound-data', b'opus', b'fc6e8120f7b82efd4dec6f067d0f4af7ee27220307090f8595517139761252409ea93e4ba08d59b009a96efabc9a99f5895c2b084db0ab0ccc9665dc54e58a3a1dcacb6156fab84b6031c74b4f353ffb16c68c0959510e63d1f632a95358ee673d969c210f18b1dd765204a857c631e281960b9988d4821a34bf5d0729cf4696d8a00dfa08115cdd6de84b9bc8f216d6924e071018ebb6d4ac3c3d8298cb1813', {b'duration': 20000000, b'timestamp': 13500000, b'time': 159963558, 'sequence': 0}),
				('sound-data', b'opus', b'fc6dd5d0f08acc6ae38aca6dc1038b2da49ca1fa69220405c8556f553e6352680ad0c403b94285a32259dd9455d157090ab602ac2256b4426779083ed9f119fe261de3fb7bafd3e1508cf38b47a7ff62d8d15443c095bd8ca63d152a6b1dcce71d70c79763163c2ed5e804eafffa0eb267b59bb35a1a34bdd7074a8f1696d8a406f0b4c457377ebc25cdadb789b5a49381c4063a44c7b6d4ac2bebebef316d77', {b'duration': 20000000, b'timestamp': 33500000, b'time': 159963576, 'sequence': 0}),
				('sound-data', b'opus', b'fc4d2dfba53a9041a76a560e128ed23c27e6ba1a5dd7aaf9fa0ef2c801e748dc8a7262ca5821ccee59a209ccd97be931a62b02651d11af09e7d26aedbbb52a490a75463dccc52843b488e9ffd8b45ff6e5fe3cbcb4e872170cee673a82d953af2e3ce570ca82176af40df8db59735cdcdecfe0444d0faeebce583aa70241c05d1406f0c06d7bddd6defadc6b6de26d6924e071017dbfdb25645f0055f3d569a5', {b'duration': 20000000, b'timestamp': 53500000, b'time': 159963596, 'sequence': 0}),
				('sound-data', b'opus', b'fc4d2e0df8779efc983d56a4881571c36a50ce90597b0be6a8d4d9194d5620c2c0bd0b9d7ecb0b8e724e7a9acbb9e9cf1d5ec31635f1bfa99ec410c49fc09bed96b9dd5a9b372c0e09a9ffd8ab8bfe3cbcdb97f2170cd3a1ddcce7505b2824c81aefefec32a085dabd037e36d65f5fd652f9c33d96673b2bcedf4d2a21d7d5dd1406f0c06d7bddd6defadc6b6de26d6924e071017d8fdb25645f50105c730413', {b'duration': 20000000, b'timestamp': 73500000, b'time': 159963616, 'sequence': 0}),
				('sound-data', b'opus', '', {'end-of-stream': True, 'sequence': 0}),
			]
		def feed_data():
			packet = packet_data.pop(0)
			self.handle_packet(packet)
			if packet_data:
				return True
			self.mixin.stop_receiving_sound()
			self.main_loop.quit()
			return False
		def check_start():
			if not self.packets:
				return True
			self.verify_packet(0, ("sound-control", "start", "opus"))
			self.glib.timeout_add(100, feed_data)
			return False
		self.glib.timeout_add(100, check_start)
		self.glib.timeout_add(5000, stop)
		#self.debug_all()
		self.main_loop.run()
		assert not packet_data, "data was not fed to the receiver"
		self.verify_packet(0, ("sound-control", "start", "opus"))
		self.verify_packet(1, ("sound-control", "new-sequence", 1))
		#assert not self.packets, "sent some unexpected packets: %s" % (self.packets,)
		assert self.mixin.sound_sink is None, "sink is still active: %s" % self.mixin.sound_sink


def main():
	if WIN32:
		return
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
