#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time

from xpra.server.pam import pam_session #@UnresolvedImport

def daemonize():
    os.chdir("/")
    if os.fork():
        os._exit(0)     #pylint: disable=protected-access
    os.setsid()
    if os.fork():
        os._exit(0)     #pylint: disable=protected-access

stdout = sys.stdout
stderr = sys.stderr
def log(message, *args):
    global stdout
    stdout.write("%s\n" % (message % (args)))

def main():
    if len(sys.argv) not in (2,3):
        print("invalid number of arguments")
        print("usage: %s uid [gid]" % sys.argv[0])
        return 1
    if os.getuid()!=0:
        print("must be execute as root!")
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

    log("username=%s", username)
    log("home=%s", home)
    log("XDG_RUNTIME_DIR=%s (exists=%s)", xrd, os.path.exists(xrd))
    daemonize()

    from xpra.os_util import FDChangeCaptureContext
    fdc = FDChangeCaptureContext()
    with fdc:
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
        env = pam.get_envlist()
    log("new fds: %s", fdc.get_new_fds())
    log("pam env: %s", env)
    log("XDG_RUNTIME_DIR=%s (exists=%s)", xrd, os.path.exists(xrd))

    logpath = "/tmp/test0.log"
    if os.path.exists(logpath):
        os.rename(logpath, logpath + ".old")
    logfd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.fchown(logfd, uid, gid)

    from xpra.server.server_util import redirect_std_to_log
    stdout, stderr = redirect_std_to_log(logfd, *fdc.get_new_fds())
    stdout.write("Entering daemon mode; "
                 + "any further errors will be reported to:\n"
                 + ("  %s\n" % logpath))
    sys.stdout.write("log file start 1")
    log("log file start 2")
    #close stdout / stderr
    stdout.close()
    stderr.close()
    #we should not be using stdout or stderr from this point:
    del stdout
    del stderr

    #setuid / setgid:
    os.initgroups(username, gid)
    import grp      #@UnresolvedImport
    groups = [gr.gr_gid for gr in grp.getgrall() if (username in gr.gr_mem)]
    os.setgroups(groups)
    os.setgid(gid)
    os.setuid(uid)
    print("done setuid / setgid")

    for _ in range(10):
        log("XDG_RUNTIME_DIR=%s (exists=%s)", xrd, os.path.exists(xrd))
        time.sleep(0.1)
    time.sleep(10)
    log("exit")


if __name__ == "__main__":
    r = main()
    sys.exit(r)
