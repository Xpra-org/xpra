# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("filters")


class WindowPropertyFilter(object):
    def __init__(self, property_name, value, recurse=False):
        self.property_name = property_name
        self.value = value
        self.recurse = recurse

    def get_window(self, window):
        return window

    def get_window_value(self, window):
        return window.get_property(self.property_name)

    def matches(self, window):
        try:
            w = self.get_window(window)
            log("get_window(%s)=%s", window, w)
            v = self.get_window_value(w)
            log("%s.matches(%s) %s(..)=%s", self, w, self.get_window_value, v)
        except Exception:
            log("%s.matches(%s) %s(..) error:", self, w, self.get_window_value, exc_info=True)
            return False
        e = self.evaluate(v)
        log("%s.evaluate(%s)=%s (window(%s)=%s)", self, v, e, window, w)
        return e

    def evaluate(self, window_value):
        raise NotImplementedError()


class WindowPropertyIn(WindowPropertyFilter):

    def evaluate(self, window_value):
        vtypes = set([type(x) for x in self.value])
        if len(vtypes)==1 and list(vtypes)[0]==str:
            #coerce value to match:
            window_value = str(window_value)
        return window_value in self.value

    def __repr__(self):
        return "WindowPropertyIn(%s=%s, recurse=%s)" % (self.property_name, self.value, self.recurse)


class WindowPropertyNotIn(WindowPropertyIn):

    def evaluate(self, window_value):
        return not(WindowPropertyIn.evaluate(self, window_value))

    def __repr__(self):
        return "WindowPropertyNotIn(%s=%s, recurse=%s)" % (self.property_name, self.value, self.recurse)


def get_window_filter(object_name, property_name, operator, value):
    oname = object_name.lower()
    if oname not in ("window", "window-parent"):
        raise ValueError("invalid object name '%s'" % object_name)
    recurse = oname=="window-parent"
    if operator=="=":
        window_filter = WindowPropertyIn(property_name, [value], recurse)
    elif operator=="!=":
        window_filter = WindowPropertyNotIn(property_name, [value], recurse)
    else:
        raise ValueError("invalid window filter operator: %s" % operator)
    log("get_window_filter%s=%s", (object_name, property_name, operator, value), window_filter)
    return window_filter
