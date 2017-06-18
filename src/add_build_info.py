#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import datetime
import subprocess
import socket
import platform
import os.path
import re
import sys

def bytestostr(x):
    return str(x)
if sys.version > '3':
    unicode = str           #@ReservedAssignment
    def bytestostr(x):
        if type(x)==bytes:
            return x.decode("latin1")
        return str(x)


def update_properties(props, filename):
    eprops = get_properties(filename)
    for key,value in props.items():
        set_prop(eprops, key, value)
    save_properties(eprops, filename)

def save_properties(props, filename):
    if os.path.exists(filename):
        try:
            os.unlink(filename)
        except:
            print("WARNING: failed to delete %s" % filename)
    def u(v):
        try:
            v = v.decode()
        except:
            v = str(v)
        try:
            return v.encode("utf-8")
        except:
            return v
    with open(filename, mode='wb') as f:
        def w(v):
            f.write(u(v))
        for name in sorted(props.keys()):
            value = props[name]
            s = bytestostr(value).replace("'", "\\'")
            w(name)
            w("=")
            quote_it = type(value) not in (bool, tuple, int)
            if quote_it:
                w("'")
            w(s)
            if quote_it:
                w("'")
            w("\n")
    print("updated %s with:" % filename)
    for k in sorted(props.keys()):
        print("* %s = %s" % (str(k).ljust(20), bytestostr(props[k])))

def get_properties(filename):
    props = dict()
    if os.path.exists(filename):
        with open(filename, "rb") as f:
            for line in f:
                try:
                    s = line.decode("utf-8")
                except:
                    #str cannot be decoded!
                    s = str(line)
                s = s.strip()
                if len(s)==0:
                    continue
                if s[0] in ('!', '#'):
                    continue
                parts = s.split("=", 1)
                if len(parts)<2:
                    print("missing equal sign: %s" % s)
                    continue
                name = parts[0]
                value = parts[1]
                if value[0]!="'" or value[-1]!="'":
                    continue
                props[name]= value[1:-1]
    return props


def get_machineinfo():
    if platform.uname()[4]:
        return platform.uname()[4]
    return "unknown"

def get_cpuinfo():
    if platform.uname()[5]:
        return platform.uname()[5]
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", "rU") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(": ")[1].replace("\n", "").replace("\r", "")
    return "unknown"

def get_status_output(*args, **kwargs):
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.STDOUT
    try:
        p = subprocess.Popen(*args, **kwargs)
    except Exception as e:
        print("error running %s,%s: %s" % (args, kwargs, e))
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr

def get_output_lines(commands):
    for cmd, valid_exit_code in commands:
        try:
            returncode, stdout, stderr = get_status_output(cmd, stdin=None, shell=True)
            if returncode!=valid_exit_code:
                print("'%s' failed with return code %s" % (cmd, returncode))
                print("stderr: %s" % stderr)
                continue
            if not stdout:
                print("could not get version information")
                continue
            out = stdout.decode('utf-8')
            return out.splitlines()
        except:
            pass
    return  []

def get_first_line_output(commands):
    lines = get_output_lines(commands)
    if len(lines)>0:
        return lines[0]
    return  ""

def get_nvcc_version():
    options = []
    for p in ("/usr/local/cuda/bin", "/opt/cuda/bin", ""):
        nvcc = os.path.join(p, "nvcc")
        if p=="" or os.path.exists(nvcc):
            options.append(("%s --version" % (nvcc), 0))
    lines = get_output_lines(options)
    if len(lines)>0:
        vline = lines[-1]
        vpos = vline.rfind(", V")
        if vpos>0:
            return vline[vpos+3:]
    return None

def get_compiler_version():
    #FIXME: we assume we'll use GCC if it is on the path...
    test_options = [("gcc --version", 0)]
    if sys.platform.startswith("win"):
        test_options.append(("cl", 0))
        test_options.append((os.path.join(os.environ.get("VCINSTALLDIR", ""), "bin", "cl"), 0))
    return get_first_line_output(test_options)

def get_linker_version():
    #FIXME: we assume we'll use GCC if it is on the path...
    test_options = [("ld --version", 0)]
    if sys.platform.startswith("win"):
        test_options.append(("link", 1100))
        test_options.append((os.path.join(os.environ.get("VCINSTALLDIR", ""), "bin", "link"), 1100))
    return get_first_line_output(test_options)


def set_prop(props, key, value):
    if value is None:
        return
    if value!="unknown" or props.get(key) is None:
        props[key] = value

def get_platform_name():
    #better version info than standard python platform:
    if sys.platform.startswith("sun"):
        #couldn't find a better way to distinguish opensolaris from solaris...
        with open("/etc/release") as f:
            data = f.read()
        if data and str(data).lower().find("opensolaris"):
            return "OpenSolaris"
        return "Solaris"
    if sys.platform.find("darwin")>=0:
        try:
            #ie: Mac OS X 10.5.8
            return "Mac OS X %s" % platform.mac_ver()[0]
        except:
            return "Mac OS X"
    if sys.platform.find("openbsd")>=0:
        return "OpenBSD"
    if sys.platform.startswith("win"):
        #TODO: use something a bit faster:
        try:
            o = subprocess.Popen('systeminfo', stdout=subprocess.PIPE).communicate()[0]
            try:
                o = str(o, "latin-1")  # Python 3+
            except:
                pass
            return re.search("OS Name:\s*(.*)", o).group(1).strip()
        except:
            pass
        return "Microsoft Windows"
    if sys.platform.find("bsd")>=0:
        return "BSD"
    try:
        from xpra.os_util import get_linux_distribution
        ld = get_linux_distribution()
        if ld:
            return "Linux %s" % (" ".join(ld))
    except:
        pass
    return sys.platform


BUILD_INFO_FILE = "./xpra/build_info.py"
def record_build_info(is_build=True):
    global BUILD_INFO_FILE
    props = get_properties(BUILD_INFO_FILE)
    if is_build:
        try:
            import getpass
            set_prop(props, "BUILT_BY", getpass.getuser())
        except:
            set_prop(props, "BUILT_BY", os.environ.get("USER"))
        set_prop(props, "BUILT_ON", socket.gethostname())
        set_prop(props, "BUILD_DATE", datetime.date.today().isoformat())
        set_prop(props, "BUILD_TIME", datetime.datetime.now().strftime("%H:%M"))
        set_prop(props, "BUILD_MACHINE", get_machineinfo())
        set_prop(props, "BUILD_CPU", get_cpuinfo())
        set_prop(props, "BUILD_BIT", platform.architecture()[0])
        set_prop(props, "BUILD_OS", get_platform_name())
        try:
            from Cython import __version__ as cython_version
        except:
            cython_version = "unknown"
        set_prop(props, "PYTHON_VERSION", ".".join(str(x) for x in sys.version_info[:3]))
        set_prop(props, "CYTHON_VERSION", cython_version)
        set_prop(props, "COMPILER_VERSION", get_compiler_version())
        set_prop(props, "NVCC_VERSION", get_nvcc_version())
        set_prop(props, "LINKER_VERSION", get_linker_version())
        set_prop(props, "RELEASE_BUILD", not bool(os.environ.get("BETA", "")))
        #record pkg-config versions:
        PKG_CONFIG = os.environ.get("PKG_CONFIG", "pkg-config")
        for pkg in ("libc",
                    "vpx", "libvpx", "x264", "x265",
                    "avcodec", "avutil", "swscale",
                    "nvenc",
                    "x11", "xrandr", "xtst", "xfixes", "xkbfile", "xcomposite", "xdamage", "xext",
                    "gtk+-3.0", "pycairo", "pygobject-2.0", "pygtk-2.0", ):
            #fugly magic for turning the package atom into a legal variable name:
            pkg_name = pkg.lstrip("lib").replace("+", "").split("-")[0]
            cmd = [PKG_CONFIG, "--modversion", pkg]
            returncode, out, _ = get_status_output(cmd)
            if returncode==0:
                set_prop(props, "lib_"+pkg_name, out.decode().replace("\n", "").replace("\r", ""))

    save_properties(props, BUILD_INFO_FILE)


def load_ignored_changed_files():
    ignored = []
    with open("./ignored_changed_files.txt", "rU") as f:
        for line in f:
            s = line.strip()
            if len(s)==0:
                continue
            if s[0] in ('!', '#'):
                continue
            ignored.append(s)
    return ignored

def get_svn_props():
    props = {
                "REVISION" : "unknown",
                "LOCAL_MODIFICATIONS" : "unknown"
            }
    #find revision:
    proc = subprocess.Popen("svnversion -n ..", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    (out, _) = proc.communicate()
    if proc.returncode!=0:
        print("'svnversion -n' failed with return code %s" % proc.returncode)
        return  props
    if not out:
        print("could not get version information")
        return  props
    out = out.decode('utf-8')
    if out=="exported":
        print("svn repository information is missing ('exported')")
        return  props
    pos = out.find(":")
    if pos>=0:
        out = out[pos+1:]
    rev_str = ""
    for c in out:
        if c in "0123456789":
            rev_str += c
    if not rev_str:
        print("could not parse version information from string: %s (original version string: %s)" % (rev_str, out))
        return  props

    rev = int(rev_str)
    props["REVISION"] = rev
    #find number of local files modified:
    changes = 0
    proc = subprocess.Popen("svn status", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    (out, _) = proc.communicate()
    if proc.poll()!=0:
        print("could not get status of local files")
        return  props

    lines = out.decode('utf-8').splitlines()
    for line in lines:
        if not line.startswith("M"):
            continue
        parts = line.split(" ", 1)
        if len(parts)!=2:
            continue
        filename = parts[1].strip()
        ignore = False
        for x in load_ignored_changed_files():
            #use a normalized path ("/") that does not interfere with regexp:
            norm_path = filename.replace(os.path.sep, "/")
            if norm_path==x:
                print("'%s' matches ignore list entry: '%s' exactly, not counting it as a modified file" % (filename, x))
                ignore = True
                break
            rstr = r"^%s$" % x.replace("*", ".*")
            regexp = re.compile(rstr)
            if regexp.match(norm_path):
                print("'%s' matches ignore list regexp: '%s', not counting it as a modified file" % (filename, x))
                ignore = True
                break
        if ignore:
            continue
        changes += 1
        print("WARNING: found modified file: %s" % filename)
    props["LOCAL_MODIFICATIONS"] = changes
    return props

SRC_INFO_FILE = "./xpra/src_info.py"
def record_src_info():
    update_properties(get_svn_props(), SRC_INFO_FILE)

def has_src_info():
    return os.path.exists(SRC_INFO_FILE) and os.path.isfile(SRC_INFO_FILE)

def main():
    if not has_src_info():
        record_src_info()
    record_build_info(True)


if __name__ == "__main__":
    main()
