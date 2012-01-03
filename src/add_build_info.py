#!/usr/bin/env python

# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from datetime import date
import subprocess, sys
import getpass
import socket
import platform

def get_svn_props():
    props = {}
    #find revision:
    proc = subprocess.Popen("svnversion -n", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    (out, _) = proc.communicate()
    if not out:
        print("could not get version information")
        return  props
    pos = out.find(":")
    if pos>=0:
        out = out[pos+1:]
    rev_str = ""
    for c in out:
        if c in "0123456789":
            rev_str += c
    if not rev_str:
        print("could not parse version information from string: %s" % rev_str)
        return  props
        
    rev = int(rev_str)
    props["REVISION"] = rev
    #find number of local files modified:
    changes = 0
    proc = subprocess.Popen("svn status", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    (out, _) = proc.communicate()
    if not out:
        print("could not get status of local files")
        return  props
    
    for line in out.splitlines():
        if sys.platform.startswith("win") and line.find("\\wcw"):
            """ windows is easily confused, symlinks for example - ignore them """
            continue
        if line.startswith("M") and line.find("build_info.py")<0:
            changes += 1
            print("WARNING: found modified file: %s" % line)
    props["LOCAL_MODIFICATIONS"] = changes
    return props

def append_properties_to_file(props):
    #append to build_info.py:
    f = open("./xpra/build_info.py", 'a')
    for name,value in props.items():
        f.write("%s='%s'\n" % (name,value))
    f.close()
    print("updated build_info.py with %s" % props)

def main():
    props = {"BUILT_BY":getpass.getuser(),
            "BUILT_ON":socket.gethostname(),
            "BUILD_DATE":date.today().isoformat(),
            "BUILD_CPU":(platform.uname()[5] or "unknown"),
            "BUILD_BIT": platform.architecture()[0]
            }
    for k,v in get_svn_props().items():
        props[k] = v
    append_properties_to_file(props)

def append_svn_props():
    props = get_svn_props()
    append_properties_to_file(props)

if __name__ == "__main__":
    main()
