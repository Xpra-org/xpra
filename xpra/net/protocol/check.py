# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import Packet


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
    tree = [f"{packet[0]!r} packet"]
    if not isinstance(packet[0], str):
        verify_error("packet type is not a string: %s", packet[0])
        return False
    return do_verify_packet(tree, packet)


def do_verify_packet(tree, packet) -> bool:
    def err(msg):
        verify_error("%s in %s", msg, "->".join(tree))

    def new_tree(append):
        nt = tree[:]
        nt.append(append)
        return nt

    if packet is None:
        err("None value")
        return False
    r = True
    if isinstance(packet, (list, tuple, Packet)):
        for i, x in enumerate(packet):
            if not do_verify_packet(new_tree(f"[{i}]"), x):
                r = False
    elif isinstance(packet, dict):
        for k, v in packet.items():
            if not do_verify_packet(new_tree(f"key for value={v!r}"), k):
                r = False
            if not do_verify_packet(new_tree(f"value for key={k!r}"), v):
                r = False
    elif isinstance(packet, (int, bool, str, bytes, memoryview)):
        "OK - supported"
    else:
        err(f"unsupported type: {type(packet)}")
        r = False
    return r
