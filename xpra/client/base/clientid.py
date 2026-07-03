# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import uuid
from typing import Any

from xpra.net.common import FULL_INFO
from xpra.os_util import get_user_uuid
from xpra.util.version import vparts, XPRA_VERSION
from xpra.client.base.stub import StubClientMixin


class ClientID(StubClientMixin):
    """
    Essential client information
    """
    PREFIX = "clientid"

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        self.uuid: str = get_user_uuid()
        self.session_id: str = uuid.uuid4().hex

    def get_caps(self) -> dict[str, Any]:
        caps = {
            "uuid": self.uuid,
            "version": vparts(XPRA_VERSION, FULL_INFO + 1),
            "session-id": self.session_id,
        }
        if FULL_INFO > 0:
            caps |= {
                # `client_type` is identity state owned by the concrete client
                # (set before this subsystem even exists - see `defaults_init`):
                "client_type": self.client.client_type,
            }
        return caps

    def get_info(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "version": XPRA_VERSION,
            "session-id": self.session_id,
            "client_type": self.client.client_type,
        }
