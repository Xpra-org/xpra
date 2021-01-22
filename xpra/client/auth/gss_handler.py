# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import csv
from xpra.os_util import bytestostr, OSX
from xpra.log import Logger

log = Logger("auth")


class Handler:

    def __init__(self, client, **_kwargs):
        self.client = client
        self.services = os.environ.get("XPRA_GSS_SERVICES", "*").split(",")

    def __repr__(self):
        return "gss"

    def get_digest(self) -> str:
        return "gss"

    def handle(self, packet) -> bool:
        digest = bytestostr(packet[3])
        if not digest.startswith("gss:"):
            #not a gss challenge
            log("%s is not a gss challenge", digest)
            return False
        try:
            import gssapi       #@UnresolvedImport
            self.gssapi = gssapi
            if OSX and False:
                from gssapi.raw import (cython_converters, cython_types, oids)  # @UnresolvedImport
                assert cython_converters and cython_types and oids
        except ImportError as e:
            log.warn("Warning: cannot use gss authentication handler")
            log.warn(" %s", e)
            return False
        service = bytestostr(digest.split(b":", 1)[1])
        if service not in self.services and "*" not in self.services:
            log.warn("Warning: invalid GSS request for service '%s'", service)
            log.warn(" services supported: %s", csv(self.services))
            return False
        log("gss service=%s", service)
        service_name = self.gssapi.Name(service)
        try:
            ctx = self.gssapi.SecurityContext(name=service_name, usage="initiate")
            token = ctx.step()
        except Exception as e:
            log("gssapi failure", exc_info=True)
            log.error("Error: gssapi client authentication failure:")
            try:
                for x in str(e).split(":", 2):
                    log.error(" %s", x.lstrip(" "))
            except Exception:
                log.error(" %s", e)
            return False
        log("gss token=%s", repr(token))
        self.client.send_challenge_reply(packet, token)
        return True
