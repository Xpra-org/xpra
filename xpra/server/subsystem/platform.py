# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.util.version import get_platform_info


class PlatformServer(StubServerMixin):
    """
    Exposes platform info, populates the cache during threaded initialization.
    """
    PREFIX = "platform"

    def threaded_setup(self) -> None:
        get_platform_info()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            PlatformServer.PREFIX: get_platform_info(),
        }
