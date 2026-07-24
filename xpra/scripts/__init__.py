# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

# workaround for macos where we need to setup the application name early,
# before we import the macos components
if sys.platform == "darwin":
    import os
    if appname := os.environ.get("APPNAME", ""):
        from xpra.util.system import set_proc_title
        set_proc_title(appname)
    os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")
