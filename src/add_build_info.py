#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=bare-except

import datetime
import subprocess
import socket
import platform
import os.path
import re
import sys


def bytestostr(x):
    if isinstance(x, bytes):
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
        except OSError:
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
            quote_it = not isinstance(value, (bool, tuple, int))
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
                except UnicodeDecodeError:
                    #str cannot be decoded!
                    s = str(line)
                s = s.strip()
                if not s:
                    continue
                if s[0] in ('!', '#'):
                    continue
                parts = s.split("=", 1)
                if len(parts)<2:
                    print("missing equal sign: %s" % s)
                    continue
                name = parts[0]
                value = parts[1]
                if not value:
                    continue
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

def get_output_lines(cmd, valid_exit_code=0):
    try:
        returncode, stdout, stderr = get_status_output(cmd, shell=True)
        if returncode!=valid_exit_code:
            print("'%s' failed with return code %s" % (cmd, returncode))
            print("stderr: %s" % stderr)
            return ()
        if not stdout:
            print("could not get output from command '%s'" % (cmd,))
            return ()
        out = stdout.decode('utf-8')
        return out.splitlines()
    except Exception as e:
        print("error running '%s': %s" % (cmd, e))
    return  ()

def get_first_line_output(cmd, valid_exit_code=0):
    lines = get_output_lines(cmd, valid_exit_code)
    if lines:
        return lines[0]
    return  ""

def get_nvcc_version():
    for p in ("/usr/local/cuda/bin", "/opt/cuda/bin", ""):
        nvcc = os.path.join(p, "nvcc")
        if p=="" or os.path.exists(nvcc):
            cmd = "%s --version" % (nvcc)
            lines = get_output_lines(cmd)
            if lines:
                vline = lines[-1]
                vpos = vline.rfind(", V")
                if vpos>0:
                    return vline[vpos+3:]
    return None

def get_compiler_version():
    cc_version = "%s --version" % os.environ.get("CC", "gcc")
    if sys.platform=="darwin":
        lines = get_output_lines(cc_version)
        for line in lines:
            if line.startswith("Apple"):
                return line
        return None
    return get_first_line_output(cc_version)

def get_linker_version():
    if sys.platform=="darwin":
        ld_version = "%s -v" % os.environ.get("LD", "ld")
        lines = get_output_lines(ld_version)
        for line in lines:
            if line.find("using: ")>0:
                return line.split("using: ", 1)[1]
        return None
    ld_version = "%s --version" % os.environ.get("LD", "ld")
    return get_first_line_output(ld_version)


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
        try:
            o = subprocess.Popen('systeminfo', stdout=subprocess.PIPE).communicate()[0]
            try:
                o = str(o, "latin-1")  # Python 3+
            except:
                pass
            return re.search(r"OS Name:\s*(.*)", o).group(1).strip()
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
        source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
        if source_epoch:
            #reproducible builds:
            build_time = datetime.datetime.utcfromtimestamp(int(source_epoch))
            build_date = build_time.date()
        else:
            #win32, macos and older build environments:
            build_time = datetime.datetime.now()
            build_date = datetime.date.today()
            #also record username and hostname:
            try:
                import getpass
                set_prop(props, "BUILT_BY", getpass.getuser())
            except:
                set_prop(props, "BUILT_BY", os.environ.get("USER"))
            set_prop(props, "BUILT_ON", socket.gethostname())
        set_prop(props, "BUILD_DATE", build_date.isoformat())
        set_prop(props, "BUILD_TIME", build_time.strftime("%H:%M"))
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
                    "vpx", "vpx", "x264", "x265", "webp", "yuv", "nvenc", "nvfbc",
                    "avcodec", "avutil", "swscale",
                    "nvenc",
                    "x11", "xrandr", "xtst", "xfixes", "xkbfile", "xcomposite", "xdamage", "xext",
                    "gobject-introspection-1.0",
                    "gtk+-3.0", "py3cairo", "pygobject-3.0", "gtk+-x11-3.0",
                    "python3",
                    ):
            #fugly magic for turning the package atom into a legal variable name:
            pkg_name = pkg.lstrip("lib").replace("+", "").replace("-", "_")
            if pkg_name.split("_")[-1].rstrip("0123456789.")=="":
                pkg_name = "_".join(pkg_name.split("_")[:-1])
            cmd = [PKG_CONFIG, "--modversion", pkg]
            returncode, out, _ = get_status_output(cmd)
            if returncode==0:
                set_prop(props, "lib_"+pkg_name, out.decode().replace("\n", "").replace("\r", ""))

    save_properties(props, BUILD_INFO_FILE)


def get_svn_props(warn=True):
    props = {
                "REVISION" : "unknown",
                "LOCAL_MODIFICATIONS" : "unknown"
            }
    #find revision:
    proc = subprocess.Popen("svnversion -n ..", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
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
    proc = subprocess.Popen("svn status", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
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
        changes += 1
        if warn:
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
