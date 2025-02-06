# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.challenge.handler import AuthenticationHandler
from xpra.util.str_fn import csv
from xpra.os_util import WIN32
from xpra.log import Logger

log = Logger("auth")


def log_kerberos_exception(e):
    try:
        for x in e.args:
            if isinstance(x, (list, tuple)):
                try:
                    log.error(" %s", csv(x))
                    continue
                except Exception:
                    pass
            log.error(" %s", x)
    except Exception:
        log.estr(e)


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        services_str = kwargs.pop("kerberos-services", "") or os.environ.get("XPRA_KERBEROS_SERVICES", "") or "*"
        self.services = services_str.split(",")

    def __repr__(self):
        return "kerberos"

    def get_digest(self) -> str:
        return "kerberos"

    def handle(self, challenge: bytes, digest: str, prompt: str):  # pylint: disable=unused-argument
        if not digest.startswith("kerberos:"):
            log("%s is not a kerberos challenge", digest)
            # not a kerberos challenge
            return None
        try:
            # pylint: disable=import-outside-toplevel
            if WIN32:
                import winkerberos as kerberos
            else:
                import kerberos
        except ImportError as e:
            log.warn("Warning: cannot use kerberos authentication handler")
            log.warn(" %s", e)
            return False
        service = digest.split(":", 1)[1]
        if service not in self.services and "*" not in self.services:
            log.warn("Warning: invalid kerberos request for service '%s'", service)
            log.warn(" services supported: %s", csv(self.services))
            return None
        log("kerberos service=%s", service)
        try:
            r, ctx = kerberos.authGSSClientInit(service)  # @UndefinedVariable
            if r != 1:
                log("kerberos.authGSSClientInit failed and returned %s", r)
                return None
        except Exception as e:
            log("kerberos.authGSSClientInit(%s)", service, exc_info=True)
            log.error("Error: cannot initialize kerberos client:")
            log_kerberos_exception(e)
            return None
        try:
            kerberos.authGSSClientStep(ctx, "")  # @UndefinedVariable
        except Exception as e:
            log("kerberos.authGSSClientStep", exc_info=True)
            log.error("Error: kerberos client authentication failure:")
            log_kerberos_exception(e)
            return None
        token = kerberos.authGSSClientResponse(ctx)  # @UndefinedVariable
        log("kerberos token=%s", token)
        return token
