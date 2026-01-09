# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable
from importlib import import_module

from xpra.client.base.stub import StubClientMixin
from xpra.platform.info import get_username
from xpra.scripts.config import InitExit
from xpra.net.digest import get_salt, gendigest, get_digests, get_salt_digests
from xpra.net.common import Packet
from xpra.common import ConnectionMessage, noop
from xpra.util.io import use_gui_prompt
from xpra.util.env import envbool
from xpra.util.parsing import parse_simple_dict
from xpra.util.thread import start_thread
from xpra.util.str_fn import std, obsc, hexstr
from xpra.util.objects import typedict
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("auth")

GLib = gi_import("GLib")

SKIP_UI = envbool("XPRA_SKIP_UI", False)
ALLOW_UNENCRYPTED_PASSWORDS = envbool("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", False)
ALLOW_LOCALHOST_PASSWORDS = envbool("XPRA_ALLOW_LOCALHOST_PASSWORDS", True)

ALL_CHALLENGE_HANDLERS = os.environ.get("XPRA_ALL_CHALLENGE_HANDLERS",
                                        "uri,file,env,kerberos,gss,u2f,prompt,prompt,prompt,prompt").split(",")


class ChallengeClient(StubClientMixin):
    """
    Adds ability to handle challenge packets
    """

    def __init__(self):
        self.username = ""
        self.password = None
        self.password_file: list[str] = []
        self.password_index = 0
        self.password_sent = False
        self.has_password = False
        self.challenge_handlers_option = ()
        self.challenge_handlers = []

    def init(self, opts) -> None:
        self.username = opts.username or os.environ.get("XPRA_USERNAME", "")
        self.password = opts.password
        self.password_file = opts.password_file
        self.challenge_handlers_option = opts.challenge_handlers
        self.has_password = bool(self.password or self.password_file or os.environ.get("XPRA_PASSWORD"))

    def get_info(self) -> dict[str, tuple]:
        return {}

    def get_caps(self) -> dict[str, Any]:
        digests = list(get_digests())
        # add "kerberos", "gss" and "u2f" digests if enabled:
        for handler in self.challenge_handlers:
            digest = handler.get_digest()
            if digest and digest not in digests:
                digests.append(digest)
        caps = {
            "salt-digest": get_salt_digests()
        }
        if digests:
            caps["digest"] = tuple(digests)
        # set for authentication:
        caps["username"] = self.username or get_username()
        log(f"challenge caps for handlers={self.challenge_handlers} : {caps=}")
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        if not self.password_sent and self.has_password:
            p = self._protocol
            if not p or p.TYPE == "xpra":
                self.warn_and_quit(ExitCode.NO_AUTHENTICATION, "the server did not request our password")
                return False
        return True

    def setup_connection(self, _conn) -> None:
        self.init_challenge_handlers()

    def init_challenge_handlers(self) -> None:
        # register the authentication challenge handlers:
        log("init_challenge_handlers() %r", self.challenge_handlers_option)
        ch = tuple(x.strip() for x in (self.challenge_handlers_option or ()))
        for ch_name in ch:
            if ch_name == "none":
                continue
            if ch_name == "all":
                items = ALL_CHALLENGE_HANDLERS
                ierror = log.debug
            else:
                items = (ch_name,)
                ierror = log.warn
            for auth in items:
                instance = self.get_challenge_handler(auth, ierror)
                if instance:
                    self.challenge_handlers.append(instance)
        log("challenge-handlers=%r", self.challenge_handlers)

    def get_challenge_handler(self, auth: str, import_error_logger: Callable):
        # the module may have attributes,
        # ie: file:filename=password.txt
        parts = auth.split(":", 1)
        mod_name = parts[0]
        kwargs: dict[str, Any] = {}
        if len(parts) == 2:
            kwargs = parse_simple_dict(parts[1])
        kwargs["protocol"] = self._protocol
        kwargs["display-desc"] = self.display_desc
        if "password" not in kwargs and self.password:
            kwargs["password"] = self.password
        if self.password_file:
            kwargs["password-files"] = self.password_file
        kwargs["challenge_prompt_function"] = self.do_process_challenge_prompt

        auth_mod_name = f"xpra.challenge.{mod_name}"
        log(f"auth module name for {auth!r}: {auth_mod_name!r}")
        try:
            auth_module = import_module(auth_mod_name)
            auth_class = auth_module.Handler
            log(f"{auth_class}({kwargs})")
            instance = auth_class(**kwargs)
            return instance
        except ImportError as e:
            import_error_logger(f"Error: authentication handler {mod_name!r} is not available")
            import_error_logger(f" {e}")
        except Exception as e:
            log("get_challenge_handler(%s)", auth, exc_info=True)
            log.error("Error: cannot instantiate authentication handler")
            log.error(f" {mod_name!r}: {e}")
        return None

    def _process_challenge(self, packet: Packet) -> None:
        log(f"processing challenge: {packet[1:]}")
        if not self.validate_challenge_packet(packet):
            return
        # soft dependency on base client:
        cancel_vct = getattr(self, "cancel_verify_connected_timer", noop)
        cancel_vct()
        start_thread(self.do_process_challenge, "call-challenge-handlers", True, (packet,))

    def do_process_challenge(self, packet: Packet) -> None:
        digest = packet.get_str(3)
        log(f"challenge handlers: {self.challenge_handlers}, digest: {digest}")
        while self.challenge_handlers:
            handler = self.pop_challenge_handler(digest)
            try:
                challenge = packet.get_bytes(1)
                prompt = "password"
                if len(packet) >= 6:
                    prompt = std(packet.get_str(5), extras="-,./: '")
                log(f"calling challenge handler {handler} with {challenge=} and {prompt=}")
                value = handler.handle(challenge=challenge, digest=digest, prompt=prompt)
                log(f"{handler.handle}({packet})={obsc(value)}")
                if value:
                    self.send_challenge_reply(packet, value)
                    # stop since we have sent the reply
                    return
            except InitExit as e:
                # the handler is telling us to give up
                # (ie: pinentry was cancelled by the user)
                log(f"{handler.handle}({packet}) raised {e!r}")
                log.info(f"exiting: {e}")
                GLib.idle_add(self.disconnect_and_quit, e.status, str(e))
                return
            except Exception as e:
                log(f"{handler.handle}({packet})", exc_info=True)
                log.error(f"Error in {handler} challenge handler:")
                log.estr(e)
                continue
        log.warn("Warning: failed to connect, authentication required")
        GLib.idle_add(self.disconnect_and_quit, ExitCode.PASSWORD_REQUIRED, "authentication required")

    def pop_challenge_handler(self, digest: str = ""):
        # find the challenge handler most suitable for this digest type,
        # otherwise take the first one
        digest_type = digest.split(":")[0]  # ie: "kerberos:value" -> "kerberos"
        index = 0
        for i, handler in enumerate(self.challenge_handlers):
            if handler.get_digest() == digest_type:
                index = i
                break
        return self.challenge_handlers.pop(index)

    # utility method used by some authentication handlers,
    # and overridden in UI client to provide a GUI dialog
    def do_process_challenge_prompt(self, prompt="password"):
        log(f"do_process_challenge_prompt({prompt}) use_gui_prompt={use_gui_prompt()}")
        if SKIP_UI:
            return None
        # pylint: disable=import-outside-toplevel
        if not use_gui_prompt():
            import getpass
            log("stdin isatty, using password prompt")
            password = getpass.getpass("%s :" % self.get_challenge_prompt(prompt))
            log("password read from tty via getpass: %s", obsc(password))
            return password
        self.show_progress(100, "challenge prompt")
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command() + ["_pass", prompt]
        try:
            from subprocess import Popen, PIPE
            proc = Popen(cmd, stdout=PIPE)
            from xpra.util.child_reaper import get_child_reaper
            get_child_reaper().add_process(proc, "password-prompt", cmd, True, True)
            out, err = proc.communicate(None, 60)
            log("err(%s)=%s", cmd, err)
            password = out.decode()
            return password
        except OSError:
            log("Error: failed to show GUI for password prompt", exc_info=True)
            return None

    def auth_error(self, code: ExitValue,
                   message: str,
                   server_message: str | ConnectionMessage = ConnectionMessage.AUTHENTICATION_FAILED) -> None:
        log.error("Error: authentication failed:")
        log.error(f" {message}")
        self.disconnect_and_quit(code, server_message)

    def validate_challenge_packet(self, packet) -> bool:
        p = self._protocol
        if not p:
            return False
        digest = packet.get_str(3).split(":", 1)[0]
        # don't send XORed password unencrypted:
        if digest in ("xor", "des"):
            # verify that the connection is already encrypted,
            # or that it will be configured for encryption in `send_challenge_reply`:
            encrypted = p.is_sending_encrypted() or bool(self.get_encryption())
            local = self.display_desc.get("local", False)
            log(f"{digest} challenge, encrypted={encrypted}, local={local}")
            if local and ALLOW_LOCALHOST_PASSWORDS:
                return True
            if not encrypted and not ALLOW_UNENCRYPTED_PASSWORDS:
                self.auth_error(ExitCode.ENCRYPTION,
                                f"server requested {digest!r} digest, cowardly refusing to use it without encryption",
                                "invalid digest")
                return False
        salt_digest = "xor"
        if len(packet) >= 5:
            salt_digest = packet.get_str(4)
        if salt_digest in ("xor", "des"):
            self.auth_error(ExitCode.INCOMPATIBLE_VERSION, f"server uses legacy salt digest {salt_digest!r}")
            return False
        return True

    def get_challenge_prompt(self, prompt="password") -> str:
        text = f"Please enter the {prompt}"
        try:
            from xpra.net.bytestreams import pretty_socket  # pylint: disable=import-outside-toplevel
            conn = self._protocol._conn
            text += f",\n connecting to {conn.socktype} server {pretty_socket(conn.remote)}"
        except (AttributeError, TypeError):
            pass
        return text

    def send_challenge_reply(self, packet: Packet, value) -> None:
        if not value:
            self.auth_error(ExitCode.PASSWORD_REQUIRED,
                            "this server requires authentication and no password is available")
            return
        encryption = self.get_encryption()
        if encryption:
            assert len(packet) >= 3, "challenge does not contain encryption details to use for the response"
            server_cipher = typedict(packet.get_dict(2))
            key = self.get_encryption_key()
            if not self.set_server_encryption(server_cipher, key):
                return
        # some authentication handlers give us the response and salt,
        # ready to use without needing to use the digest
        # (ie: u2f handler)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            self.do_send_challenge_reply(*value)
            return
        password = value
        # all server versions support a client salt,
        # they also tell us which digest to use:
        server_salt = packet.get_bytes(1)
        digest = packet.get_str(3)
        actual_digest = digest.split(":", 1)[0]
        if actual_digest == "des":
            salt = client_salt = server_salt
        else:
            length = len(server_salt)
            salt_digest = "xor"
            if len(packet) >= 5:
                salt_digest = packet.get_str(4)
            if salt_digest == "xor":
                # with xor, we have to match the size
                if length < 16:
                    raise ValueError(f"server salt is too short: only {length} bytes, minimum is 16")
                if length > 256:
                    raise ValueError(f"server salt is too long: {length} bytes, maximum is 256")
            else:
                # other digest, 32 random bytes is enough:
                length = 32
            client_salt = get_salt(length)
            salt = gendigest(salt_digest, client_salt, server_salt)
            log(f"combined {salt_digest} salt({hexstr(server_salt)}, {hexstr(client_salt)})={hexstr(salt)}")

        challenge_response = gendigest(actual_digest, password, salt)
        if not challenge_response:
            log(f"invalid digest module {actual_digest!r}")
            self.auth_error(ExitCode.UNSUPPORTED,
                            f"server requested {actual_digest} digest but it is not supported", "invalid digest")
            return
        log(f"{actual_digest}({obsc(password)!r}, {salt!r})={obsc(challenge_response)!r}")
        self.do_send_challenge_reply(challenge_response, client_salt)

    def do_send_challenge_reply(self, challenge_response: bytes, client_salt: bytes) -> None:
        self.password_sent = True
        if self._protocol.TYPE == "rfb":
            self._protocol.send_challenge_reply(challenge_response)
            return
        # call send_hello from the UI thread:
        GLib.idle_add(self.send_hello, challenge_response, client_salt)

    def init_packet_handlers(self) -> None:
        self.add_packets("challenge", main_thread=True)
