# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import csv
from xpra.os_util import bytestostr, OSX
from xpra.log import Logger

log = Logger("auth")


class Handler:

    def __init__(self, client, **kwargs):
        self.client = client
        self.services = (kwargs.pop("gss-services", "") or os.environ.get("XPRA_GSS_SERVICES", "") or "*").split(",")

    def __repr__(self):
        return "gss"

    @staticmethod
    def get_digest() -> str:
        return "gss"

    def handle(self, challenge:str, digest, prompt:str):  # pylint: disable=unused-argument
        if not digest.startswith("gss:"):
            #not a gss challenge
            log("%s is not a gss challenge", digest)
            return None
        try:
            #pylint: disable=import-outside-toplevel
            import gssapi       #@UnresolvedImport
            self.gssapi = gssapi
            if OSX:
                # this is a workaround for `py2app`,
                # to ensure it includes all the modules we need:
                from gssapi.raw import cython_converters, cython_types, oids    # @UnresolvedImport
                assert cython_converters and cython_types and oids
        except ImportError as e:
            log.warn("Warning: cannot use gss authentication handler")
            log.warn(" %s", e)
            return None
        service = bytestostr(digest.split(b":", 1)[1])
        if service not in self.services and "*" not in self.services:
            log.warn("Warning: invalid GSS request for service '%s'", service)
            log.warn(" services supported: %s", csv(self.services))
            return None
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
                log.estr(e)
            return None
        log("gss token=%s", repr(token))
        return token
