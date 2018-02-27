# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.version_util import version_compat_check
from xpra.os_util import bytestostr
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.exit_codes import EXIT_INCOMPATIBLE_VERSION


class ServerInfoMixin(StubClientMixin):

    def __init__(self):
        self._remote_machine_id = None
        self._remote_uuid = None
        self._remote_version = None
        self._remote_revision = None
        self._remote_platform = None
        self._remote_platform_release = None
        self._remote_platform_platform = None
        self._remote_platform_linux_distribution = None
        self.server_client_shutdown = True

    def parse_server_capabilities(self):
        c = self.server_capabilities
        self._remote_machine_id = c.strget("machine_id")
        self._remote_uuid = c.strget("uuid")
        self._remote_version = c.strget("build.version", c.strget("version"))
        self._remote_revision = c.strget("build.revision", c.strget("revision"))
        self._remote_platform = c.strget("platform")
        self._remote_platform_release = c.strget("platform.release")
        self._remote_platform_platform = c.strget("platform.platform")
        self.server_client_shutdown = c.boolget("client-shutdown", True)
        #linux distribution is a tuple of different types, ie: ('Linux Fedora' , 20, 'Heisenbug')
        pld = c.listget("platform.linux_distribution")
        if pld and len(pld)==3:
            def san(v):
                if type(v)==int:
                    return v
                return bytestostr(v)
            self._remote_platform_linux_distribution = [san(x) for x in pld]
        verr = version_compat_check(self._remote_version)
        if verr is not None:
            self.warn_and_quit(EXIT_INCOMPATIBLE_VERSION, "incompatible remote version '%s': %s" % (self._remote_version, verr))
            return False
        return True
