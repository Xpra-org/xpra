#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs.test_csc import test_csc


def test_csc_swscale():
    print("test_csc_swscale()")
    from xpra.codecs.csc_swscale.colorspace_converter import ColorspaceConverter    #@UnresolvedImport
    test_csc(ColorspaceConverter)


def main():
    import logging
    import sys
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    test_csc_swscale()


if __name__ == "__main__":
    main()
