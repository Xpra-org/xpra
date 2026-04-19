# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Sequence

from xpra.common import noop


GET_SOURCES_BY_TYPE: Final[str] = "get_sources_by_type"


def get_sources_by_type(server, subsystem_type: type, exclude=None) -> Sequence:
    fn = getattr(server, GET_SOURCES_BY_TYPE, noop)
    if fn == noop:
        from xpra.log import Logger
        Logger("server").error("Error: no %r in %s", GET_SOURCES_BY_TYPE, server)
        return ()
    return fn(subsystem_type, exclude)


def may_update_bandwidth_limits(server) -> None:
    # this method is only available when the NetworkState mixin is enabled:
    update_bandwidth_limits = getattr(server, "update_bandwidth_limits", noop)
    update_bandwidth_limits()
