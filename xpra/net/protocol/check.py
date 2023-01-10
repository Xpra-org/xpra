# This file is part of Xpra.
# Copyright (C) 2011-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def verify_packet(packet):
    """ look for None values which may have caused the packet to fail encoding """
    if not isinstance(packet, list):
        return False
    if not packet:
        raise ValueError(f"invalid packet: {packet} ({type(packet)})")
    tree = [f"{packet[0]!r} packet"]
    return do_verify_packet(tree, packet)

def do_verify_packet(tree, packet):
    def err(msg):
        from xpra.log import Logger
        log = Logger("network")
        log.error("%s in %s", msg, "->".join(tree))
    def new_tree(append):
        nt = tree[:]
        nt.append(append)
        return nt
    if packet is None:
        err("None value")
        return False
    r = True
    if isinstance(packet, (list, tuple)):
        for i, x in enumerate(packet):
            if not do_verify_packet(new_tree(f"[{i}]"), x):
                r = False
    elif isinstance(packet, dict):
        for k,v in packet.items():
            if not do_verify_packet(new_tree(f"key for value={v!r}"), k):
                r = False
            if not do_verify_packet(new_tree(f"value for key={k!r}"), v):
                r = False
    elif isinstance(packet, (int, bool, str, bytes, memoryview)):
        pass
    else:
        err(f"unsupported type: {type(packet)}")
        r = False
    return r
