# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util.str_fn import csv
from xpra.net.ssl.common import get_ssl_logger
from xpra.scripts.config import InitException


def parse_ssl_options_mask(options: str):
    # parse ssl-options as CSV to an int bitmask:
    import ssl
    ssl_options = 0
    for x in options.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "OP_" + x.upper(), None)
        if v is None:
            raise InitException(f"invalid ssl option: {x!r}")
        ssl_options |= v
    get_ssl_logger().debug(" options=%#x", ssl_options)
    return ssl_options


def parse_ssl_verify_mask(verify_flags: str) -> int:
    # parse ssl-verify-flags as CSV:
    import ssl
    ssl_verify_flags = 0
    for x in verify_flags.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "VERIFY_" + x.upper(), None)
        if v is None:
            raise InitException(f"invalid ssl verify-flag: {x!r}")
        ssl_verify_flags |= v
    get_ssl_logger().debug(" verify-flags=%#x", ssl_verify_flags)
    return int(ssl_verify_flags)


def parse_ssl_protocol(protocol: str, server_side=True):
    import ssl
    if protocol.lower() in ("tls", "auto"):
        return ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLSv1_2
    proto = getattr(ssl, "PROTOCOL_" + protocol.upper().replace("TLSV", "TLSv"), None)
    if proto is None:
        values = [k[len("PROTOCOL_"):] for k in dir(ssl) if k.startswith("PROTOCOL_")]
        raise InitException(f"invalid ssl-protocol {protocol!r}, must be one of: " + csv(values))
    return proto


def parse_ssl_verify_mode(verify_mode_str: str):
    # parse verify-mode:
    import ssl
    ssl_cert_reqs = getattr(ssl, "CERT_" + verify_mode_str.upper(), None)
    if ssl_cert_reqs is None:
        values = [k[len("CERT_"):].lower() for k in dir(ssl) if k.startswith("CERT_")]
        raise InitException(f"invalid ssl verify-mode {verify_mode_str!r}, must be one of: " + csv(values))
    get_ssl_logger().debug(" verify-mode(%s)=%s", verify_mode_str, ssl_cert_reqs)
    return ssl_cert_reqs
