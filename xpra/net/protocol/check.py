# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.util.env import envint


MAX_PACKET_NESTING = max(1, envint("XPRA_MAX_PACKET_NESTING", 32))
MAX_PACKET_CONTAINER_ITEMS = max(1, envint("XPRA_MAX_PACKET_CONTAINER_ITEMS", 65536))
MAX_PACKET_NODES = max(MAX_PACKET_CONTAINER_ITEMS, envint("XPRA_MAX_PACKET_NODES", 262144))
MAX_PACKET_TEXT_SIZE = max(1, envint("XPRA_MAX_PACKET_TEXT_SIZE", 1024 * 1024))
MAX_PATH_KEY_SIZE = 32


def format_packet_path(path) -> str:
    """Render a `(parent, step)` linked path, built by `walk_packet` when tracking the path."""
    steps = []
    while path:
        path, step = path
        steps.append(step)
    parts = ["packet"]
    for step in reversed(steps):
        if isinstance(step, int):
            parts.append(f"[{step}]")
        else:
            # dict steps are `(is_key, key)` tuples:
            is_key, key = step
            text = repr(key)
            if len(text) > MAX_PATH_KEY_SIZE:
                text = text[:MAX_PATH_KEY_SIZE] + "..."
            parts.append(f".key({text})" if is_key else f"[{text}]")
    return "".join(parts)


def packet_structure_error(packet: Packet) -> str:
    """Return an error for a decoded packet which is unsafe to dispatch."""
    if not isinstance(packet, Packet):
        return f"invalid packet type {type(packet)}"
    error, _ = walk_packet(packet.data, False)
    if not error:
        return ""
    # walk it again, this time keeping track of the path to report where the error is:
    error, path = walk_packet(packet.data, True)
    return f"{error} at {format_packet_path(path)}" if path else error


def walk_packet(data, track_path: bool) -> tuple[str, tuple | None]:
    """
    Return the first error found and its path, or an empty error string.
    Tracking the path is slower, so the caller only enables it when an error has already been found.
    The path is a linked `(parent, step)` tuple, formatted by `format_packet_path`.
    """
    stack: list[tuple[Any, int, tuple | None]] = [(data, 0, None)]
    seen_containers: set[int] = set()
    nodes = 0
    while stack:
        value, depth, path = stack.pop()
        nodes += 1
        if nodes > MAX_PACKET_NODES:
            return f"packet contains more than {MAX_PACKET_NODES} values", None
        if isinstance(value, str):
            if len(value) > MAX_PACKET_TEXT_SIZE:
                return f"packet string is too large: {len(value)} characters", path
            continue
        if isinstance(value, (bytes, memoryview, int, bool)):
            continue
        if value is None:
            return "packet contains a None value", path
        if not isinstance(value, (list, tuple, dict)):
            return f"packet contains unsupported type {type(value)}", path
        if value:
            container_id = id(value)
            if container_id in seen_containers:
                return "packet contains an aliased or cyclic container", path
            seen_containers.add(container_id)
        if depth >= MAX_PACKET_NESTING:
            return f"packet nesting exceeds {MAX_PACKET_NESTING} levels", path
        if len(value) > MAX_PACKET_CONTAINER_ITEMS:
            return f"packet container has {len(value)} items, maximum is {MAX_PACKET_CONTAINER_ITEMS}", path
        depth += 1
        if isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth, (path, (True, key)) if track_path else None))
                stack.append((item, depth, (path, (False, key)) if track_path else None))
        elif track_path:
            stack.extend((item, depth, (path, i)) for i, item in enumerate(value))
        else:
            stack.extend((item, depth, None) for item in value)
    return "", None


def verify_error(msg, *args) -> None:
    from xpra.log import Logger
    log = Logger("network")
    log.error(msg, *args)


def verify_packet(packet) -> bool:
    """ look for None values which may have caused the packet to fail encoding """
    if not packet:
        verify_error("invalid packet: %s (%s)", packet, type(packet))
        return False
    if not isinstance(packet, Packet):
        verify_error("invalid type for packet: %s", type(packet))
        return False
    if error := packet_structure_error(packet):
        verify_error("invalid packet: %s", error)
        return False
    return True
