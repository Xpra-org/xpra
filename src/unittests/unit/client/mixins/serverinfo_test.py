#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.serverinfo_mixin import ServerInfoMixin
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class AudioClientTest(ClientMixinTest):

	def test_audio(self):
		def _ServerInfoMixin():
			x = ServerInfoMixin()
			def warn_and_quit(*_args):
				pass
			x.warn_and_quit = warn_and_quit
			return x
		opts = AdHocStruct()
		x = self._test_mixin_class(_ServerInfoMixin, opts, {
			"machine_id" : "123",
			"uuid"	: "some-uuid",
			"build.version"	: "3.0",
			"build.revision" : "23000",
			"hostname"	: "localhost",
			"display" : ":99",
			"platform" : "linux2",
			"platform.release" : "dunno",
			"platform.platform" : "platformX",
			})
		del x.server_capabilities["build.version"]
		assert not x.parse_server_capabilities(), "should have failed when version is missing"
		version = "0.1"
		x.server_capabilities["build.version"] = version
		assert not x.parse_server_capabilities(), "should have failed with version %s" % version

def main():
	unittest.main()


if __name__ == '__main__':
	main()
