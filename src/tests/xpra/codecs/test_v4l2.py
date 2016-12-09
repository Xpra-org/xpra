#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def test_push():
    import time
    from PIL import Image, ImageDraw
    from xpra.codecs.v4l2.pusher import Pusher  #@UnresolvedImport
    p = Pusher()
    W = 640
    H = 480
    W = 480
    H = 640
    p.init_context(W, H, W, "YUV420P", "/dev/video1")
    print("actual dimensions: %s - requested=%s" % ((p.get_width(), p.get_height()), (W, H)))
    from xpra.codecs.csc_swscale.colorspace_converter import ColorspaceConverter #@UnresolvedImport
    csc = ColorspaceConverter()
    csc.init_context(W, H, "BGRX", W, H, "YUV420P")
    print("csc=%s" % csc)
    from xpra.codecs.image_wrapper import ImageWrapper
    def h(v):
        return ("0"+("%#x" % v)[2:])[-2:].upper()
    i = 0
    while True:
        for r, g, b in (
                        (0,   255,   0),
                        (0,     0, 255),
                        (255, 255, 255),
                        (255,   0,   0),
                        (128, 128, 128),
                        ):
            name = "%s%s%s" % (h(r), h(g), h(b))
            print("testing with RGB: %s" % name)
            rgbx = (chr(r)+chr(g)+chr(b)+chr(255)) * (W*H)
            image = Image.frombytes("RGBA", (W, H), rgbx, "raw", "RGBA", W*4, 1)
            draw = ImageDraw.Draw(image)
            if i%3==0:
                draw.polygon([(W//2, H//4), (W//4, H*3//4), (W*3//4, H*3//4)], (0, 0, 0, 255))
            elif i%3==1:
                draw.rectangle([W//8, H//8, W*7//8, H*7//8], fill=(b, g, r,255), outline=(128,255,128,128))
                draw.rectangle([W//4, H//4, W*3//4, H*3//4], fill=(g, r, b,255), outline=(255,128,128,128))
                draw.rectangle([W*3//8, H*3//8, W*5//8, H*5//8], fill=(r, g, b,255), outline=(128,128,255,128))
            else:
                c = [255, 0, 0]*2
                for j in range(3):
                    ci = (i+j) % 3
                    fc = tuple(c[(ci):(ci+3)]+[255])
                    draw.rectangle([W*j//3, 0, W*(j+1)//3, H], fill=fc, outline=(128,255,128,128))
            image.save("./%s.png" % name, "png")
            bgrx = image.tobytes('raw', "BGRA")
            import binascii
            #print("%s=%s" % (name, binascii.hexlify(bgrx)))
            with open("./latest.hex", "wb") as f:
                f.write(binascii.hexlify(bgrx))
            bgrx_image = ImageWrapper(0, 0, W, H, bgrx, "BGRX", 32, W*4, planes=ImageWrapper.PACKED)
            image = csc.convert_image(bgrx_image)
            for _ in range(100):
                #print(".")
                p.push_image(image)
                time.sleep(0.05)
            i += 1

def main():
    test_push()


if __name__ == "__main__":
    main()
