# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("server")


from xpra.util import std
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.os_util import platform_name


"""
Store information about the client.
"""
class ClientInfoMixin(StubSourceMixin):

    def __init__(self):
        self.init_vars()

    def cleanup(self):
        self.init_vars()

    def init_vars(self):
        self.uuid = ""
        self.machine_id = ""
        self.hostname = ""
        self.username = ""
        self.name = ""
        self.argv = ()
        # client capabilities/options:
        self.client_setting_change = False
        self.client_type = None
        self.client_version = None
        self.client_revision= None
        self.client_bits = 0
        self.client_platform = None
        self.client_machine = None
        self.client_processor = None
        self.client_release = None
        self.client_linux_distribution = None
        self.client_proxy = False
        self.client_wm_name = None
        self.client_session_type = None
        self.client_session_type_full = None
        self.client_connection_data = {}
        self.proxy_hostname = None
        self.proxy_platform = None
        self.proxy_release = None
        self.proxy_version = None
        self.proxy_version = None
        
    def parse_client_caps(self, c):
        self.uuid = c.strget("uuid")
        self.machine_id = c.strget("machine_id")
        self.hostname = c.strget("hostname")
        self.username = c.strget("username")
        self.name = c.strget("name")
        self.argv = c.strlistget("argv")
        self.client_type = c.strget("client_type", "PyGTK")
        self.client_platform = c.strget("platform")
        self.client_machine = c.strget("platform.machine")
        self.client_processor = c.strget("platform.processor")
        self.client_release = c.strget("platform.sysrelease")
        self.client_linux_distribution = c.strlistget("platform.linux_distribution")
        self.client_version = c.strget("version")
        self.client_revision = c.strget("build.revision")
        self.client_bits = c.intget("python.bits")
        self.client_proxy = c.boolget("proxy")
        self.client_wm_name = c.strget("wm_name")
        self.client_session_type = c.strget("session-type")
        self.client_session_type_full = c.strget("session-type.full", "")
        self.client_setting_change = c.boolget("setting-change")
        self.proxy_hostname = c.strget("proxy.hostname")
        self.proxy_platform = c.strget("proxy.platform")
        self.proxy_release = c.strget("proxy.platform.sysrelease")
        self.proxy_version = c.strget("proxy.version")
        self.proxy_version = c.strget("proxy.build.version", self.proxy_version)
        log("client uuid %s", self.uuid)

    def get_connect_info(self):
        cinfo = []
        pinfo = ""
        if self.client_platform:
            pinfo = " %s" % platform_name(self.client_platform, self.client_linux_distribution or self.client_release)
        if self.client_session_type:
            pinfo += " %s" % self.client_session_type
        revinfo = ""
        if self.client_revision:
            revinfo="-r%s" % self.client_revision
        bitsstr = ""
        if self.client_bits:
            bitsstr = " %i-bit" % self.client_bits
        cinfo.append("%s%s client version %s%s%s" % (std(self.client_type), pinfo, std(self.client_version), std(revinfo), bitsstr))
        msg = ""
        if self.hostname:
            msg += "connected from '%s'" % std(self.hostname)
        if self.username:
            msg += " as '%s'" % std(self.username)
            if self.name and self.name!=self.username:
                msg += " - '%s'" % std(self.name)
        if msg:
            cinfo.append(msg)
        if self.client_proxy:
            msg = "via %s proxy version %s" % (platform_name(self.proxy_platform, self.proxy_release), std(self.proxy_version or "unknown"))
            if self.proxy_hostname:
                msg += " on '%s'" % std(self.proxy_hostname)
            cinfo.append(msg)
        return cinfo


    def get_info(self):
        info = {
                "version"           : self.client_version or "unknown",
                "revision"          : self.client_revision or "unknown",
                "platform_name"     : platform_name(self.client_platform, self.client_release),
                "session-type"      : self.client_session_type,
                "session-type.full" : self.client_session_type_full,
                "uuid"              : self.uuid,
                "hostname"          : self.hostname,
                "argv"              : self.argv,
                }

        def addattr(k, name):
            v = getattr(self, name)
            if v is not None:
                info[k] = v
        for x in ("type", "platform", "release", "machine", "processor", "proxy", "wm_name", "session_type"):
            addattr(x, "client_"+x)
        return info
