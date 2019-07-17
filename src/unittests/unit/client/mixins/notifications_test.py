#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.notifications import NotificationClient


class NotificationClientTest(NotificationClient):

	def test_notification(self):
		x = NotificationClient()
		self.mixin = x
		opts = AdHocStruct()
		opts.notifications = True
		x.init(opts)
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"notifications" : True,
			"notifications.close" : True,
			})
		x.parse_server_capabilities()

def main():
	unittest.main()


if __name__ == '__main__':
	main()
