#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import
from xpra.client.base.stub import StubClientMixin

# default:
PlatformClient: type | None = StubClientMixin

platform_import(globals(), "client", True,
                "PlatformClient")
