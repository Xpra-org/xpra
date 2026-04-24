# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket
from typing import Any

from xpra.net.common import FULL_INFO
from xpra.platform.info import get_name, get_username
from xpra.os_util import get_machine_id, BITS
from xpra.client.base.stub import StubClientMixin


class InfoClient(StubClientMixin):
    """
    Adds extra information about the client
    """

    def __init__(self):
        pass

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if FULL_INFO > 1:
            caps |= {
                "python.version": sys.version_info[:3],
                "python.bits": BITS,
                "user": get_username(),
                "name": get_name(),
                "argv": sys.argv,
            }
            try:
                caps["hostname"] = socket.gethostname()
            except socket.error:
                pass
            vi = self.get_version_info()
            caps["build"] = vi
        if mid := get_machine_id():
            caps["machine_id"] = mid
        return caps

    def get_info(self) -> dict[str, Any]:
        return self.get_caps()
