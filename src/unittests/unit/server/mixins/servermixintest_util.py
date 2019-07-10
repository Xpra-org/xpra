#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.gtk_common.gobject_compat import import_glib


class ServerMixinTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super(ServerMixinTest, cls).setUpClass()
        cls.glib = import_glib()
        cls.main_loop = cls.glib.MainLoop()

    def setUp(self):
        self.mixin = None

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if self.mixin:
            self.mixin.cleanup()
            self.mixin = None

    def stop(self):
        self.glib.timeout_add(1000, self.main_loop.quit)

    def _test_mixin_class(self, mclass, opts):
        x = self.mixin = mclass()
        x.idle_add = self.glib.idle_add
        x.timeout_add = self.glib.timeout_add
        x.source_remove = self.glib.source_remove
        x.init(opts)
        x.init_sockets([])
        x.setup()
        x.threaded_setup()
        x.get_info(None)
        x.get_caps(None)
