# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hmac
import hashlib
from collections.abc import Callable, Sequence

from xpra.common import SizedBuffer
from xpra.util.str_fn import csv, strtobytes, hexstr, memoryview_to_bytes
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("network", "crypto")

BLOCKLISTED_HASHES = ("sha1", "md5")
DEFAULT_SALT_LENGTH = envint("XPRA_DEFAULT_SALT_LENGTH", 64)


def get_digests() -> Sequence[str]:
    digests = ["xor"]
    digests += [f"hmac+{x}" for x in tuple(reversed(sorted(hashlib.algorithms_available)))
                if not x.startswith("shake_") and x not in BLOCKLISTED_HASHES and getattr(hashlib, x, None) is not None]
    try:
        from xpra.net.rfb import d3des  # pylint: disable=import-outside-toplevel
        assert d3des
        digests.append("des")
    except (ImportError, TypeError):  # pragma: no cover
        pass
    return tuple(digests)


def get_digest_module(digest: str) -> Callable | None:
    log(f"get_digest_module({digest})")
    if not digest or not digest.startswith("hmac"):
        return None
    try:
        digest_module = digest.split("+")[1]  # ie: "hmac+sha512" -> "sha512"
    except IndexError:
        return None
    try:
        return getattr(hashlib, digest_module)
    except AttributeError as e:
        log("no '%s' attribute in hashlib: %s", digest_module, e)
        return None


def choose_digest(options: Sequence[str]) -> str:
    assert len(options) > 0, "no digest options"
    log(f"choose_digest({options})")
    # prefer stronger hashes:
    for h in ("sha512", "sha384", "sha256", "sha224"):
        hname = f"hmac+{h}"
        if hname in options:
            return hname
    if "xor" in options:
        return "xor"
    if "des" in options:
        return "des"
    raise ValueError(f"no known digest options found in '{csv(options)}'")


def gendigest(digest: str, password_in, salt_in: SizedBuffer) -> bytes:
    assert password_in and salt_in
    salt: bytes = memoryview_to_bytes(salt_in)
    password: bytes = strtobytes(password_in)
    if digest == "des":
        from xpra.net.rfb.d3des import generate_response  # pylint: disable=import-outside-toplevel
        password = password.ljust(8, b"\x00")[:8]
        salt = salt.ljust(16, b"\x00")[:16]
        v = generate_response(password, salt)
        return strtobytes(hexstr(v))
    if digest in ("xor", "kerberos", "gss", "keycloak"):
        # kerberos, gss and keycloak use xor because we need to use the actual token
        # at the other end
        salt = salt.ljust(len(password), b"\x00")[:len(password)]
        from xpra.buffers.cyxor import xor_str  # pylint: disable=import-outside-toplevel
        v = xor_str(password, salt)
        return memoryview_to_bytes(v)
    digestmod = get_digest_module(digest)
    if not digestmod:
        log(f"invalid digest module {digest!r}")
        return b""
        # warn_server_and_exit(ExitCode.UNSUPPORTED,
        #    "server requested digest '%s' but it is not supported" % digest, "invalid digest")
    return strtobytes(hmac.new(password, salt, digestmod=digestmod).hexdigest())


def verify_digest(digest: str, password: str, salt, challenge_response: bytes) -> bool:
    log("verify_digest%s", (digest, "..", salt, challenge_response))
    if not (digest and password and salt and challenge_response):
        log("digest: missing argument")
        return False
    verify = gendigest(digest, password, salt)
    verified = hmac.compare_digest(verify, challenge_response)
    log("verify_digest(..) %r vs %r", verify, challenge_response)
    if not verified:
        log(f"expected {verify!r} but got {challenge_response!r}")
    return verified


def get_salt(length: int = DEFAULT_SALT_LENGTH) -> bytes:
    # too short: we would not feed enough random data to HMAC
    if length < 32:
        raise ValueError(f"salt is too short: only {length} bytes")
    # too long: limit the amount of random data we request from the system
    if length >= 1024:
        raise ValueError(f"salt is too long: {length} bytes")
    # all server versions support a client salt,
    # they also tell us which digest to use:
    return os.urandom(length)
