# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.platform.dotxpra_common import LIVE, DEAD, UNKNOWN, INACCESSIBLE, osexpand

PIPE_PREFIX = "Xpra\\"
PIPE_ROOT = "\\\\"
PIPE_PATH = "%s.\\pipe\\" % PIPE_ROOT


class DotXpra(object):
    def __init__(self, sockdir=None, sockdirs=[], actual_username="", *args, **kwargs):
        self.username = actual_username

    def osexpand(self, v):
        return osexpand(v, self.username)

    def mksockdir(self, d):
        #socket-dir is not used by the win32 shadow server
        pass

    def socket_path(self, local_display_name):
        return PIPE_PATH+PIPE_PREFIX+local_display_name.replace(":", "")

    LIVE = LIVE
    DEAD = DEAD
    UNKNOWN = UNKNOWN
    INACCESSIBLE = INACCESSIBLE

    def get_server_state(self, sockpath, timeout=5):
        return self.UNKNOWN

    def socket_paths(self, check_uid=0, matching_state=None, matching_display=None):
        return self.get_all_namedpipes().values()

    #this is imported by winswitch, so we can't change the method signature
    def sockets(self, check_uid=0, matching_state=None):
        #flatten the dictionnary into a list:
        return self.get_all_namedpipes().items()

    #find the matching sockets, and return:
    #(state, local_display, sockpath)
    def socket_details(self, check_uid=0, matching_state=None, matching_display=None):
        return {PIPE_PREFIX.rstrip("\\"): [(LIVE, display, pipe_name) for display, pipe_name in self.get_all_namedpipes().items()]}

    def get_all_namedpipes(self):
        from xpra.log import Logger
        log = Logger("network")
        xpra_pipes = {}
        for pipe_name in os.listdir(PIPE_PATH):
            if not pipe_name.startswith(PIPE_PREFIX):
                log("found non-xpra pipe: %s", pipe_name)
                continue
            name = pipe_name[len(PIPE_PREFIX):]
            #found an xpra pipe
            #FIXME: filter using matching_display?
            xpra_pipes[name] = pipe_name
        log("get_all_namedpipes()=%s", xpra_pipes)
        return xpra_pipes
