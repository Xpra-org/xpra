# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
from typing import TypeAlias

from xpra.util.env import osexpand, envint
from xpra.log import Logger
from xpra.common import NotificationID

log = Logger("notify")

AUTO_DELETE_DELAY = envint("XPRA_AUTO_DELETE_DELAY", 60)

NID: TypeAlias = int | NotificationID


class NotifierBase:

    def __init__(self, closed_cb=None, action_cb=None):
        # posix only - but degrades ok on non-posix:
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        self.temp_files = {}
        self.closed_cb = closed_cb
        self.action_cb = action_cb
        self.handles_actions = False

    def cleanup(self) -> None:
        tf = self.temp_files
        if tf:
            self.temp_files = {}
            for nid in self.temp_files:
                self.clean_notification(nid)

    def show_notify(self, dbus_id, tray, nid: NID,
                    app_name: str, replaces_nid: NID, app_icon,
                    summary: str, body: str, actions, hints, timeout: int, icon) -> None:
        raise NotImplementedError()

    def get_icon_string(self, nid: NID, app_icon, icon) -> str:
        if app_icon and not os.path.isabs(app_icon):
            # safe to use
            return app_icon
        if not icon:
            return ""
        ext = icon[0]
        if ext in ("png", "webp", "jpeg"):
            icon_data = icon[3]
            from xpra.platform.paths import get_xpra_tmp_dir
            tmp = osexpand(get_xpra_tmp_dir())
            d = tmp
            missing = []
            while d and not os.path.exists(d):
                missing.append(d)
                d = os.path.dirname(d)
            for d in reversed(missing):
                os.mkdir(d, 0o700)
            temp = tempfile.NamedTemporaryFile(mode='w+b', suffix='.%s' % ext,
                                               prefix='xpra-notification-icon-', dir=tmp, delete=False)
            temp.write(icon_data)
            temp.close()
            self.temp_files[int(nid)] = temp.name
            if AUTO_DELETE_DELAY > 0:
                from xpra.os_util import gi_import
                GLib = gi_import("GLib")
                GLib.timeout_add(AUTO_DELETE_DELAY, self.clean_notification, nid)
            return temp.name
        return ""

    def clean_notification(self, nid: NID) -> None:
        temp_file = self.temp_files.pop(int(nid), "")
        log("clean_notification(%s) temp_file=%s", nid, temp_file)
        if temp_file:
            try:
                os.unlink(temp_file)
            except Exception as e:
                log("failed to remove temporary icon file '%s':", temp_file)
                log(" %s", e)

    def dbus_check(self, dbus_id) -> bool:
        if dbus_id and self.dbus_id == dbus_id:
            log.warn("remote dbus instance is the same as our local one")
            log.warn(" cannot forward notification to ourself as this would create a loop")
            log.warn(" disable notifications to avoid this warning")
            return False
        return True
