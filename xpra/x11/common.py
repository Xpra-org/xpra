# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class Unmanageable(Exception):
    pass


REPR_FUNCTIONS = {}


# Just to make it easier to pass around and have a helpful debug logging.
# Really, just a python objects where we can stick random bags of attributes.
class X11Event:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        d = {}
        for k,v in self.__dict__.items():
            if k in ("name", "display", "type"):
                continue
            if k=="serial":
                d[k] = "%#x" % v
            else:
                fn = REPR_FUNCTIONS.get(type(v), str)
                d[k] = fn(v)
        return "<X11:%s %r>" % (self.name, d)
