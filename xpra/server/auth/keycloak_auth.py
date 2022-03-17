# This file is part of Xpra.
# Copyright (C) 2016-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2022 Nathalie Casati <nat@yuka.ch>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import json

from xpra.util import typedict
from xpra.server.auth.sys_auth_base import SysAuthenticator, log
from keycloak import KeycloakOpenID
from oauthlib.oauth2 import WebApplicationClient

KEYCLOAK_SERVER_URL = os.environ.get("XPRA_KEYCLOAK_SERVER_URL", "http://localhost:8080/auth/")
KEYCLOAK_REALM_NAME = os.environ.get("XPRA_KEYCLOAK_REALM_NAME", "example_realm")
KEYCLOAK_CLIENT_ID  = os.environ.get("XPRA_KEYCLOAK_CLIENT_ID", "example_client")
KEYCLOAK_CLIENT_SECRET_KEY = os.environ.get("XPRA_KEYCLOAK_CLIENT_SECRET_KEY", "secret")
KEYCLOAK_REDIRECT_URI = os.environ.get("XPRA_KEYCLOAK_REDIRECT_URI", "http://localhost/login/")
KEYCLOAK_SCOPE = os.environ.get("XPRA_KEYCLOAK_SCOPE", "openid")
KEYCLOAK_GRANT_TYPE = os.environ.get("XPRA_KEYCLOAK_GRANT_TYPE", "authorization_code")


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        self.server_url = kwargs.pop("server_url", KEYCLOAK_SERVER_URL)
        self.realm_name = kwargs.pop("realm_name", KEYCLOAK_REALM_NAME)
        self.client_id = kwargs.pop("client_id", KEYCLOAK_CLIENT_ID)
        self.client_secret_key = kwargs.pop("client_secret_key", KEYCLOAK_CLIENT_SECRET_KEY)
        self.redirect_uri = kwargs.pop("redirect_uri", KEYCLOAK_REDIRECT_URI)
        self.scope = kwargs.pop("scope", KEYCLOAK_SCOPE)
        self.grant_type = kwargs.pop("grant_type", KEYCLOAK_GRANT_TYPE)
        kwargs["prompt"] = kwargs.pop("prompt", "keycloak")

        if KEYCLOAK_GRANT_TYPE == "authorization_code":
          super().__init__(**kwargs)
          log("keycloak auth: server_url=%s, client_id=%s, realm_name=%s, redirect_uri=%s, scope=%s, grant_type=%s",
              self.server_url, self.client_id, self.realm_name, self.redirect_uri, self.scope, self.grant_type)

          # Get authorization code
          client = WebApplicationClient(KEYCLOAK_CLIENT_ID)
          authorization_url = KEYCLOAK_SERVER_URL + 'realms/' + KEYCLOAK_REALM_NAME + '/protocol/openid-connect/auth'
          self.salt = client.prepare_request_uri(
                      authorization_url,
                      redirect_uri = KEYCLOAK_REDIRECT_URI,
                      scope = [KEYCLOAK_SCOPE],
          )
        else:
          raise(NotImplementedError("Warning: only grant type \"authorization_code\" is currently supported."))

    def __repr__(self):
        return "keycloak"

    def get_challenge(self, digests):
        assert not self.challenge_sent
        if "keycloak" not in digests:
            log.error("Error: client does not support keycloak authentication")
            return None
        self.challenge_sent = True
        return self.salt, "keycloak"

    def check(self, response_json) -> bool:
        assert self.challenge_sent
        
        if response_json is None or response_json == "":
          log.error("keycloak authentication failed: invalid response received from authorization endpoint.")
          return False
        
        #log("response_json: %s", repr(response_json))
        response = json.loads(response_json)

        if type(response) != dict or ("code" not in response and "error" not in response):
          log.error("keycloak authentication failed: invalid response received from authorization endpoint.")
          return False

        log("check(%s)", repr(response))

        if "error" in response:
          log.error("keycloak authentication failed with error %s: %s", response["error"], response["error_description"])
          return False

        if "code" in response:
          # Configure client
          keycloak_openid = KeycloakOpenID(server_url=KEYCLOAK_SERVER_URL,
                            client_id=KEYCLOAK_CLIENT_ID,
                            realm_name=KEYCLOAK_REALM_NAME,
                            client_secret_key=KEYCLOAK_CLIENT_SECRET_KEY)

          try:
            # Get well_known
            #config_well_know = keycloak_openid.well_know()
            #log("well_known: %s", repr(config_well_know))
        
            # Get token
            token = keycloak_openid.token(code=response["code"], grant_type=[KEYCLOAK_GRANT_TYPE], redirect_uri=KEYCLOAK_REDIRECT_URI)

            # Verify token
            token_info = keycloak_openid.introspect(token['access_token'])
            #log("token_info: %s", repr(token_info))

            if token_info["active"]:
              # Get userinfo
              #user_info = keycloak_openid.userinfo(token['access_token'])
              #log("userinfo_info: %s", repr(user_info))

              log("keycloak authentication succeeded: token is active")
            else:
              log.error("keycloak authentication failed: token is not active")
            return token_info["active"]
          except Exception as e:
            log.error("keycloak authentication failed with error code %s: %s", e.response_code, e.error_message)
            return False
