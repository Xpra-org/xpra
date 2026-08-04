# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from functools import lru_cache
from collections.abc import Sequence

from xpra.log import Logger
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS

log = Logger("util", "gsettings")

# (schema, key) regular expression pairs matching the GSettings which the
# "gsettings" subsystem synchronizes by default: the client only reads and sends
# the keys matching its own allowlist, and the server only accepts and applies
# the keys matching its own one - each end can use a different allowlist by giving
# the `gsettings-sync` option a list of "schema:key" patterns instead of a boolean.
# This default list is overridable via XPRA_GSETTINGS_ALLOWLIST
# (comma-separated "schema:key" patterns):
_DEFAULT_GSETTINGS_ALLOWLIST = (
    "org.gnome.desktop.interface:gtk-theme",
    "org.gnome.desktop.interface:icon-theme",
    "org.gnome.desktop.interface:cursor-theme",
    "org.gnome.desktop.interface:cursor-size",
    "org.gnome.desktop.interface:font-name",
    "org.gnome.desktop.interface:monospace-font-name",
    "org.gnome.desktop.interface:document-font-name",
    "org.gnome.desktop.interface:color-scheme",
    "org.gnome.desktop.interface:font-antialiasing",
    "org.gnome.desktop.interface:font-hinting",
    "org.gnome.desktop.wm.preferences:theme",
    "org.gnome.desktop.wm.preferences:button-layout",
    "org.gnome.desktop.wm.preferences:titlebar-font",
    "org.gnome.desktop.sound:theme-name",
    "org.gnome.desktop.sound:event-sounds",
    "org.gnome.desktop.a11y.interface:high-contrast",
)

# `all` and `*` are user friendly aliases for the "match everything" pattern:
ALL_GSETTINGS: Sequence[str] = ("all", "*")
ALL_GSETTINGS_PATTERN = ".*"
GVARIANT_TYPE_ALIASES = {
    "bool": "b",
    "boolean": "b",
    "double": "d",
    "float": "d",
    "int": "i",
    "str": "s",
    "string": "s",
    "uint": "u",
}


def gsettings_key(schema: str, key: str) -> str:
    return f"{schema}:{key}"


def parse_gsettings_key(name: str) -> tuple[str, str]:
    schema, key = name.split(":", 1)
    return schema, key


@lru_cache(maxsize=256)
def _compile(pattern: str):
    return re.compile(pattern)


def gsettings_match(allowlist: Sequence[tuple[str, str]], schema: str, key: str) -> bool:
    """Does this (schema, key) pair match any of the allowlist patterns?"""
    return any(_compile(sp).fullmatch(schema) and _compile(kp).fullmatch(key) for sp, kp in allowlist)


def split_gsettings_entries(value: str) -> tuple[str, ...]:
    """Split comma-separated entries without splitting GVariant containers."""
    entries: list[str] = []
    current: list[str] = []
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    quote = ""
    escaped = False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in depths:
            depths[char] += 1
        elif char in closing:
            opener = closing[char]
            depths[opener] = max(0, depths[opener] - 1)
        elif char == "," and not any(depths.values()):
            entries.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        entries.append("".join(current))
    return tuple(entries)


def split_gsettings_value(specification: str) -> tuple[str, str]:
    """Split VALUE(TYPE), allowing compound GVariant types such as ``(ii)``."""
    if not specification.endswith(")"):
        raise ValueError("expected value(type)")
    depth = 0
    for index in range(len(specification) - 1, -1, -1):
        char = specification[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                value = specification[:index].strip()
                variant_type = specification[index + 1:-1].strip()
                if not variant_type:
                    raise ValueError("the GVariant type must not be empty")
                return value, variant_type
    raise ValueError("expected value(type)")


def parse_gsettings_value(text: str):
    """Parse canonical GVariant text or a client-supplied ``value(type)`` literal."""
    # Keep GLib lazy: fixed-value clients import this module but only servers
    # need to parse the forwarded GVariant value.
    from xpra.os_util import gi_import
    GLib = gi_import("GLib")
    try:
        return GLib.Variant.parse(None, text, None, None)
    except Exception:
        pass
    try:
        value, variant_type = split_gsettings_value(text)
        variant_type = GVARIANT_TYPE_ALIASES.get(variant_type.lower(), variant_type)
        if not GLib.VariantType.string_is_valid(variant_type):
            raise ValueError(f"invalid GVariant type {variant_type!r}")
        value_type = GLib.VariantType.new(variant_type)
        if not value_type.is_definite():
            raise ValueError(f"indefinite GVariant type {variant_type!r}")
        if variant_type in ("s", "o", "g") and not value.startswith(("'", '"')):
            return GLib.Variant(variant_type, value)
        return GLib.Variant.parse(value_type, value, None, None)
    except Exception:
        log("failed to parse gsettings value %r", text, exc_info=True)
        return None


def _parse_gsettings_allowlist(value: str) -> tuple[tuple[str, str], ...]:
    patterns: list[tuple[str, str]] = []
    for entry in split_gsettings_entries(value):
        entry = entry.strip()
        if not entry:
            continue
        # Fixed values are interpreted by clients; on servers their left-hand
        # side is the selector which authorizes that schema and key.
        fixed_value = "=" in entry
        if fixed_value:
            entry = entry.split("=", 1)[0].strip()
            if ":" not in entry:
                log.warn("Warning: ignoring invalid gsettings value selector %r", entry)
                continue
        # entries without a separator match every key of the matching schemas:
        schema, key = parse_gsettings_key(entry) if ":" in entry else (entry, ALL_GSETTINGS_PATTERN)
        if fixed_value:
            if not schema or not key:
                log.warn("Warning: ignoring invalid gsettings value selector %r", entry)
                continue
            schema, key = re.escape(schema), re.escape(key)
        try:
            _compile(schema)
            _compile(key)
        except re.error as e:
            log.warn("Warning: ignoring invalid gsettings pattern %r: %s", entry, e)
            continue
        patterns.append((schema, key))
    return tuple(patterns)


GSETTINGS_ALLOWLIST: tuple[tuple[str, str], ...] = _parse_gsettings_allowlist(
    os.environ.get("XPRA_GSETTINGS_ALLOWLIST", ",".join(_DEFAULT_GSETTINGS_ALLOWLIST))
)


def parse_gsettings_allowlist(value: str, auto: bool = True) -> tuple[tuple[str, str], ...]:
    """
    Parse the value of the `gsettings-sync` option into a list of (schema, key) regex pairs.
    Boolean values and `auto` select the default allowlist (`auto` only if `auto` is True),
    `all` (or `*`) matches everything,
    anything else is parsed as a comma separated list of `schema:key` patterns.
    An empty tuple means that synchronization is disabled.
    """
    v = (value or "auto").strip()
    lv = v.lower()
    if lv in FALSE_OPTIONS:
        return ()
    if lv in ALL_GSETTINGS:
        return ((ALL_GSETTINGS_PATTERN, ALL_GSETTINGS_PATTERN), )
    if lv in TRUE_OPTIONS:
        return GSETTINGS_ALLOWLIST
    if lv == "auto":
        return GSETTINGS_ALLOWLIST if auto else ()
    # an explicit list of patterns is always honoured:
    return _parse_gsettings_allowlist(v)


def parse_gsettings_option(value: str, auto: bool) -> \
        tuple[tuple[tuple[str, str], ...], dict[tuple[str, str], str]]:
    """Return local selectors and fixed ``schema:key=value(type)`` assignments."""
    entries = split_gsettings_entries((value or "auto").strip())
    selectors: list[str] = []
    assignments: dict[tuple[str, str], str] = {}
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            selectors.append(entry)
            continue
        name, specification = entry.split("=", 1)
        try:
            schema, key = name.strip().split(":", 1)
            if not schema or not key:
                raise ValueError("schema and key must not be empty")
            assignments[(schema, key)] = specification.strip()
        except ValueError as e:
            log.warn("Warning: ignoring invalid GSettings value %r: %s", entry, e)
    selectors_value = ",".join(selectors)
    allowlist = parse_gsettings_allowlist(selectors_value, auto) if selectors_value else ()
    return allowlist, assignments
