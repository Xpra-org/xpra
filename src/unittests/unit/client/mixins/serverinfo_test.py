#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.serverinfo_mixin import ServerInfoMixin
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class ServerInfoClientTest(ClientMixinTest):

	def test_audio(self):
		waq = []
		def _ServerInfoMixin():
			x = ServerInfoMixin()
			def warn_and_quit(*args):
				waq.append(args)
			x.warn_and_quit = warn_and_quit
			return x
		opts = AdHocStruct()
		caps = typedict({
			"machine_id" : "123",
			"uuid"	: "some-uuid",
			"build.version"	: "3.0",
			"build.revision" : "23000",
			"hostname"	: "localhost",
			"display" : ":99",
			"platform" : "linux2",
			"platform.release" : "dunno",
			"platform.platform" : "platformX",
			"platform.linux_distribution" : ('Linux Fedora', 20, 'Heisenbug'),
			})
		x = self._test_mixin_class(_ServerInfoMixin, opts, caps)
		del caps["build.version"]
		assert not x.parse_server_capabilities(caps), "should have failed when version is missing"
		version = "0.1"
		caps["build.version"] = version
		assert not x.parse_server_capabilities(caps), "should have failed with version %s" % version


def main():
	unittest.main()


if __name__ == '__main__':
	main()
