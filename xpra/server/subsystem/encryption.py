# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any, NoReturn

from xpra.common import FULL_INFO
from xpra.util.io import filedata_nocrlf
from xpra.util.str_fn import strtobytes, csv, repr_ellipsized
from xpra.util.objects import typedict
from xpra.util.parsing import parse_encoded_bin_data, str_to_bool
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("crypto")

ENCRYPTED_SOCKET_TYPES = os.environ.get("XPRA_ENCRYPTED_SOCKET_TYPES", "tcp,ws")


def proto_crypto_caps(proto) -> dict[str, Any]:
    if not proto:
        return {}
    if FULL_INFO > 1 or proto.encryption:
        from xpra.net.crypto import get_crypto_caps
        return get_crypto_caps(FULL_INFO)
    return {}


def get_encryption_key(authenticators: tuple = (), keyfile: str = "") -> bytes:
    # if we have a keyfile specified, use that:
    log(f"get_encryption_key({authenticators}, {keyfile})")
    if keyfile:
        log(f"loading encryption key from keyfile {keyfile!r}")
        v = filedata_nocrlf(keyfile)
        if v:
            return v
    KVAR = "XPRA_ENCRYPTION_KEY"
    v = os.environ.get(KVAR, "")
    if v:
        log(f"using encryption key from {KVAR!r} environment variable")
        return strtobytes(v)
    if authenticators:
        for authenticator in authenticators:
            v = authenticator.get_password()
            if v:
                log(f"using password from authenticator {authenticator}")
                return v
    return b""


def setup_encryption(proto: SocketProtocol, c: typedict) -> dict[str, Any] | None:
    def fail(msg: str) -> NoReturn:
        log("setup_encryption failed: %s", msg)
        raise ValueError(msg)

    c = typedict(c.dictget("encryption") or {})
    cipher = c.strget("cipher").upper()
    log(f"setup_encryption(..) for cipher={cipher!r} : {c}")
    if not cipher:
        if proto.encryption:
            log(f"client does not provide encryption tokens: encryption={c}")
            return fail("missing encryption tokens from client")
        # no encryption requested
        return {}

    # check that the server supports encryption:
    if not proto.encryption:
        return fail("the server does not support encryption on this connection")
    server_cipher = proto.encryption.split("-")[0].upper()
    if server_cipher != cipher:
        return fail(
            f"the server is configured for {server_cipher!r} not {cipher!r} as requested by the client")
    from xpra.net.crypto import (
        DEFAULT_PADDING, ALL_PADDING_OPTIONS,
        DEFAULT_MODE, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
        DEFAULT_KEY_STRETCH, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM,
        new_cipher_caps, get_ciphers, get_key_hashes,
    )
    cipher_mode = c.strget("mode", "").upper()
    if not cipher_mode:
        cipher_mode = DEFAULT_MODE
    if proto.encryption.find("-") > 0:
        # server specifies the mode to use
        server_cipher_mode = proto.encryption.split("-")[1].upper()
        if server_cipher_mode != cipher_mode:
            return fail(f"the server is configured for {server_cipher}-{server_cipher_mode}"
                        f"not {cipher}-{cipher_mode} as requested by the client")
    cipher_iv = c.strget("iv")
    iterations = c.intget("key_stretch_iterations")
    key_salt = c.bytesget("key_salt")
    key_hash = c.strget("key_hash", DEFAULT_KEY_HASH)
    key_stretch = c.strget("key_stretch", DEFAULT_KEY_STRETCH)
    padding = c.strget("padding", DEFAULT_PADDING)
    always_pad = c.boolget("always-pad", DEFAULT_ALWAYS_PAD)
    stream = c.boolget("stream", DEFAULT_STREAM)
    padding_options = c.strtupleget("padding.options", (DEFAULT_PADDING,))
    ciphers = get_ciphers()
    if cipher not in ciphers:
        log.warn(f"Warning: unsupported cipher: {cipher!r}")
        if ciphers:
            log.warn(" should be: " + csv(ciphers))
        return fail("unsupported cipher")
    if key_stretch != "PBKDF2":
        return fail(f"unsupported key stretching {key_stretch!r}")
    encryption_key = proto.keydata or get_encryption_key(proto.authenticators, proto.keyfile)
    if not encryption_key:
        return fail("encryption key is missing")
    if padding not in ALL_PADDING_OPTIONS:
        return fail(f"unsupported padding {padding!r}")
    key_hashes = get_key_hashes()
    if key_hash not in key_hashes:
        return fail(f"unsupported key hash algorithm {key_hash!r}")
    log("setting output cipher using %s-%s encryption key '%s'",
        cipher, cipher_mode, repr_ellipsized(encryption_key))
    key_size = c.intget("key_size", DEFAULT_KEYSIZE)
    try:
        proto.set_cipher_out(cipher + "-" + cipher_mode, strtobytes(cipher_iv),
                             encryption_key, key_salt, key_hash, key_size,
                             iterations, padding, always_pad, stream)
    except ValueError as e:
        return fail(f"{e}")
    # use the same cipher as used by the client:
    encryption_caps = new_cipher_caps(proto, cipher, cipher_mode or DEFAULT_MODE, encryption_key,
                                      padding_options, always_pad, stream)
    log("server encryption=%s", encryption_caps)
    return {"encryption": encryption_caps}


def parse_encryption(protocol, socket_options: dict[str, Any], tcp_encryption: str, tcp_encryption_keyfile: str) -> None:
    protocol.encryption = socket_options.get("encryption", "")
    protocol.keyfile = socket_options.get("encryption-keyfile", "") or socket_options.get("keyfile", "")
    raw_keydata = socket_options.get("encryption-keydata", "") or socket_options.get("keydata", "")
    protocol.keydata = parse_encoded_bin_data(raw_keydata)
    conn = getattr(protocol, "_conn", None)
    socktype = getattr(conn, "socktype", "")
    if socktype in ENCRYPTED_SOCKET_TYPES:
        # special case for legacy encryption code:
        protocol.encryption = protocol.encryption or tcp_encryption
        protocol.keyfile = protocol.keyfile or tcp_encryption_keyfile
    enc = (protocol.encryption or "").lower()
    if enc and not enc.startswith("aes") and not str_to_bool(enc, False):
        protocol.encryption = None
    log("%s: encryption=%s, keyfile=%s", socktype, protocol.encryption, protocol.keyfile)
    if protocol.encryption:
        from xpra.net.crypto import crypto_backend_init
        crypto_backend_init()
        from xpra.net.crypto import (
            ENCRYPT_FIRST_PACKET,
            DEFAULT_IV,
            DEFAULT_SALT,
            DEFAULT_KEY_HASH,
            DEFAULT_KEYSIZE,
            DEFAULT_ITERATIONS,
            DEFAULT_ALWAYS_PAD,
            DEFAULT_STREAM,
            INITIAL_PADDING,
        )
        if ENCRYPT_FIRST_PACKET:
            log(f"encryption={protocol.encryption}, keyfile={protocol.keyfile!r}")
            password = protocol.keydata or get_encryption_key((), protocol.keyfile)
            iv = strtobytes(DEFAULT_IV)
            protocol.set_cipher_in(protocol.encryption, iv,
                                   password, DEFAULT_SALT, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                   DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM)
    log(f"encryption={protocol.encryption}, keyfile={protocol.keyfile!r}")


class EncryptionServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.encryption = ""
        self.encryption_keyfile = ""
        self.tcp_encryption = ""
        self.tcp_encryption_keyfile = ""

    def init(self, opts) -> None:
        self.encryption = opts.encryption
        self.encryption_keyfile = opts.encryption_keyfile
        self.tcp_encryption = opts.tcp_encryption
        self.tcp_encryption_keyfile = opts.tcp_encryption_keyfile
        if self.encryption or self.tcp_encryption:
            from xpra.net.crypto import crypto_backend_init  # pylint: disable=import-outside-toplevel
            crypto_backend_init()

    def get_caps(self, source) -> dict[str, Any]:
        return proto_crypto_caps(None if source is None else source.protocol)

    def parse_encryption(self, protocol, socket_options: dict[str, Any]) -> None:
        return parse_encryption(protocol, socket_options, self.tcp_encryption, self.tcp_encryption_keyfile)

    def get_info(self, _proto) -> dict[str, Any]:
        if FULL_INFO:
            return {
                "encryption": self.encryption or "",
                "tcp-encryption": self.tcp_encryption or "",
            }
        return {}
