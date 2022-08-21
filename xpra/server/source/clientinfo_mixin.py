# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import std, typedict, net_utf8
from xpra.common import FULL_INFO
from xpra.version_util import vparts
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.os_util import platform_name
from xpra.log import Logger

log = Logger("server")


class ClientInfoMixin(StubSourceMixin):
    """
    Store information about the client.
    """

    def cleanup(self):
        self.init_state()

    def init_state(self):
        self.uuid = ""
        self.session_id = ""
        self.machine_id = ""
        self.hostname = ""
        self.username = ""
        self.user = ""
        self.name = ""
        self.argv = ()
        self.sharing = False
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
        self.client_opengl = {}
        self.proxy_hostname = None
        self.proxy_platform = None
        self.proxy_release = None
        self.proxy_version = None
        self.proxy_version = None

    def parse_client_caps(self, c : typedict):
        self.uuid = c.strget("uuid")
        self.session_id = c.strget("session-id")
        self.machine_id = c.strget("machine_id")
        self.hostname = c.strget("hostname")
        self.username = c.strget("username")
        self.user = c.strget("user")
        self.name = c.strget("name")
        self.argv = c.strtupleget("argv")
        self.sharing = c.boolget("share")
        self.client_type = c.strget("client_type", "")
        self.client_platform = c.strget("platform")
        self.client_machine = c.strget("platform.machine")
        self.client_processor = c.strget("platform.processor")
        self.client_release = c.strget("platform.sysrelease")
        self.client_linux_distribution = c.strtupleget("platform.linux_distribution")
        self.client_version = c.strget("version")
        self.client_revision = c.strget("build.revision")
        self.client_bits = c.intget("python.bits")
        self.client_proxy = c.boolget("proxy")
        self.client_wm_name = c.conv_get("wm_name", "", net_utf8)
        self.client_session_type = c.strget("session-type")
        self.client_session_type_full = c.strget("session-type.full", "")
        self.client_setting_change = c.boolget("setting-change")
        self.client_opengl = typedict(c.dictget("opengl") or {})
        self.proxy_hostname = c.strget("proxy.hostname")
        self.proxy_platform = c.strget("proxy.platform")
        self.proxy_release = c.strget("proxy.platform.sysrelease")
        self.proxy_version = c.strget("proxy.version")
        self.proxy_version = c.strget("proxy.build.version", self.proxy_version)
        log("client uuid %s", self.uuid)

    def get_connect_info(self) -> list:
        #client platform / version info:
        pinfo = [std(self.client_type)]
        if FULL_INFO>0:
            if self.client_platform:
                pinfo += [platform_name(self.client_platform, self.client_linux_distribution or self.client_release)]
            if self.client_session_type:
                pinfo += [self.client_session_type]
            revinfo = f"-r{self.client_revision}" if isinstance(self.client_revision, int) else ""
            bitsstr = f" {self.client_bits}-bit" if self.client_bits else ""
            version = self.client_version
        else:
            revinfo = bitsstr = ""
            version = (self.client_version or "").split(".")[0]
        pinfo += [f"client version {std(version)}{std(revinfo)}{bitsstr}"]
        cinfo = [" ".join(x for x in pinfo if x)]
        if FULL_INFO>0:
            #connection info:
            if self.hostname or self.username:
                msg = "connected from %r" % std(self.hostname or "unknown host")
                if self.username:
                    msg += " as '%s'" % std(self.username)
                    if self.name and self.name!=self.username:
                        msg += " - '%s'" % std(self.name)
                if msg:
                    cinfo.append(msg)
            #proxy info
            if self.client_proxy:
                msg = "via %s proxy version %s" % (
                    platform_name(self.proxy_platform, self.proxy_release),
                    std(self.proxy_version or "unknown")
                    )
                if self.proxy_hostname:
                    msg += " on '%s'" % std(self.proxy_hostname)
                cinfo.append(msg)
            #opengl info:
            if self.client_opengl:
                msg = "OpenGL is "
                if not self.client_opengl.boolget("enabled"):
                    msg += "disabled"
                else:
                    msg += "enabled"
                    driver_info = self.client_opengl.strget("renderer") or self.client_opengl.strget("vendor")
                    if driver_info:
                        msg += " with %s" % driver_info
                cinfo.append(msg)
        return cinfo


    def get_info(self) -> dict:
        info = {
                "sharing"           : bool(self.sharing),
                }
        if self.client_version:
            info["version"] = vparts(self.client_version, FULL_INFO+1)
        def addattr(k, name=None):
            v = getattr(self, (name or k).replace("-", "_"))
            #skip empty values:
            if v:
                info[k.replace("_", "-")] = v
        for k in ("session-id", "uuid"):
            addattr(k)
        if FULL_INFO>1:
            for k in ("user", "name", "argv"):
                addattr(k)
            for x in (
                "revision",
                "type", "platform", "release", "machine", "processor", "proxy",
                "wm_name", "session_type", "session_type_full"):
                addattr(x, "client_"+x)
            info["platform_name"] = platform_name(self.client_platform, self.client_release)
        return info
