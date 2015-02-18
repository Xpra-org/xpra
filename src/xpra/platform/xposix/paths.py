# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import site


def get_install_prefix():
    #special case for "user" installations, ie:
    #$HOME/.local/lib/python2.7/site-packages/xpra/platform/paths.py
    try:
        base = site.getuserbase()
    except:
        base = site.USER_BASE
    if __file__.startswith(base):
        return base
    return sys.prefix

def get_resources_dir():
    #is there a better/cleaner way?
    options = [get_install_prefix(),
               sys.exec_prefix,
               "/usr",
               "/usr/local"]
    for x in options:
        p = os.path.join(x, "share", "xpra")
        if os.path.exists(p) and os.path.isdir(p):
            return p
    try:
        # test for a local installation path (run from source tree):
        local_share_path = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), "..", "share", "xpra"))
        if os.path.exists(local_share_path) and os.path.isdir(local_share_path):
            return local_share_path
    except:
        pass
    return os.getcwd()

def get_app_dir():
    return get_resources_dir()

def get_icon_dir():
    return os.path.join(get_app_dir(), "icons")
