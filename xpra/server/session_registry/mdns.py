# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
mDNS session registry.

The proxy listens for Xpra mDNS advertisements and exposes every discovered
session to authenticated clients. If a client supplies a target hint
(`session-name` or `display`), lookup matches it against the grouped session's
name, uuid, display, and endpoint URIs. Without a hint, the first discovered
session is selected.
"""

import threading
from typing import Optional

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE, get_listener_class
from xpra.net.session_discovery import (
    SessionEndpoint,
    SessionGroup,
    endpoint_uri,
    group_session_endpoints,
    mdns_txt_to_dict,
    normalize_mdns_host,
)
from xpra.os_util import getgid, getuid
from xpra.server.session_registry import Session, SessionRegistry
from xpra.util.objects import typedict
from xpra.util.parsing import str_to_bool
from xpra.log import Logger

log = Logger("auth", "mdns")


class Registry(SessionRegistry):
    NAME = "mdns"

    def __init__(self, **options):
        super().__init__(**options)
        self.hide_ipv6 = str_to_bool(options.get("hide-ipv6"), False)
        self.include_proxy = str_to_bool(options.get("include-proxy"), False)
        self.server_uuid = str(options.get("uuid", ""))
        self._endpoints: list[SessionEndpoint] = []
        self._lock = threading.Lock()
        self._listeners = []
        listener_class = get_listener_class()
        if not listener_class:
            raise RuntimeError("mdns registry requires mDNS listener support")
        for service_type in (XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE):
            listener = listener_class(
                service_type,
                mdns_add=self.mdns_add,
                mdns_remove=self.mdns_remove,
                mdns_update=self.mdns_update,
            )
            self._listeners.append(listener)
            listener.start()

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text) -> None:
        log("mdns registry add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        if self.hide_ipv6 and address.find(":") >= 0:
            return
        text_rec = mdns_txt_to_dict(text)
        if not self.include_proxy and text_rec.get("type") == "proxy":
            log("mdns registry ignoring proxy service %r", name)
            return
        if self.server_uuid and text_rec.get("uuid") == self.server_uuid:
            log("mdns registry ignoring own service %r", name)
            return
        host = normalize_mdns_host(host, stype, domain, text_rec.get("mode", ""))
        endpoint = SessionEndpoint(
            source="mdns",
            interface=interface,
            protocol=protocol,
            name=name,
            stype=stype,
            domain=domain,
            host=host,
            address=address,
            port=port,
            text=text_rec,
        )
        with self._lock:
            if endpoint not in self._endpoints:
                self._endpoints.append(endpoint)

    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, _r_flags) -> None:
        log("mdns registry remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain))
        cmp = (r_interface, r_protocol, r_name, r_stype, r_domain)
        with self._lock:
            self._endpoints = [
                endpoint for endpoint in self._endpoints
                if (
                    endpoint.interface,
                    endpoint.protocol,
                    endpoint.name,
                    endpoint.stype,
                    endpoint.domain,
                ) != cmp
            ]

    def mdns_update(self, r_name, r_type) -> None:
        log("mdns registry update%s", (r_name, r_type))

    def cleanup(self) -> None:
        listeners = tuple(self._listeners)
        self._listeners = []
        for listener in listeners:
            try:
                listener.stop()
            except Exception as e:
                log("mdns registry cleanup failed for %s", listener, exc_info=True)
                log.warn("Warning: failed to stop mDNS listener")
                log.warn(" %s", e)

    def list_sessions(self) -> list[Session]:
        return [
            session for session in (
                self._session_from_group(group, None) for group in self._groups().values()
            )
            if session is not None
        ]

    def lookup(self, authenticator, client_caps: Optional[typedict] = None) -> Session | None:
        groups = self._groups()
        if not groups:
            return None
        hints = self._request_hints(client_caps)
        log("%s.lookup(%s) hints=%r among %i mdns session(s)", self, authenticator, hints, len(groups))
        for i, group in enumerate(groups.values()):
            log("%i: %r, %r: %s", i, group.session_name, group.display, group.endpoints)
        for requested in hints:
            for group in groups.values():
                if self._matches(group, requested):
                    return self._session_from_group(group, authenticator, self._selected_display(group, requested))
        if hints:
            return None
        for group in groups.values():
            session = self._session_from_group(group, authenticator, self._selected_display(group))
            if session:
                return session
        return None

    def get_info(self) -> dict:
        return {
            "mdns": {
                "sessions": {
                    i: {
                        "uuid": group.uuid,
                        "session-name": group.session_name,
                        "display": group.display,
                        "username": group.username,
                        "endpoints": [endpoint_uri("", endpoint) for endpoint in group.endpoints],
                    }
                    for i, group in enumerate(self._groups().values())
                },
            },
        }

    def _groups(self) -> dict[object, SessionGroup]:
        with self._lock:
            endpoints = list(self._endpoints)
        return group_session_endpoints(endpoints)

    @staticmethod
    def _request_hints(client_caps: Optional[typedict]) -> list[str]:
        """
        Identifying hints sent by the client to pick a target session,
        in priority order. Each will be tried against every known group.
        """
        hints: list[str] = []

        def add(v: str) -> None:
            if v and v not in hints:
                hints.append(v)
        if client_caps is None:
            return hints
        # new-style: a top-level "session" sub-dict from `XpraClientBase.get_session_caps`
        session = client_caps.dictget("session")
        if session:
            sd = typedict(session)
            for key in ("name", "uuid", "display"):
                add(sd.strget(key))
        # legacy: top-level "session-name", and "display" as a string
        add(client_caps.strget("session-name"))
        raw = client_caps.get("display")
        if BACKWARDS_COMPATIBLE and isinstance(raw, str):
            add(str(raw))
        return hints

    @staticmethod
    def _matches(group: SessionGroup, requested: str) -> bool:
        if requested in (group.session_name, group.uuid, group.display):
            return True
        if group.display.startswith(":") and requested == group.display[1:]:
            return True
        return any(requested == endpoint_uri("", endpoint) for endpoint in group.endpoints)

    @staticmethod
    def _selected_display(group: SessionGroup, requested: str = "") -> str:
        displays = [uri for uri in (endpoint_uri("", endpoint) for endpoint in group.endpoints) if uri]
        if requested and requested in displays:
            return requested
        return displays[0] if displays else ""

    @staticmethod
    def _uid_gid(authenticator) -> tuple[int, int]:
        try:
            uid = authenticator.get_uid()
            gid = authenticator.get_gid()
        except (AttributeError, NotImplementedError):
            uid = getuid()
            gid = getgid()
        return uid, gid

    def _session_from_group(self, group: SessionGroup, authenticator, selected_display: str = "") -> Session | None:
        displays = [uri for uri in (endpoint_uri("", endpoint) for endpoint in group.endpoints) if uri]
        if not displays:
            return None
        if selected_display not in displays:
            selected_display = displays[0]
        if authenticator is None:
            uid = gid = -1
        else:
            uid, gid = self._uid_gid(authenticator)
        return Session(
            uid=uid,
            gid=gid,
            displays=displays,
            uuid=group.uuid,
            session_name=group.session_name,
            selected_display=selected_display,
        )
