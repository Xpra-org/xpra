# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Send an SMS verification code through a provider's HTTP API, optionally after asking for the phone number."""

import json
import os
import re
from collections import deque
from collections.abc import Callable
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import quote, quote_plus, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from xpra.auth.code_base import CodeAuthenticator, OUTPUT_LIMIT, make_ssl_context, pop_positive, pop_ssl_options
from xpra.auth.sys_auth_base import log
from xpra.util.parsing import ALL_BOOLEAN_OPTIONS, TRUE_OPTIONS

E164 = re.compile(r"\+[1-9][0-9]{6,14}", re.ASCII)
COUNTRY = re.compile(r"\+[1-9][0-9]{0,2}", re.ASCII)
SENDER = re.compile(r"[A-Za-z0-9 .+-]{1,15}", re.ASCII)
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", re.ASCII)
PLACEHOLDER = re.compile(r"\{(to|to_digits|from|code|message)\}")
NUMBER_SEPARATORS = str.maketrans("", "", " -.()")
DEFAULT_BODY = '{"sender": "{from}", "recipient": "{to_digits}", "content": "{message}"}'
DEFAULT_MESSAGE = "Your Xpra verification code is {code}"
CONTENT_TYPES = {
    "json": "application/json",
    "form": "application/x-www-form-urlencoded",
}
MAX_MESSAGE = 160


def validate_number(value: str) -> str:
    """Normalize to E.164: `+` followed by the country code and subscriber number."""
    if not isinstance(value, str) or len(value) > 32 or not value.isascii():
        raise ValueError("invalid phone number")
    number = value.translate(NUMBER_SEPARATORS)
    if number.startswith("00"):
        number = "+" + number[2:]
    if not E164.fullmatch(number):
        raise ValueError("invalid phone number")
    return number


def json_escape(value: str) -> str:
    return json.dumps(value)[1:-1]


def url_escape(value: str) -> str:
    return quote(value, safe="")


def form_escape(value: str) -> str:
    return quote_plus(value, safe="")


def render(template: str, values: dict[str, str], escape: Callable[[str], str]) -> str:
    # Single pass, so a substituted value can never introduce another placeholder.
    return PLACEHOLDER.sub(lambda m: escape(values[m.group(1)]), template)


def parse_headers(data: str) -> list[tuple[str, str]]:
    headers = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition(":")
        name = name.strip()
        value = value.strip()
        if not sep or not HEADER_NAME.fullmatch(name) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid header line")
        headers.append((name, value))
    return headers


class NoRedirectHandler(HTTPRedirectHandler):
    """urllib would forward our headers, including API keys, to the redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Authenticator(CodeAuthenticator):
    __slots__ = (
        "body", "body_format", "country", "headers_file", "http_insecure", "http_ssl_options", "http_timeout",
        "message", "method", "sender", "url",
    )
    KIND = "sms"
    DESTINATION_OPTION = "number"
    DEFAULT_QUERY = "SELECT phone FROM users WHERE username=:username"
    DEFAULT_PROMPT = "SMS verification code"
    MAX_RESPONSE = 32
    SENDS: dict[tuple[str, str], deque[float]] = {}
    SEND_LOCK = Lock()

    def __init__(self, **kwargs):
        cwd = kwargs.get("exec_cwd", os.getcwd())
        self.url = kwargs.pop("url", "")
        insecure = str(kwargs.pop("http-insecure", "no")).lower()
        if insecure not in ALL_BOOLEAN_OPTIONS:
            raise ValueError("http-insecure must be a boolean")
        self.http_insecure = insecure in TRUE_OPTIONS
        parts = urlsplit(self.url)
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise ValueError("url must be an absolute http or https URL")
        if parts.username or parts.password:
            raise ValueError("url must not contain credentials, use headers-file")
        if parts.scheme == "http" and not self.http_insecure:
            raise ValueError("http urls require http-insecure=yes")
        self.http_ssl_options = pop_ssl_options(kwargs, "http-", cwd)
        if self.http_ssl_options and parts.scheme != "https":
            raise ValueError("http-ssl options require an https url")
        self.http_timeout = pop_positive(kwargs, "http-timeout", 10)
        self.method = kwargs.pop("method", "POST").upper()
        if self.method not in ("POST", "PUT", "GET"):
            raise ValueError("method must be POST, PUT or GET")
        self.body_format = kwargs.pop("body-format", "json")
        if self.body_format not in CONTENT_TYPES:
            raise ValueError("body-format must be json or form")
        body_file = kwargs.pop("body-file", "")
        if body_file:
            with open(os.path.join(cwd, body_file), encoding="utf-8") as f:
                self.body = f.read().strip()
        else:
            self.body = DEFAULT_BODY if self.body_format == "json" else ""
        if self.method == "GET" and body_file:
            raise ValueError("GET requests have no body, use placeholders in the url")
        if self.method != "GET" and not self.body:
            raise ValueError("a body-file is required for form requests")
        self.headers_file = kwargs.pop("headers-file", "")
        if self.headers_file:
            self.headers_file = os.path.join(cwd, self.headers_file)
            self.read_headers()
        self.sender = kwargs.pop("from", "")
        if self.sender and not SENDER.fullmatch(self.sender):
            raise ValueError("invalid sender")
        self.message = kwargs.pop("message", DEFAULT_MESSAGE)
        if "{code}" not in self.message:
            raise ValueError("message must contain {code}")
        self.country = kwargs.pop("country", "")
        if self.country and not COUNTRY.fullmatch(self.country):
            raise ValueError("country must be a calling code, ie: +33")
        super().__init__(**kwargs)
        if self.mode == "fixed":
            self.address = validate_number(self.address)
        elif self.address:
            raise ValueError(f"number cannot be used with {self.mode} mode")
        if self.country and self.mode != "prompt":
            raise ValueError("country requires prompt mode")
        # fail now rather than when a client connects:
        if len(self.render_message("0" * 12)) > MAX_MESSAGE:
            raise ValueError(f"message must not exceed {MAX_MESSAGE} characters")
        self.make_request("+10000000000", "0" * self.digits)

    def get_destination_prompt(self) -> str:
        return f"Mobile phone number (default country {self.country})" if self.country else "Mobile phone number (with country code)"

    def parse_prompted_destination(self, value: str) -> str:
        number = value.translate(NUMBER_SEPARATORS)
        if self.country and number and not number.startswith(("+", "00")):
            number = self.country + number.removeprefix("0")
        return validate_number(number)

    def validate_destination(self, value: str) -> str:
        return validate_number(value)

    def render_message(self, code: str) -> str:
        return self.message.replace("{code}", code)

    def read_headers(self) -> list[tuple[str, str]]:
        with open(self.headers_file, encoding="utf-8") as f:
            return parse_headers(f.read())

    def make_request(self, number: str, code: str) -> Request:
        values = {
            "to": number,
            "to_digits": number.removeprefix("+"),
            "from": self.sender,
            "code": code,
            "message": self.render_message(code),
        }
        url = render(self.url, values, url_escape)
        data = None
        if self.method != "GET":
            if self.body_format == "json":
                body = render(self.body, values, json_escape)
                json.loads(body)
            else:
                body = render(self.body, values, form_escape)
            data = body.encode("utf-8")
        request = Request(url, data=data, method=self.method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "xpra")
        if data is not None:
            request.add_header("Content-Type", CONTENT_TYPES[self.body_format])
        return request

    def send_code(self, address: str, code: str) -> None:
        request = self.make_request(address, code)
        if self.headers_file:
            for name, value in self.read_headers():
                request.add_header(name, value)
        handlers = [NoRedirectHandler()]
        if request.type == "https":
            handlers.append(HTTPSHandler(context=make_ssl_context(self.http_ssl_options)))
        try:
            response = build_opener(*handlers).open(request, timeout=self.http_timeout)  # nosec B310
        except HTTPError as e:
            # raised for error statuses and refused redirects
            e.close()
            raise ValueError(f"sms provider returned status {e.code}") from None
        with response:
            reply = response.read(OUTPUT_LIMIT)
            log("sms provider replied with status %s: %r", response.status, reply)
            if not 200 <= response.status < 300:
                raise ValueError(f"unexpected sms provider status {response.status}")
