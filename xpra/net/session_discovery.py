# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from dataclasses import dataclass, field
from typing import Any

from xpra.net.constants import DEFAULT_PORTS
from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr

try:
    local_host_name = socket.gethostname()
except OSError:
    local_host_name = "localhost"


@dataclass(frozen=True)
class SessionEndpoint:
    source: str
    interface: Any = None
    protocol: Any = None
    name: str = ""
    stype: str = ""
    domain: str = ""
    host: str = ""
    address: str = ""
    port: int = 0
    text: dict[str, Any] = field(default_factory=dict)

    @property
    def typed_text(self) -> typedict:
        return typedict(self.text)

    @property
    def uuid(self) -> str:
        return self.typed_text.strget("uuid")

    @property
    def display(self) -> str:
        return self.typed_text.strget("display")

    @property
    def username(self) -> str:
        return self.typed_text.strget("username")

    @property
    def session_name(self) -> str:
        return self.typed_text.strget("name") or self.typed_text.strget("session")

    @property
    def platform(self) -> str:
        return self.typed_text.strget("platform")

    @property
    def session_type(self) -> str:
        return self.typed_text.strget("type")

    @property
    def mode(self) -> str:
        return self.typed_text.strget("mode")

    @property
    def icon(self):
        return self.text.get("icon")

    def as_record_tuple(self) -> tuple[Any, Any, str, str, str, str, str, int, dict[str, Any]]:
        return (
            self.interface,
            self.protocol,
            self.name,
            self.stype,
            self.domain,
            self.host,
            self.address,
            self.port,
            self.text,
        )


@dataclass
class SessionGroup:
    key: object
    endpoints: list[SessionEndpoint] = field(default_factory=list)
    host: str = ""
    display: str = ""
    uuid: str = ""
    username: str = ""
    session_name: str = ""
    platform: str = ""
    session_type: str = ""
    icon: Any = None


def normalize_mdns_host(host: str, stype: str = "", domain: str = "", mode: str = "") -> str:
    if not host:
        return host
    suffixes = []
    if stype:
        suffixes.append(stype)
        if domain:
            suffixes.append(stype.rstrip(".") + "." + domain.strip(".") + ".")
            suffixes.append(stype.rstrip(".") + "." + domain.strip("."))
    for suffix in suffixes:
        if host.endswith(suffix):
            host = host[:-len(suffix)]
            break
    if mode and host.endswith(mode + "."):
        host = host[:-len(mode + ".")]
    if host.endswith(".local."):
        host = host[:-len(".local.")]
    if host.endswith("."):
        host = host[:-1]
    return host


def normalized_session_host(endpoint: SessionEndpoint) -> str:
    host = endpoint.host
    if endpoint.domain == "local" and host.endswith(".local"):
        host = host[:-len(".local")]
    return host


def session_group_key(endpoint: SessionEndpoint) -> object:
    if endpoint.uuid:
        return endpoint.uuid
    return normalized_session_host(endpoint).rstrip("."), endpoint.display


def group_session_endpoints(endpoints: list[SessionEndpoint]) -> dict[object, SessionGroup]:
    grouped: dict[object, list[SessionEndpoint]] = {}
    for endpoint in endpoints:
        grouped.setdefault(session_group_key(endpoint), []).append(endpoint)
    session_groups: dict[object, SessionGroup] = {}
    for key, recs in grouped.items():
        group = SessionGroup(key=key, endpoints=recs)
        if isinstance(key, tuple):
            host, display = key
            group.host = str(host)
            group.display = str(display)
            group.uuid = str(display)
        else:
            group.uuid = str(key)
            hosts = [
                normalized_session_host(rec) for rec in recs
                if not normalized_session_host(rec).startswith("local")
            ]
            if not hosts:
                hosts = [normalized_session_host(rec) for rec in recs]
            group.host = hosts[0] if hosts else ""
        for endpoint in recs:
            if not group.username:
                group.username = endpoint.username
            if not group.platform:
                group.platform = endpoint.platform
            if not group.session_type:
                group.session_type = endpoint.session_type
            if not group.display:
                group.display = endpoint.display
            if not group.session_name:
                group.session_name = endpoint.session_name
            if group.icon is None:
                group.icon = endpoint.icon
        if not isinstance(key, tuple) and group.host in (
                "localhost", "localhost.localdomain", "127.0.0.1", "::1", local_host_name):
            group.host = "local"
        session_groups[key] = group
    return session_groups


def endpoint_uri(password: str, endpoint: SessionEndpoint) -> str:
    return get_uri(password, *endpoint.as_record_tuple())


def get_uri(password: str, interface, protocol, name: str, stype: str, domain, host: str,
            address, port: int, text) -> str:
    dstr = ""
    tt = typedict(text)
    display = tt.strget("display")
    username = tt.strget("username")
    mode = tt.strget("mode")
    if not mode:
        # guess the mode from the service name,
        # ie: "localhost.localdomain :2 (wss)" -> "wss"
        # ie: "localhost.localdomain :2 (ssh-2)" -> "ssh"
        pos = name.rfind("(")
        if name.endswith(")") and pos > 0:
            mode = name[pos + 1:-1].split("-")[0]
            if mode not in ("tcp", "ws", "wss", "ssl", "ssh"):
                return ""
        else:
            mode = "tcp"
    if display and display.startswith(":"):
        dstr = display[1:]
    # append interface to IPv6 host URI for link local addresses ("fe80:"):
    if interface and address.lower().startswith("fe80:"):
        # ie: "fe80::c1:ac45:7351:ea69%eth1"
        try:
            if isinstance(interface, int):
                iface = socket.if_indextoname(interface)
            else:
                iface = str(interface)
            address += "%" + iface
        except (OSError, TypeError):
            pass
    uri = f"{mode}://"
    if username:
        if password:
            uri += f"{username}:{password}@{address}"
        else:
            uri += f"{username}@{address}"
    else:
        uri += address
    if port > 0:
        if DEFAULT_PORTS.get(mode, 0) != port:  # NOSONAR @SuppressWarnings("python:S1066")
            uri += f":{port}"
    if protocol not in ("socket", "named-pipe"):
        uri += "/"
        if dstr:
            uri += "%s" % dstr
    return uri


def mdns_txt_to_dict(text) -> dict[str, Any]:
    return {bytestostr(k): bytestostr(v) for k, v in (text or {}).items()}
