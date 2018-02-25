#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import typedict
from xpra.os_util import POSIX, OSX, BytesIOClass


class SourceMixinsTest(unittest.TestCase):

	def test_clientinfo(self):
		from xpra.server.source.clientinfo_mixin import ClientInfoMixin
		x = ClientInfoMixin()
		x.init_state()
		assert x.get_connect_info()
		assert x.get_info()
		c = typedict()
		x.parse_client_caps(c)
		assert x.get_connect_info()
		assert x.get_info()
		x.cleanup()
		assert x.get_connect_info()
		assert x.get_info()

	def test_clientdisplay(self):
		from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
		x = ClientDisplayMixin()
		x.init_state()
		assert x.get_info()
		c = typedict()
		x.parse_client_caps(c)
		assert x.get_info()
		x.cleanup()
		assert x.get_info()

	def test_webcam(self):
		if not POSIX or OSX:
			return
		from xpra.platform.xposix.webcam import get_virtual_video_devices, check_virtual_dir
		if not check_virtual_dir():
			return
		devices = get_virtual_video_devices()
		if not devices:
			return
		from xpra.server.source.webcam_mixin import WebcamMixin
		wm = WebcamMixin(True, None, ["png", "jpeg"])
		wm.hello_sent = True
		packets = []
		def send(*args):
			packets.append(args)
		#wm.send = send
		wm.send_async = send
		try:
			assert wm.get_info()
			device_id = 0
			w, h = 640, 480
			assert wm.start_virtual_webcam(device_id, w, h)
			assert wm.get_info().get("webcam", {}).get("active-devices", 0)==1
			assert len(packets)==1	#ack sent
			frame_no = 0
			encoding = "png"
			buf = BytesIOClass()
			from PIL import Image
			image = Image.new('RGB', size=(w, h), color=(155, 0, 0))
			image.save(buf, 'jpeg')
			data = buf.getvalue()
			buf.close()
			wm.process_webcam_frame(device_id, frame_no, encoding, w, h, data)
			assert len(packets)==2	#ack sent
			wm.stop_virtual_webcam(device_id)
		finally:
			wm.cleanup()
		

def main():
	unittest.main()


if __name__ == '__main__':
	main()
