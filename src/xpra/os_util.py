#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import sys
import signal
import uuid

#hide some ugly python3 compat:
try:
    import _thread as thread            #@UnresolvedImport @UnusedImport (python3)
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
_memoryview = builtins.__dict__.get("memoryview")
_buffer = builtins.__dict__.get("buffer")


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


if sys.version_info[0] < 3:
    def strtobytes(x):
        return str(x)
    def bytestostr(x):
        return str(x)
else:
    def strtobytes(x):
        if type(x)==bytes:
            return x
        return str(x).encode("latin1")
    def bytestostr(x):
        if type(x)==bytes:
            return x.decode("latin1")
        return str(x)

def memoryview_to_bytes(v):
    if type(v)==bytes:
        return v
    if _memoryview and isinstance(v, _memoryview):
        return v.tobytes()
    if _buffer and isinstance(v, _buffer):
        return bytes(v)
    if isinstance(v, bytearray):
        return bytes(v)
    return v


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
        values = [v]
        if sys_platform=="win32" or sys_platform.startswith("linux"):
            if type(release) in (tuple, list):
                values += list(release)
            else:
                values.append(release)
        return " ".join([str(x) for x in values if x])
    for k,v in PLATFORMS.items():
        regexp = re.compile(k)
        if regexp.match(sys_platform):
            return rel(v)
    return rel(sys_platform)


def get_hex_uuid():
    return uuid.uuid4().hex

def get_int_uuid():
    return uuid.uuid4().int

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
        assert os.name=="posix"
        v = load_binary_file("/etc/issue")
        return v.find("Ubuntu")>=0
    except:
        return False

def is_Fedora():
    try:
        assert os.name=="posix"
        v = load_binary_file("/etc/issue")
        return v.find("Fedora")>=0
    except:
        return False

def getUbuntuVersion():
    from xpra.scripts.config import python_platform
    distro = ""
    if hasattr(python_platform, "linux_distribution"):
        distro = python_platform.linux_distribution()
    if distro and len(distro)==3 and distro[0]=="Ubuntu":
        ur = distro[1]  #ie: "12.04"
        try:
            rnum = [int(x) for x in ur.split(".")]  #ie: [12, 4]
            return rnum
        except:
            pass
    return []

def is_unity():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "unity"


def load_binary_file(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "rb") as f:
            return f.read()
    except:
        return None

#here so we can override it when needed
def force_quit(status=1):
    os._exit(status)


def livefds():
    live = set()
    try:
        MAXFD = os.sysconf("SC_OPEN_MAX")
    except:
        MAXFD = 256
    for fd in range(0, MAXFD):
        try:
            s = os.fstat(fd)
            if s:
                live.add(fd)
        except:
            continue
    return live

#code to temporarily redirect stderr and restore it afterwards, adapted from:
#http://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python
#used by the sound code to get rid of the stupid gst warning below:
#"** Message: pygobject_register_sinkfunc is deprecated (GstObject)"
#ideally we would redirect to a buffer so we could still capture and show these messages in debug out
class HideStdErr(object):

    def __init__(self, *args, **kw):
        self.savedstderr = None

    def __enter__(self):
        if os.name=="posix" and os.getppid()==1:
            #this interferes with server daemonizing?
            return
        sys.stderr.flush() # <--- important when redirecting to files
        self.savedstderr = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        sys.stderr = os.fdopen(self.savedstderr, 'w')

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.savedstderr is not None:
            os.dup2(self.savedstderr, 2)

class HideSysArgv(object):

    def __init__(self, *args, **kw):
        self.savedsysargv = None

    def __enter__(self):
        self.savedsysargv = sys.argv
        sys.argv = sys.argv[:1]

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.savedsysargv is not None:
            sys.argv = self.savedsysargv


def disable_stdout_buffering():
    import gc
    # Appending to gc.garbage is a way to stop an object from being
    # destroyed.  If the old sys.stdout is ever collected, it will
    # close() stdout, which is not good.
    gc.garbage.append(sys.stdout)
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

def setbinarymode(fd):
    if sys.platform.startswith("win"):
        #turn on binary mode:
        try:
            import msvcrt
            msvcrt.setmode(fd, os.O_BINARY)         #@UndefinedVariable
        except:
            from xpra.log import Logger
            log = Logger("util")
            log.error("setting stdin to binary mode failed", exc_info=True)

def find_lib_ldconfig(libname):
    libname = re.escape(libname)

    arch_map = {"x86_64": "libc6,x86-64"}
    arch = arch_map.get(os.uname()[4], "libc6")

    pattern = r'^\s+lib%s\.[^\s]+ \(%s(?:,.*?)?\) => (.*lib%s[^\s]+)' % (libname, arch, libname)

    #try to find ldconfig first, which may not be on the $PATH
    #(it isn't on Debian..)
    ldconfig = "ldconfig"
    for d in ("/sbin", "/usr/sbin"):
        t = os.path.join(d, "ldconfig")
        if os.path.exists(t):
            ldconfig = t
            break
    import subprocess
    p = subprocess.Popen([ldconfig, "-p"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = p.communicate()[0]

    libpath = re.search(pattern, data, re.MULTILINE)
    if libpath:
        libpath = libpath.group(1)
    return libpath

def find_lib(libname):
    #it would be better to rely on dlopen to find the paths
    #but I cannot find a way of getting ctypes to tell us the path
    #it found the library in
    assert os.name=="posix"
    libpaths = os.environ.get("LD_LIBRARY_PATH", "").split(":")
    libpaths.append("/usr/lib64")
    libpaths.append("/usr/lib")
    for libpath in libpaths:
        if not libpath or not os.path.exists(libpath):
            continue
        libname_so = os.path.join(libpath, libname)
        if os.path.exists(libname_so):
            return libname_so
    return None


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
