# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from PyQt4 import QtCore

from xpra.log import Logger
log = Logger()


from Queue import Queue
class Invoker(QtCore.QObject):
    def __init__(self):
        super(Invoker, self).__init__()
        self.queue = Queue()

    def invoke(self, func, *args):
        f = lambda: func(*args)
        self.queue.put(f)
        QtCore.QMetaObject.invokeMethod(self, "handler", QtCore.Qt.QueuedConnection)

    @QtCore.pyqtSlot()
    def handler(self):
        f = self.queue.get()
        f()
invoker = Invoker()

def invoke_in_main_thread(func, *args):
    invoker.invoke(func,*args)


class QtScheduler(object):

    timers = set()

    @staticmethod
    def idle_add(fn, *args):
        log.info("idle_add(%s, %s)", fn, repr(args)[:100])
        invoke_in_main_thread(fn, *args)

    @staticmethod
    def timeout_add(delay, fn, *args):
        log.info("timeout_add(%s, %s, %s)", delay, fn, repr(args)[:100])
        invoke_in_main_thread(QtScheduler.do_timeout_add, delay, fn, *args)

    @staticmethod
    def do_timeout_add(delay, fn, *args):
        timer = QtCore.QTimer()
        QtScheduler.timers.add(timer)
        def timer_callback():
            log.info("timer_callback() calling %s(%s)", fn, repr(args)[:100])
            x = fn(*args)
            if not bool(x):
                timer.stop()
                QtScheduler.timers.remove(timer)
        timer.timeout.connect(timer_callback)
        timer.start(delay)

    @staticmethod
    def source_remove(self, *args):
        raise Exception("override me!")

qt_scheduler = None
def getQtScheduler():
    global qt_scheduler
    if qt_scheduler is None:
        qt_scheduler = QtScheduler()
    return qt_scheduler
