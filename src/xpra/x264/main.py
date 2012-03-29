# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

w = 800
h = 600

f = None
try:
    f = open("x264test.rgb", mode='rb')
    data = f.read()
finally:
    if f:
        f.close()

def main():
    from xpra.x264.encoder import Encoder
    encoder = Encoder()
    print("encoder.init(%s,%s)" % (w, h))
    encoder.init(w, h)
    stride = w*3
    try:
        err, size, compressed = encoder.compress_image(data, stride)
        if err!=0:
            raise Exception("error %s during compression" % err)
        print("encoder.compress_image(%s bytes, %s)=%s,%s" % (len(data), stride, size, len(compressed)))
    finally:
        i = encoder.clean()
        print("encoder.clean()=%s" % i)

    from xpra.x264.decoder import Decoder
    decoder = Decoder()
    print("decoder.init(%s,%s)" % (w, h))
    decoder.init(w, h)
    try:
        err, outstride, decompressed = decoder.decompress_image(compressed)
        print("decoder.decompress_image(%s bytes)=%s" % (len(compressed), (err, outstride, len(decompressed))))
        decoder.free_image()
        assert len(decompressed)==len(data)
        if err!=0:
            raise Exception("error %s during decompression" % err)
    finally:
        i = decoder.clean()
        print("decoder.clean()=%s" % i)

if __name__ == "__main__":
    main()
