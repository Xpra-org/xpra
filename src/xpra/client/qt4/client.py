# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from PyQt4 import QtCore, QtGui

from xpra.log import Logger
log = Logger()

from xpra.client.ui_client_base import UIXpraClient
from xpra.net.protocol import set_scheduler
from xpra.client.qt4.qt_keyboard_helper import QtKeyboardHelper
from xpra.client.qt4.scheduler import getQtScheduler
from xpra.client.qt4.client_window import ClientWindow
set_scheduler(getQtScheduler())

sys.modules['gtk']=None
sys.modules['pygtk']=None
sys.modules['gi']=None


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


class XpraClient(UIXpraClient):

    def __init__(self, conn, opts):
        self.QtInit()
        UIXpraClient.__init__(self, conn, opts)

    def QtInit(self):
        self.app = QtGui.QApplication([])
        self.event_loop = QtCore.QEventLoop()
        self.timers = set()

    def client_type(self):
        #overriden in subclasses!
        return "Python/Qt4"

    def get_client_window_class(self, metadata):
        return ClientWindow


    def connect(self, *args):
        log.warn("connect(%s) not implemented for Qt!", args)

    def emit(self, *args):
        log.warn("emit(%s) not implemented for Qt!", args)


    def supports_system_tray(self):
        return False

    def make_clipboard_helper(self):
        return None

    def make_keyboard_helper(self, keyboard_sync, key_shortcuts):
        return QtKeyboardHelper(self.send, keyboard_sync, key_shortcuts, self.send_layout, self.send_keymap)

    def get_screen_sizes(self):
        return  [1280, 1024]

    def get_root_size(self):
        return  1280, 1024

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass

    def group_leader_for_pid(self, pid, wid):
        return None



    def idle_add(self, fn, *args):
        log.info("idle_add(%s, %s)", fn, args)
        def cb():
            fn(*args)
        invoke_in_main_thread(cb)

    def timeout_add(self, delay, fn, *args):
        def main_thread_cb():
            timer = QtCore.QTimer()
            self.timers.add(timer)
            def timer_callback():
                log.info("timer_callback() calling %s(%s)", fn, args)
                x = fn(*args)
                if not bool(x):
                    timer.stop()
                    self.timers.remove(timer)
            timer.timeout.connect(timer_callback)
            timer.start(delay)
        invoke_in_main_thread(main_thread_cb)

    def source_remove(self, *args):
        raise Exception("override me!")


    def run(self):
        log.info("QtXpraClient.run()")
        self.install_signal_handlers()
        self.glib_init()
        log.info("QtXpraClient.run() event_loop=%s", self.event_loop)
        #self.event_loop.exec_()
        self.app.exec_()
        log.info("QtXpraClient.run() main loop ended, returning exit_code=%s", self.exit_code)
        return  self.exit_code

    def quit(self, exit_code=0):
        log("XpraClient.quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        def force_quit(*args):
            os._exit(1)
        QtCore.QTimer.singleShot(5000, force_quit)
        self.cleanup()
        def quit_after():
            self.event_loop.exit(self.exit_code)
        QtCore.QTimer.singleShot(1000, quit_after)


    def get_current_modifiers(self):
        #modifiers_mask = gdk.get_default_root_window().get_pointer()[-1]
        return []

    def mask_to_names(self, mask):
        if self._client_extras is None:
            return []
        return self._client_extras.mask_to_names(mask)


    def make_hello(self, challenge_response=None):
        capabilities = UIXpraClient.make_hello(self, challenge_response)
        capabilities["named_cursors"] = False
        #add_qt_version_info(capabilities, QtGui)
        return capabilities


    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        pass
