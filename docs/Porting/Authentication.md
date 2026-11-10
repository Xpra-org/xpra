# Authentication

This page specifies the wire format of xpra's challenge / response authentication.
For configuring the server side, see the [authentication modules](../Usage/Authentication.md).
The packets themselves are listed in the
[protocol specification](../Network/Protocol.md#53-authentication-and-upgrade-packets).

Xpra's challenge / response protects the password from passive observers for the
`hmac` digests only, and never authenticates the server. Use TLS or SSH on any network
you do not trust: they protect the whole session, and they verify the server.

<div class="docs-section-heading" markdown="1">

## Overview

</div>

1. The client lists the digests it supports in its `hello`: `digest` for the password
   digests and `salt-digest` for the salt combination digests (see below). Both are
   REQUIRED when the server uses authentication.
2. When the connection requires authentication, the server answers with:

   ```text
   ["challenge", server_salt:bytes, auth_caps:map, digest:str, salt_digest:str, prompt:str]
   ```

   * `server_salt`: 64 random bytes.
   * `auth_caps`: encryption parameters for the optional AES layer, empty otherwise.
   * `digest`: the digest to use for the response, chosen from the client's `digest`
     list. It may carry a suffix after a colon, ie: `gss:xpra@host` or
     `SCRAM-SHA-256:client-first`: the client selects its handler using the part
     before the colon.
   * `salt_digest`: the digest to use to combine the salts, chosen from the client's
     `salt-digest` list.
   * `prompt`: what the server is asking for, usually `password`. Show it to the user
     when asking for the secret.
3. The client sends its `hello` again: all the same capabilities, plus
   `challenge_response`, `challenge_client_salt` and `challenge_padding` (all byte strings).
4. The server either accepts the client (sending its `hello`), sends another `challenge`
   (when several authentication modules are configured, or for a multi-step mechanism),
   or closes the connection with `authentication failed`.

A client that already knows it will authenticate MAY send a reduced first `hello`
containing only the core capabilities (`protocol-version`, `encoders`, `digest`, `salt-digest`,
`username`, ...) plus `challenge: true`. The server then always answers with a
`challenge`, and the client sends its full capabilities along with the response.

<div class="docs-section-heading" markdown="1">

## Digest names

</div>

| Name | Response | Notes |
|---|---|---|
| `hmac+sha512`, `hmac+sha384`, `hmac+sha256`, `hmac+sha224` | HMAC of the combined salt, see below | Preferred in that order. Servers ignore other `hmac+` variants when choosing |
| `xor` | the password XORed with the combined salt | Needed by modules that verify the password itself (`pam`, `ldap`, `ldap3`, `kerberos-password`, `exec`). Sends the password reversibly |
| `des` | VNC style DES challenge | Used for VNC compatibility only |
| `kerberos`, `gss`, `keycloak` | the token XORed with the combined salt | The token comes from the platform's Kerberos / GSSAPI library or the Keycloak flow |
| `SCRAM-SHA-256`, `SCRAM-SHA-256-PLUS`, ... | RFC 5802 messages | Multi-step, see below |
| `u2f`, `fido2` | a signature from a security key | See below |

The server picks the strongest digest supported by its authentication module **and
listed by the client**: a client that does not list the digest a module requires
cannot authenticate with that module. For `salt-digest`, list the same `hmac+` digests:
servers refuse to use `xor` or `des` to combine salts.

A client MUST NOT send a response computed with `xor`, `des`, `kerberos`, `gss` or
`keycloak` over a connection that is not encrypted (TLS, WebSocket over TLS, SSH, QUIC,
or the AES layer), except to a local socket: the secret can be recovered from the
response. The reference client refuses to. The server does not check this.

<div class="docs-section-heading" markdown="1">

## Computing an `hmac` response

</div>

```text
client_salt   = 32 random bytes
salt          = lowercase_hex(HMAC(key=client_salt, msg=server_salt, hash=salt_digest))   (ASCII bytes)
response      = lowercase_hex(HMAC(key=password,    msg=salt,        hash=digest))        (ASCII bytes)
padding       = random bytes, max(32, 512 - len(response)) of them
```

Both HMAC results are sent and used as their **hexadecimal ASCII representation**,
not as raw bytes: the combined `salt` that is fed into the second HMAC is the 64 or
128 character hex string, and `challenge_response` is a hex string too.

The `password` bytes are the Latin-1 encoding of the password when every character can
be represented in Latin-1, and its UTF-8 encoding otherwise. A password containing
`é` but no character outside Latin-1 is therefore *not* UTF-8 encoded.

The client then sends:

| Key | Value |
|---|---|
| `challenge_response` | `response` |
| `challenge_client_salt` | `client_salt` (the raw 32 bytes) |
| `challenge_padding` | `padding`: hides the length of the response from observers of encrypted traffic |

The server computes the same `salt` from the salts, and accepts the client if one of
the passwords it knows gives the same `response`. Each combined salt can only be used
once.

### Test vectors

With `server_salt` = the 64 bytes `00 01 02 ... 3f`, `client_salt` = the 32 bytes
`a0 a1 a2 ... bf`, and the password `secret`:

| `salt_digest` | combined `salt` |
|---|---|
| `hmac+sha256` | `9af35b27ab791298b28e4e70a13342e8f94ae85ef9f8a7bcf2e28d49a113ede6` |
| `hmac+sha512` | `68c21ecaf6775ab6335dfa5fa25e6466a12398e3c1d01fe333803a66e354fc3e63ad9ce7a286cde4355a9cd2441314704ca96edfc542e8639ef0a7367402b8b7` |

| `digest` and `salt_digest` | `challenge_response` |
|---|---|
| `hmac+sha256` | `9d85c3522cfa016edb779f946f077ee9c34d647b35e3b6cc388d090dc809c323` |
| `hmac+sha512` | `78f1bdb7b59b05229c7675f71c38b63155c788ba2184e2f5b669f3f35d8159468713de185e90622a66d89dc3f02d67baf7bae6acb89515b7a7c08a8513d6d3f9` |

With `hmac+sha256` for both, the password `pässwörd€` (UTF-8 encoded, since `€` is
not in Latin-1) gives `35ecd3610ec3de9d10cefd1d5be0719c4f0a10a4a821b0dada4392fb9f010850`.

<div class="docs-section-heading" markdown="1">

## Other digests

</div>

**`xor`, `kerberos`, `gss`, `keycloak`:** the combined `salt` is computed as above.
The response is `secret XOR salt`, byte by byte, where `salt` is truncated or padded
with zero bytes to the length of the secret. Secrets longer than the combined salt
(64 or 128 bytes) are therefore partly sent as they are: this is one more reason to
only use these digests over an encrypted connection. With `xor`, the secret is the
password, encoded as for `hmac`. With the others, it is the token obtained from the
corresponding library.

Test vector: with the salts above and `hmac+sha256` as `salt_digest`, the `xor`
response for `secret` is the 6 bytes `4a 04 05 41 50 16`.

**`des`:** the client salt is the server salt itself. The password is padded with zero
bytes or truncated to 8 bytes, the salt to 16 bytes, and the response is the VNC DES
challenge response, as lowercase hex.

**SCRAM:** the server sends three `challenge` packets, with `digest` set to
`<mechanism>:client-first`, `<mechanism>:server-first` and `<mechanism>:server-final`.
Their `server_salt` field carries the server's SCRAM message (RFC 5802), except in the
first one where it is a random salt to be ignored. The client answers each one with a
new `hello` whose `challenge_response` is its next SCRAM message as ASCII bytes: the
`client-first-message`, then the `client-final-message`, and finally `OK` once it has
verified the server's signature. The `-PLUS` variants use TLS channel binding.

**`u2f`, `fido2`:** the client answers with the security key's signature as
`challenge_response` and the relying party / origin string as `challenge_client_salt`;
no salt combination is done. These require matching server-side key registration, see
the [authentication modules](../Usage/Authentication.md).

<div class="docs-section-heading" markdown="1">

## Multiple authentication steps

</div>

A server socket can chain several authentication modules, and some modules need several
round-trips. Each step is a new `challenge` packet, with a new `server_salt`, `digest`
and `prompt`, and each is answered with a new complete `hello`. A client should therefore
keep its credentials or prompt again for each challenge: the `prompt` tells the user what
is being asked for (ie: `password`, then `one-time password`).

The client MUST answer each challenge within 120 seconds of receiving it, or the
server closes the connection with `login timeout`.
