#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.shadow_server_base import take_root_screenshot

def test_screenshot():
    print("grabbing screenshot")
    w, h, encoding, rowstride, data = take_root_screenshot()
    print("screenshot %sx%s %s encoding, rowstride=%s" % (w, h, encoding, rowstride))
    print("got %s bytes" % len(data))
    filename = "screenshot.png"
    with open(filename, "wb") as f:
        f.write(data)
    print("saved to %s" % filename)

def main():
    test_screenshot()


if __name__ == "__main__":
    main()
