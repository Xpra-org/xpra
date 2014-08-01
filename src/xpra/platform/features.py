# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#defaults which may be overriden by platform_import:
LOCAL_SERVERS_SUPPORTED = False
SHADOW_SUPPORTED = False
MMAP_SUPPORTED = False
SYSTEM_TRAY_SUPPORTED = False
DEFAULT_SSH_CMD = False
GOT_PASSWORD_PROMPT_SUGGESTION = ""
CLIPBOARDS = []
CLIPBOARD_WANT_TARGETS = False
CLIPBOARD_GREEDY = False
CLIPBOARD_NATIVE_CLASS = None
CAN_DAEMONIZE = False
UI_THREAD_POLLING = 0

_features_list_ = ["LOCAL_SERVERS_SUPPORTED",
                "SHADOW_SUPPORTED",
                "CAN_DAEMONIZE",
                "MMAP_SUPPORTED",
                "SYSTEM_TRAY_SUPPORTED",
                "DEFAULT_SSH_CMD",
                "GOT_PASSWORD_PROMPT_SUGGESTION",
                "CLIPBOARDS",
                "CLIPBOARD_WANT_TARGETS",
                "CLIPBOARD_GREEDY",
                "CLIPBOARD_NATIVE_CLASS",
                "UI_THREAD_POLLING"]
from xpra.platform import platform_import
platform_import(globals(), "features", False,
                *_features_list_)


def main():
    from xpra.util import nonl, pver
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s : %s" % (k.ljust(32), nonl(pver(v))))
    from xpra.platform import init, clean
    try:
        init("Features-Info", "Features Info")
        d = {}
        for k in sorted(_features_list_):
            d[k] = globals()[k]
        print_dict(d)
    finally:
        clean()

if __name__ == "__main__":
    main()
