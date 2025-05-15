# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.str_fn import std
from xpra.common import FULL_INFO
from xpra.util.version import vparts
from xpra.server.source.stub import StubClientConnection
from xpra.util.system import platform_name
from xpra.log import Logger

log = Logger("server")


def get_glinfo_message(opengl: typedict) -> str:
    msg = "OpenGL is "
    if not opengl.boolget("enabled"):
        msg += "disabled"
    else:
        msg += "enabled"
        backend = opengl.strget("backend")
        if backend:
            msg += f" using {backend} backend"
        driver_info = opengl.strget("renderer") or opengl.strget("vendor")
        if driver_info:
            msg += f" with {std(driver_info)}"
    return msg


class ClientInfoConnection(StubClientConnection):
    """
    Store information about the client.
    """

    def cleanup(self) -> None:
        self.init_state()

    def init_state(self) -> None:
        self.uuid = ""
        self.session_id = ""
        self.machine_id = ""
        self.hostname = ""
        self.username = ""
        self.user = ""
        self.name = ""
        self.argv: Sequence[str] = ()
        self.sharing = False
        # client capabilities/options:
        self.client_type = ""
        self.client_version = ""
        self.client_revision = ""
        self.client_bits = 0
        self.client_platform = ""
        self.client_machine = ""
        self.client_processor = ""
        self.client_release = ""
        self.client_linux_distribution: Sequence[str] = ()
        self.client_proxy = False
        self.client_wm_name = ""
        self.client_session_type = ""
        self.client_session_type_full = ""
        self.client_opengl: typedict = typedict()
        self.proxy_hostname = ""
        self.proxy_platform = ""
        self.proxy_release = ""
        self.proxy_version = ""
        self.proxy_version = ""

    def parse_client_caps(self, c: typedict) -> None:
        self.uuid = c.strget("uuid")
        self.session_id = c.strget("session-id")
        self.machine_id = c.strget("machine_id")
        self.hostname = c.strget("hostname")
        self.username = c.strget("username")
        self.user = c.strget("user")
        self.name = c.strget("name")
        self.argv = c.strtupleget("argv")
        self.sharing = c.boolget("share")
        self.client_type = c.strget("client_type")
        self.client_platform = c.strget("platform")
        self.client_machine = c.strget("platform.machine")
        self.client_processor = c.strget("platform.processor")
        self.client_release = c.strget("platform.sysrelease")
        self.client_linux_distribution = c.strtupleget("platform.linux_distribution")
        self.client_version = c.strget("version")
        self.client_revision = c.strget("build.revision")
        self.client_bits = c.intget("python.bits")
        self.client_proxy = c.boolget("proxy")
        self.client_wm_name = c.strget("wm_name")
        self.client_session_type = c.strget("session-type")
        self.client_session_type_full = c.strget("session-type.full")
        self.client_opengl = typedict(c.dictget("opengl") or {})
        self.proxy_hostname = c.strget("proxy.hostname")
        self.proxy_platform = c.strget("proxy.platform")
        self.proxy_release = c.strget("proxy.platform.sysrelease")
        self.proxy_version = c.strget("proxy.version")
        self.proxy_version = c.strget("proxy.build.version", self.proxy_version)
        log(f"client uuid {self.uuid!r}")

    def get_connect_info(self) -> list[str]:
        # client platform / version info:
        pinfo = [std(self.client_type)]
        if FULL_INFO > 0:
            if self.client_platform:
                pinfo += [platform_name(self.client_platform, self.client_linux_distribution or self.client_release)]
            if self.client_session_type:
                pinfo += [self.client_session_type]
            revinfo = f"-r{self.client_revision}" if isinstance(self.client_revision, int) else ""
            bitsstr = f" {self.client_bits}-bit" if self.client_bits not in (0, 64) else ""
            version = self.client_version
        else:
            revinfo = bitsstr = ""
            version = (self.client_version or "").split(".")[0]
        pinfo += [f"client version {std(version)}{std(revinfo)}{bitsstr}"]
        cinfo = [" ".join(x for x in pinfo if x)]
        if FULL_INFO > 0:
            if self.hostname or self.username:
                cinfo.append(self.get_connected_info_message())
            if self.client_proxy:
                cinfo.append(self.get_proxy_info_message())
            if self.client_opengl:
                cinfo.append(get_glinfo_message(self.client_opengl))
        return cinfo

    def get_connected_info_message(self) -> str:
        msg = "connected"
        if self.hostname:
            msg += f" from {std(self.hostname)!r}"
        if self.username:
            msg += f" as {std(self.username)!r}"
            if self.name and self.name != self.username:
                msg += f" - {std(self.name)!r}"
        return msg

    def get_proxy_info_message(self) -> str:
        pname = platform_name(self.proxy_platform, self.proxy_release)
        msg = f"via {pname} proxy"
        if self.proxy_version:
            msg += f" version {std(self.proxy_version)}"
        if self.proxy_hostname:
            msg += f" on {std(self.proxy_hostname)!r}"
        return msg

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "sharing": bool(self.sharing),
        }
        if self.client_version:
            info["version"] = vparts(self.client_version, FULL_INFO + 1)

        def addattr(key, name=None):
            v = getattr(self, (name or key).replace("-", "_"))
            # skip empty values:
            if v:
                info[key.replace("_", "-")] = v

        for k in ("session-id", "uuid"):
            addattr(k)
        if FULL_INFO > 1:
            for k in ("user", "name", "argv"):
                addattr(k)
            for x in (
                    "revision",
                    "type", "platform", "release", "machine", "processor", "proxy",
                    "wm_name", "session_type", "session_type_full",
            ):
                addattr(x, "client_" + x)
            info["platform_name"] = platform_name(self.client_platform, self.client_release)
        return info
