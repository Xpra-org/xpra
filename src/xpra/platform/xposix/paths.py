# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys


def get_app_dir():
    return os.path.join(sys.exec_prefix, "share", "xpra")

def get_icon_dir():
    return os.path.join(get_app_dir(), "icons")
