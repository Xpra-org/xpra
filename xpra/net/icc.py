# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Validation for ICC profile data obtained from the local operating system or a peer."""

from typing import Any
from collections.abc import Mapping, Sequence

from xpra.util.env import envint
from xpra.util.str_fn import bytestostr, single_line

MAX_ICC_DISPLAYS: int = max(1, envint("XPRA_MAX_ICC_DISPLAYS", 16))
MAX_ICC_PROFILE_SIZE: int = max(128, envint("XPRA_MAX_ICC_PROFILE_SIZE", 4 * 1024 * 1024))
MAX_ICC_TOTAL_SIZE: int = max(MAX_ICC_PROFILE_SIZE, envint("XPRA_MAX_ICC_TOTAL_SIZE", 16 * 1024 * 1024))
MAX_ICC_TEXT_SIZE: int = 1024

ICC_BINARY_FIELDS: Sequence[str] = ("data", "icc-data", "icc-profile")
ICC_TEXT_FIELDS: Sequence[str] = (
    "source", "name", "info", "copyright", "manufacturer", "model", "description", "default-intent",
)
ICC_INTEGER_FIELDS: Sequence[str] = ("version", "components", "color-table-count")
ICC_BOOLEAN_FIELDS: Sequence[str] = ("supports-output", "wide-gamut")
ICC_FIELDS: frozenset[str] = frozenset(ICC_BINARY_FIELDS + ICC_TEXT_FIELDS + ICC_INTEGER_FIELDS + ICC_BOOLEAN_FIELDS)


def _profile_bytes(key: str, value: Any) -> bytes:
    if isinstance(value, str):
        try:
            data = value.encode("latin1")
        except UnicodeEncodeError:
            data = value.encode("utf8")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
    else:
        raise TypeError(f"ICC profile field {key!r} is not a byte string: {type(value)}")
    if len(data) > MAX_ICC_PROFILE_SIZE:
        raise ValueError(f"ICC profile field {key!r} is too large: {len(data)} bytes")
    if not data:
        return data
    if len(data) < 128:
        raise ValueError(f"ICC profile field {key!r} is too small: {len(data)} bytes")
    declared_size = int.from_bytes(data[:4], "big")
    if declared_size != len(data):
        raise ValueError(f"ICC profile field {key!r} declares {declared_size} bytes, but contains {len(data)}")
    if data[36:40] != b"acsp":
        raise ValueError(f"ICC profile field {key!r} has an invalid signature")
    return data


def _profile_text(key: str, value: Any) -> str:
    if not isinstance(value, (str, bytes)):
        raise TypeError(f"ICC profile field {key!r} is not text: {type(value)}")
    text = bytestostr(value)
    if len(text) > MAX_ICC_TEXT_SIZE:
        raise ValueError(f"ICC profile field {key!r} is too large: {len(text)} characters")
    return single_line(text)


def _validate_icc_profile(profile: Any) -> tuple[dict[str, Any], int]:
    if not isinstance(profile, Mapping):
        raise TypeError(f"ICC profile is not a dictionary: {type(profile)}")
    validated: dict[str, Any] = {}
    size = 0
    for key, value in profile.items():
        if not isinstance(key, str) or key not in ICC_FIELDS:
            raise ValueError(f"unsupported ICC profile field {key!r}")
        if key in ICC_BINARY_FIELDS:
            data = _profile_bytes(key, value)
            validated[key] = data
            size += len(data)
        elif key in ICC_TEXT_FIELDS:
            text = _profile_text(key, value)
            validated[key] = text
            size += len(text.encode("utf8"))
        elif key in ICC_INTEGER_FIELDS:
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 2**31:
                raise ValueError(f"invalid ICC profile field {key!r}: {value!r}")
            validated[key] = value
        elif key in ICC_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise TypeError(f"ICC profile field {key!r} is not a boolean: {type(value)}")
            validated[key] = value
    if size > MAX_ICC_PROFILE_SIZE:
        raise ValueError(f"ICC profile metadata is too large: {size} bytes")
    return validated, size


def validate_icc_profile(profile: Any) -> dict[str, Any]:
    """Validate and return a detached, canonical ICC profile dictionary."""
    return _validate_icc_profile(profile)[0]


def validate_icc_data(icc_data: Any) -> dict[str, Any]:
    """Validate the ``global`` and per-display ICC dictionaries carried by ``display-configure``."""
    if not isinstance(icc_data, Mapping):
        raise TypeError(f"ICC data is not a dictionary: {type(icc_data)}")
    unknown = set(icc_data).difference(("global", "display"))
    if unknown:
        raise ValueError(f"unsupported ICC data fields: {sorted(unknown, key=str)!r}")
    validated: dict[str, Any] = {}
    total_size = 0
    if "global" in icc_data:
        profile, size = _validate_icc_profile(icc_data["global"])
        validated["global"] = profile
        total_size += size
    if "display" in icc_data:
        display_data = icc_data["display"]
        if not isinstance(display_data, Mapping):
            raise TypeError(f"display ICC data is not a dictionary: {type(display_data)}")
        if len(display_data) > MAX_ICC_DISPLAYS:
            raise ValueError(f"too many display ICC profiles: {len(display_data)}")
        displays: dict[int, dict[str, Any]] = {}
        for display, raw_profile in display_data.items():
            if not isinstance(display, int) or isinstance(display, bool) or not 0 <= display < MAX_ICC_DISPLAYS:
                raise ValueError(f"invalid ICC display index {display!r}")
            profile, size = _validate_icc_profile(raw_profile)
            displays[display] = profile
            total_size += size
        validated["display"] = displays
    if total_size > MAX_ICC_TOTAL_SIZE:
        raise ValueError(f"ICC data is too large: {total_size} bytes")
    return validated
