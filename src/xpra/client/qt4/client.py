# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from PyQt4 import QtCore, QtGui

from xpra.log import Logger
log = Logger()

from xpra.client.ui_client_base import UIXpraClient

sys.modules['gtk']=None
sys.modules['pygtk']=None
sys.modules['gi']=None


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

    def connect(self, *args):
        log.warn("connect(%s) not implemented for Qt!", args)

    def get_screen_sizes(self):
        return  [1280, 1024]
        
    def get_root_size(self):
        return  1280, 1024

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass


    def idle_add(self, fn, *args):
        log.info("idle_add(%s, %s)", fn, args)
        def timer_callback(*targs):
            log.info("timer_callback(%s) calling %s(%s)", targs, fn, args)
            x = fn(*args)
            if bool(x):
                QtCore.QTimer.singleShot(0, timer_callback)
        QtCore.QTimer.singleShot(0, timer_callback)

    def timeout_add(self, delay, fn, *args):
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
