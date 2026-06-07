# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side "loopback" harness for the authentication handshake.

Unlike the subsystem loopback harness (`unit/loopback_util.py`), authentication is
not a packet subsystem: the server side is a `SysAuthenticator` driven by
`xpra.server.auth.AuthenticationManager`, and the client side is the
`ChallengeClient` mixin. This helper wires the *real* client challenge dispatch
(`ChallengeClient.do_process_challenge` -> `send_challenge_reply` ->
`do_send_challenge_reply`) to a *real* server authenticator and exchanges the
actual `challenge` packet / `challenge_response` capability between them.

This catches drift between the client's salt/digest computation
(`send_challenge_reply`) and the server's verification (`authenticate_hmac`) that
the isolated tests cannot: `unit/server/auth_test.py` re-implements the client
math by hand, and `unit/auth/auth_handlers_test.py` only calls `handler.handle`.
"""

from xpra.net.common import Packet
from xpra.net.packet_type import CHALLENGE
from xpra.net.digest import get_digests, get_salt_digests
from xpra.util.objects import typedict


class _FakeProtocol:
    """Minimal stand-in for the real network protocol used by ChallengeClient."""
    TYPE = "xpra"
    _conn = None

    def is_sending_encrypted(self) -> bool:
        return True


def _hmac_digests():
    return [d for d in get_digests() if d.startswith("hmac")]


def make_challenge_client(handler, username, captured, errors):
    """
    Build a real ChallengeClient with just enough plumbing injected to run the
    challenge dispatch in-process. `send_hello` (the exit of a successful reply)
    and `disconnect_and_quit` (the failure paths) are captured.
    """
    from xpra.client.base.challenge import ChallengeClient
    client = ChallengeClient()
    client._protocol = _FakeProtocol()
    client.display_desc = {}
    client.username = username
    # inject the handler directly rather than going through init_challenge_handlers:
    client.challenge_handlers = [handler]
    # capture the reply (do_send_challenge_reply calls send_hello for TYPE=="xpra"):
    client.send_hello = lambda challenge_response=b"", client_salt=b"": captured.append((challenge_response, client_salt))
    # capture the failure paths (auth_error / "authentication required"):
    client.disconnect_and_quit = lambda *args: errors.append(args)
    return client


def challenge_roundtrip(handler, authenticator, username="foo", digests=None, salt_digests=None):
    """
    Drive one full authentication handshake between a client challenge `handler`
    and a server `authenticator`, exchanging the real `challenge` packet.

    Returns (passed, captured, errors):
    - passed: result of authenticator.authenticate(...) (False if no reply was sent)
    - captured: list of (challenge_response, client_salt) tuples the client sent
    - errors: list of disconnect_and_quit(...) argument tuples (failure paths)
    """
    digests = digests if digests is not None else _hmac_digests()
    salt_digests = salt_digests if salt_digests is not None else list(get_salt_digests())

    salt, digest = authenticator.get_challenge(digests)
    assert salt and digest, f"{authenticator!r}.get_challenge({digests}) returned ({salt!r}, {digest!r})"
    salt_digest = authenticator.choose_salt_digest(salt_digests)
    assert salt_digest not in ("xor", "des"), f"insecure salt digest chosen: {salt_digest!r}"

    captured: list = []
    errors: list = []
    client = make_challenge_client(handler, username, captured, errors)

    packet = Packet(CHALLENGE, salt, {}, digest, salt_digest, authenticator.prompt)
    # exercise the real validation, then the real dispatch (synchronously):
    assert client.validate_challenge_packet(packet), "client rejected the challenge packet"
    client.do_process_challenge(packet)

    if not captured:
        # the client did not send a reply (no credential available)
        return False, captured, errors

    challenge_response, client_salt = captured[0]
    caps = typedict({
        "challenge_response": challenge_response,
        "challenge_client_salt": client_salt,
        "username": username,
    })
    passed = authenticator.authenticate(caps)
    return passed, captured, errors
