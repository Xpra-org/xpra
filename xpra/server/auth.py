# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence, Iterable

from xpra.common import ConnectionMessage
from xpra.net.common import Packet, SOCKET_TYPES
from xpra.net.digest import get_salt, choose_digest
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server.subsystem.stub import StubServerMixin
from xpra.auth.auth_helper import get_auth_module, AuthDef
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.util.str_fn import csv, nicestr, hexstr
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("auth")

GLib = gi_import("GLib")

CHALLENGE_TIMEOUT = envint("XPRA_CHALLENGE_TIMEOUT", 120)


# noinspection PyMethodMayBeStatic
class AuthenticatedServer(StubServerMixin):
    """
        Adds authentication methods to ServerCore.
        Unlike other server subsystems,
        this one requires some functions only present in ServerCore and not in the stub:
        self.disconnect_client
        self.hello_oked
        The entry point is self.verify_auth
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        log("AuthenticatedServer.__init__()")
        self.auth_classes: dict[str, Sequence[AuthDef]] = {}
        self.password_file: Iterable[str] = ()

    def init(self, opts) -> None:
        log("ServerCore.init(%s)", opts)
        self.password_file = opts.password_file
        self.init_auth(opts)

    def init_auth(self, opts) -> None:
        for x in SOCKET_TYPES:
            if x == "hyperv":
                # we don't support listening on hyperv sockets yet
                continue
            if x in ("socket", "named-pipe"):
                # use local-auth for these:
                opts_value = opts.auth
            else:
                opts_value = getattr(opts, f"{x}_auth")
            self.auth_classes[x] = self.get_auth_modules(x, opts_value)
        log(f"init_auth(..) auth={self.auth_classes}")

    def get_auth_modules(self, socket_type: str, auth_strs: Iterable[str]) -> Sequence[AuthDef]:
        modules = tuple(get_auth_module(auth_str) for auth_str in auth_strs)
        log(f"get_auth_modules({socket_type}, {auth_strs})={modules}")
        return modules

    def make_authenticators(self, socktype: str, remote: dict[str, Any], conn) -> Sequence[Any]:
        log("make_authenticators%s socket options=%s", (socktype, remote, conn), conn.options)
        sock_options = conn.options
        sock_auth = sock_options.get("auth", "")
        if sock_auth:
            # per socket authentication option:
            # ie: --bind-tcp=0.0.0.0:10000,auth=hosts,auth=file:filename=pass.txt:foo=bar
            # -> sock_auth = ["hosts", "file:filename=pass.txt:foo=bar"]
            if not isinstance(sock_auth, (list, dict)):
                sock_auth = sock_auth.split(",")
            auth_classes = self.get_auth_modules(conn.socktype, sock_auth)
        else:
            # use authentication configuration defined for all sockets of this type:
            if socktype not in self.auth_classes:
                raise RuntimeError(f"invalid socket type {socktype!r}")
            auth_classes = self.auth_classes[socktype]
        i = 0
        authenticators = []
        if auth_classes:
            log(f"creating authenticators {csv(auth_classes)} for {socktype}")
            for auth_name, _, aclass, options in auth_classes:
                opts = dict(options)
                opts["remote"] = remote
                opts.update(sock_options)
                opts["connection"] = conn

                def parse_socket_dirs(v) -> Sequence[str]:
                    if isinstance(v, (tuple, list)):
                        return v
                    # FIXME: this can never actually match ","
                    # because we already split connection options with it.
                    # We need to change the connection options parser to be smarter
                    return str(v).split(",")

                opts["socket-dirs"] = parse_socket_dirs(opts.get("socket-dirs", self._socket_dirs))
                try:
                    for o in ("self",):
                        if o in opts:
                            raise ValueError(f"illegal authentication module options {o!r}")
                    log(f"{auth_name} : {aclass}({opts})")
                    authenticator = aclass(**opts)
                except Exception:
                    log(f"{aclass}({opts})", exc_info=True)
                    raise
                log(f"authenticator {i}={authenticator}")
                authenticators.append(authenticator)
                i += 1
        return tuple(authenticators)

    def send_challenge(self, proto: SocketProtocol, salt: bytes, auth_caps: dict, digest: str, salt_digest: str,
                       prompt: str = "password") -> None:
        proto.send_now(Packet("challenge", salt, auth_caps, digest, salt_digest, prompt))
        self.schedule_verify_connection_accepted(proto, CHALLENGE_TIMEOUT)

    def auth_failed(self, proto: SocketProtocol, msg: str | ConnectionMessage, authenticator=None) -> None:
        log.warn("Warning: authentication failed")
        wmsg = nicestr(msg)
        if authenticator:
            wmsg = f"{authenticator!r}: "+wmsg
        log.warn(f" {wmsg}")
        GLib.timeout_add(1000, self.disconnect_client, proto, msg)

    def verify_auth(self, proto: SocketProtocol, packet, c: typedict) -> None:
        remote = {}
        for key in ("hostname", "uuid", "session-id", "username", "name"):
            v = c.strget(key)
            if v:
                remote[key] = v
        conn = proto._conn
        if not conn or proto.is_closed():
            log(f"connection {proto} is already closed")
            return
        if not proto.authenticators:
            socktype = conn.socktype_wrapped
            try:
                proto.authenticators = self.make_authenticators(socktype, remote, conn)
            except ValueError as e:
                log(f"instantiating authenticator for {socktype}", exc_info=True)
                self.auth_failed(proto, str(e))
                return
            except Exception as e:
                log(f"instantiating authenticator for {socktype}", exc_info=True)
                log.error(f"Error instantiating authenticators for {proto.socket_type} connection:")
                log.estr(e)
                self.auth_failed(proto, str(e))
                return

        digest_modes = c.strtupleget("digest", ("hmac",))
        salt_digest_modes = c.strtupleget("salt-digest", ("xor",))
        # client may have requested encryption:
        auth_caps: dict[str, Any] = {}
        try:
            from xpra.server.subsystem.encryption import setup_encryption
            auth_caps = setup_encryption(proto, c)
            if auth_caps is None:
                return
        except ImportError as e:
            log(f"unable to call setup_encryption: {e}")

        def send_fake_challenge() -> None:
            # fake challenge so the client will send the real hello:
            salt: bytes = get_salt()
            digest: str = choose_digest(digest_modes)
            salt_digest: str = choose_digest(salt_digest_modes)
            self.send_challenge(proto, salt, auth_caps, digest, salt_digest)

        # skip the authentication module we have "passed" already:
        remaining_authenticators = tuple(x for x in proto.authenticators if not x.passed)
        log("processing authentication with %s, remaining=%s, digest_modes=%s, salt_digest_modes=%s",
            proto.authenticators, remaining_authenticators, digest_modes, salt_digest_modes)
        # verify each remaining authenticator:
        for index, authenticator in enumerate(proto.authenticators):
            if authenticator not in remaining_authenticators:
                log(f"authenticator[{index}]={authenticator} (already passed)")
                continue

            def fail(msg: str | ConnectionMessage) -> None:
                self.auth_failed(proto, msg, authenticator)

            req = authenticator.requires_challenge()
            csent = authenticator.challenge_sent
            log(f"authenticator[{index}]={authenticator}, requires-challenge={req}, challenge-sent={csent}")
            if not req:
                # this authentication module does not need a challenge
                # (ie: "peercred", "exec" or "none")
                if not authenticator.authenticate(c):
                    fail("authentication failed")
                    return
                authenticator.passed = True
                log(f"authentication passed for {authenticator} (no challenge needed)")
                continue
            if not csent:
                # we'll re-schedule this when we call send_challenge()
                # as the authentication module is free to take its time
                self.cancel_verify_connection_accepted(proto)
                # note: we may have received a challenge_response from a previous auth module's challenge
                try:
                    salt, digest = authenticator.get_challenge(digest_modes)
                except (AttributeError, ValueError, NameError) as e:
                    log.warn("Warning: unable to generate an authentication challenge")
                    log.warn(" %s", e)
                    fail("authentication challenge processing error")
                    return
                if not (salt or digest):
                    if authenticator.requires_challenge():
                        fail("invalid state, unexpected challenge response")
                        return
                    log.warn(f"Warning: authentication module {authenticator!r} does not require any credentials")
                    log.warn(f" but the client {proto} supplied them")
                    # fake challenge so the client will send the real hello:
                    send_fake_challenge()
                    return
                actual_digest = digest.split(":", 1)[0]
                log(f"get_challenge({digest_modes})={hexstr(salt)}, {digest}")
                countinfo = ""
                if len(proto.authenticators) > 1:
                    countinfo += f" ({index + 1} of {len(proto.authenticators)})"
                log.info(f"Authentication required by {authenticator!r} authenticator module{countinfo}")
                log.info(
                    f" sending challenge using {actual_digest!r} digest over {conn.socktype_wrapped} connection")
                if actual_digest not in digest_modes:
                    fail(f"cannot proceed without {actual_digest!r} digest support")
                    return
                salt_digest: str = authenticator.choose_salt_digest(salt_digest_modes)
                log(f"{authenticator}.choose_salt_digest({salt_digest_modes})={salt_digest!r}")
                if salt_digest in ("xor", "des"):
                    fail(f"insecure salt digest {salt_digest!r} rejected")
                    return
                log(f"{authenticator!r} sending challenge {authenticator.prompt!r}")
                self.send_challenge(proto, salt, auth_caps, digest, salt_digest, authenticator.prompt)
                return
            if not authenticator.authenticate(c):
                fail(ConnectionMessage.AUTHENTICATION_FAILED)
                return
        client_expects_challenge = c.strget("challenge")
        if client_expects_challenge:
            log.warn("Warning: client expects an authentication challenge,")
            log.warn(" sending a fake one")
            send_fake_challenge()
            return
        log(f"all {len(proto.authenticators)} authentication modules passed")
        capabilities = packet.get_dict(1)
        c = typedict(capabilities)
        self.auth_verified(proto, c, auth_caps)

    def auth_verified(self, proto: SocketProtocol, caps: typedict, auth_caps: dict) -> None:
        command_req = tuple(str(x) for x in caps.tupleget("command_request"))
        if command_req:
            # call from UI thread:
            log(f"auth_verified(..) command request={command_req}")
            GLib.idle_add(self.handle_command_request, proto, *command_req)
            return
        proto.clean_authenticators()
        # continue processing hello packet in UI thread:
        GLib.idle_add(self.call_hello_oked, proto, caps, auth_caps)

    def call_hello_oked(self, proto: SocketProtocol, c: typedict, auth_caps: dict) -> None:
        raise NotImplementedError()
