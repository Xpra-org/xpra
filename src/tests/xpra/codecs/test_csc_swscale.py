#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#from tests.xpra.codecs.test_csc import test_csc_planar, test_csc_rgb
from tests.xpra.codecs.test_csc import test_all


def test_csc_swscale():
    print("test_csc_swscale()")
    from xpra.codecs.csc_swscale import colorspace_converter #@UnresolvedImport
    #test_csc_rgb(colorspace_converter)
    #test_csc_planar(colorspace_converter)
    test_all(colorspace_converter)


def main():
    test_csc_swscale()


if __name__ == "__main__":
    main()
