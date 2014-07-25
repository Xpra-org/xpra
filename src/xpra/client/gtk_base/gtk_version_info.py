#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util import nonl, pver
from xpra.gtk_common.gtk_util import GTK_VERSION_INFO

def main():
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s : %s" % (str(k).replace(".version", "").ljust(12), nonl(pver(v))))
    from xpra.platform import init, clean
    try:
        init("GTK-Version-Info", "GTK Version Info")
        print_dict(GTK_VERSION_INFO)
    finally:
        clean()


if __name__ == "__main__":
    main()
