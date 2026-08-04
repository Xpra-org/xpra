# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.objects import typedict
from xpra.net.common import parse_gsettings_allowlist, gsettings_match, gsettings_key
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

Gio = gi_import("Gio")

log = Logger("client", "gsettings")


class GSettingsClient(StubClientSubsystem):
    """
    Forward an allowlisted set of the client's GSettings to the server,
    re-sending individual keys as they change.
    """
    __slots__ = ("allowlist", "enabled", "server_enabled", "settings", "sync")

    PREFIX = "gsettings"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.sync = ""
        # the (schema, key) regular expressions to synchronize:
        self.allowlist: tuple[tuple[str, str], ...] = ()
        self.enabled = False
        self.server_enabled = False
        # keep references to the `Gio.Settings` objects we watch, to avoid garbage collection:
        self.settings: dict[str, Any] = {}

    def init(self, opts) -> None:
        self.sync = opts.gsettings_sync
        # `auto` enables synchronization of the default allowlist
        # everywhere except MacOS and MS Windows,
        # the option can also specify the `schema:key` patterns to synchronize:
        self.allowlist = parse_gsettings_allowlist(opts.gsettings_sync, not (OSX or WIN32))
        self.enabled = bool(self.allowlist)
        log("gsettings_sync(%s)=%s, allowlist=%s", opts.gsettings_sync, self.enabled, self.allowlist)

    def cleanup(self) -> None:
        settings = self.settings
        self.settings = {}
        for s in settings.values():
            try:
                s.disconnect_by_func(self._gsetting_changed)
            except Exception:
                log("error disconnecting from %s", s, exc_info=True)

    def get_caps(self) -> dict[str, Any]:
        if self.enabled:
            return {"gsettings": True}
        return {}

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_enabled = c.boolget("gsettings")
        log("parse_server_capabilities() gsettings enabled=%s, server=%s",
            self.enabled, self.server_enabled)
        if self.enabled and self.server_enabled:
            self.client.after_handshake(self.setup_gsettings)
        return True

    def allowed(self, schema: str, key: str) -> bool:
        return gsettings_match(self.allowlist, schema, key)

    def get_keys(self) -> tuple[tuple[str, str], ...]:
        # match the allowlist patterns against every key of every schema
        # installed on this system - relocatable schemas are skipped
        # since they have no fixed path:
        source = Gio.SettingsSchemaSource.get_default()
        keys: list[tuple[str, str]] = []
        # `list_schemas` returns a (non-relocatable, relocatable) tuple:
        for schema_id in source.list_schemas(True)[0]:
            schema = source.lookup(schema_id, True)
            if schema:
                keys += [(schema_id, key) for key in schema.list_keys() if self.allowed(schema_id, key)]
        log("get_keys() matched %i keys", len(keys))
        return tuple(keys)

    def setup_gsettings(self) -> None:
        values: dict[str, str] = {}
        # `get_keys` only returns keys which do exist, so they are safe to read:
        for schema_id, key in self.get_keys():
            try:
                s = self.settings.get(schema_id)
                if s is None:
                    s = Gio.Settings.new(schema_id)
                    self.settings[schema_id] = s
                values[gsettings_key(schema_id, key)] = s.get_value(key).print_(True)
                # watch this key for live changes:
                s.connect(f"changed::{key}", self._gsetting_changed, schema_id)
            except Exception as e:
                log("error reading gsettings %s:%s", schema_id, key, exc_info=True)
                log.warn("Warning: unable to read GSettings %r / %r: %s", schema_id, key, e)
        if values:
            log("sending initial gsettings: %s", values)
            self.send("gsettings-update", values)

    def _gsetting_changed(self, settings, key: str, schema: str) -> None:
        if not self.allowed(schema, key):
            return
        try:
            value = settings.get_value(key).print_(True)
        except Exception:
            log("error reading changed gsetting %s:%s", schema, key, exc_info=True)
            return
        log("gsetting changed: %s:%s=%s", schema, key, value)
        self.send("gsettings-update", {gsettings_key(schema, key): value})
