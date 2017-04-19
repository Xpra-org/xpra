#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import sys
import signal
import uuid
import time

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


WIN32 = sys.platform.startswith("win")
OSX = sys.platform.startswith("darwin")
LINUX = sys.platform.startswith("linux")


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
    if isinstance(v, memoryview):
        return v.tobytes()
    if _buffer and isinstance(v, _buffer):
        return bytes(v)
    if isinstance(v, bytearray):
        return bytes(v)
    return v


def setsid():
    #run in a new session
    if os.name=="posix":
        os.setsid()


def getuid():
    if os.name=="posix":
        return os.getuid()
    return 0

def getgid():
    if os.name=="posix":
        return os.getgid()
    return 0

def get_username_for_uid(uid):
    if os.name=="posix":
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_name
        except KeyError:
            pass
    return ""

def get_groups(username):
    if os.name=="posix":
        import grp      #@UnresolvedImport
        return [gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem]
    return []

def get_group_id(group):
    try:
        import grp      #@UnresolvedImport
        gr = grp.getgrnam(group)
        return gr.gr_gid
    except:
        return -1


def platform_release(release):
    if OSX:
        try:
            import plistlib
            pl = plistlib.readPlist('/System/Library/CoreServices/SystemVersion.plist')
            return pl['ProductUserVisibleVersion']
        except:
            pass
    return release

def platform_name(sys_platform, release):
    if not sys_platform:
        return "unknown"
    PLATFORMS = {"win32"    : "Microsoft Windows",
                 "cygwin"   : "Windows/Cygwin",
                 "linux.*"  : "Linux",
                 "darwin"   : "Mac OS X",
                 "freebsd.*": "FreeBSD",
                 "os2"      : "OS/2",
                 }
    def rel(v):
        values = [v]
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


monotonic_time = time.time
try:
    from xpra.monotonic_time import _monotonic_time     #@UnresolvedImport
    assert _monotonic_time()>0
    monotonic_time = _monotonic_time
except Exception as e:
    pass

def is_distribution_variant(variant=b"Debian", os_file="/etc/os-release"):
    if os.name!="posix":
        return False
    try:
        if get_linux_distribution()[0]==variant:
            return True
    except:
        pass
    try:
        v = load_binary_file(os_file)
        return any(l.find(variant)>=0 for l in v.splitlines() if l.startswith("NAME="))
    except:
        return False

def is_Ubuntu():
    return is_distribution_variant(b"Ubuntu")

def is_Debian():
    return is_distribution_variant(b"Debian")

def is_Raspbian():
    return is_distribution_variant(b"Raspbian")

def is_Fedora():
    return is_distribution_variant(b"Fedora")

def is_Arch():
    return is_distribution_variant(b"Arch")

def is_CentOS():
    return is_distribution_variant(b"CentOS")

def is_RedHat():
    return is_distribution_variant(b"RedHat")


_linux_distribution = None
def get_linux_distribution():
    global _linux_distribution
    if LINUX and not _linux_distribution:
        #linux_distribution is deprecated in Python 3.5 and it causes warnings,
        #so use our own code first:
        import subprocess
        cmd = ["lsb_release", "-a"]
        try:
            p = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = p.communicate()
            assert p.returncode==0 and out
        except:
            try:
                from xpra.scripts.config import python_platform
                _linux_distribution = python_platform.linux_distribution()
            except:
                _linux_distribution = ("unknown", "unknown", "unknown")
        else:
            d = {}
            for line in strtobytes(out).splitlines():
                line = bytestostr(line)
                parts = line.rstrip("\n\r").split(":", 1)
                if len(parts)==2:
                    d[parts[0].lower().replace(" ", "_")] = parts[1].strip()
            v = [d.get(x) for x in ("distributor_id", "release", "codename")]
            if None not in v:
                return tuple([bytestostr(x) for x in v])
    return _linux_distribution

def getUbuntuVersion():
    distro = get_linux_distribution()
    if distro and len(distro)==3 and distro[0]=="Ubuntu":
        ur = distro[1]  #ie: "12.04"
        try:
            rnum = [int(x) for x in ur.split(".")]  #ie: [12, 4]
            return rnum
        except:
            pass
    return []

def is_unity():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower().startswith("unity")


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


class OSEnvContext(object):

    def __init__(self):
        self.env = os.environ.copy()
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_val, exc_tb):
        os.environ.clear()
        os.environ.update(self.env)
    def __repr__(self):
        return "OSEnvContext"


def disable_stdout_buffering():
    import gc
    # Appending to gc.garbage is a way to stop an object from being
    # destroyed.  If the old sys.stdout is ever collected, it will
    # close() stdout, which is not good.
    gc.garbage.append(sys.stdout)
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

def setbinarymode(fd):
    if WIN32:
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


def pollwait(process, timeout=5):
    start = monotonic_time()
    while monotonic_time()-start<timeout:
        v = process.poll()
        if v is not None:
            return v
        time.sleep(0.1)
    return None

def which(command):
    from distutils.spawn import find_executable
    return find_executable(command)

def get_status_output(*args, **kwargs):
    import subprocess
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    try:
        p = subprocess.Popen(*args, **kwargs)
    except Exception as e:
        print("error running %s,%s: %s" % (args, kwargs, e))
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")


def is_systemd_pid1():
    if not os.name=="posix":
        return False
    d = load_binary_file("/proc/1/cmdline")
    return d and d.find(b"/systemd")>=0

def main():
    from xpra.log import Logger
    log = Logger("util")
    sp = sys.platform
    log.info("platform_name(%s)=%s", sp, platform_name(sp, ""))
    if LINUX:
        log.info("linux_distribution=%s", get_linux_distribution())
        log.info("Ubuntu=%s", is_Ubuntu())
        if is_Ubuntu():
            log.info("Ubuntu version=%s", getUbuntuVersion())
        log.info("Unity=%s", is_unity())
        log.info("Fedora=%s", is_Fedora())
        log.info("systemd=%s", is_systemd_pid1())
    log.info("get_machine_id()=%s", get_machine_id())
    log.info("get_user_uuid()=%s", get_user_uuid())
    log.info("get_hex_uuid()=%s", get_hex_uuid())
    log.info("get_int_uuid()=%s", get_int_uuid())


if __name__ == "__main__":
    main()
