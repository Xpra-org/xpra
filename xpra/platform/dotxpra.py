# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import glob
import socket
import errno
import stat

from xpra.os_util import get_util_logger, osexpand, umask_context
from xpra.platform.dotxpra_common import PREFIX, LIVE, DEAD, UNKNOWN, INACCESSIBLE
from xpra.platform import platform_import

DISPLAY_PREFIX = ":"


def norm_makepath(dirpath, name):
    if DISPLAY_PREFIX and name.startswith(DISPLAY_PREFIX):
        name = name[len(DISPLAY_PREFIX):]
    return os.path.join(dirpath, PREFIX + name)

def strip_display_prefix(s):
    if s.startswith(DISPLAY_PREFIX):
        return s[len(DISPLAY_PREFIX):]
    return s

def debug(msg, *args, **kwargs):
    log = get_util_logger()
    log(msg, *args, **kwargs)

def is_socket(sockpath, check_uid=None):
    try:
        s = os.stat(sockpath)
    except OSError as e:
        debug("is_socket(%s) path cannot be accessed: %s", sockpath, e)
        #socket cannot be accessed
        return False
    if not stat.S_ISSOCK(s.st_mode):
        return False
    if check_uid is not None:
        if s.st_uid!=check_uid:
            #socket uid does not match
            debug("is_socket(%s) uid %i does not match %s", sockpath, s.st_uid, check_uid)
            return False
    return True


class DotXpra:
    def __init__(self, sockdir=None, sockdirs=None, actual_username="", uid=0, gid=0):
        self.uid = uid or os.getuid()
        self.gid = gid or os.getgid()
        self.username = actual_username
        sockdirs = sockdirs or []
        if not sockdir:
            if sockdirs:
                sockdir = sockdirs[0]
            else:
                sockdir = "undefined"
        elif sockdir not in sockdirs:
            sockdirs.insert(0, sockdir)
        self._sockdir = self.osexpand(sockdir)
        self._sockdirs = [self.osexpand(x) for x in sockdirs]

    def osexpand(self, v):
        return osexpand(v, self.username, self.uid, self.gid)

    def __repr__(self):
        return "DotXpra(%s, %s - %i:%i - %s)" % (self._sockdir, self._sockdirs, self.uid, self.gid, self.username)

    def mksockdir(self, d, mode=0o700, uid=None, gid=None):
        if not d:
            return
        if not os.path.exists(d):
            if uid is None:
                uid = self.uid
            if gid is None:
                gid = self.gid
            parent = os.path.dirname(d)
            if parent and parent!="/" and not os.path.exists(parent):
                self.mksockdir(parent, mode, uid, gid)
            with umask_context(0):
                os.mkdir(d, mode)
            if uid!=os.getuid() or gid!=os.getgid():
                os.lchown(d, uid, gid)
        elif d!="/tmp":
            try:
                st_mode = os.stat(d).st_mode
                if st_mode&0o777!=mode:
                    log = get_util_logger()
                    log.warn("Warning: socket directory '%s'", d)
                    log.warn(" expected permissions %s but found %s", oct(mode), oct(st_mode&0o777))
            except OSError:
                get_util_logger().log("mksockdir%s", (d, mode, uid, gid), exc_info=True)

    def socket_expand(self, path):
        return osexpand(path, self.username, uid=self.uid, gid=self.gid)

    def norm_socket_paths(self, local_display_name):
        return [norm_makepath(x, local_display_name) for x in self._sockdirs]

    def socket_path(self, local_display_name):
        return norm_makepath(self._sockdir, local_display_name)

    LIVE = LIVE
    DEAD = DEAD
    UNKNOWN = UNKNOWN
    INACCESSIBLE = INACCESSIBLE

    def get_server_state(self, sockpath, timeout=5):
        if not os.path.exists(sockpath):
            return DotXpra.DEAD
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(timeout)
        try:
            sock.connect(sockpath)
            return DotXpra.LIVE
        except socket.error as e:
            debug("get_server_state: connect(%s)=%s (timeout=%s)", sockpath, e, timeout)
            err = e.args[0]
            if err==errno.EACCES:
                return DotXpra.INACCESSIBLE
            if err==errno.ECONNREFUSED:
                #could be the server is starting up
                debug("ECONNREFUSED")
                return DotXpra.UNKNOWN
            if err==errno.EWOULDBLOCK:
                debug("EWOULDBLOCK")
                return DotXpra.DEAD
            if err==errno.ENOENT:
                debug("ENOENT")
                return DotXpra.DEAD
            return self.UNKNOWN
        finally:
            try:
                sock.close()
            except IOError:
                debug("%s.close()", sock, exc_info=True)


    def displays(self, check_uid=None, matching_state=None):
        return list(set(v[1] for v in self.sockets(check_uid, matching_state)))

    def sockets(self, check_uid=None, matching_state=None):
        #flatten the dictionnary into a list:
        return list(set((v[0], v[1]) for details_values in
                        self.socket_details(check_uid, matching_state).values() for v in details_values))

    def socket_paths(self, check_uid=None, matching_state=None, matching_display=None):
        paths = []
        for details in self.socket_details(check_uid, matching_state, matching_display).values():
            for _, _, socket_path in details:
                paths.append(socket_path)
        return paths


    def _unique_sock_dirs(self):
        dirs = []
        if self._sockdir!="undefined":
            dirs.append(self._sockdir)
        dirs += [x for x in self._sockdirs if x not in dirs]
        seen = set()
        for d in dirs:
            if d in seen or not d:
                continue
            seen.add(d)
            real_dir = os.path.realpath(osexpand(d))
            if real_dir!=d:
                if real_dir in seen:
                    continue
                seen.add(real_dir)
            if not os.path.exists(real_dir):
                debug("socket_details: directory '%s' does not exist", real_dir)
                continue
            yield real_dir

    def get_display_state(self, display):
        state = None
        for d in self._unique_sock_dirs():
            #look for a 'socket' in the session directory
            #ie: /run/user/1000/xpra/10
            session_dir = os.path.join(d, strip_display_prefix(display))
            if os.path.exists(session_dir):
                #ie: /run/user/1000/xpra/10/socket
                sockpath = os.path.join(session_dir, "socket")
                if os.path.exists(sockpath):
                    state = self.is_socket_match(sockpath, None, (self.LIVE, self.UNKNOWN))
                    if state:
                        return state
            #when not using a session directory,
            #add the prefix to prevent clashes on NFS:
            #ie: "~/.xpra/HOSTNAME-10"
            sockpath = os.path.join(d, PREFIX+strip_display_prefix(display))
            state = self.is_socket_match(sockpath, None, (self.LIVE, self.UNKNOWN))
            if state:
                return state
        return state or self.DEAD

    #find the matching sockets, and return:
    #(state, local_display, sockpath) for each socket directory we probe
    def socket_details(self, check_uid=None, matching_state=None, matching_display=None):
        sd = {}
        debug("socket_details%s sockdir=%s, sockdirs=%s",
              (check_uid, matching_state, matching_display), self._sockdir, self._sockdirs)
        def add_result(d, item):
            results = sd.setdefault(d, [])
            if item not in results:
                results.append(item)
        def add_session_dir(session_dir, display):
            if not os.path.exists(session_dir):
                debug("add_session_dir%s path does not exist", (session_dir, display))
                return
            if not os.path.isdir(session_dir):
                debug("add_session_dir%s not a directory", (session_dir, display))
                return
            #ie: /run/user/1000/xpra/10/socket
            sockpath = os.path.join(session_dir, "socket")
            if os.path.exists(sockpath):
                state = self.is_socket_match(sockpath, None, matching_state)
                debug("add_session_dir(%s) state(%s)=%s", (session_dir, display), sockpath, state)
                if state:
                    local_display = DISPLAY_PREFIX+strip_display_prefix(display)
                    add_result(session_dir, (state, local_display, sockpath))
        for d in self._unique_sock_dirs():
            #if we know the display name,
            #we know the corresponding session dir:
            if matching_display:
                session_dir = os.path.join(d, strip_display_prefix(matching_display))
                add_session_dir(session_dir, matching_display)
            else:
                #find all the directories that could be session directories:
                for p in os.listdir(d):
                    try:
                        int(p)
                    except ValueError:
                        continue
                    session_dir = os.path.join(d, p)
                    add_session_dir(session_dir, p)
            #ie: "~/.xpra/HOSTNAME-"
            base = os.path.join(d, PREFIX)
            if matching_display:
                dstr = strip_display_prefix(matching_display)
            else:
                dstr = "*"
            potential_sockets = glob.glob(base + dstr)
            for sockpath in sorted(potential_sockets):
                state = self.is_socket_match(sockpath, check_uid, matching_state)
                if state:
                    local_display = DISPLAY_PREFIX+sockpath[len(base):]
                    add_result(d, (state, local_display, sockpath))
        return sd

    def is_socket_match(self, sockpath, check_uid=None, matching_state=None):
        if not is_socket(sockpath, check_uid):
            return None
        state = self.get_server_state(sockpath)
        if matching_state and state!=matching_state:
            debug("is_socket_match%s state '%s' does not match", (sockpath, check_uid, matching_state), state)
            return None
        return state


#win32 re-defines DotXpra for namedpipes:
platform_import(globals(), "dotxpra", False,
                "DotXpra",
                "DISPLAY_PREFIX",
                "norm_makepath")
