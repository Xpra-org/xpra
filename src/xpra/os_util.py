#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import sys
import signal

#hide some ugly python3 compat:
try:
    import _thread    as thread         #@UnresolvedImport @UnusedImport (python3)
except:
    import thread                       #@Reimport @UnusedImport

try:
    from queue import Queue             #@UnresolvedImport @UnusedImport (python3)
except ImportError:
    from Queue import Queue             #@Reimport @UnusedImport

try:
    import builtins                     #@UnresolvedImport @UnusedImport (python3)
except:
    import __builtin__ as builtins      #@Reimport @UnusedImport


SIGNAMES = {}
for x in [x for x in dir(signal) if x.startswith("SIG") and not x.startswith("SIG_")]:
    SIGNAMES[getattr(signal, x)] = x


#use cStringIO, fallback to StringIO,
#and python3 is making life more difficult yet again:
try:
    from io import BytesIO as BytesIOClass              #@UnusedImport
except:
    try:
        from cStringIO import StringIO as BytesIOClass  #@Reimport @UnusedImport
    except:
        from StringIO import StringIO as BytesIOClass   #@Reimport @UnusedImport
try:
    from StringIO import StringIO as StringIOClass      #@UnusedImport
except:
    try:
        from cStringIO import StringIO as StringIOClass #@Reimport @UnusedImport
    except:
        from io import StringIO as StringIOClass        #@Reimport @UnusedImport


if sys.version_info < (2, 6):
    from sets import ImmutableSet
else:
    ImmutableSet = frozenset


if sys.version < '3':
    def strtobytes(x):
        return x
    def bytestostr(x):
        return x
else:
    def strtobytes(x):
        if type(x)==bytes:
            return x
        return x.encode()
    def bytestostr(x):
        if type(x)==str:
            return x
        return x.decode()


def data_to_buffer(in_data):
    if sys.version>='3':
        data = bytearray(in_data.encode("latin1"))
    else:
        try:
            data = bytearray(in_data)
        except:
            #old python without bytearray:
            data = str(in_data)
    return BytesIOClass(data)

def platform_name(sys_platform, release):
    if not sys_platform:
        return "unknown"
    PLATFORMS = {"win32"    : "Microsoft Windows",
                 "cygwin"   : "Windows/Cygwin",
                 "linux.*"  : "Linux",
                 "darwin"   : "Mac OSX",
                 "freebsd.*": "FreeBSD",
                 "os2"      : "OS/2",
                 }
    def rel(v):
        if sys_platform=="win32" and release:
            return "%s %s" % (v, release)
        return v
    for k,v in PLATFORMS.items():
        regexp = re.compile(k)
        if regexp.match(sys_platform):
            return rel(v)
    return rel(sys_platform)

def os_info(sys_platform, platform_release, platform_platform, platform_linux_distribution):
    s = [platform_name(sys_platform, platform_release)]
    if platform_linux_distribution and len(platform_linux_distribution)==3 and len(platform_linux_distribution[0])>0:
        s.append(" ".join([str(x) for x in platform_linux_distribution]))
    elif platform_platform:
        s.append(platform_platform)
    return s


try:
    if os.environ.get("XPRA_TEST_UUID_WRAPPER", "0")=="1":
        raise ImportError("testing uuidgen codepath")
    import uuid

    def get_hex_uuid():
        return uuid.uuid4().hex

    def get_int_uuid():
        return uuid.uuid4().int

except ImportError:
    #fallback to using the 'uuidgen' command:
    def get_hex_uuid():
        from commands import getstatusoutput
        s, o = getstatusoutput('uuidgen')
        if s!=0:
            raise Exception("no uuid module and 'uuidgen' failed!")
        return o.replace("-", "")

    def get_int_uuid():
        hex_uuid = get_hex_uuid()
        return int(hex_uuid, 16)


def get_machine_id():
    """
        Try to get uuid string which uniquely identifies this machine.
        Warning: only works on posix!
        (which is ok since we only used it on posix at present)
    """
    v = u""
    if os.name=="posix":
        for filename in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            v = load_binary_file(filename)
            if v is not None:
                break
    return  str(v).strip("\n\r")

def get_user_uuid():
    """
        Try to generate a uuid string which is unique to this user.
        (relies on get_machine_id to uniquely identify a machine)
    """
    import hashlib
    u = hashlib.sha1()
    def uupdate(ustr):
        u.update(ustr.encode("utf-8"))
    uupdate(get_machine_id())
    if os.name=="posix":
        uupdate(u"/")
        uupdate(str(os.getuid()))
        uupdate(u"/")
        uupdate(str(os.getgid()))
    uupdate(os.environ.get("HOME", ""))
    return u.hexdigest()

def is_Ubuntu():
    try:
        v = load_binary_file("/etc/issue")
        return bool(v) and v.find("Ubuntu")>=0
    except:
        pass
    return False

def load_binary_file(filename):
    if not os.path.exists(filename):
        return None
    f = None
    try:
        f = open(filename, "rb")
        try:
            return f.read()
        finally:
            f.close()
    except:
        return None

#here so we can override it when needed
def force_quit(status=1):
    os._exit(status)


def main():
    from xpra.log import Logger
    log = Logger("util")
    sp = sys.platform
    log.info("platform_name(%s)=%s", sp, platform_name(sp, ""))
    log.info("get_machine_id()=%s", get_machine_id())
    log.info("get_hex_uuid()=%s", get_hex_uuid())
    log.info("get_int_uuid()=%s", get_int_uuid())


if __name__ == "__main__":
    main()
