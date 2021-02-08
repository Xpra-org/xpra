#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.notifications import NotificationClient
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class NotificationClientTest(ClientMixinTest):

	def test_notification(self):
		opts = AdHocStruct()
		opts.notifications = True
		self._test_mixin_class(NotificationClient, opts, {
			"notifications" : True,
			"notifications.close" : True,
			})

def main():
	unittest.main()


if __name__ == '__main__':
	main()
