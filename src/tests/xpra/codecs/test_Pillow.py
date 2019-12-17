#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def main():
    from xpra.codecs.pillow.encoder import selftest
    #from xpra.codecs.pillow.encode import log
    #log.enable_debug()
    selftest(True)


if __name__ == "__main__":
    main()
