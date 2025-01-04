#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import TypeAlias
from collections.abc import Sequence


# These chipsets will use OpenGL,
# there will not be any warnings, even if the vendor is greylisted:
GL_MATCH_LIST: TypeAlias = dict[str, Sequence[str]]

WHITELIST: GL_MATCH_LIST = {
}

# Chipsets from these vendors will be disabled without triggering any warnings:
GREYLIST: GL_MATCH_LIST = {
    "renderer":
        (
            "SVGA3D",
            "Software Rasterizer",
            "llvmpipe",
            # "NV134",
        ),
}

# These chipsets will be disabled by default:
BLOCKLIST: GL_MATCH_LIST = {
    "renderer":
        (),
    "vendor":
        (
            # "VMware, Inc.",
            # "Humper",
            # to disable nvidia, uncomment this:
            # "NVIDIA Corporation",
        ),
    "platform":
        (
            # "darwin",
        ),
}


# for testing:
# GREYLIST["vendor"].append("NVIDIA Corporation")
# WHITELIST["renderer"] = ["GeForce GTX 760/PCIe/SSE2"]
# frequent crashes on OSX with GT 650M: (see ticket #808)
# if OSX:
#    GREYLIST.setdefault("vendor", []).append("NVIDIA Corporation")


class OpenGLFatalError(ImportError):
    pass
