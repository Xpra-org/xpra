# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Validation of the values found in clipboard packets:
the peer is not trusted, selection, target and type names must be short and printable
- those names may become X11 atoms - and the clipboard data is bounded before it reaches the clipboard proxies.
"""

import struct
from typing import Any
from collections.abc import Sequence

from xpra.net.packet_values import get_int
from xpra.util.env import envint
from xpra.util.str_fn import repr_ellipsized

MAX_SELECTION_NAME: int = 64
MAX_SELECTIONS: int = 8
MAX_TARGET_NAME: int = 256
# each target may become an X11 atom, and those are never freed:
MAX_CLIPBOARD_TARGETS: int = envint("XPRA_MAX_CLIPBOARD_TARGETS", 100)
MAX_CLIPBOARD_ORIGIN_SIZE: int = 64
MAX_CLIPBOARD_OPTIONS: int = 16
MAX_WIRE_ENCODING: int = 16

WIRE_ENCODINGS: Sequence[str] = ("bytes", "integers", "atoms")
# the size of each item, in bytes, for each X11 property format:
# (format 32 is a C `long`, which is 8 bytes on 64-bit platforms)
FORMAT_SIZES: dict[int, int] = {8: 1, 16: 2, 32: struct.calcsize(b"@L")}


def get_name(value, max_size: int = MAX_TARGET_NAME, what: str = "target") -> str:
    """
    selection, target and type names: printable ASCII, from 1 to `max_size` characters,
    raises `ValueError` otherwise
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            value = bytes(value).decode("ascii")
        except UnicodeDecodeError:
            raise ValueError(f"invalid clipboard {what} name {repr_ellipsized(value)}") from None
    if not isinstance(value, str) or not 0 < len(value) <= max_size or not all(" " <= c <= "~" for c in value):
        raise ValueError(f"invalid clipboard {what} name {repr_ellipsized(value)}")
    return value


def get_selection(value) -> str:
    return get_name(value, MAX_SELECTION_NAME, "selection")


def get_names(values, what: str = "target") -> tuple[str, ...]:
    """ the valid names from a sequence, the invalid ones are dropped """
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"expected a sequence of clipboard {what} names, got a {type(values)}")
    names = []
    for value in values:
        try:
            names.append(get_name(value, what=what))
        except ValueError:
            pass
    return tuple(names)


def parse_wire_data(encoding: str, dformat: int, data, max_size: int) -> tuple[Any, int]:
    """
    validate clipboard data in wire format, returns the data and its size in bytes,
    raises `ValueError` or `TypeError` if the data is malformed or larger than `max_size`
    """
    if encoding not in WIRE_ENCODINGS:
        raise ValueError(f"invalid clipboard wire encoding {repr_ellipsized(encoding)}")
    item_size = FORMAT_SIZES.get(dformat, 0)
    if not item_size:
        raise ValueError(f"invalid clipboard data format {dformat!r}")
    if encoding == "bytes":
        if isinstance(data, str):
            # the html5 client sends strings:
            data = data.encode("utf8")
        elif not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"invalid clipboard data type {type(data)} for 'bytes' encoding")
        size = len(data)
    elif encoding == "integers":
        if not isinstance(data, (tuple, list)):
            raise TypeError(f"invalid clipboard data type {type(data)} for 'integers' encoding")
        size = len(data) * item_size
        if size > max_size:
            raise ValueError(f"clipboard data is too large: {size} bytes, maximum is {max_size}")
        limit = 2 ** (8 * item_size)
        if any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < limit for v in data):
            raise ValueError(f"invalid {dformat}-bit clipboard integers {repr_ellipsized(data)}")
        data = tuple(data)
    else:
        data = get_names(data)
        size = sum(len(name) for name in data)
    if size > max_size:
        raise ValueError(f"clipboard data is too large: {size} bytes, maximum is {max_size}")
    return data, size


def parse_clipboard_data_items(items, max_size: int) -> dict[str, tuple[str, int, str, Any]]:
    """
    the `data` option of `clipboard-data` packets:
    exactly 4 fields for each target, and all the targets share the `max_size` byte budget
    """
    if not isinstance(items, dict):
        raise TypeError(f"invalid clipboard data type {type(items)}")
    if len(items) > MAX_CLIPBOARD_TARGETS:
        raise ValueError(f"too much clipboard data: {len(items)} targets, maximum is {MAX_CLIPBOARD_TARGETS}")
    budget = max_size
    data = {}
    for target, item in items.items():
        target = get_name(target)
        if not isinstance(item, (tuple, list)) or len(item) != 4:
            raise ValueError(f"invalid clipboard data for target {target!r}: {repr_ellipsized(item)}")
        dtype = get_name(item[0], what="type")
        dformat = get_int(item[1], "format", 256, "clipboard data")
        encoding = item[2]
        if not isinstance(encoding, str):
            raise TypeError(f"invalid clipboard wire encoding type {type(encoding)}")
        wire_data, size = parse_wire_data(encoding, dformat, item[3], budget)
        budget -= size
        data[target] = (dtype, dformat, encoding, wire_data)
    return data
