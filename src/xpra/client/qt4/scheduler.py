# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from PyQt4 import QtCore

from xpra.log import Logger
log = Logger()


class QtScheduler(object):

    timers = set()

    @staticmethod
    def idle_add(fn, *args):
        log.info("idle_add(%s, %s)", fn, args)
        def timer_callback(*targs):
            log.info("timer_callback(%s) calling %s(%s)", targs, fn, args)
            x = fn(*args)
            if bool(x):
                QtCore.QTimer.singleShot(0, timer_callback)
        QtCore.QTimer.singleShot(0, timer_callback)

    @staticmethod
    def timeout_add(delay, fn, *args):
        timer = QtCore.QTimer()
        QtScheduler.timers.add(timer)
        def timer_callback():
            log.info("timer_callback() calling %s(%s)", fn, args)
            x = fn(*args)
            if not bool(x):
                timer.stop()
                QtScheduler.timers.remove(timer)
        timer.timeout.connect(timer_callback)
        timer.start(delay)

    @staticmethod
    def source_remove(self, *args):
        raise Exception("override me!")
