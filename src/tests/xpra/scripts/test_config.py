#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main():
    if len(sys.argv)!=2:
        print("usage: %s filename" % sys.argv[0])
        return 1
    filename = sys.argv[1]
    from xpra.scripts import config
    def debug(*args):
        print(args[0] % tuple(list(args)[1:]))
    config.debug = debug
    d = config.read_config(filename)
    print("read_config(%s)=%s" % (filename, d))

if __name__ == "__main__":
    sys.exit(main())
