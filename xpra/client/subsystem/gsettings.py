# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.objects import typedict
from xpra.util.parsing import str_to_bool
from xpra.net.common import GSETTINGS_ALLOWLIST, gsettings_key
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

Gio = gi_import("Gio")

log = Logger("client", "gsettings")


class GSettingsClient(StubClientSubsystem):
    """
    Forward an allowlisted set of the client's GSettings to the server,
    re-sending individual keys as they change.
    """
    __slots__ = ("enabled", "server_enabled", "settings", "sync")

    PREFIX = "gsettings"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.sync = ""
        self.enabled = False
        self.server_enabled = False
        # keep references to the `Gio.Settings` objects we watch, to avoid garbage collection:
        self.settings: dict[str, Any] = {}

    def init(self, opts) -> None:
        self.sync = opts.gsettings_sync
        # `auto` enables synchronization everywhere except MacOS and MS Windows:
        self.enabled = str_to_bool(opts.gsettings_sync, not (OSX or WIN32))
        log("gsettings_sync(%s)=%s", opts.gsettings_sync, self.enabled)

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

    def setup_gsettings(self) -> None:
        source = Gio.SettingsSchemaSource.get_default()
        values: dict[str, str] = {}
        for schema_id, key in GSETTINGS_ALLOWLIST:
            schema = source.lookup(schema_id, True)
            if not schema or not schema.has_key(key):
                continue
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
        if (schema, key) not in GSETTINGS_ALLOWLIST:
            return
        try:
            value = settings.get_value(key).print_(True)
        except Exception:
            log("error reading changed gsetting %s:%s", schema, key, exc_info=True)
            return
        log("gsetting changed: %s:%s=%s", schema, key, value)
        self.send("gsettings-update", {gsettings_key(schema, key): value})
