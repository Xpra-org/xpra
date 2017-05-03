# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gtk import gdk

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
            elif v and type(v)==gdk.Window:
                d[k] = "%#x" % v.xid
            elif v and type(v)==gdk.Display:
                d[k] = "%s" % v.get_name()
            else:
                d[k] = v
        return "<X11:%s %r>" % (self.name, d)
