#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import sys
import signal
import uuid
import time
import struct
import binascii

#hide some ugly python3 compat:
try:
    import _thread as thread            #@UnresolvedImport @UnusedImport (python3)
except ImportError:
    import thread                       #@Reimport @UnusedImport
assert thread

try:
    from queue import Queue             #@UnresolvedImport @UnusedImport (python3)
except ImportError:
    from Queue import Queue             #@Reimport @UnusedImport
assert Queue

try:
    import builtins                     #@UnresolvedImport @UnusedImport (python3)
except ImportError:
    import __builtin__ as builtins      #@Reimport @UnusedImport
assert builtins
_buffer = builtins.__dict__.get("buffer")


SIGNAMES = {}
for signame in (sig for sig in dir(signal) if sig.startswith("SIG") and not sig.startswith("SIG_")):
    SIGNAMES[getattr(signal, signame)] = signame


WIN32 = sys.platform.startswith("win")
OSX = sys.platform.startswith("darwin")
LINUX = sys.platform.startswith("linux")
NETBSD = sys.platform.startswith("netbsd")
OPENBSD = sys.platform.startswith("openbsd")
FREEBSD  = sys.platform.startswith("freebsd")

POSIX = os.name=="posix"
PYTHON2 = sys.version_info[0]==2
PYTHON3 = sys.version_info[0]==3

BITS = struct.calcsize(b"P")*8


if PYTHON2:
    def strtobytes(x):
        return str(x)
    def bytestostr(x):
        return str(x)
    def hexstr(v):
        return binascii.hexlify(str(v))
else:
    def strtobytes(x):
        if isinstance(x, bytes):
            return x
        return str(x).encode("latin1")
    def bytestostr(x):
        if isinstance(x, bytes):
            return x.decode("latin1")
        return str(x)
    def hexstr(v):
        return bytestostr(binascii.hexlify(strtobytes(v)))


util_logger = None
def get_util_logger():
    global util_logger
    if not util_logger:
        from xpra.log import Logger
        util_logger = Logger("util")
    return util_logger

def memoryview_to_bytes(v):
    if isinstance(v, bytes):
        return v
    if isinstance(v, memoryview):
        return v.tobytes()
    if _buffer and isinstance(v, _buffer):
        return bytes(v)
    if isinstance(v, bytearray):
        return bytes(v)
    return strtobytes(v)


def setsid():
    #run in a new session
    if POSIX:
        os.setsid()


def getuid():
    if POSIX:
        return os.getuid()
    return 0

def getgid():
    if POSIX:
        return os.getgid()
    return 0

def get_shell_for_uid(uid):
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_shell
        except KeyError:
            pass
    return ""

def get_username_for_uid(uid):
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_name
        except KeyError:
            pass
    return ""

def get_home_for_uid(uid):
    if POSIX:
        from pwd import getpwuid
        try:
            return getpwuid(uid).pw_dir
        except KeyError:
            pass
    return ""

def get_groups(username):
    if POSIX:
        import grp      #@UnresolvedImport
        return [gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem]
    return []

def get_group_id(group):
    try:
        import grp      #@UnresolvedImport
        gr = grp.getgrnam(group)
        return gr.gr_gid
    except (ImportError, KeyError):
        return -1


def platform_release(release):
    if OSX:
        SYSTEMVERSION_PLIST = "/System/Library/CoreServices/SystemVersion.plist"
        try:
            import plistlib
            if PYTHON2:
                pl = plistlib.readPlist('/System/Library/CoreServices/SystemVersion.plist') #pylint: disable=deprecated-method
            else:
                with open(SYSTEMVERSION_PLIST, "rb") as f:
                    pl = plistlib.load(f)           #@UndefinedVariable
            return pl['ProductUserVisibleVersion']
        except Exception as e:
            get_util_logger().debug("platform_release(%s)", release, exc_info=True)
            get_util_logger().warn("Warning: failed to get release information")
            get_util_logger().warn(" from '%s':", SYSTEMVERSION_PLIST)
            get_util_logger().warn(" %s", e)
    return release


def platform_name(sys_platform, release=None):
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
        if isinstance(release, (tuple, list)):
            values += list(release)
        else:
            values.append(release)
        return " ".join([str(x) for x in values if x])
    for k,v in PLATFORMS.items():
        regexp = re.compile(k)
        if regexp.match(sys_platform):
            return rel(v)
    return rel(sys_platform)


def get_rand_chars(l=16, chars=b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    import random
    return b"".join(chars[random.randint(0, len(chars)-1):][:1] for _ in range(l))

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
    if POSIX:
        for filename in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            v = load_binary_file(filename)
            if v is not None:
                break
    elif WIN32:
        v = uuid.getnode()
    return bytestostr(v).strip("\n\r")

def get_user_uuid():
    """
        Try to generate a uuid string which is unique to this user.
        (relies on get_machine_id to uniquely identify a machine)
    """
    user_uuid = os.environ.get("XPRA_USER_UUID")
    if user_uuid:
        return user_uuid
    import hashlib
    u = hashlib.sha1()
    def uupdate(ustr):
        u.update(ustr.encode("utf-8"))
    uupdate(get_machine_id())
    if POSIX:
        uupdate(u"/")
        uupdate(str(os.getuid()))
        uupdate(u"/")
        uupdate(str(os.getgid()))
    uupdate(os.path.expanduser("~/"))
    return u.hexdigest()


try:
    from xpra.monotonic_time import _monotonic_time     #@UnresolvedImport
    assert _monotonic_time()>0
    monotonic_time = _monotonic_time
except (ImportError, AssertionError):
    monotonic_time = time.time


def is_X11():
    if OSX or WIN32:
        return False
    if PYTHON2:
        return True
    try:
        from xpra.x11.gtk3.gdk_bindings import is_X11_Display   #@UnresolvedImport
        return is_X11_Display()
    except ImportError:
        get_util_logger().debug("failed to load x11 bindings", exc_info=True)
        return True

saved_env = os.environ.copy()
def is_Wayland():
    return _is_Wayland(saved_env)

def _is_Wayland(env):
    backend = env.get("GDK_BACKEND", "")
    if backend=="wayland":
        return True
    return backend!="x11" and (
        bool(env.get("WAYLAND_DISPLAY")) or env.get("XDG_SESSION_TYPE")=="wayland"
        )


def is_distribution_variant(variant=b"Debian"):
    if not POSIX:
        return False
    try:
        v = load_os_release_file()
        return any(l.find(variant)>=0 for l in v.splitlines() if l.startswith(b"NAME="))
    except Exception:
        pass
    try:
        if variant==b"RedHat" and get_linux_distribution()[0].startswith(variant):
            return True
        if get_linux_distribution()[0]==variant:
            return True
    except Exception:
        pass
    return False

def get_distribution_version_id():
    if not POSIX:
        return ""
    try:
        v = load_os_release_file()
        for l in v.splitlines():
            if l.startswith(b"VERSION_ID="):
                return l.split(b"=", 1)[1]
    except Exception:
        pass
    return ""

os_release_file_data = False
def load_os_release_file():
    global os_release_file_data
    if os_release_file_data is False:
        try:
            os_release_file_data = load_binary_file("/etc/os-release")
        except (OSError, IOError):
            os_release_file_data = None
    return os_release_file_data

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
            out = p.communicate()[0]
            assert p.returncode==0 and out
        except Exception:
            try:
                from xpra.scripts.config import python_platform
                _linux_distribution = python_platform.linux_distribution()
            except Exception:
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
            return tuple(int(x) for x in ur.split("."))  #ie: (12, 4)
        except ValueError:
            pass
    return ()

def is_unity():
    d = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return d.find("unity")>=0 or d.find("ubuntu")>=0

def is_gnome():
    if os.environ.get("XDG_SESSION_DESKTOP", "").split("-", 1)[0] in ("i3", "ubuntu", ):
        #"i3-gnome" is not really gnome... ie: the systray does work!
        return False
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("gnome")>=0

def is_kde():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("kde")>=0


def is_WSL():
    if not POSIX:
        return False
    r = None
    for f in ("/proc/sys/kernel/osrelease", "/proc/version"):
        r = load_binary_file(f)
        if r:
            break
    return r is not None and r.find(b"Microsoft")>=0


def get_generic_os_name():
    for k,v in {
            "linux"     : "linux",
            "darwin"    : "osx",
            "win"       : "win32",
            "freebsd"   : "freebsd",
            }.items():
        if sys.platform.startswith(k):
            return v
    return sys.platform

def get_cpu_count():
    #sensible default:
    cpus = 2
    try:
        try:
            #python3:
            cpus = os.cpu_count()
        except AttributeError:
            try:
                from cpuinfo import get_cpu_info
                cpus = int(get_cpu_info().get("count"))
            except Exception:
                #python2:
                import multiprocessing
                cpus = multiprocessing.cpu_count()
    except Exception:
        pass
    return cpus


def filedata_nocrlf(filename):
    v = load_binary_file(filename)
    if v is None:
        get_util_logger().error("failed to load '%s'", filename)
        return None
    return v.strip(b"\n\r")

def load_binary_file(filename):
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "rb") as f:
            return f.read()
    except Exception as e:
        get_util_logger().warn("Warning: failed to load '%s':", filename)
        get_util_logger().warn(" %s", e)
        return None

#here so we can override it when needed
def force_quit(status=1):
    os._exit(status)  #pylint: disable=protected-access


def register_SIGUSR_signals(idle_add):
    if not os.name=="posix":
        return
    from xpra.util import dump_all_frames, dump_gc_frames
    def sigusr1(*_args):
        log = get_util_logger().info
        log("SIGUSR1")
        idle_add(dump_all_frames, log)
    def sigusr2(*_args):
        log = get_util_logger().info
        log("SIGUSR2")
        idle_add(dump_gc_frames, log)
    signal.signal(signal.SIGUSR1, sigusr1)
    signal.signal(signal.SIGUSR2, sigusr2)


def livefds():
    live = set()
    try:
        MAXFD = os.sysconf("SC_OPEN_MAX")
    except ValueError:
        MAXFD = 256
    for fd in range(0, MAXFD):
        try:
            s = os.fstat(fd)
        except Exception:
            continue
        else:
            if s:
                live.add(fd)
    return live

def close_fds(excluding=(0, 1, 2)):
    try:
        MAXFD = os.sysconf("SC_OPEN_MAX")
    except ValueError:
        MAXFD = 256
    for i in range(0, MAXFD):
        if i not in excluding:
            try:
                os.close(i)
            except (IOError, OSError):
                pass

def get_all_fds():
    fd_dirs = ["/dev/fd", "/proc/self/fd"]
    fds = []
    for fd_dir in fd_dirs:
        if os.path.exists(fd_dir):
            for fd_str in os.listdir(fd_dir):
                try:
                    fd = int(fd_str)
                    fds.append(fd)
                except OSError:
                    # This exception happens inevitably, because the fd used
                    # by listdir() is already closed.
                    pass
            return fds
    sys.stderr.write("Uh-oh, can't close fds, please port me to your system...\n")
    return fds

def close_all_fds(exceptions=()):
    for fd in get_all_fds():
        try:
            if fd not in exceptions:
                os.close(fd)
        except OSError:
            # This exception happens inevitably, because the fd used
            # by listdir() is already closed.
            pass

def use_tty():
    from xpra.util import envbool
    if envbool("XPRA_NOTTY", False):
        return False
    from xpra.platform.gui import use_stdin
    return use_stdin()


def shellsub(s, subs=None):
    """ shell style string substitution using the dictionary given """
    if subs:
        for var,value in subs.items():
            s = s.replace("$%s" % var, str(value))
            s = s.replace("${%s}" % var, str(value))
    return s


def osexpand(s, actual_username="", uid=0, gid=0, subs=None):
    def expanduser(s):
        if actual_username and s.startswith("~/"):
            #replace "~/" with "~$actual_username/"
            return os.path.expanduser("~%s/%s" % (actual_username, s[2:]))
        return os.path.expanduser(s)
    from collections import OrderedDict
    d = OrderedDict(subs or {})
    d.update({
        "PID"   : os.getpid(),
        "HOME"  : expanduser("~/"),
        })
    if os.name=="posix":
        d.update({
            "UID"   : uid or os.geteuid(),
            "GID"   : gid or os.getegid(),
            })
        if not OSX:
            from xpra.platform.xposix.paths import get_runtime_dir
            d["XDG_RUNTIME_DIR"] = os.environ.get("XDG_RUNTIME_DIR", get_runtime_dir())
    if actual_username:
        d["USERNAME"] = actual_username
        d["USER"] = actual_username
    #first, expand the substitutions themselves,
    #as they may contain references to other variables:
    ssub = OrderedDict()
    for k,v in d.items():
        ssub[k] = expanduser(shellsub(str(v), d))
    return os.path.expandvars(expanduser(shellsub(expanduser(s), ssub)))


def path_permission_info(filename, ftype=None):
    if not POSIX:
        return []
    info = []
    try:
        import stat
        stat_info = os.stat(filename)
        if not ftype:
            ftype = "file"
            if os.path.isdir(filename):
                ftype = "directory"
        info.append("permissions on %s %s: %s" % (ftype, filename, oct(stat.S_IMODE(stat_info.st_mode))))
        import pwd
        import grp      #@UnresolvedImport
        user = pwd.getpwuid(stat_info.st_uid)[0]
        group = grp.getgrgid(stat_info.st_gid)[0]
        info.append("ownership %s:%s" % (user, group))
    except Exception as e:
        info.append("failed to query path information for '%s': %s" % (filename, e))
    return info


#code to temporarily redirect stderr and restore it afterwards, adapted from:
#http://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python
#used by the sound code to get rid of the stupid gst warning below:
#"** Message: pygobject_register_sinkfunc is deprecated (GstObject)"
#ideally we would redirect to a buffer so we could still capture and show these messages in debug out
class HideStdErr(object):

    def __init__(self, *_args):
        self.savedstderr = None

    def __enter__(self):
        if POSIX and os.getppid()==1:
            #this interferes with server daemonizing?
            return
        sys.stderr.flush() # <--- important when redirecting to files
        self.savedstderr = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        sys.stderr = os.fdopen(self.savedstderr, 'w')

    def __exit__(self, *_args):
        if self.savedstderr is not None:
            os.dup2(self.savedstderr, 2)

class HideSysArgv(object):

    def __init__(self, *_args):
        self.savedsysargv = None

    def __enter__(self):
        self.savedsysargv = sys.argv
        sys.argv = sys.argv[:1]

    def __exit__(self, *_args):
        if self.savedsysargv is not None:
            sys.argv = self.savedsysargv


class OSEnvContext(object):

    def __init__(self):
        self.env = os.environ.copy()
    def __enter__(self):
        pass
    def __exit__(self, *_args):
        os.environ.clear()
        os.environ.update(self.env)
    def __repr__(self):
        return "OSEnvContext"


class FDChangeCaptureContext(object):

    def __init__(self):
        self.enter_fds = []
        self.exit_fds = []
    def __enter__(self):
        self.enter_fds = get_all_fds()
    def __exit__(self, *_args):
        self.exit_fds = get_all_fds()
    def __repr__(self):
        return "FDChangeCaptureContext"
    def get_new_fds(self):
        return sorted(tuple(set(self.exit_fds)-set(self.enter_fds)))
    def get_lost_fds(self):
        return sorted(tuple(set(self.enter_fds)-set(self.exit_fds)))

class DummyContextManager(object):

    def __enter__(self):
        pass
    def __exit__(self, *_args):
        pass
    def __repr__(self):
        return "DummyContextManager"


#workaround incompatibility between paramiko and gssapi:
class nomodule_context(object):

    def __init__(self, module_name):
        self.module_name = module_name
    def __enter__(self):
        self.saved_module = sys.modules.get(self.module_name)
        sys.modules[self.module_name] = None
    def __exit__(self, *_args):
        if sys.modules.get(self.module_name) is None:
            if self.saved_module is None:
                try:
                    del sys.modules[self.module_name]
                except KeyError:
                    pass
            else:
                sys.modules[self.module_name] = self.saved_module
    def __repr__(self):
        return "nomodule_context(%s)" % self.module_name

class umask_context(object):

    def __init__(self, umask):
        self.umask = umask
    def __enter__(self):
        self.orig_umask = os.umask(self.umask)
    def __exit__(self, *_args):
        os.umask(self.orig_umask)
    def __repr__(self):
        return "umask_context(%s)" % self.umask


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
            msvcrt.setmode(fd, os.O_BINARY)         #@UndefinedVariable pylint: disable=no-member
        except (OSError, IOError):
            get_util_logger().error("setting stdin to binary mode failed", exc_info=True)

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
    p = subprocess.Popen([ldconfig, "-p"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    data = bytestostr(p.communicate()[0])

    libpath = re.search(pattern, data, re.MULTILINE)        #@UndefinedVariable
    if libpath:
        libpath = libpath.group(1)
    return libpath

def find_lib(libname):
    #it would be better to rely on dlopen to find the paths
    #but I cannot find a way of getting ctypes to tell us the path
    #it found the library in
    assert POSIX
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
    try:
        return find_executable(command)
    except Exception:
        get_util_logger().debug("find_executable(%s)", command, exc_info=True)
        return None

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
    if not POSIX:
        return False
    d = load_binary_file("/proc/1/cmdline")
    return d and d.find(b"/systemd")>=0


def get_ssh_port():
    #FIXME: how do we find out which port ssh is on?
    if WIN32:
        return 0
    return 22


def setuidgid(uid, gid):
    if not POSIX:
        return
    log = get_util_logger()
    if os.getuid()!=uid or os.getgid()!=gid:
        #find the username for the given uid:
        from pwd import getpwuid
        try:
            username = getpwuid(uid).pw_name
        except KeyError:
            raise Exception("uid %i not found" % uid)
        #set the groups:
        if hasattr(os, "initgroups"):   # python >= 2.7
            os.initgroups(username, gid)
        else:
            import grp      #@UnresolvedImport
            groups = [gr.gr_gid for gr in grp.getgrall() if username in gr.gr_mem]
            os.setgroups(groups)
    #change uid and gid:
    try:
        if os.getgid()!=gid:
            os.setgid(gid)
    except OSError as e:
        log.error("Error: cannot change gid to %i:", gid)
        if os.getgid()==0:
            #don't run as root!
            raise
        log.error(" %s", e)
        log.error(" continuing with gid=%i", os.getgid())
    try:
        if os.getuid()!=uid:
            os.setuid(uid)
    except OSError as e:
        log.error("Error: cannot change uid to %i:", uid)
        if os.getuid()==0:
            #don't run as root!
            raise
        log.error(" %s", e)
        log.error(" continuing with uid=%i", os.getuid())
    log("new uid=%s, gid=%s", os.getuid(), os.getgid())

def get_peercred(sock):
    if LINUX:
        SO_PEERCRED = 17
        log = get_util_logger()
        try:
            import socket
            creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize(b'3i'))
            pid, uid, gid = struct.unpack(b'3i',creds)
            log("peer: %s", (pid, uid, gid))
            return pid, uid, gid
        except IOError as  e:
            log("getsockopt", exc_info=True)
            log.error("Error getting peer credentials: %s", e)
            return None
    elif FREEBSD:
        #TODO: use getpeereid
        #then pwd to get the gid?
        pass
    return None


def main():
    sp = sys.platform
    log = get_util_logger()
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
