# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("window")


class WindowPropertyFilter(object):
    def __init__(self, property_name, value):
        self.property_name = property_name
        self.value = value

    def get_window_value(self, window):
        return window.get_property(self.property_name)

    def show(self, window):
        try:
            v = self.get_window_value(window)
            log("%s.show(%s) %s(..)=%s", type(self).__name__, window, self.get_window_value, v)
        except Exception:
            log("%s.show(%s) %s(..) error:", type(self).__name__, window, self.get_window_value, exc_info=True)
            v = None
        e = self.evaluate(v)
        return e

    def evaluate(self, window_value):
        raise NotImplementedError()


class WindowPropertyIn(WindowPropertyFilter):

    def evaluate(self, window_value):
        return window_value in self.value


class WindowPropertyNotIn(WindowPropertyIn):

    def evaluate(self, window_value):
        return not(WindowPropertyIn.evaluate(window_value))
