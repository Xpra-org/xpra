# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import strtobytes, bytestostr
import traceback
import threading
import sys

def dump_exc():
    """Call this from a except: clause to print a nice traceback."""
    print("".join(traceback.format_exception(*sys.exc_info())))

# A simple little class whose instances we can stick random bags of attributes
# on.
class AdHocStruct(object):
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))


class AtomicInteger(object):
    def __init__(self, integer = 0):
        self.counter = integer
        self.lock = threading.RLock()

    def increase(self, inc = 1):
        self.lock.acquire()
        self.counter = self.counter + inc
        v = self.counter
        self.lock.release()
        return v

    def decrease(self, dec = 1):
        self.lock.acquire()
        self.counter = self.counter - dec
        v = self.counter
        self.lock.release()
        return v

    def get(self):
        return self.counter

    def __str__(self):
        return str(self.counter)

class typedict(dict):

    def capsget(self, key, default):
        v = self.get(strtobytes(key), default)
        if sys.version >= '3' and type(v)==bytes:
            v = bytestostr(v)
        return v

    def strget(self, k, default=None):
        v = self.capsget(k, default)
        if v is None:
            return None
        return str(v)

    def intget(self, k, d=0):
        return int(self.capsget(k, d))

    def boolget(self, k, default_value=False):
        return bool(self.capsget(k, default_value))

    def dictget(self, k, default_value={}):
        v = self.capsget(k, default_value)
        if v is None:
            return None
        assert type(v)==dict, "expected a dict value for %s but got %s" % (k, type(v))
        return v

    def intpair(self, k, default_value=None):
        v = self.intlistget(k, default_value)
        if v is None:
            return default_value
        if len(v)!=2:
            #"%s is not a pair of numbers: %s" % (k, len(v))
            return default_value
        return v

    def strlistget(self, k, default_value=[]):
        return self.listget(k, default_value, str)

    def intlistget(self, k, default_value=[]):
        return self.listget(k, default_value, int)

    def listget(self, k, default_value=[], item_type=None, max_items=None):
        v = self.capsget(k, default_value)
        if v is None:
            return default_value
        assert type(v) in (list, tuple), "expected a list or tuple value for %s but got %s" % (k, type(v))
        if item_type:
            for x in v:
                assert type(x)==item_type, "invalid item type for %s %s: expected %s but got %s" % (type(v), k, item_type, type(x))
        if max_items is not None:
            assert len(v)<=max_items, "too many items in %s %s: maximum %s allowed, but got %s" % (type(v), k, max_items, len(v))
        return v


def std(_str, extras="-,./ "):
    def f(v):
        return str.isalnum(str(v)) or v in extras
    return filter(f, _str)

def alnum(_str):
    def f(v):
        return str.isalnum(str(v))
    return filter(f, _str)

def nn(x):
    if x is None:
        return  ""
    return x

def nonl(x):
    if x is None:
        return None
    return str(x).replace("\n", "\\n").replace("\r", "\\r")

def xor(s1,s2):
    return ''.join(chr(ord(a) ^ ord(b)) for a,b in zip(s1,s2))
