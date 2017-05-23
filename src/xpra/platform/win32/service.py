#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading
from xpra.log import Logger
from xpra.platform import init, clean

class Handler(object):

    def __init__(self):
        init("Xpra Service", "Xpra Service")
        self.log = Logger("server", "win32")
        self.log.info("Service.init()")
        self.stopEvent = threading.Event()
        self.stopRequestedEvent = threading.Event()

    def Initialize(self, configFileName):
        self.log.info("Service.Initialize(%s)", configFileName)

    def SessionChanged(self, sessionId, eventType):
        self.log.info("Service.SessionChanged(%s, %s)", sessionId, eventType)

    def Run(self):
        self.log.info("Service.Run()")
        self.stopRequestedEvent.wait()
        self.stopEvent.set()
        clean()

    def Stop(self):
        self.log.info("Service.Stop()")
        self.stopRequestedEvent.set()
        self.stopEvent.wait()
