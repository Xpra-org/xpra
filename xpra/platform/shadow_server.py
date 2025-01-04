# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence

from xpra.platform import platform_import

SHADOW_OPTIONS: dict[str, Callable[[], bool]] = {}

GSTREAMER_CAPTURE_ELEMENTS: Sequence[str] = ()


def ShadowServer(*_args):  # pragma: no cover
    raise NotImplementedError()


platform_import(globals(), "shadow_server", True,
                "ShadowServer",
                "SHADOW_OPTIONS",
                "GSTREAMER_CAPTURE_ELEMENTS",
                )
