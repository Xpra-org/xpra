#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel

from collections import namedtuple
from threading import Lock
from typing import Callable, Any, Tuple, Dict

from xpra.log import Logger
from xpra.net.protocol.header import (
    FLAGS_RENCODE, FLAGS_RENCODEPLUS, FLAGS_YAML, FLAGS_BENCODE, FLAGS_NOHEADER,
    pack_header,
    )
from xpra.os_util import strtobytes
from xpra.util import envbool

#all the encoders we know about, in the best compatibility order:
ALL_ENCODERS : Tuple[str, ...] = ("rencodeplus", "bencode", "yaml", "rencode", "none")
#order for performance:
PERFORMANCE_ORDER : Tuple[str, ...] = ("rencodeplus", "rencode", "bencode", "yaml")

Encoding = namedtuple("Encoding", ["name", "flag", "version", "encode", "decode"])

ENCODERS : Dict[str,Encoding] = {}


def init_rencode() -> Encoding:
    import rencode  # @UnresolvedImport
    rencode_lock = Lock()
    rencode_dumps = rencode.dumps
    def do_rencode(v):
        with rencode_lock:
            return rencode_dumps(v), FLAGS_RENCODE
    return Encoding("rencode", FLAGS_RENCODE, rencode.__version__, do_rencode, rencode.loads)

def init_rencodeplus() -> Encoding:
    from xpra.net.rencodeplus import rencodeplus    # type: ignore[attr-defined]
    rencodeplus_dumps = rencodeplus.dumps  # @UndefinedVariable
    def do_rencodeplus(v):
        return rencodeplus_dumps(v), FLAGS_RENCODEPLUS
    return Encoding("rencodeplus", FLAGS_RENCODEPLUS, rencodeplus.__version__, do_rencodeplus, rencodeplus.loads)  # @UndefinedVariable

def init_bencode() -> Encoding:
    from xpra.net.bencode import bencode, bdecode, __version__
    def do_bencode(v):
        return bencode(v), FLAGS_BENCODE
    def do_bdecode(data):
        packet, l = bdecode(data)
        if len(data)!=l:
            raise RuntimeError(f"expected {l} bytes, but got {len(data)}")
        return packet
    return Encoding("bencode", FLAGS_BENCODE, __version__, do_bencode, do_bdecode)

def init_yaml() -> Encoding:
    #json messes with strings and unicode (makes it unusable for us)
    from yaml import dump, safe_load, __version__
    def yaml_dump(v):
        return dump(v).encode("latin1"), FLAGS_YAML
    return Encoding("yaml", FLAGS_YAML, __version__, yaml_dump, safe_load)

def init_none() -> Encoding:
    def encode(data):
        #just send data as a string for clients that don't understand xpra packet format:
        import codecs
        def b(x):
            if isinstance(x, bytes):
                return x
            return codecs.latin_1_encode(x)[0]
        return b(": ".join(str(x) for x in data)+"\n"), FLAGS_NOHEADER
    return Encoding("none", FLAGS_NOHEADER, 0, encode, None)


def init_encoders(*names) -> None:
    for x in names:
        if x not in ALL_ENCODERS:
            logger = Logger("network", "protocol")
            logger.warn("Warning: invalid encoder '%s'", x)
            continue
        if not envbool("XPRA_"+x.upper(), True):
            continue
        fn = globals().get(f"init_{x}")
        try:
            assert callable(fn)
            e = fn()
            assert e
            ENCODERS[x] = e
        except (ImportError, AttributeError, AssertionError):
            logger = Logger("network", "protocol")
            logger.debug("no %s", x, exc_info=True)

def init_all() -> None:
    init_encoders(*(list(ALL_ENCODERS)+["none"]))


def get_packet_encoding_caps(full_info : int=1) -> Dict[str,Any]:
    caps : Dict[str,Any] = {}
    for name in ALL_ENCODERS:
        d = caps.setdefault(name, {})
        e = ENCODERS.get(name)
        d[""] = e is not None
        if e is None:
            continue
        if full_info>1 and e.version:
            d["version"] = e.version
    return caps

def get_enabled_encoders(order: Tuple[str, ...]=ALL_ENCODERS) -> Tuple[str, ...]:
    return tuple(x for x in order if x in ENCODERS)


def get_encoder(e) -> Callable:
    if e not in ALL_ENCODERS:
        raise ValueError(f"invalid encoder name {e!r}")
    if e not in ENCODERS:
        raise ValueError(f"{e!r} is not available")
    return ENCODERS[e].encode

def get_packet_encoding_type(protocol_flags:int) -> str:
    if protocol_flags & FLAGS_RENCODEPLUS:
        return "rencodeplus"
    if protocol_flags & FLAGS_RENCODE:
        return "rencode"
    if protocol_flags & FLAGS_YAML:
        return "yaml"
    return "bencode"


class InvalidPacketEncodingException(Exception):
    pass


def pack_one_packet(packet:Tuple) -> bytes:
    ee = get_enabled_encoders()
    if ee:
        e = get_encoder(ee[0])
        data, flags = e(packet)
        return pack_header(flags, 0, 0, len(data))+data
    return strtobytes(packet)


def decode(data, protocol_flags:int):
    if isinstance(data, memoryview):
        data = data.tobytes()
    ptype = get_packet_encoding_type(protocol_flags)
    e = ENCODERS.get(ptype)
    if e:
        return e.decode(data)
    raise InvalidPacketEncodingException(f"{ptype!r} decoder is not available")


def main(): # pragma: no cover
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    with program_context("Packet Encoding", "Packet Encoding Info"):
        init_all()
        print_nested_dict(get_packet_encoding_caps())


if __name__ == "__main__":  # pragma: no cover
    main()
