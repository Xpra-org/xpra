#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.shadow_server import take_root_screenshot

def test_screenshot():
    print("grabbing screenshot")
    w, h, encoding, rowstride, data = take_root_screenshot()
    print("screenshot %sx%s %s encoding, rowstride=%s" % (w, h, encoding, rowstride))
    print("got %s bytes" % len(data))
    filename = "screenshot.png"
    f = open(filename, "wb")
    f.write(data)
    f.close()
    print("saved to %s" % filename)

def main():
    test_screenshot()


if __name__ == "__main__":
    main()
