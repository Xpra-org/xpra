# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
from typing import Sequence, Any

from paramiko import PasswordRequiredException, SSHException

from xpra.net.bytestreams import SocketConnection
from xpra.net.ssh.util import LOG_EOF
from xpra.scripts.pinentry import input_pass
from xpra.util.io import load_binary_file
from xpra.util.str_fn import csv
from xpra.log import Logger
from xpra.util.thread import start_thread

log = Logger("network", "ssh")
if log.is_debug_enabled():
    import logging
    logging.getLogger("paramiko").setLevel(logging.DEBUG)


def keymd5(k) -> str:
    import binascii
    f = binascii.hexlify(k.get_fingerprint()).decode("latin1")
    s = "MD5"
    while f:
        s += ":" + f[:2]
        f = f[2:]
    return s


def get_sha256_fingerprint_for_keyfile(keyfile: str) -> str:
    import base64
    import binascii
    import hashlib
    if os.path.exists(f"{keyfile}.pub"):
        keyfile = f"{keyfile}.pub"
    with open(keyfile) as f:
        data = f.read()
    if not data:
        return ""
    if data.startswith("ssh-"):
        data = data.split(" ")[1]
    digest = hashlib.sha256(binascii.a2b_base64(data)).digest()
    # the fingerprint skips the padding at the end of the base64 encoded value:
    encoded = base64.b64encode(digest).rstrip(b'=')
    return "SHA256:" + encoded.decode("ascii")


def get_key_fingerprints(keyfiles: Sequence[str]) -> list[str]:
    allowed_key_fingerprints: list[str] = []
    failed: dict[str, str] = {}
    for keyfile in keyfiles:
        try:
            fingerprint = get_sha256_fingerprint_for_keyfile(keyfile)
            if fingerprint:
                allowed_key_fingerprints.append(fingerprint)
        except (ValueError, OSError) as e:
            if os.path.exists(keyfile):
                log(f"failed to load agent key fingerprint from {keyfile!r}: {e}")
                failed[keyfile] = str(e)
    if failed:
        log.info("unable to load key fingerprints for %s", csv(repr(keyfile) for keyfile in failed.keys()))
    return allowed_key_fingerprints


def load_private_key(keyfile_path: str):
    if not os.path.exists(keyfile_path):
        log(f"no keyfile at {keyfile_path!r}")
        return None
    log(f"trying {keyfile_path!r}")
    import paramiko
    try_key_formats: Sequence[str] = ()
    for kf in ("RSA", "DSS", "ECDSA", "Ed25519"):
        if keyfile_path.lower().endswith(kf.lower()):
            try_key_formats = (kf,)
            break
    if not try_key_formats:
        try_key_formats = ("RSA", "DSS", "ECDSA", "Ed25519")
    for pkey_classname in try_key_formats:
        pkey_class = getattr(paramiko, f"{pkey_classname}Key", None)
        if pkey_class is None:
            log(f"no {pkey_classname} key type")
            continue
        log(f"trying to load as {pkey_classname}")
        try:
            key = pkey_class.from_private_key_file(keyfile_path)
            log(f"{keyfile_path!r} as {pkey_classname}: {keymd5(key)}")
            log.info(f"loaded {pkey_classname} private key from {keyfile_path!r}")
            return key
        except PasswordRequiredException as e:
            log(f"{keyfile_path!r} keyfile requires a passphrase: {e}")
            passphrase = input_pass(f"please enter the passphrase for {keyfile_path!r}")
            if not passphrase:
                continue
            try:
                key = pkey_class.from_private_key_file(keyfile_path, passphrase)
                log.info(f"loaded {pkey_classname} private key from {keyfile_path!r}")
                return key
            except SSHException as ke:
                log("from_private_key_file", exc_info=True)
                log.info(f"cannot load key from file {keyfile_path}:")
                for emsg in str(ke).split(". "):
                    if emsg.startswith("('"):
                        emsg = emsg[2:]
                    if emsg.endswith(")."):
                        emsg = emsg[:-2]
                    if emsg:
                        log.info(" %s.", emsg)
        except Exception:
            log(f"auth_publickey() loading as {pkey_classname}", exc_info=True)
            key_data = load_binary_file(keyfile_path)
            if key_data and key_data.find(b"BEGIN OPENSSH PRIVATE KEY") >= 0:
                log(" (OpenSSH private key file)")
    return None


class SSHSocketConnection(SocketConnection):

    def __init__(self, ssh_channel, sock, sockname: str | tuple | list,
                 peername, target, info=None, socket_options=None):
        self._raw_socket = sock
        super().__init__(ssh_channel, sockname, peername, target, "ssh", info, socket_options)

    def get_raw_socket(self):
        return self._raw_socket

    def start_stderr_reader(self) -> None:
        start_thread(self._stderr_reader, "ssh-stderr-reader", daemon=True)

    def _stderr_reader(self) -> None:
        chan = self._socket
        stderr = chan.makefile_stderr("rb", 1)
        while self.active:
            v = stderr.readline()
            if not v:
                if LOG_EOF and self.active:
                    log.info("SSH EOF on stderr of %s", chan.get_name())
                break
            s = v.rstrip(b"\n\r").decode()
            if s:
                log.info(" SSH: %r", s)

    def peek(self, n) -> bytes:
        if not self._raw_socket:
            return b""
        return self._raw_socket.recv(n, socket.MSG_PEEK)

    def get_socket_info(self) -> dict[str, Any]:
        if not self._raw_socket:
            return {}
        return self.do_get_socket_info(self._raw_socket)

    def get_info(self) -> dict[str, Any]:
        i = super().get_info()
        s = self._socket
        if s:
            i["ssh-channel"] = {
                "id": s.get_id(),
                "name": s.get_name(),
            }
        return i
