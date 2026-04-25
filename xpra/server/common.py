# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from collections.abc import Sequence
from xpra.net.compression import Compressed

from xpra.common import noop

GET_SOURCES_BY_TYPE: Final[str] = "get_sources_by_type"


def get_sources_by_type(server, subsystem_type=object, exclude=None) -> Sequence:
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


def make_icon_packet(*names: str) -> tuple[str, int, int, str, int, Compressed]:
    import os
    from io import BytesIO
    from xpra.platform.paths import get_icon_filename
    from xpra.util.io import load_binary_file
    from xpra.codecs.pillow.decoder import open_only
    from xpra.net.packet_type import DISPLAY_ICON
    for icon_name in names:
        filename = get_icon_filename(icon_name)
        if not os.path.exists(filename):
            continue
        fdata = load_binary_file(filename)
        if not fdata:
            continue
        img = open_only(fdata)
        w, h = img.size
        buf = BytesIO()
        img.save(buf, "png")
        data = buf.getvalue()
        buf.close()
        return DISPLAY_ICON, w, h, "png", w*4, Compressed("png", data)
    raise RuntimeError("failed to locate any icons")
