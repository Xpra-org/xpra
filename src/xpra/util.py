# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
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

    def __repr__(self):
        return "AtomicInteger(%s)" % self.counter


    def __int__(self):
        return self.counter

    def __eq__(self, other):
        try:
            return self.counter==int(other)
        except:
            return -1

    def __cmp__(self, other):
        try:
            return self.counter-int(other)
        except:
            return -1


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


def log_screen_sizes(root_w, root_h, sizes):
    try:
        do_log_screen_sizes(root_w, root_h, sizes)
    except Exception, e:
        from xpra.log import Logger
        log = Logger("util")
        log.warn("failed to parse screen size information: %s", e)

def prettify_plug_name(s, default=""):
    if not s:
        return default
    #prettify strings on win32
    return s.lstrip("0\\").lstrip(".\\").replace("0\\", "-")

def do_log_screen_sizes(root_w, root_h, sizes):
    from xpra.log import Logger
    log = Logger()
    #old format, used by some clients (android):
    if len(sizes)==2 and type(sizes[0])==int and type(sizes[1])==int:
        return
    for s in sizes:
        if len(s)<10:
            log.info(" %s", s)
            continue
        #more detailed output:
        display_name, width, height, width_mm, height_mm, \
        monitors, work_x, work_y, work_width, work_height = s[:11]
        #always log plug name:
        info = ["'%s'" % prettify_plug_name(display_name)]
        if width!=root_w or height!=root_h:
            #log plug dimensions if not the same as display (root):
            info.append("%sx%s" % (width, height))
        info.append("(%sx%s mm)" % (width_mm, height_mm))
        if work_width!=width or work_height!=height or work_x!=0 or work_y!=0:
            #log workarea if not the same as plug size:
            info.append("workarea: %sx%s" % (work_width, work_height))
            if work_x!=0 or work_y!=0:
                #log position if not (0, 0)
                info.append("at %sx%s" % (work_x, work_y))
        log.info("  "+" ".join(info))
        i = 0
        for m in monitors:
            i += 1
            if len(m)<7:
                log.info("    %s", m)
                continue
            plug_name, plug_x, plug_y, plug_width, plug_height, plug_width_mm, plug_height_mm = m[:8]
            info = ['%s' % prettify_plug_name(plug_name, "monitor %s" % i)]
            if plug_width!=width or plug_height!=height or plug_x!=0 or plug_y!=0:
                info.append("%sx%s" % (plug_width, plug_height))
                if plug_x!=0 or plug_y!=0:
                    info.append("at %sx%s" % (plug_x, plug_y))
            if (plug_width_mm!=width_mm or plug_height_mm!=height_mm) and (plug_width_mm>0 or plug_height_mm>0):
                info.append("(%sx%s mm)" % (plug_width_mm, plug_height_mm))
            log.info("    "+" ".join(info))


def dump_references(log, instances, exclude=[]):
    import gc
    import inspect
    gc.collect()
    cf = inspect.currentframe()
    exclude.append(instances)
    exclude.append([cf])
    for instance in instances:
        referrers = [x for x in gc.get_referrers(instance) if (x not in exclude and len([y for y in exclude if x in y])==0)]
        log.info("referrers for %s: %s", instance, len(referrers))
        for i in range(len(referrers)):
            r = referrers[i]
            log.info("[%s] in %s", i, type(r))
            if inspect.isframe(r):
                log.info("  frame info: %s", str(inspect.getframeinfo(r))[:1024])
            elif type(r)==list:
                listref = gc.get_referrers(r)
                log.info("  list: %s..  %s referrers: %s", str(r[:32])[:1024], len(listref), str(listref[:32])[:1024])
            elif type(r)==dict:
                if len(r)>64:
                    log.info("  %s items: %s", len(r), str(r)[:1024])
                    continue
                for k,v in r.items():
                    if k is instance:
                        log.info("  key with value=%s", v)
                    elif v is instance:
                        log.info("  for key=%s", k)
            else:
                log.info("     %s : %s", type(r), r)


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


def is_unity():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "unity"
