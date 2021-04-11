# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import csv
from xpra.os_util import bytestostr, WIN32
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
        log.error(" %s", e)

class Handler(object):

    def __init__(self, client, **_kwargs):
        self.client = client
        self.services = os.environ.get("XPRA_KERBEROS_SERVICES", "*").split(",")

    def __repr__(self):
        return "kerberos"

    def get_digest(self):
        return "kerberos"

    def handle(self, packet):
        digest = bytestostr(packet[3])
        if not digest.startswith("kerberos:"):
            log("%s is not a kerberos challenge", digest)
            #not a kerberos challenge
            return False
        try:
            if WIN32:
                import winkerberos as kerberos
            else:
                import kerberos         #@UnresolvedImport
        except ImportError as e:
            log.warn("Warning: cannot use kerberos authentication handler")
            log.warn(" %s", e)
            return False
        service = digest.split(":", 1)[1]
        if service not in self.services and "*" not in self.services:
            log.warn("Warning: invalid kerberos request for service '%s'", service)
            log.warn(" services supported: %s", csv(self.services))
            return False
        log("kerberos service=%s", service)
        try:
            r, ctx = kerberos.authGSSClientInit(service)
            assert r==1, "return code %s" % r
        except Exception as e:
            log("kerberos.authGSSClientInit(%s)", service, exc_info=True)
            log.error("Error: cannot initialize kerberos client:")
            log_kerberos_exception(e)
            return False
        try:
            kerberos.authGSSClientStep(ctx, "")
        except Exception as e:
            log("kerberos.authGSSClientStep", exc_info=True)
            log.error("Error: kerberos client authentication failure:")
            log_kerberos_exception(e)
            return False
        token = kerberos.authGSSClientResponse(ctx)
        log("kerberos token=%s", token)
        self.client.send_challenge_reply(packet, token)
        return True
