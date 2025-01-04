# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2022 Nathalie Casati <nat@yuka.ch>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import json
from collections.abc import Sequence

from xpra.auth.sys_auth_base import SysAuthenticator, log

KEYCLOAK_SERVER_URL = os.environ.get("XPRA_KEYCLOAK_SERVER_URL", "https://localhost:8080/auth/")
KEYCLOAK_REALM_NAME = os.environ.get("XPRA_KEYCLOAK_REALM_NAME", "example_realm")
KEYCLOAK_CLIENT_ID = os.environ.get("XPRA_KEYCLOAK_CLIENT_ID", "example_client")
KEYCLOAK_CLIENT_SECRET_KEY = os.environ.get("XPRA_KEYCLOAK_CLIENT_SECRET_KEY", "secret")
KEYCLOAK_REDIRECT_URI = os.environ.get("XPRA_KEYCLOAK_REDIRECT_URI", "http://localhost/login/")
KEYCLOAK_CLAIM_FIELD = os.environ.get("XPRA_KEYCLOAK_CLAIM_FIELD", "")  # field containing groups claim
KEYCLOAK_AUTH_GROUPS = os.environ.get("XPRA_KEYCLOAK_AUTH_GROUPS", "")  # authorized groups
KEYCLOAK_AUTH_CONDITION = os.environ.get("XPRA_KEYCLOAK_AUTH_CONDITION", "and")  # authentication condition
KEYCLOAK_SCOPE = os.environ.get("XPRA_KEYCLOAK_SCOPE", "openid")
KEYCLOAK_GRANT_TYPE = os.environ.get("XPRA_KEYCLOAK_GRANT_TYPE", "authorization_code")


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        self.server_url = kwargs.pop("server_url", KEYCLOAK_SERVER_URL)
        self.realm_name = kwargs.pop("realm_name", KEYCLOAK_REALM_NAME)
        self.client_id = kwargs.pop("client_id", KEYCLOAK_CLIENT_ID)
        self.client_secret_key = kwargs.pop("client_secret_key", KEYCLOAK_CLIENT_SECRET_KEY)
        self.redirect_uri = kwargs.pop("redirect_uri", KEYCLOAK_REDIRECT_URI)
        self.claim_field = kwargs.pop("claim_field", KEYCLOAK_CLAIM_FIELD)
        self.auth_groups = set(kwargs.pop("auth_groups", KEYCLOAK_AUTH_GROUPS).split())
        self.auth_condition = kwargs.pop("auth_condition", KEYCLOAK_AUTH_CONDITION)
        self.scope = kwargs.pop("scope", KEYCLOAK_SCOPE)
        self.grant_type = kwargs.pop("grant_type", KEYCLOAK_GRANT_TYPE)

        # use keycloak as default prompt
        kwargs["prompt"] = kwargs.pop("prompt", "keycloak")

        if self.grant_type != "authorization_code":
            raise ValueError(f"grant type {self.grant_type!r} is not supported, only \"authorization_code\"")

        super().__init__(**kwargs)
        log("keycloak auth: server_url=%s, client_id=%s, realm_name=%s, redirect_uri=%s, scope=%s, grant_type=%s",
            self.server_url, self.client_id, self.realm_name, self.redirect_uri, self.scope, self.grant_type)

        try:
            # noinspection PyPackageRequirements
            from oauthlib.oauth2 import WebApplicationClient
            # Get authorization code
            client = WebApplicationClient(self.client_id)
            authorization_url = self.server_url + 'realms/' + self.realm_name + '/protocol/openid-connect/auth'
            client_uri = client.prepare_request_uri(authorization_url,
                                                    redirect_uri=self.redirect_uri,
                                                    scope=[self.scope],
                                                    )
            self.salt = client_uri.encode("utf8")
        except ImportError as e:  # pragma: no cover
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use keycloak authentication:")
            log.warn(" %s", e)
            # unsure how to fail the auth at this point so we raise the exception
            raise

    def __repr__(self):
        return "keycloak"

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        assert not self.challenge_sent
        if "keycloak" not in digests:
            log.error("Error: client does not support keycloak authentication")
            return b"", ""
        self.challenge_sent = True
        return self.salt, "keycloak"

    def check(self, response_json: bytes) -> bool:
        log(f"check({response_json!r})")
        assert self.challenge_sent
        if not response_json:
            log.error("Error: keycloak authentication failed")
            log.error(" invalid response received from authorization endpoint")
            return False

        try:
            response = json.loads(response_json)
        except (json.JSONDecodeError, TypeError):
            log.error("Error: keycloak authentication failed")
            log.error(" invalid response received from authorization endpoint")
            log("failed to parse json: %r", response_json, exc_info=True)
            return False
        log(f"json.loads({response_json!r})={response!r}")

        if not isinstance(response, dict):
            log.error("Error: keycloak authentication failed")
            log.error(" invalid response received from authorization endpoint")
            log("response is of type %r but dict type is required", type(response))
            log("failed to load response %r", response)
            return False

        log("check(%r)", response)
        auth_code = response.get("code")
        error = response.get("error")

        if error:
            log.error("Error: keycloak authentication failed")
            log.error("%s: %s", error, response.get("error_description"))
            return False

        if not auth_code:
            log.error("Error: keycloak authentication failed")
            log.error(" invalid response received from authorization endpoint")
            return False

        try:
            # pylint: disable=import-outside-toplevel
            from keycloak import KeycloakOpenID
            from keycloak.exceptions import KeycloakError
        except ImportError as e:
            log("check(..)", exc_info=True)
            log.warn("Warning: cannot use keycloak authentication:")
            log.warn(" %s", e)
            return False

        try:
            # Configure client
            keycloak_openid = KeycloakOpenID(server_url=self.server_url,
                                             client_id=self.client_id,
                                             realm_name=self.realm_name,
                                             client_secret_key=self.client_secret_key)

            # Get well_known
            if hasattr(keycloak_openid, "well_known"):
                # version 1.8 and later:
                # https://github.com/marcospereirampj/python-keycloak/commit/6bfbd0d15fa5981f35e5a6866b3efd62ef0dc968
                config_well_known = keycloak_openid.well_known()
            else:
                config_well_known = keycloak_openid.well_know()
            log("well_known: %r", config_well_known)

            # Get token
            token = keycloak_openid.token(code=auth_code,
                                          grant_type=[self.grant_type],
                                          redirect_uri=self.redirect_uri)

            # Verify token
            access_token = token.get("access_token")
            if not access_token:
                log.error("Error: keycloak authentication failed as access token is missing")
                return False

            token_info = keycloak_openid.introspect(access_token)
            log("token_info: %r", token_info)

            token_state = token_info.get("active")
            if token_state is None:
                log.error("Error: keycloak authentication failed as token state is missing")
                return False

            if token_state is False:
                log.error("Error: keycloak authentication failed as token state not active")
                return False

            if token_state is not True:
                log.error("Error: keycloak authentication failed as token state is invalid")
                return False

            log("keycloak: token is active")

            user_info = keycloak_openid.userinfo(access_token)
            log("user_info: %r", user_info)

            log("claim_field: %r", self.claim_field)
            log("auth_groups: %r", self.auth_groups)

            # if claim_field is defined, check that the auth_groups match the groups_claim condition
            if self.claim_field:
                if not self.auth_groups:
                    log.error("Error: keycloak authentication failed as auth_groups is invalid")
                    return False

                def extract_groups_claim(data_dict, keys):

                    """
                    Extracts a nested value from a dictionary using a list of keys.

                    This function is specifically designed to handle nested dictionaries,
                    such as the ones provided by Keycloak userinfo.

                    For example, userinfo could contain the following structure:

                    "resource_access": {
                        "roles": {
                            "group": [
                                "client-group-1",
                                "client-group-2"
                            ]
                        }
                    }

                    In this scenario, the function traverses the dictionary using the keys
                    ['resource_access', 'roles', 'group'] to extract the list of groups
                    ['client-group-1', 'client-group-2'].

                    Args:
                        data_dict (dict): The dictionary from which to extract the nested value.
                        keys (list): A list of keys that represents the path to the desired value
                                     in the nested dictionary.

                    Returns:
                        The nested value extracted from the dictionary. If the sequence of keys is
                        exhausted, it returns the portion of the dictionary that it has navigated to.
                    """
                    return extract_groups_claim(data_dict[keys.pop(0)], keys) if len(keys) else data_dict

                groups_claim = set(extract_groups_claim(user_info, self.claim_field.split('.')))
                log("groups_claim: %r", groups_claim)

                if self.auth_condition == "or":
                    if not self.auth_groups.intersection(groups_claim):
                        log.error("Error: keycloak authentication failed as groups claim is not satisfied")
                        return False
                elif self.auth_condition == "and":
                    if not self.auth_groups.issubset(groups_claim):
                        log.error("Error: keycloak authentication failed as groups claim is not satisfied")
                        return False
                else:
                    log.error("Error: keycloak authentication failed as auth_condition is invalid")
                    return False

            log("keycloak authentication succeeded")
            return True
        except KeycloakError as e:
            log.error("Error: keycloak authentication failed")
            log.error(" error code %s: %s", e.response_code, e.error_message)
            return False


def main(args) -> int:  # pragma: no cover
    if len(args) != 2:
        print("invalid number of arguments")
        print("usage:")
        print(f"{args[0]} response_json")
        return 1
    response_json = args[1]

    a = Authenticator()
    a.get_challenge(("keycloak", ))

    if not a.check(response_json):
        print("failed")
        return -1
    print("success")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
