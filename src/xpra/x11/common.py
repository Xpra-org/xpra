# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#if you want to use a virtual screen bigger than 32767x32767
#you will need to change those values, but some broken toolkits
#will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE = 2**15-1

class Unmanageable(Exception):
    pass


REPR_FUNCTIONS = {}


# Just to make it easier to pass around and have a helpful debug logging.
# Really, just a python objects where we can stick random bags of attributes.
class X11Event(object):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        d = {}
        for k,v in self.__dict__.items():
            if k=="name":
                continue
            elif k=="serial":
                d[k] = "%#x" % v
            else:
                fn = REPR_FUNCTIONS.get(type(v), str)
                d[k] = fn(v)
        return "<X11:%s %r>" % (self.name, d)
