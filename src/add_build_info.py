#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import datetime
import subprocess
import getpass
import socket
import platform
import os.path
import re
import sys


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
    with open(filename, mode='w') as f:
        for name,value in props.items():
            s = str(value).replace("'", "\\'")
            f.write("%s='%s'\n" % (name, s))
    print("updated %s with:" % filename)
    for k in sorted(props.keys()):
        print("* %s = %s" % (str(k).ljust(20), props[k]))

def get_properties(filename):
    props = dict()
    if os.path.exists(filename):
        with open(filename, "rU") as f:
            for line in f:
                s = line.strip()
                if len(s)==0:
                    continue
                if s[0] in ('!', '#'):
                    continue
                parts = s.split("=", 1)
                name = parts[0]
                value = parts[1]
                if value[0]!="'" or value[-1]!="'":
                    continue
                props[name]= value[1:-1]
    return props


def get_cpuinfo():
    if platform.uname()[5]:
        return platform.uname()[5]
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", "rU") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(": ")[1].replace("\n", "").replace("\r", "")
    return "unknown"

def get_first_line_output(commands):
    for cmd, valid_exit_code in commands:
        try:
            proc = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
            stdout, _ = proc.communicate()
            if proc.returncode!=valid_exit_code:
                print("'%s' failed with return code %s" % (cmd, proc.returncode))
                continue
            if not stdout:
                print("could not get version information")
                continue
            out = stdout.decode('utf-8')
            return out.splitlines()[0]
        except:
            pass
    return  ""

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
            import wmi            #@UnresolvedImport
            c = wmi.WMI()
            for os in c.Win32_OperatingSystem():
                eq = os.Caption.find("=")
                if eq>0:
                    return (os.Caption[:eq]).strip()
                return os.Caption
        except:
            pass
        return "Microsoft Windows"
    if sys.platform.find("bsd")>=0:
        return "BSD"
    if sys.platform.find("linux")>=0 and hasattr(platform, "linux_distribution"):
        return "Linux %s" % (" ".join(platform.linux_distribution()))
    return sys.platform


BUILD_INFO_FILE = "./xpra/build_info.py"
def record_build_info(is_build=True):
    global BUILD_INFO_FILE
    props = get_properties(BUILD_INFO_FILE)
    if is_build:
        set_prop(props, "BUILT_BY", getpass.getuser())
        set_prop(props, "BUILT_ON", socket.gethostname())
        set_prop(props, "BUILD_DATE", datetime.date.today().isoformat())
        set_prop(props, "BUILD_TIME", datetime.datetime.now().strftime("%H:%M"))
        set_prop(props, "BUILD_CPU", get_cpuinfo())
        set_prop(props, "BUILD_BIT", platform.architecture()[0])
        set_prop(props, "BUILD_OS", get_platform_name())
        try:
            from Cython import __version__ as cython_version
        except:
            cython_version = "unknown"
        set_prop(props, "PYTHON_VERSION", sys.version_info[:3])
        set_prop(props, "CYTHON_VERSION", cython_version)
        set_prop(props, "COMPILER_VERSION", get_compiler_version())
        set_prop(props, "LINKER_VERSION", get_linker_version())
        set_prop(props, "RELEASE_BUILD", not bool(os.environ.get("BETA", "")))
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
