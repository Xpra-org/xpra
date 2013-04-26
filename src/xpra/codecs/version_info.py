# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def add_codec_version_info(capabilities):
    try:
        from xpra.codecs.vpx import codec as vpx_codec
        capabilities["encoding.vpx.version"] = vpx_codec.get_version()
    except:
        pass
    try:
        from xpra.codecs.x264 import codec as x264_codec
        capabilities["encoding.x264.version"] = x264_codec.get_version()
    except:
        pass
