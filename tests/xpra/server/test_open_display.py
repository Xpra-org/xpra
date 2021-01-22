#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.wait_for_x_server import wait_for_x_server       #@UnresolvedImport
import os

wait_for_x_server(os.environ.get("DISPLAY", ":0"), 5)
