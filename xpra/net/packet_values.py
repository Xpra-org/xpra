# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Bounds checks for the free-form values found in packets received from a peer we do not trust,
ie: the options of `window-draw` and `webcam-frame` packets, or the `audio-data` metadata.
"""

# limits for the values we do not validate more specifically:
MAX_KEY_SIZE: int = 64
MAX_VALUE_ITEMS: int = 64
MAX_VALUE_SIZE: int = 1024
MAX_VALUE_DEPTH: int = 2


def check_key(key, what="option") -> None:
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_SIZE:
        raise ValueError(f"invalid {what} key {key!r}")


def check_value(key: str, value, what="option", depth: int = 0, max_depth: int = MAX_VALUE_DEPTH) -> None:
    """
    verify that `value` only contains scalars, strings and containers,
    with bounded sizes and nesting depth, raises `ValueError` or `TypeError`
    """
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, (str, bytes)):
        if len(value) > MAX_VALUE_SIZE:
            raise ValueError(f"{what} {key!r} is too large: {len(value)} bytes")
        return
    if isinstance(value, (tuple, list, dict)):
        if depth >= max_depth:
            raise ValueError(f"{what} {key!r} is nested too deeply")
        if len(value) > MAX_VALUE_ITEMS:
            raise ValueError(f"{what} {key!r} has too many items: {len(value)}")
        if isinstance(value, dict):
            for k, v in value.items():
                check_key(k, what)
                check_value(f"{key}.{k}", v, what, depth + 1, max_depth)
        else:
            for v in value:
                check_value(key, v, what, depth + 1, max_depth)
        return
    raise TypeError(f"invalid type for {what} {key!r}: {type(value)}")


def get_int_tuples(value, key: str, size: int, max_items: int, limit: int, what="option") -> tuple[tuple[int, ...], ...]:
    """ a sequence of at most `max_items` tuples of `size` integers, all within -`limit` and `limit` """
    if not isinstance(value, (tuple, list)) or len(value) > max_items:
        raise ValueError(f"invalid {what} {key!r}")
    items = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != size:
            raise ValueError(f"invalid {what} {key!r} item {item!r}")
        if any(not isinstance(v, int) or isinstance(v, bool) or abs(v) > limit for v in item):
            raise ValueError(f"invalid {what} {key!r} item {item!r}")
        items.append(tuple(item))
    return tuple(items)


def get_mmap_chunks(value, max_chunks: int, what="option") -> tuple[tuple[int, int], ...]:
    """ the `(offset, length)` pairs describing data written to an mmap area """
    chunks = get_int_tuples(value, "chunks", 2, max_chunks, 2**32, what)
    if any(offset < 0 or length <= 0 for offset, length in chunks):
        raise ValueError(f"invalid mmap chunks: {chunks!r}")
    return chunks  # type: ignore[return-value]


def get_int(value, key: str, limit: int = 2**63, what="option") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or abs(value) >= limit:
        raise ValueError(f"invalid {what} {key!r}: {value!r}")
    return value
