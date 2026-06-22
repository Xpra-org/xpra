# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.str_fn import bytestostr
from xpra.util.parsing import str_to_bool
from xpra.net.common import Packet, GSETTINGS_ALLOWLIST, parse_gsettings_key
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

GLib = gi_import("GLib")
Gio = gi_import("Gio")

log = Logger("server", "gsettings")


class GSettingsServer(StubSubsystem):
    """
    Applies an allowlisted set of GSettings forwarded by a single connected client,
    layered on top of the server-side `defaults` baseline.

    The original value of every key we modify is saved and restored when the server
    shuts down. Client overrides are reverted (back to the baseline) whenever more than
    one client is connected, or when the last client disconnects - because the server
    session is shared and there is no sensible way to merge conflicting preferences.
    """

    PREFIX = "gsettings"

    def __init__(self, server=None):
        super().__init__(server)
        self.sync_enabled = False
        # server-side baseline applied for the server's lifetime,
        # variant servers may inject values here - {(schema, key): gvariant_text}:
        self.defaults: dict[tuple[str, str], str] = {}
        # the original value of every key we have modified - {(schema, key): GLib.Variant}:
        self.original: dict[tuple[str, str], Any] = {}

    def init(self, opts) -> None:
        # `auto` enables synchronization everywhere except MacOS and MS Windows:
        self.sync_enabled = str_to_bool(opts.gsettings_sync, not (OSX or WIN32))
        log("gsettings_sync(%s)=%s", opts.gsettings_sync, self.sync_enabled)

    def setup(self) -> None:
        if self.sync_enabled:
            self.update_gsettings()

    def cleanup(self) -> None:
        # stop applying, then restore everything we touched to its original value:
        self.sync_enabled = False
        for sk, variant in tuple(self.original.items()):
            self._set(sk, variant)
        self.original = {}

    def get_caps(self, _source) -> dict[str, Any]:
        if self.sync_enabled:
            return {"gsettings": True}
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "gsettings": {
                "enabled": self.sync_enabled,
                "defaults": {f"{schema}:{key}": value for (schema, key), value in self.defaults.items()},
            }
        }

    def init_packet_handlers(self) -> None:
        self.add_packets("gsettings-update", main_thread=True)

    def _process_gsettings_update(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        gsettings = getattr(ss, "gsettings", None)
        if gsettings is None:
            return
        settings = packet.get_dict(1)
        for name, value in settings.items():
            try:
                sk = parse_gsettings_key(bytestostr(name))
            except ValueError:
                continue
            if sk in GSETTINGS_ALLOWLIST:
                gsettings[sk] = bytestostr(value)
        log("updated client gsettings: %s", gsettings)
        self.update_gsettings()

    def add_new_client(self, ss, c) -> None:
        self.update_gsettings()

    def cleanup_protocol(self, protocol) -> None:
        # the source has already been removed from the server at this point,
        # so we can re-evaluate which settings (if any) should be applied:
        self.update_gsettings()

    # --- core apply / restore logic ---

    def desired(self) -> dict[tuple[str, str], str]:
        target = dict(self.defaults)
        sources = tuple(self.server._server_sources.values())
        # only honour client values when exactly one client is connected:
        if len(sources) == 1:
            for sk, value in getattr(sources[0], "gsettings", {}).items():
                if sk in GSETTINGS_ALLOWLIST:
                    target[sk] = value
        return target

    def update_gsettings(self) -> None:
        if not self.sync_enabled:
            return
        target = self.desired()
        log("update_gsettings() target=%s", target)
        for sk in target:
            self._ensure_original(sk)
        for sk, original in self.original.items():
            text = target.get(sk)
            if text is None:
                # key no longer targeted: revert to its original value
                self._set(sk, original)
                continue
            variant = self._parse(text)
            if variant is not None:
                self._set(sk, variant)

    @staticmethod
    def _get_settings(schema_id: str, key: str):
        # return a `Gio.Settings` only if the schema exists and contains the key
        # (calling `get_value` on a missing key would abort the process):
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(schema_id, True)
        if not schema or not schema.has_key(key):
            return None
        return Gio.Settings.new(schema_id)

    def _ensure_original(self, sk: tuple[str, str]) -> None:
        if sk in self.original:
            return
        schema, key = sk
        try:
            s = self._get_settings(schema, key)
            if s is not None:
                self.original[sk] = s.get_value(key)
        except Exception as e:
            log("error reading gsettings %s:%s", schema, key, exc_info=True)
            log.error("Error reading GSettings %r / %r:", schema, key)
            log.estr(e)

    @staticmethod
    def _parse(text: str):
        # parse annotated GVariant text (sent by the client) back into a `GLib.Variant`;
        # a malformed value must not break the rest of the update:
        try:
            return GLib.Variant.parse(None, text, None, None)
        except Exception:
            log("failed to parse gsettings value %r", text, exc_info=True)
            return None

    def _set(self, sk: tuple[str, str], variant) -> None:
        schema, key = sk
        try:
            s = self._get_settings(schema, key)
            if s is None:
                return
            current = s.get_value(key)
            if variant.get_type_string() != current.get_type_string():
                log("skipping gsettings %s:%s: type mismatch (%s vs %s)",
                    schema, key, variant.get_type_string(), current.get_type_string())
                return
            if current.equal(variant):
                return
            log("setting gsettings %s:%s=%s", schema, key, variant.print_(True))
            s.set_value(key, variant)
        except Exception as e:
            log("error setting gsettings %s:%s=%s", schema, key, variant, exc_info=True)
            log.error("Error setting GSettings %r / %r:", schema, key)
            log.estr(e)
