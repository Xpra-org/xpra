#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.log import Logger
log = Logger("network", "protocol")
from xpra.net.header import FLAGS_RENCODE, FLAGS_YAML   #, FLAGS_BENCODE


rencode_dumps, rencode_loads, rencode_version = None, None, None
try:
    try:
        import rencode
        rencode_dumps = rencode.dumps
        rencode_loads = rencode.loads
        try:
            log("loaded rencode version %s from %s", rencode.__version__, rencode.__file__)
        except:
            log.warn("rencode at '%s' lacks versioning information", rencode.__file__)
            rencode_version = "unknown"
    except ImportError as e:
        log.warn("rencode import error: %s", e)
except Exception as e:
    log.error("error loading rencode", exc_info=True)
has_rencode = rencode_dumps is not None and rencode_loads is not None and rencode_version is not None
use_rencode = has_rencode and os.environ.get("XPRA_USE_RENCODER", "1")=="1"
log("packet encoding: has_rencode=%s, use_rencode=%s, version=%s", has_rencode, use_rencode, rencode_version)


bencode, bdecode, bencode_version = None, None, None
if sys.version_info[0]<3:
    #bencode needs porting to Python3..
    try:
        try:
            from xpra.net.bencode import bencode, bdecode, __version__ as bencode_version
        except ImportError as e:
            log.warn("bencode import error: %s", e, exc_info=True)
    except Exception as e:
        log.error("error loading bencoder", exc_info=True)
has_bencode = bencode is not None and bdecode is not None
use_bencode = has_bencode and os.environ.get("XPRA_USE_BENCODER", "1")=="1"
log("packet encoding: has_bencode=%s, use_bencode=%s, version=%s", has_bencode, use_bencode, bencode_version)


yaml_encode, yaml_decode, yaml_version = None, None, None
try:
    #json messes with strings and unicode (makes it unusable for us)
    import yaml
    yaml_encode = yaml.dump
    yaml_decode = yaml.load
    yaml_version = yaml.__version__
except ImportError:
    log("yaml not found")
has_yaml = yaml_encode is not None and yaml_decode is not None
use_yaml = has_yaml and os.environ.get("XPRA_USE_YAML", "1")=="1"
log("packet encoding: has_yaml=%s, use_yaml=%s, version=%s", has_yaml, use_yaml, yaml_version)


def do_bencode(data):
    return bencode(data), 0

def do_rencode(data):
    return  rencode_dumps(data), FLAGS_RENCODE

def do_yaml(data):
    return yaml_encode(data), FLAGS_YAML


def get_packet_encoding_caps():
    caps = {
            "rencode"               : use_rencode,
            "bencode"               : use_bencode,
            "yaml"                  : use_yaml,
           }
    if has_rencode:
        assert rencode_version is not None
        caps["rencode.version"] = rencode_version
    if has_bencode:
        assert bencode_version is not None
        caps["bencode.version"] = bencode_version
    if has_yaml:
        assert yaml_version is not None
        caps["yaml.version"] = yaml_version
    return caps


#all the encoders we know about, in best compatibility order:
ALL_ENCODERS = ["bencode", "rencode", "yaml"]

#order for performance:
PERFORMANCE_ORDER = ["rencode", "bencode", "yaml"]

_ENCODERS = {
        "rencode"   : do_rencode,
        "bencode"   : do_bencode,
        "yaml"      : do_yaml,
           }

def get_enabled_encoders(order=ALL_ENCODERS):
    enabled = [x for x,b in {
                "rencode"               : use_rencode,
                "bencode"               : use_bencode,
                "yaml"                  : use_yaml,
                }.items() if b]
    log("get_enabled_encoders(%s) enabled=%s", order, enabled)
    #order them:
    return [x for x in order if x in enabled]


def get_encoder(e):
    assert e in ALL_ENCODERS, "invalid encoder name: %s" % e
    assert e in get_enabled_encoders(), "%s is not available" % e
    return _ENCODERS[e]

def get_encoder_name(e):
    assert e in _ENCODERS.values(), "invalid encoder: %s" % e
    for k,v in _ENCODERS.items():
        if v==e:
            return k
    raise Exception("impossible bug!")


def get_packet_encoding_type(protocol_flags):
    if protocol_flags & FLAGS_RENCODE:
        return "rencode"
    elif protocol_flags & FLAGS_YAML:
        return "yaml"
    else:
        return "bencode"


class InvalidPacketEncodingException(Exception):
    pass


def decode(data, protocol_flags):
    if protocol_flags & FLAGS_RENCODE:
        if not has_rencode:
            raise InvalidPacketEncodingException("rencode is not available")
        if not use_rencode:
            raise InvalidPacketEncodingException("rencode is disabled")
        return list(rencode_loads(data))
    elif protocol_flags & FLAGS_YAML:
        if not has_yaml:
            raise InvalidPacketEncodingException("yaml is not available")
        if not use_yaml:
            raise InvalidPacketEncodingException("yaml is disabled")
        return list(yaml_decode(data))
    else:
        if not has_bencode:
            raise InvalidPacketEncodingException("bencode is not available")
        if not use_bencode:
            raise InvalidPacketEncodingException("bencode is disabled")
        #if sys.version>='3':
        #    data = data.decode("latin1")
        packet, l = bdecode(data)
        assert l==len(data)
        return packet


def main():
    from xpra.platform import init, clean
    try:
        init("Packet Encoding", "Packet Encoding Info")
        for k,v in sorted(get_packet_encoding_caps().items()):
            print(k.ljust(20)+": "+str(v))
    finally:
        #this will wait for input on win32:
        clean()


if __name__ == "__main__":
    main()
