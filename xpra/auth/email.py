# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Send an SMTP verification code, optionally after asking for its destination."""

import hmac
import os
import re
import secrets
import shlex
import smtplib
import ssl
from collections import deque
from collections.abc import Sequence
from email.message import EmailMessage
from ipaddress import ip_address
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from threading import Event, Lock, Thread
from time import monotonic

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.net.digest import choose_digest, gendigest, get_salt
from xpra.net.tls.parsing import parse_ssl_options_mask, parse_ssl_protocol, parse_ssl_verify_mask, parse_ssl_verify_mode
from xpra.util.objects import typedict
from xpra.util.parsing import ALL_BOOLEAN_OPTIONS, TRUE_OPTIONS, parse_encoded_bin_data

LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", re.ASCII)
DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", re.ASCII)
OUTPUT_LIMIT = 4096
SMTP_SSL_OPTIONS = (
    "ca-certs", "ca-data", "cert", "key", "key-password-file", "check-hostname", "server-verify-mode",
    "protocol", "verify-flags", "options", "ciphers",
)


def validate_address(value: str) -> str:
    if not isinstance(value, str) or len(value) > 254 or value.count("@") != 1 or not value.isascii():
        raise ValueError("invalid email address")
    local, domain = value.split("@")
    if not 1 <= len(local) <= 64 or not LOCAL_PART.fullmatch(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("invalid email local part")
    if not domain or len(domain) > 253 or not all(DOMAIN_LABEL.fullmatch(label) for label in domain.split(".")):
        raise ValueError("invalid email domain")
    return f"{local}@{domain.lower()}"


def pop_positive(kwargs: dict, name: str, default: int, maximum: int = 86400) -> int:
    value = int(kwargs.pop(name, default))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def lookup_command(command: Sequence[str], username: str, timeout: int) -> str:
    """Bound both the helper's stdout and the time spent reading / waiting."""
    output: list[bytes] = []
    finished = Event()
    deadline = monotonic() + timeout
    with Popen((*command, username), stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, bufsize=0) as proc:
        def read_output() -> None:
            data = bytearray()
            try:
                while len(data) <= OUTPUT_LIMIT:
                    chunk = proc.stdout.read(OUTPUT_LIMIT + 1 - len(data))
                    if not chunk:
                        output.append(bytes(data))
                        return
                    data.extend(chunk)
            except (OSError, ValueError):
                pass
            finally:
                finished.set()

        reader = Thread(target=read_output, name="email-address-lookup", daemon=True)
        reader.start()
        try:
            if not finished.wait(max(0, deadline - monotonic())):
                raise ValueError("email lookup command timed out")
            if not output:
                raise ValueError("email lookup command output exceeds limit or cannot be read")
            if proc.wait(timeout=max(0, deadline - monotonic())) != 0:
                raise ValueError("email lookup command failed")
        except TimeoutExpired:
            raise ValueError("email lookup command timed out") from None
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
            reader.join(timeout=0.1)
    # Permit one line terminator from a command-line helper, never address lists.
    return output[0].decode("utf-8").removesuffix("\n").removesuffix("\r")


class Authenticator(SysAuthenticator):
    __slots__ = (
        "address", "cancelled", "code", "code_digest", "code_prompt", "command", "connection", "digits", "expires",
        "from_address", "lock", "lookup", "lookup_timeout", "mode", "pending_challenge", "query", "smtp_host",
        "smtp_password_file", "smtp_port", "smtp_security", "smtp_ssl_options", "smtp_timeout", "smtp_username", "state", "timeout", "uri",
    )
    CLIENT_USERNAME = True
    DEFAULT_PROMPT = "Email verification code"
    SENDS: dict[tuple[str, str], deque[float]] = {}
    SEND_LOCK = Lock()
    MAX_SEND_KEYS = 10000

    def __init__(self, **kwargs):
        self.mode = kwargs.pop("mode", "fixed")
        self.address = kwargs.pop("address", "")
        if self.address.startswith(r"\@"):
            self.address = self.address[1:]
        self.lookup = kwargs.pop("lookup", "")
        self.uri = kwargs.pop("uri", "")
        self.query = kwargs.pop("query", "SELECT email FROM users WHERE username=:username")
        self.command = shlex.split(kwargs.pop("command", ""))
        self.lookup_timeout = pop_positive(kwargs, "lookup-timeout", 10)
        self.digits = pop_positive(kwargs, "digits", 6, 12)
        if self.digits < 6:
            raise ValueError("digits must be at least 6")
        self.timeout = pop_positive(kwargs, "timeout", 120)
        self.smtp_host = kwargs.pop("smtp-host", "")
        self.smtp_security = kwargs.pop("smtp-security", "starttls")
        if self.smtp_security not in ("starttls", "tls", "plain"):
            raise ValueError("smtp-security must be starttls, tls or plain")
        self.smtp_ssl_options = {name: kwargs.pop(f"smtp-ssl-{name}") for name in SMTP_SSL_OPTIONS if f"smtp-ssl-{name}" in kwargs}
        if any(name.startswith("smtp-ssl-") for name in kwargs):
            raise ValueError("unsupported smtp-ssl option")
        if self.smtp_ssl_options and self.smtp_security == "plain":
            raise ValueError("smtp-ssl options require smtp-security=tls or starttls")
        if "check-hostname" in self.smtp_ssl_options:
            value = str(self.smtp_ssl_options["check-hostname"]).lower()
            if value not in ALL_BOOLEAN_OPTIONS:
                raise ValueError("smtp-ssl-check-hostname must be a boolean")
            self.smtp_ssl_options["check-hostname"] = value in TRUE_OPTIONS
        if any(self.smtp_ssl_options.get(name) for name in ("key", "key-password-file")) and not self.smtp_ssl_options.get("cert"):
            raise ValueError("smtp-ssl-key and smtp-ssl-key-password-file require smtp-ssl-cert")
        port = {"starttls": 587, "tls": 465, "plain": 25}[self.smtp_security]
        self.smtp_port = pop_positive(kwargs, "smtp-port", port, 65535)
        self.smtp_timeout = pop_positive(kwargs, "smtp-timeout", 10)
        self.smtp_username = kwargs.pop("smtp-username", "")
        self.smtp_password_file = kwargs.pop("smtp-password-file", "")
        if bool(self.smtp_username) != bool(self.smtp_password_file):
            raise ValueError("SMTP login requires both smtp-username and smtp-password-file")
        if not self.smtp_host:
            raise ValueError("smtp-host is required")
        self.from_address = validate_address(kwargs.pop("from", ""))
        if self.mode == "fixed":
            self.address = validate_address(self.address)
        elif self.mode in ("prompt", "derived"):
            if self.address:
                if not self.address.startswith("@"):
                    raise ValueError("prompt and derived address must start with @")
                self.address = "@" + validate_address("user" + self.address).split("@", 1)[1]
            elif self.mode == "derived":
                raise ValueError("derived mode requires a domain")
        elif self.mode == "lookup":
            if self.lookup not in ("sql", "exec"):
                raise ValueError("lookup must be sql or exec")
            if self.lookup == "sql" and not (self.uri and self.query):
                raise ValueError("SQL lookup requires uri and query")
            if self.lookup == "exec" and not self.command:
                raise ValueError("exec lookup requires command")
        else:
            raise ValueError("mode must be fixed, prompt, lookup or derived")
        cwd = kwargs.get("exec_cwd", os.getcwd())
        if self.smtp_password_file:
            self.smtp_password_file = os.path.join(cwd, self.smtp_password_file)
        for name in ("ca-certs", "cert", "key", "key-password-file"):
            path = self.smtp_ssl_options.get(name)
            if path and not (name == "ca-certs" and path == "default"):
                self.smtp_ssl_options[name] = os.path.join(cwd, path)
        self.connection = kwargs.get("connection")
        self.lock = Lock()
        self.cancelled = Event()
        self.code = self.code_digest = ""
        self.expires = 0.0
        self.state = "new"
        self.pending_challenge: tuple[bytes, str, str] | None = None
        super().__init__(**kwargs)
        self.code_prompt = self.prompt

    def __repr__(self):
        return "email"

    def get_uid(self) -> int:
        return -1

    def get_gid(self) -> int:
        return -1

    def get_sessions(self) -> None:
        return None

    def resolve_address(self) -> str:
        if self.mode == "fixed":
            return self.address
        if self.mode == "derived":
            return validate_address(self.username + self.address)
        if not self.username or len(self.username) > 1024 or any(ord(c) < 32 for c in self.username):
            raise ValueError("invalid lookup username")
        if self.lookup == "exec":
            return validate_address(lookup_command(self.command, self.username, self.lookup_timeout))
        from sqlalchemy import create_engine, text
        engine = create_engine(self.uri, hide_parameters=True)
        try:
            with engine.connect() as connection:
                with connection.execute(text(self.query), {"username": self.username}) as result:
                    rows = result.fetchmany(2)
                    if len(rows) != 1 or len(rows[0]) != 1:
                        raise ValueError("SQL lookup must return one row with one address")
                    value = rows[0][0]
                    if not isinstance(value, str):
                        raise ValueError("SQL lookup must return a string")
                    return validate_address(value)
        finally:
            engine.dispose()

    def reserve_send(self, address: str) -> None:
        now = monotonic()
        # Keep each local part's case for delivery, but fold it for the limiter.
        keys = [("recipient", address.lower())]
        remote = getattr(self.connection, "remote", None)
        if isinstance(remote, (tuple, list)) and remote:
            try:
                peer = ip_address(str(remote[0]).split("%", 1)[0])
                peer = getattr(peer, "ipv4_mapped", None) or peer
                keys.append(("peer", str(peer)))
            except ValueError:
                pass
        with self.SEND_LOCK:
            for key, attempts in tuple(self.SENDS.items()):
                window = 60 if key[0] == "recipient" else 300
                while attempts and attempts[0] <= now - window:
                    attempts.popleft()
                if not attempts:
                    del self.SENDS[key]
            if len(self.SENDS) + sum(key not in self.SENDS for key in keys) > self.MAX_SEND_KEYS:
                raise ValueError("email send tracking limit reached")
            for key in keys:
                limit = 1 if key[0] == "recipient" else 5
                if len(self.SENDS.get(key, ())) >= limit:
                    raise ValueError("email send rate limit reached")
            for key in keys:
                self.SENDS.setdefault(key, deque()).append(now)

    def make_ssl_context(self) -> ssl.SSLContext:
        settings = self.smtp_ssl_options
        context = ssl.create_default_context()
        if "protocol" in settings:
            protocol = parse_ssl_protocol(settings["protocol"], server_side=False)
            if protocol == ssl.PROTOCOL_TLS_SERVER:
                raise ValueError("SMTP requires a client SSL protocol")
            if protocol != context.protocol:
                defaults = context
                context = ssl.SSLContext(protocol)
                context.options |= defaults.options
                context.verify_flags = defaults.verify_flags
                context.verify_mode = defaults.verify_mode
                context.check_hostname = defaults.check_hostname
                context.load_default_certs()
        verify_mode = parse_ssl_verify_mode(settings.get("server-verify-mode", "required"))
        check_hostname = settings.get("check-hostname", verify_mode != ssl.CERT_NONE)
        if check_hostname and verify_mode == ssl.CERT_NONE:
            raise ValueError("hostname checking requires SMTP certificate verification")
        context.check_hostname = False
        context.verify_mode = verify_mode
        context.check_hostname = check_hostname
        if "verify-flags" in settings:
            context.verify_flags = parse_ssl_verify_mask(settings["verify-flags"].replace("+", ","))
        if "options" in settings:
            context.options |= parse_ssl_options_mask(settings["options"].replace("+", ","))
        if "ciphers" in settings:
            context.set_ciphers(settings["ciphers"])
        ca_certs = settings.get("ca-certs")
        if ca_certs and ca_certs != "default":
            if os.path.isdir(ca_certs):
                context.load_verify_locations(capath=ca_certs)
            else:
                context.load_verify_locations(cafile=ca_certs)
        if "ca-data" in settings:
            ca_data = settings["ca-data"]
            if not ca_data.startswith("-----BEGIN CERTIFICATE-----"):
                ca_data = parse_encoded_bin_data(ca_data)
            if not ca_data:
                raise ValueError("invalid smtp-ssl-ca-data")
            context.load_verify_locations(cadata=ca_data)
        if settings.get("cert"):
            password = ""
            if settings.get("key-password-file"):
                with open(settings["key-password-file"], encoding="utf-8") as password_file:
                    password = password_file.read().removesuffix("\n").removesuffix("\r")
            # An explicit password, including an empty one, prevents interactive OpenSSL prompts.
            context.load_cert_chain(settings["cert"], settings.get("key") or None, password=password)
        return context

    def send_code(self, address: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = address
        message["Subject"] = "Xpra email verification code"
        message.set_content(f"Your Xpra verification code is: {code}\n\n"
                            f"It expires in {self.timeout} seconds after submission to the mail server.\n"
                            f"Requested for login user: {self.username!r}\n"
                            "If you did not request this connection, ignore this email.\n")
        smtp_class = smtplib.SMTP_SSL if self.smtp_security == "tls" else smtplib.SMTP
        options = {"timeout": self.smtp_timeout}
        context = self.make_ssl_context() if self.smtp_security != "plain" else None
        if self.smtp_security == "tls":
            options["context"] = context
        with smtp_class(self.smtp_host, self.smtp_port, **options) as smtp:
            if self.smtp_security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if self.smtp_username:
                with open(self.smtp_password_file, encoding="utf-8") as password_file:
                    password = password_file.read().removesuffix("\n").removesuffix("\r")
                smtp.login(self.smtp_username, password)
            if smtp.send_message(message, from_addr=self.from_address, to_addrs=[address]):
                raise ValueError("SMTP recipient refused")

    def issue_code(self, address: str) -> tuple[bytes, str]:
        if self.cancelled.is_set():
            raise ValueError("email authentication cancelled")
        self.reserve_send(address)
        code = f"{secrets.randbelow(10 ** self.digits):0{self.digits}d}"
        self.send_code(address, code)
        with self.lock:
            if self.cancelled.is_set():
                raise ValueError("email authentication cancelled")
            self.code = code
            self.expires = monotonic() + self.timeout
            self.state = "code"
            self.salt = get_salt()
            self.digest = self.code_digest
            self.prompt = self.code_prompt
            self.challenge_sent = True
            return self.salt, self.digest

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        with self.lock:
            if self.state != "new" or self.cancelled.is_set():
                return b"", ""
            self.state = "sending"
        try:
            self.code_digest = choose_digest(tuple(d for d in digests if d.startswith("hmac+")))
            if self.mode == "prompt":
                self.req_xor(digests)
                with self.lock:
                    if self.cancelled.is_set():
                        raise ValueError("email authentication cancelled")
                    self.state = "address"
                    self.prompt = f"Email username for {self.address}" if self.address else "Email address"
                    return self.do_get_challenge(("xor",))
            return self.issue_code(self.resolve_address())
        except Exception:
            self.cleanup()
            # Do not expose SMTP replies, lookup output, DSNs or credentials.
            raise ValueError("cannot issue email authentication challenge") from None

    def get_next_challenge(self) -> tuple[()] | tuple[bytes, str, str]:
        with self.lock:
            pending = self.pending_challenge
            self.pending_challenge = None
            return pending or ()

    def authenticate(self, caps: typedict) -> bool:
        try:
            with self.lock:
                if self.cancelled.is_set() or self.state not in ("address", "code") or not self.salt or not self.validate_caps(caps):
                    raise ValueError("unexpected email authentication response")
                if self.state == "code":
                    salt = self.get_response_salt(caps.bytesget("challenge_client_salt"))
                    expected = gendigest(self.digest, self.code, salt)
                    valid = monotonic() < self.expires and hmac.compare_digest(expected, caps.bytesget("challenge_response"))
                    self.code = ""
                    self.expires = 0.0
                    self.state = "complete" if valid else "failed"
                    self.passed = valid
                    return valid
                response = caps.bytesget("challenge_response")
                if len(response) > 254:
                    raise ValueError("email address response too long")
                # Use bytes here: decoding a random client salt as text can corrupt it.
                salt = self.get_response_salt(caps.bytesget("challenge_client_salt"))
                value = gendigest("xor", response, salt).decode("ascii")
                if self.address and "@" in value:
                    raise ValueError("only an email local part is allowed")
                address = validate_address(value + self.address)
                self.state = "sending"
            salt, digest = self.issue_code(address)
            with self.lock:
                if self.cancelled.is_set():
                    return False
                self.pending_challenge = salt, digest, self.prompt
            return True
        except Exception:
            log.warn("Warning: email authentication failed")
        self.cleanup()
        return False

    def cleanup(self) -> None:
        self.cancelled.set()
        with self.lock:
            self.code = ""
            self.expires = 0.0
            self.salt = None
            self.pending_challenge = None
            if self.state != "complete":
                self.state = "failed"
