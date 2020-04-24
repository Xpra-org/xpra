# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.version_util import version_compat_check
from xpra.os_util import bytestostr
from xpra.util import typedict, get_util_logger
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.exit_codes import EXIT_INCOMPATIBLE_VERSION


class ServerInfoMixin(StubClientMixin):

    def __init__(self):
        self._remote_machine_id = None
        self._remote_uuid = None
        self._remote_version = None
        self._remote_revision = None
        self._remote_modifications = 0
        self._remote_build_date = ""
        self._remote_build_time = ""
        self._remote_hostname = None
        self._remote_display = None
        self._remote_platform = None
        self._remote_platform_release = None
        self._remote_platform_platform = None
        self._remote_platform_linux_distribution = None
        self._remote_python_version = ""
        self._remote_lib_versions = {}
        self._remote_subcommands = ()

    def parse_server_capabilities(self, c : typedict) -> bool:
        self._remote_machine_id = c.strget("machine_id")
        self._remote_uuid = c.strget("uuid")
        self._remote_version = c.strget("build.version", c.strget("version"))
        self._remote_revision = c.strget("build.revision", c.strget("revision"))
        mods = c.rawget("build.local_modifications")
        if mods and str(mods).find("dfsg")>=0:
            get_util_logger().warn("Warning: the xpra server is running a buggy Debian version")
            get_util_logger().warn(" those are usually out of date and unstable")
        else:
            self._remote_modifications = c.intget("build.local_modifications", 0)
        self._remote_build_date = c.strget("build.date")
        self._remote_build_time = c.strget("build.time")
        self._remote_hostname = c.strget("hostname")
        self._remote_display = c.strget("display")
        self._remote_platform = c.strget("platform")
        self._remote_platform_release = c.strget("platform.release")
        self._remote_platform_platform = c.strget("platform.platform")
        self._remote_python_version = c.strget("python.version")
        self._remote_subcommands = c.strtupleget("subcommands")
        for x in ("glib", "gobject", "gtk", "gdk", "cairo", "pango", "sound.gst", "sound.pygst"):
            v = c.rawget("%s.version" % x, None)
            if v is not None:
                self._remote_lib_versions[x] = v
        #linux distribution is a tuple of different types, ie: ('Linux Fedora' , 20, 'Heisenbug')
        pld = c.tupleget("platform.linux_distribution")
        if pld and len(pld)==3:
            def san(v):
                if isinstance(v, int):
                    return v
                return bytestostr(v)
            self._remote_platform_linux_distribution = [san(x) for x in pld]
        verr = version_compat_check(self._remote_version)
        if verr is not None:
            self.warn_and_quit(EXIT_INCOMPATIBLE_VERSION,
                               "incompatible remote version '%s': %s" % (self._remote_version, verr))
            return False
        return True
