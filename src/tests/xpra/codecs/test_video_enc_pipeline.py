#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.video_helper import getVideoHelper



def test_load():
    #NOTE: we assume that the scores:
    # - make nvenc less desirable at HQ (maybe not?)
    # - make cuda csc beat swscale
    vep = getVideoHelper()
    vep.may_init()


def main():
    import logging
    logging.root.setLevel(logging.DEBUG)
    test_load()


if __name__ == "__main__":
    main()
