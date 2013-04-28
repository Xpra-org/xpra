# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys


def get_app_dir():
    try:
        # test for a local installation path (run from source tree):
        local_share_path = os.path.join(os.path.dirname(sys.argv[0]), "..", "share", "xpra")
        if os.path.exists(local_share_path):
            return local_share_path
    except:
        pass
    #is there a better/cleaner way?
    options = [os.path.join(sys.exec_prefix, "share", "xpra"),
               "/usr/share/xpra",
               "/usr/local/share/xpra"]
    for x in options:
        if os.path.exists(x):
            return x
    return os.getcwd()

def get_icon_dir():
    return os.path.join(get_app_dir(), "icons")
