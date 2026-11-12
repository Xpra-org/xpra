# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import Packet
from xpra.util.env import envint


MAX_PACKET_NESTING = max(1, envint("XPRA_MAX_PACKET_NESTING", 32))
MAX_PACKET_CONTAINER_ITEMS = max(1, envint("XPRA_MAX_PACKET_CONTAINER_ITEMS", 65536))
MAX_PACKET_NODES = max(MAX_PACKET_CONTAINER_ITEMS, envint("XPRA_MAX_PACKET_NODES", 262144))
MAX_PACKET_TEXT_SIZE = max(1, envint("XPRA_MAX_PACKET_TEXT_SIZE", 1024 * 1024))


def packet_structure_error(packet: Packet) -> str:
    """Return an error for a decoded packet which is unsafe to dispatch."""
    if not isinstance(packet, Packet):
        return f"invalid packet type {type(packet)}"
    stack = [(packet.data, 0)]
    seen_containers: set[int] = set()
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_PACKET_NODES:
            return f"packet contains more than {MAX_PACKET_NODES} values"
        if isinstance(value, str):
            if len(value) > MAX_PACKET_TEXT_SIZE:
                return f"packet string is too large: {len(value)} characters"
            continue
        if isinstance(value, (bytes, memoryview, int, bool)):
            continue
        if value is None:
            return "packet contains a None value"
        if not isinstance(value, (list, tuple, dict)):
            return f"packet contains unsupported type {type(value)}"
        if value:
            container_id = id(value)
            if container_id in seen_containers:
                return "packet contains an aliased or cyclic container"
            seen_containers.add(container_id)
        if depth >= MAX_PACKET_NESTING:
            return f"packet nesting exceeds {MAX_PACKET_NESTING} levels"
        if len(value) > MAX_PACKET_CONTAINER_ITEMS:
            return f"packet container has {len(value)} items, maximum is {MAX_PACKET_CONTAINER_ITEMS}"
        if isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        else:
            stack.extend((item, depth + 1) for item in value)
    return ""


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
