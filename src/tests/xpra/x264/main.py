# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

w = 800
h = 600

import xpra
import os.path
f = None
data = None
try:
    for filename in [os.path.join(os.path.dirname(xpra.__file__), "xpra", "x264", "x264test.rgb"),
                     os.path.join(os.getcwd(), "xpra", "x264", "x264test.rgb"),
                     os.path.join(os.getcwd(), "x264test.rgb")]:
        if os.path.exists(filename):
            f = open(filename, mode='rb')
            data = f.read()
            break
        else:
            print("%s not found" % filename)
finally:
    if f:
        f.close()
assert data, "x264test.rgb not found!"

def main():
    from xpra.x264.codec import Encoder     #@UnresolvedImport
    encoder = Encoder()
    print("encoder.init_context(%s,%s,{})" % (w, h))
    encoder.init_context(w, h, {})
    stride = w*3
    try:
        err, size, compressed = encoder.compress_image(data, stride)
        if err!=0:
            raise Exception("error %s during compression" % err)
        print("encoder.compress_image(%s bytes, %s)=%s,%s" % (len(data), stride, size, len(compressed)))
    finally:
        i = encoder.clean()
        print("encoder.clean()=%s" % i)

    from xpra.x264.codec import Decoder     #@UnresolvedImport
    decoder = Decoder()
    print("decoder.init_context(%s,%s,{})" % (w, h))
    decoder.init_context(w, h, {})
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
