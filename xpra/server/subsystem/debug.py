# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.os_util import POSIX
from xpra.common import init_leak_detection, CPUINFO
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("network")


class DebugServer(StubServerMixin):
    """
    Mixin for system state debugging, leak detection (file descriptors, memory)
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.mem_bytes = 0
        self.cpu_info: dict = {}

    def init(self, opts) -> None:
        self.init_cpuinfo()

    def setup(self) -> None:
        def is_closed() -> bool:
            return getattr(self, "_closing", False)

        init_leak_detection(is_closed)

    def get_info(self, _source=None) -> dict[str, Any]:
        info = {}
        if POSIX:
            info["load"] = tuple(int(x * 1000) for x in os.getloadavg())
        if self.mem_bytes:
            info["total-memory"] = self.mem_bytes
        if self.cpu_info:
            info["cpuinfo"] = {k: v for k, v in self.cpu_info.items() if k != "python_version"}
        return info

    def init_cpuinfo(self) -> None:
        if not CPUINFO:
            return
        # this crashes if not run from the UI thread!
        try:
            from cpuinfo import get_cpu_info
        except ImportError as e:
            log("no cpuinfo: %s", e)
            return
        self.cpu_info = get_cpu_info()
        if self.cpu_info:
            c = typedict(self.cpu_info)
            count = c.intget("count", 0)
            brand = c.strget("brand")
            if count > 0 and brand:
                log.info("%ix %s", count, brand)
