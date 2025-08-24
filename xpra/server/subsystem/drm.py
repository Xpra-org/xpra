# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.server.subsystem.stub import StubServerMixin


class DRMInfo(StubServerMixin):
    PREFIX = "drm"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.display = os.environ.get("DISPLAY", "")
        self.drm_info = {}

    def threaded_setup(self) -> None:
        try:
            from xpra.codecs.drm.drm import query  # pylint: disable=import-outside-toplevel
        except ImportError as e:
            from xpra.log import Logger
            log = Logger("screen")
            log(f"no drm query: {e}")
        else:
            self.drm_info = query()

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if self.drm_info:
            info = dict(self.drm_info)
        return {"drm": info}
