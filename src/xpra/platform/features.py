# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
#defaults which may be overriden by platform_import:
LOCAL_SERVERS_SUPPORTED = sys.version_info[0]<3
XDUMMY = False
XDUMMY_WRAPPER = False
DISPLAYFD = False
SHADOW_SUPPORTED = True
CAN_DAEMONIZE = True
MMAP_SUPPORTED = True
SYSTEM_TRAY_SUPPORTED = False
REINIT_WINDOWS = False

CLIPBOARDS = []
CLIPBOARD_WANT_TARGETS = False
CLIPBOARD_GREEDY = False
CLIPBOARD_NATIVE_CLASS = None

UI_THREAD_POLLING = 0
OPEN_COMMAND = "xdg-open"

DEFAULT_ENV = []

DEFAULT_SSH_COMMAND = "ssh -x"
DEFAULT_PULSEAUDIO_COMMAND = "pulseaudio --start --daemonize=false --system=false " + \
                                    "--exit-idle-time=-1 -n --load=module-suspend-on-idle " + \
                                    "--load=module-null-sink --load=module-native-protocol-unix "+ \
                                    "--log-level=2 --log-target=stderr"

if sys.version<'3':
    CLIENT_MODULES = ["xpra.client.gtk2.client"]
else:
    CLIENT_MODULES = ["xpra.client.gtk3.client"]


_features_list_ = ["LOCAL_SERVERS_SUPPORTED",
                "DISPLAYFD",
                "XDUMMY",
                "XDUMMY_WRAPPER",
                "SHADOW_SUPPORTED",
                "CAN_DAEMONIZE",
                "MMAP_SUPPORTED",
                "SYSTEM_TRAY_SUPPORTED",
                "REINIT_WINDOWS",
                "DEFAULT_ENV",
                "DEFAULT_SSH_COMMAND",
                "DEFAULT_PULSEAUDIO_COMMAND",
                "CLIPBOARDS",
                "CLIPBOARD_WANT_TARGETS",
                "CLIPBOARD_GREEDY",
                "CLIPBOARD_NATIVE_CLASS",
                "UI_THREAD_POLLING",
                "CLIENT_MODULES"]
from xpra.platform import platform_import
platform_import(globals(), "features", False,
                *_features_list_)


def main():
    from xpra.util import nonl, pver
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s : %s" % (k.ljust(32), nonl(pver(v))))
    from xpra.platform import program_context
    with program_context("Features-Info", "Features Info"):
        d = {}
        for k in sorted(_features_list_):
            d[k] = globals()[k]
        print_dict(d)


if __name__ == "__main__":
    main()
