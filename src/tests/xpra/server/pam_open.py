#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time

from xpra.server.pam import pam_session #@UnresolvedImport

def daemonize():
    os.chdir("/")
    if os.fork():
        os._exit(0)
    os.setsid()
    if os.fork():
        os._exit(0)

def main():
    if len(sys.argv) not in (2,3):
        print("invalid number of arguments")
        print("usage: %s uid [gid]" % sys.argv[0])
        return 1
    uid = int(sys.argv[1])
    from pwd import getpwuid
    pw = getpwuid(uid)
    username = pw.pw_name
    home = pw.pw_dir
    if len(sys.argv)==3:
        gid = int(sys.argv[2])
    else:
        gid = pw.pw_gid
    xrd = os.path.join("/run/user", str(uid))

    print("username=%s" % username)
    print("home=%s" % home)
    print("XDG_RUNTIME_DIR=%s (exists=%s)" % (xrd, os.path.exists(xrd)))
    daemonize()
    
    pam = pam_session(service_name="xpra", uid=uid)
    pam.start()
    pam.set_env({
           #"XDG_SEAT"               : "seat1",
           #"XDG_VTNR"               : "0",
           "XDG_SESSION_TYPE"       : "x11",
           #"XDG_SESSION_CLASS"      : "user",
           "XDG_SESSION_DESKTOP"    : "xpra",
           })
    #import uuid
    #xauth_data = uuid.uuid4()
    #items = {
    #    "XAUTHDATA" : xauth_data,
    #    }
    #pam.set_items(items)
    if not pam.open():
        print("failed to open pam session!")
        return 1
    #env = pam.get_envlist()
    #print("pam env: %s" % env)
    for _ in range(10):
        print("XDG_RUNTIME_DIR=%s (exists=%s)" % (xrd, os.path.exists(xrd)))
        time.sleep(0.1)
    #start vfb?
    #log to file
    #close stdout / stderr

    #setuid / setgid:
    os.initgroups(username, gid)
    import grp      #@UnresolvedImport
    groups = [gr.gr_gid for gr in grp.getgrall() if (username in gr.gr_mem)]
    os.setgroups(groups)
    os.setgid(gid)
    os.setuid(uid)
    print("done setuid / setgid")
    for _ in range(10):
        print("XDG_RUNTIME_DIR=%s (exists=%s)" % (xrd, os.path.exists(xrd)))
        time.sleep(0.1)


if __name__ == "__main__":
    r = main()
    sys.exit(r)
