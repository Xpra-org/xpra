#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import typedict
from xpra.gtk_common.gobject_compat import import_glib


class ServerMixinTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super(ServerMixinTest, cls).setUpClass()
        cls.glib = import_glib()
        cls.main_loop = cls.glib.MainLoop()

    def setUp(self):
        self.mixin = None
        self.source = None

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if self.source:
            self.source.cleanup()
            self.source = None
        if self.mixin:
            self.mixin.cleanup()
            self.mixin = None

    def stop(self):
        self.glib.timeout_add(1000, self.main_loop.quit)

    def wait_for_threaded_init(self):
        #we don't do threading yet,
        #so no need to wait
        pass

    def _test_mixin_class(self, mclass, opts, caps=None, source_mixin_class=None):
        x = self.mixin = mclass()
        x.wait_for_threaded_init = self.wait_for_threaded_init
        x.idle_add = self.glib.idle_add
        x.timeout_add = self.glib.timeout_add
        x.source_remove = self.glib.source_remove
        x.init(opts)
        x.init_sockets([])
        x.setup()
        x.threaded_setup()
        caps = typedict(caps or {})
        send_ui = True
        self.source = None
        if source_mixin_class:
            self.source = source_mixin_class()
            self.source.init_state()
            self.source.parse_client_caps(caps)
            self.source.get_info()
        x.get_caps(self.source)
        x.get_info(None)
        x.parse_hello(self.source, caps, send_ui)
        x.get_info(self.source)
