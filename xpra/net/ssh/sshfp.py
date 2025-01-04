# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hashlib

from dns import flags
from dns.resolver import Resolver, NoAnswer, NoNameservers
from collections.abc import Callable
from xpra.log import Logger

log = Logger("ssh")

_key_algorithms: dict[str, str] = {
    'ssh-rsa': '1',
    'ssh-dss': '2',
    'ecdsa-sha2-nistp256': '3',
    'ecdsa-sha2-nistp384': '3',
    'ecdsa-sha2-nistp521': '3',
    'ssh-ed25519': '4',
}

_hash_funcs: dict[str, Callable] = {
    '1': hashlib.sha1,
    '2': hashlib.sha256,
}
if os.environ.get("XPRA_SSHFP_NOSHA1"):
    _hash_funcs.pop('1')


def check_host_key(hostname: str, key):
    try:
        return do_check_host_key(hostname, key.get_name(), key.asbytes())
    except Exception as e:
        log("check_host_key(%r, %r)", hostname, key, exc_info=True)
        return f"error checking sshfp record: {e}"


def do_check_host_key(hostname: str, keytype, keydata):
    resolver = Resolver()
    resolver.use_edns(0, flags.DO, 1280)  # type: ignore[attr-defined]
    log("do_check_host_key(%s, %s, ..) resolver=%s", hostname, keytype, resolver)

    key_alg = _key_algorithms.get(keytype)
    if key_alg is None:
        return f"Unsupported key type for SSHFP: {keytype}"
    log("key algorithm for %s: %s", keytype, key_alg)

    try:
        resp = resolver.resolve(hostname, "SSHFP", search=True)
    except (NoAnswer, NoNameservers):
        return f"could not obtain SSHFP records for host {hostname!r}"

    for item in resp:
        try:
            alg, fg_type, fg = item.to_text().split()
            log("found SSHFP record: %s", (alg, fg_type, fg))
        except ValueError:
            return "invalid SSHFP record format: " + item.to_text()

        if alg != key_alg:
            log("SSHFP record does not match algorithm")
            continue

        hash_func = _hash_funcs.get(fg_type)
        if not hash_func:
            log("unsupported hash function type: %s", fg_type)
            continue

        fg_expect = hash_func(keydata).hexdigest()
        if fg_expect == fg:
            log("found valid SSHFP record for host %s", hostname)
            if not resp.response.flags & flags.AD:  # @UndefinedVariable pylint: disable=no-member
                return "answer matches but does not have a valid DNSSEC signature"
            return True
    return "no matching SSHFP records found"


def main(argv) -> int:
    if "-v" in argv:
        log.enable_debug()
        argv.remove("-v")
    if len(argv) != 3:
        print(f"usage: {argv[0]} hostname rsaprivatekeyfile [-v]")
        return 1
    hostname = argv[1]
    keyfile = argv[2]
    from paramiko import RSAKey  # pylint: disable=import-outside-toplevel
    key = RSAKey.from_private_key_file(keyfile)
    if check_host_key(hostname, key) is True:
        return 0
    return 1


if __name__ == "__main__":
    import sys

    code = main(sys.argv)
    sys.exit(code)
