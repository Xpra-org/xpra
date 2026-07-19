# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
"""
OAuth2 Bearer token authentication.

This module validates a Bearer token supplied either:
* in HTTP headers captured during the websocket upgrade, or
* in a client capability named by the ``capability`` option.

The websocket header path is intended for deployments where an OAuth-aware
reverse proxy sits in front of Xpra. The proxy performs the browser OAuth/OIDC
login flow, then forwards only authenticated websocket requests to Xpra with a
trusted token header. Xpra must only trust these headers when clients cannot
bypass the proxy and connect to the backend port directly.

Typical proxy flow:
1. Browser authenticates with the proxy using OAuth/OIDC.
2. Browser opens the Xpra websocket through the same proxy.
3. Proxy forwards the websocket upgrade to Xpra and injects either:
   ``Authorization: Bearer <access-token>``, or another configured Bearer header.
4. Xpra stores the upgrade headers in ``connection.options["http-headers"]``.
5. This module reads the configured header and validates the Bearer token.

Example Xpra socket configuration using OAuth2 token introspection::

    --bind-tcp=127.0.0.1:14500,auth=oauth(introspection-url=https://idp.example/oauth2/introspect,client-id=xpra,client-secret=secret,scope=xpra)

Example using a proxy-injected custom header::

    --bind-tcp=127.0.0.1:14500,auth=oauth(header=X-Xpra-Authorization,introspection-url=https://idp.example/oauth2/introspect)

In that case the proxy must send::

    X-Xpra-Authorization: Bearer <access-token>

Example for simple tests or tightly controlled deployments::

    --bind-tcp=127.0.0.1:14500,auth=oauth(token=shared-test-token)

Proxy notes:
* Bind Xpra to localhost or a private network address when trusting proxy
  headers.
* Strip any incoming client-supplied authentication headers before injecting
  trusted ones.
* Use HTTPS between browser and proxy. Use a private network, TLS, or local
  loopback between proxy and Xpra.
* Browser websocket APIs cannot set arbitrary ``Authorization`` headers
  directly, so proxy-injected headers or authenticated proxy cookies are the
  practical browser deployment pattern.
* Non-browser websocket clients can usually send ``Authorization: Bearer``
  directly.
"""

import base64
import json
import hmac
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.util.objects import typedict
from xpra.util.env import envint

OAUTH_TIMEOUT = envint("XPRA_OAUTH_TIMEOUT", 10)


def get_header(headers: dict, name: str) -> str:
    lname = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lname:
            return str(value)
    return ""


def get_bearer_token(value: str) -> str:
    if not value:
        return ""
    scheme, sep, token = value.partition(" ")
    if sep and scheme.lower() == "bearer":
        return token.strip()
    return ""


class Authenticator(SysAuthenticator):

    __slots__ = (
        "audience", "capability", "client_id", "client_secret", "gid", "header", "headers", "introspection_url",
        "scope", "token", "uid", "username_claim",
    )

    def __init__(self, **kwargs):
        log("oauth.Authenticator(..)")
        self.uid = -1
        self.gid = -1
        self.header = kwargs.pop("header", "Authorization")
        self.capability = kwargs.pop("capability", "oauth.token")
        self.token = kwargs.pop("token", "")
        self.introspection_url = kwargs.pop("introspection-url", kwargs.pop("introspection_url", ""))
        self.client_id = kwargs.pop("client-id", kwargs.pop("client_id", ""))
        self.client_secret = kwargs.pop("client-secret", kwargs.pop("client_secret", ""))
        self.scope = kwargs.pop("scope", "")
        self.audience = kwargs.pop("audience", "")
        self.username_claim = kwargs.pop("username-claim", kwargs.pop("username_claim", "username"))
        connection = kwargs.get("connection", None)
        self.headers = getattr(connection, "options", {}).get("http-headers", {})
        log(f"http-headers({connection})={self.headers}")
        super().__init__(**kwargs)

    def __repr__(self):
        return "oauth"

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return False

    def get_token(self, caps: typedict) -> str:
        auth_header = get_header(self.headers, self.header)
        token = get_bearer_token(auth_header)
        if token:
            return token
        return caps.strget(self.capability, "")

    def authenticate(self, caps: typedict) -> bool:  # pylint: disable=arguments-differ
        token = self.get_token(caps)
        if not token:
            log.warn("Warning: oauth authentication failed")
            log.warn(" no bearer token found")
            return False
        if self.token:
            return self.check_token(token)
        if self.introspection_url:
            return self.check_introspection(token)
        log.warn("Warning: oauth authentication failed")
        log.warn(" no token or introspection-url configured")
        return False

    def check_token(self, token: str) -> bool:
        if hmac.compare_digest(token, self.token):
            return True
        log.warn("Warning: oauth authentication failed")
        log.warn(" bearer token does not match")
        return False

    def check_introspection(self, token: str) -> bool:
        data = {"token": token}
        if self.client_id and not self.client_secret:
            data["client_id"] = self.client_id
        request = Request(self.introspection_url, data=urlencode(data).encode("utf-8"))
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        request.add_header("Accept", "application/json")
        if self.client_id and self.client_secret:
            auth = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            request.add_header("Authorization", "Basic " + base64.b64encode(auth).decode("latin1"))
        try:
            with urlopen(request, timeout=OAUTH_TIMEOUT) as response:  # nosec B310
                response_data = response.read()
        except OSError as e:
            log("oauth introspection request failed", exc_info=True)
            log.warn("Warning: oauth authentication failed")
            log.warn(" token introspection request failed: %s", e)
            return False
        try:
            token_info = json.loads(response_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log("oauth introspection response parsing failed", exc_info=True)
            log.warn("Warning: oauth authentication failed")
            log.warn(" invalid token introspection response: %s", e)
            return False
        return self.check_token_info(token_info)

    def check_token_info(self, token_info: dict) -> bool:
        log("oauth token_info=%r", token_info)
        if not isinstance(token_info, dict):
            return False
        if token_info.get("active") is not True:
            log.warn("Warning: oauth authentication failed")
            log.warn(" token is not active")
            return False
        if self.scope:
            scopes = str(token_info.get("scope", "")).split()
            required_scopes = self.scope.split()
            if not set(required_scopes).issubset(scopes):
                log.warn("Warning: oauth authentication failed")
                log.warn(" token scope does not satisfy %r", self.scope)
                return False
        if self.audience:
            audience = token_info.get("aud", ())
            if isinstance(audience, str):
                audiences = {audience}
            else:
                audiences = set(audience or ())
            if self.audience not in audiences:
                log.warn("Warning: oauth authentication failed")
                log.warn(" token audience does not contain %r", self.audience)
                return False
        if self.username_claim:
            username = token_info.get(self.username_claim, "")
            if username:
                self.username = str(username)
        return True
