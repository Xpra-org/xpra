# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2018 Antoine Martin <antoine@xpra.org>
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


def norm_makepath(dirpath, name):
    if name[0]==":":
        name = name[1:]
    return os.path.join(dirpath, PREFIX + name)

def debug(msg, *args, **kwargs):
    log = get_util_logger()
    log(msg, *args, **kwargs)


class DotXpra(object):
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
        if d and not os.path.exists(d):
            if uid is None:
                uid = self.uid
            if gid is None:
                gid = self.gid
            with umask_context(0):
                os.mkdir(d, mode)
            if uid!=os.getuid() or gid!=os.getgid():
                os.lchown(d, uid, gid)

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


    def displays(self, check_uid=0, matching_state=None):
        return list(set(v[1] for v in self.sockets(check_uid, matching_state)))

    #this is imported by winswitch, so we can't change the method signature
    def sockets(self, check_uid=0, matching_state=None):
        #flatten the dictionnary into a list:
        return list(set((v[0], v[1]) for details_values in
                        self.socket_details(check_uid, matching_state).values() for v in details_values))

    def socket_paths(self, check_uid=0, matching_state=None, matching_display=None):
        paths = []
        for details in self.socket_details(check_uid, matching_state, matching_display).values():
            for _, _, socket_path in details:
                paths.append(socket_path)
        return paths

    def get_display_state(self, display):
        dirs = []
        if self._sockdir!="undefined":
            dirs.append(self._sockdir)
        dirs += [x for x in self._sockdirs if x not in dirs]
        debug("get_display_state(%s) sockdir=%s, sockdirs=%s, testing=%s",
              display, self._sockdir, self._sockdirs, dirs)
        seen = set()
        state = None
        for d in dirs:
            if not d or not os.path.exists(d):
                debug("get_display_state: '%s' path does not exist", d)
                continue
            real_dir = os.path.realpath(d)
            if real_dir in seen:
                continue
            seen.add(real_dir)
            #ie: "~/.xpra/HOSTNAME-"
            base = os.path.join(d, PREFIX)
            potential_sockets = glob.glob(base + display.lstrip(":"))
            for sockpath in sorted(potential_sockets):
                try:
                    s = os.stat(sockpath)
                except OSError as e:
                    debug("get_display_state: '%s' path cannot be accessed: %s", sockpath, e)
                    #socket cannot be accessed
                    continue
                if stat.S_ISSOCK(s.st_mode):
                    local_display = ":"+sockpath[len(base):]
                    if local_display!=display:
                        debug("get_display_state: '%s' display does not match (%s vs %s)",
                              sockpath, local_display, display)
                        continue
                    state = self.get_server_state(sockpath)
                    if state not in (self.DEAD, self.INACCESSIBLE):
                        return state
        return state or self.DEAD

    #find the matching sockets, and return:
    #(state, local_display, sockpath) for each socket directory we probe
    def socket_details(self, check_uid=0, matching_state=None, matching_display=None):
        import collections
        sd = collections.OrderedDict()
        dirs = []
        if self._sockdir!="undefined":
            dirs.append(self._sockdir)
        dirs += [x for x in self._sockdirs if x not in dirs]
        debug("socket_details%s sockdir=%s, sockdirs=%s, testing=%s",
              (check_uid, matching_state, matching_display), self._sockdir, self._sockdirs, dirs)
        seen = set()
        for d in dirs:
            if not d or not os.path.exists(d):
                debug("socket_details: '%s' path does not exist", d)
                continue
            real_dir = os.path.realpath(d)
            if real_dir in seen:
                continue
            seen.add(real_dir)
            #ie: "~/.xpra/HOSTNAME-"
            base = os.path.join(d, PREFIX)
            if matching_display:
                potential_sockets = glob.glob(base + matching_display.lstrip(":"))
            else:
                potential_sockets = glob.glob(base + "*")
            results = []
            for sockpath in sorted(potential_sockets):
                try:
                    s = os.stat(sockpath)
                except OSError as e:
                    debug("socket_details: '%s' path cannot be accessed: %s", sockpath, e)
                    #socket cannot be accessed
                    continue
                if stat.S_ISSOCK(s.st_mode):
                    if check_uid>0:
                        if s.st_uid!=check_uid:
                            #socket uid does not match
                            debug("socket_details: '%s' uid does not match (%s vs %s)", sockpath, s.st_uid, check_uid)
                            continue
                    state = self.get_server_state(sockpath)
                    if matching_state and state!=matching_state:
                        debug("socket_details: '%s' state does not match (%s vs %s)", sockpath, state, matching_state)
                        continue
                    local_display = ":"+sockpath[len(base):]
                    results.append((state, local_display, sockpath))
            if results:
                sd[d] = results
        return sd


#win32 re-defines DotXpra for namedpipes:
platform_import(globals(), "dotxpra", False,
                "DotXpra",
                "norm_makepath")
