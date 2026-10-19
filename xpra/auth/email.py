# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Send an SMTP verification code, optionally after asking for its destination."""

import os
import re
import smtplib
from collections import deque
from email.message import EmailMessage
from threading import Lock

from xpra.auth.code_base import CodeAuthenticator, lookup_command, make_ssl_context, pop_positive, pop_ssl_options, read_secret_file

__all__ = ("Authenticator", "lookup_command", "validate_address")

LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", re.ASCII)
DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", re.ASCII)


def validate_address(value: str) -> str:
    if not isinstance(value, str) or len(value) > 254 or value.count("@") != 1 or not value.isascii():
        raise ValueError("invalid email address")
    local, domain = value.split("@")
    if not 1 <= len(local) <= 64 or not LOCAL_PART.fullmatch(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("invalid email local part")
    if not domain or len(domain) > 253 or not all(DOMAIN_LABEL.fullmatch(label) for label in domain.split(".")):
        raise ValueError("invalid email domain")
    return f"{local}@{domain.lower()}"


class Authenticator(CodeAuthenticator):
    __slots__ = (
        "from_address", "smtp_host", "smtp_password_file", "smtp_port", "smtp_security", "smtp_ssl_options",
        "smtp_timeout", "smtp_username",
    )
    KIND = "email"
    MODES = ("fixed", "prompt", "lookup", "derived")
    DEFAULT_QUERY = "SELECT email FROM users WHERE username=:username"
    DEFAULT_PROMPT = "Email verification code"
    SENDS: dict[tuple[str, str], deque[float]] = {}
    SEND_LOCK = Lock()

    def __init__(self, **kwargs):
        self.smtp_host = kwargs.pop("smtp-host", "")
        self.smtp_security = kwargs.pop("smtp-security", "starttls")
        if self.smtp_security not in ("starttls", "tls", "plain"):
            raise ValueError("smtp-security must be starttls, tls or plain")
        cwd = kwargs.get("exec_cwd", os.getcwd())
        self.smtp_ssl_options = pop_ssl_options(kwargs, "smtp-", cwd)
        if self.smtp_ssl_options and self.smtp_security == "plain":
            raise ValueError("smtp-ssl options require smtp-security=tls or starttls")
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
        if self.smtp_password_file:
            self.smtp_password_file = os.path.join(cwd, self.smtp_password_file)
        super().__init__(**kwargs)
        if self.address.startswith(r"\@"):
            self.address = self.address[1:]
        if self.mode == "fixed":
            self.address = validate_address(self.address)
        elif self.mode in ("prompt", "derived"):
            if self.address:
                if not self.address.startswith("@"):
                    raise ValueError("prompt and derived address must start with @")
                self.address = "@" + validate_address("user" + self.address).split("@", 1)[1]
            elif self.mode == "derived":
                raise ValueError("derived mode requires a domain")

    def validate_destination(self, value: str) -> str:
        return validate_address(value)

    def get_destination_prompt(self) -> str:
        return f"Email username for {self.address}" if self.address else "Email address"

    def parse_prompted_destination(self, value: str) -> str:
        if self.address and "@" in value:
            raise ValueError("only an email local part is allowed")
        return validate_address(value + self.address)

    def derive_destination(self) -> str:
        return validate_address(self.username + self.address)

    def make_ssl_context(self):
        return make_ssl_context(self.smtp_ssl_options)

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
                smtp.login(self.smtp_username, read_secret_file(self.smtp_password_file))
            if smtp.send_message(message, from_addr=self.from_address, to_addrs=[address]):
                raise ValueError("SMTP recipient refused")
