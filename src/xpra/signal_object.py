#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import itertools
from xpra.log import Logger
log = Logger()


class SignalObject(object):
    """
        A very simple class for emulating gobject's emit()
        So we can use this with Qt too.
    """

    def __init__(self, signals=[]):
        self._signals = []
        self._signal_listeners = {}
        self._signal_id = itertools.count(1)
        self.add_signals(signals)

    def add_signals(self, signals):
        self._signals += signals

    def connect(self, signal, fn, *args):
        assert signal in self._signals, "unknown signal: %s" % signal
        listeners = self._signal_listeners.setdefault(signal, [])
        sid = self._signal_id.next()
        listeners.append((sid, fn, args))
        return sid

    def remove_listener(self, signal, sid):
        assert signal in self._signals, "unknown signal: %s" % signal
        listeners = self._signal_listeners.get(signal)
        if not listeners:
            log.warn("cannot remove signal listener %s: no listeners found for signal %s", sid, signal)
            return
        new_listeners = [x for x in listeners if x[0]!=sid]
        if len(new_listeners)==len(listeners):
            log.warn("cannot remove signal listener %s: not present in list for signal %s", sid, signal)
            return
        self._signal_listeners[signal] = new_listeners

    def emit(self, signal, *args):
        assert signal in self._signals, "unknown signal: %s" % signal
        listeners = self._signal_listeners.get(signal)
        for _, fn, fnargs in listeners:
            try:
                allargs = [self]+list(fnargs)+list(args)
                fn(*allargs)
            except Exception, e:
                log.error("error on listener %s for signal %s: %s", fn, signal, e)

    def cleanup(self):
        self._signal_listeners = {}
