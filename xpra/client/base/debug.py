# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import FULL_INFO, init_leak_detection
from xpra.platform.info import get_sys_info
from xpra.util.pysystem import get_frame_info, dump_all_frames
from xpra.util.system import get_env_info, get_sysconfig_info
from xpra.client.base.stub import StubClientMixin
from xpra.exit_codes import ExitValue
from xpra.util.env import envbool

SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)


class DebugClient(StubClientMixin):
    """
    Adds some debug functions
    """

    def run(self) -> ExitValue:
        def is_closed() -> bool:
            return getattr(self, "exit_code", None) is not None

        init_leak_detection(is_closed)
        return 0

    def cleanup(self) -> None:
        dump_all_frames()

    def get_info(self) -> dict[str, Any]:
        info = {}
        if FULL_INFO > 0:
            info = {
                "sys": get_sys_info(),
                "threads": get_frame_info(),
                "env": get_env_info(),
            }
        if SYSCONFIG:
            info["sysconfig"] = get_sysconfig_info()
        return info
