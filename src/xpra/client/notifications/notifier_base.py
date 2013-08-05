# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger()


class NotifierBase(object):

    def __init__(self):
        #posix only - but degrades ok on non-posix:
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=True):
        pass

    def close_notify(self, nid):
        pass

    def dbus_check(self, dbus_id):
        if self.dbus_id==dbus_id:
            log.error("remote dbus instance is the same as our local one, "
                      "cannot forward notification to ourself as this would create a loop")
            return  False
        return True
