# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def add_codec_version_info(capabilities):
    #for modules that do encoders and decoders in one
    try:
        from xpra.codecs.webm import __VERSION__
        capabilities["encoding.webp.version"] = __VERSION__
    except:
        pass
    try:
        from PIL import Image                   #@UnresolvedImport
        capabilities["encoding.PIL.version"] = Image.VERSION
    except:
        pass
    try:
        from xpra.codecs.csc_swscale.colorspace_converter import get_version    #@UnresolvedImport
        capabilities["encoding.swscale.version"] = get_version()
    except:
        pass


def add_encoder_version_info(capabilities):
    try:
        from xpra.codecs.vpx.encoder import get_version         #@UnresolvedImport
        capabilities["encoding.vpx.version"] = get_version()
    except:
        pass
    try:
        from xpra.codecs.enc_x264 import encoder as x264_encoder
        capabilities["encoding.x264.version"] = x264_encoder.get_version()
    except:
        pass
    add_codec_version_info(capabilities)


def add_decoder_version_info(capabilities):
    try:
        from xpra.codecs.dec_avcodec import decoder as avcodec_decoder
        capabilities["encoding.avcodec.version"] = avcodec_decoder.get_version()
    except:
        pass
    add_codec_version_info(capabilities)



def main():
    caps = {}
    add_encoder_version_info(caps)
    print("encoder_version_info=%s" % caps)
    caps = {}
    add_decoder_version_info(caps)
    print("decoder_version_info=%s" % caps)


if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
