# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

APPNAME = os.environ.get("APPNAME", "")

# workaround for macos where we need to setup the application name early,
# before we import the macos components
if sys.platform == "darwin" and APPNAME:
    from xpra.util.system import set_proc_title
    set_proc_title(APPNAME)
