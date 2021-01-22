#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def test_screenshot():
    from xpra.platform.gui import take_screenshot
    print("grabbing screenshot")
    w, h, encoding, rowstride, data = take_screenshot()
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
