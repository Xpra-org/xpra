# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.client.base.stub import StubClientMixin
from xpra.util.str_fn import csv, strtobytes, Ellipsizer
from xpra.util.io import filedata_nocrlf
from xpra.scripts.config import InitExit
from xpra.util.parsing import parse_encoded_bin_data
from xpra.exit_codes import ExitCode
from xpra.net.crypto import (
    crypto_backend_init, get_iterations, get_iv, choose_padding,
    get_ciphers, get_modes, get_key_hashes, get_salt,
    ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT, DEFAULT_STREAM,
    DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS,
    DEFAULT_MODE, DEFAULT_KEYSIZE, DEFAULT_KEY_HASH, DEFAULT_KEY_STRETCH, DEFAULT_ALWAYS_PAD,
)
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("crypto")


class AESClient(StubClientMixin):
    """
    Adds tcp encryption feature
    """

    def __init__(self):
        self.encryption = None
        self.encryption_keyfile = None
        self.server_padding_options = [DEFAULT_PADDING]

    def init(self, opts) -> None:
        self.encryption = opts.encryption or opts.tcp_encryption
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile

    def get_info(self) -> dict[str, tuple]:
        return {}

    def get_caps(self) -> dict[str, Any]:
        cipher_caps = self.get_cipher_caps()
        if cipher_caps:
            return {"encryption": cipher_caps}
        return {}

    def get_cipher_caps(self) -> dict[str, Any]:
        encryption = self.get_encryption()
        log(f"encryption={encryption}")
        if not encryption:
            return {}
        crypto_backend_init()
        enc, mode = (encryption + "-").split("-")[:2]
        if not mode:
            mode = DEFAULT_MODE
        ciphers = get_ciphers()
        if enc not in ciphers:
            raise ValueError(f"invalid encryption {enc!r}, options: {csv(ciphers) or 'none'}")
        modes = get_modes()
        if mode not in modes:
            raise ValueError(f"invalid encryption mode {mode!r}, options: {csv(modes) or 'none'}")
        iv = get_iv()
        key_salt = get_salt()
        iterations = get_iterations()
        padding = choose_padding(self.server_padding_options)
        always_pad = DEFAULT_ALWAYS_PAD
        stream = DEFAULT_STREAM
        cipher_caps: dict[str, Any] = {
            "cipher": enc,
            "mode": mode,
            "iv": iv,
            "key_salt": key_salt,
            "key_size": DEFAULT_KEYSIZE,
            "key_hash": DEFAULT_KEY_HASH,
            "key_stretch": DEFAULT_KEY_STRETCH,
            "key_stretch_iterations": iterations,
            "padding": padding,
            "padding.options": PADDING_OPTIONS,
            "always-pad": always_pad,
            "stream": stream,
        }
        log(f"cipher_caps={cipher_caps}")
        key = self.get_encryption_key()
        self._protocol.set_cipher_in(encryption, strtobytes(iv),
                                     key, key_salt, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                     iterations, padding, always_pad, stream)
        return cipher_caps

    def setup_connection(self, conn) -> None:
        if self._protocol.TYPE == "rfb":
            return
        encryption = self.get_encryption()
        if encryption and ENCRYPT_FIRST_PACKET:
            key = self.get_encryption_key()
            self._protocol.set_cipher_out(encryption, strtobytes(DEFAULT_IV),
                                          key, DEFAULT_SALT, DEFAULT_KEY_HASH, DEFAULT_KEYSIZE,
                                          DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_ALWAYS_PAD, DEFAULT_STREAM)

    def parse_server_capabilities(self, caps: typedict) -> bool:  # pylint: disable=unused-argument
        p = self._protocol
        if not p:
            return False
        encryption = self.get_encryption()
        if encryption:
            # server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(caps, key):
                return False
        return True

    def set_server_encryption(self, caps: typedict, key: bytes) -> bool:
        caps = typedict(caps.dictget("encryption") or {})
        cipher = caps.strget("cipher")
        cipher_mode = caps.strget("mode", DEFAULT_MODE)
        cipher_iv = caps.strget("iv")
        key_salt = caps.bytesget("key_salt")
        key_hash = caps.strget("key_hash", DEFAULT_KEY_HASH)
        key_size = caps.intget("key_size", DEFAULT_KEYSIZE)
        key_stretch = caps.strget("key_stretch", DEFAULT_KEY_STRETCH)
        iterations = caps.intget("key_stretch_iterations")
        padding = caps.strget("padding", DEFAULT_PADDING)
        always_pad = caps.boolget("always-pad", DEFAULT_ALWAYS_PAD)
        stream = caps.boolget("stream", DEFAULT_STREAM)
        ciphers = get_ciphers()
        key_hashes = get_key_hashes()
        # server may tell us what it supports,
        # either from hello response or from challenge packet:
        self.server_padding_options = caps.strtupleget("padding.options", (DEFAULT_PADDING,))

        def fail(msg) -> bool:
            self.warn_and_quit(ExitCode.ENCRYPTION, msg)
            return False

        if key_stretch != "PBKDF2":
            return fail(f"unsupported key stretching {key_stretch}")
        if not cipher or not cipher_iv:
            return fail("the server does not use or support encryption/password, cannot continue")
        if cipher not in ciphers:
            return fail(f"unsupported server cipher: {cipher}, allowed ciphers: {csv(ciphers)}")
        if padding not in ALL_PADDING_OPTIONS:
            return fail(f"unsupported server cipher padding: {padding}, allowed paddings: {csv(ALL_PADDING_OPTIONS)}")
        if key_hash not in key_hashes:
            return fail(f"unsupported key hashing: {key_hash}, allowed algorithms: {csv(key_hashes)}")
        p = self._protocol
        if not p:
            return False
        p.set_cipher_out(cipher + "-" + cipher_mode, strtobytes(cipher_iv),
                         key, key_salt, key_hash, key_size,
                         iterations, padding, always_pad, stream)
        return True

    def get_encryption(self) -> str:
        p = self._protocol
        if not p:
            return ""
        conn = p._conn
        if not conn:
            return ""
        # prefer the socket option, fallback to "--encryption=" option:
        encryption = conn.options.get("encryption", self.encryption)
        log(f"get_encryption() connection options encryption={encryption!r}")
        # specifying keyfile or keydata is enough:
        if not encryption and any(conn.options.get(x) for x in ("encryption-keyfile", "keyfile", "keydata")):
            encryption = f"AES-{DEFAULT_MODE}"
            log(f"found keyfile or keydata attribute, enabling {encryption!r} encryption")
        if not encryption and os.environ.get("XPRA_ENCRYPTION_KEY"):
            encryption = f"AES-{DEFAULT_MODE}"
            log("found encryption key environment variable, enabling {encryption!r} encryption")
        return encryption

    def get_encryption_key(self) -> bytes:
        conn = self._protocol._conn
        keydata = parse_encoded_bin_data(conn.options.get("keydata", ""))
        log(f"get_encryption_key() connection options keydata={Ellipsizer(keydata)}")
        if keydata:
            return keydata
        keyfile = conn.options.get("encryption-keyfile") or conn.options.get("keyfile") or self.encryption_keyfile
        if keyfile:
            if not os.path.isabs(keyfile):
                keyfile = os.path.abspath(keyfile)
            if os.path.exists(keyfile):
                keydata = filedata_nocrlf(keyfile)
                if keydata:
                    log("get_encryption_key() loaded %i bytes from '%s'", len(keydata or b""), keyfile)
                    return keydata
                log(f"get_encryption_key() keyfile {keyfile!r} is empty")
            else:
                log(f"get_encryption_key() file {keyfile!r} does not exist")
        XPRA_ENCRYPTION_KEY = "XPRA_ENCRYPTION_KEY"
        keydata = strtobytes(os.environ.get(XPRA_ENCRYPTION_KEY, ""))
        log(f"get_encryption_key() got %i bytes from {XPRA_ENCRYPTION_KEY!r} environment variable",len(keydata))
        if keydata:
            return keydata.strip(b"\n\r")
        raise InitExit(ExitCode.ENCRYPTION, "no encryption key")
