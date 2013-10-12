#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from xpra.codecs.image_wrapper import ImageWrapper
#from tests.xpra.test_util import dump_resource_usage, dump_threads
from tests.xpra.codecs.test_codec import dump_pixels, make_rgb_input, make_planar_input


DEBUG = False
PERF_LOOP = 8       #number of megapixels to test on for measuring performance
MAX_ITER = 32       #also limit total number of iterations (as each iteration takes time to setup)
SIZES = ((16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1920, 1080), (2560, 1600))
#SIZES = ((512, 512), (1920, 1080), (2560, 1600))
TEST_SIZES = SIZES + ((51, 7), (511, 3), (5, 768), (111, 555))

#Some helper methods:
def check_plane(info, data, expected, tolerance=3, pixel_stride=4, ignore_byte=-1):
    if expected is None:
        #nothing to check
        return
    assert data is not None
    print("check_plane(%s, %s:%s, %s:%s" % (info, type(data), len(data), type(expected), len(expected)))
    #chop data to same size as expected sample:
    if type(data) in (buffer, str):
        data = bytearray(data)
    if type(expected) in (buffer, str):
        expected = bytearray(expected)
    actual_data = data[:len(expected)]
    if actual_data==expected:
        return  True
    assert type(actual_data)==type(expected), "expected result as %s but got %s" % (type(expected), type(actual_data))
    assert len(actual_data)==len(expected), "expected at least %s items but got %s" % (len(expected), len(actual_data))
    #now compare values, with some tolerance for rounding (off by one):
    errs = {}
    tested = 0
    for i in range(len(expected)):
        if ignore_byte>=0:
            if (i%pixel_stride)==ignore_byte:
                continue
        va = actual_data[i]
        ve = expected[i]
        tested += 1
        if abs(va-ve)>tolerance:
            errs[i] = va, ve
    ratio = 100.0*len(errs)/tested
    if len(errs)>0:
        if ratio>1:
            print("")
            print("ERROR!")
        print("output differs for %s" % info)
        print("check_plane(%s, .., ..) expected=%s" % (info, dump_pixels(expected)))
        print("check_plane(%s, .., ..)   actual=%s" % (info, dump_pixels(data)))
        print("errors at %s locations: %s (%.1f%%)" % (len(errs), errs.items()[:10], ratio))
    return ratio<=2.1


#RGB:
def test_csc_rgb(csc_module):
    print("")
    for w,h in TEST_SIZES:
        test_csc_rgb_all(csc_module, w, h)
    for w, h in SIZES:
        perf_measure_rgb(csc_module, w, h)


def perf_measure_rgb(csc_module, w=1920, h=1080):
    count = min(MAX_ITER, int(PERF_LOOP*1024*1024/(w*h)))
    rgb_src_formats = sorted([x for x in csc_module.get_input_colorspaces() if (x.find("RGB")>=0 or x.find("BGR")>=0)])
    if DEBUG:
        print("%s: rgb src_formats=%s" % (csc_module, rgb_src_formats))
    for src_format in rgb_src_formats:
        pixels = make_rgb_input(src_format, w, h, populate=True)
        yuv_dst_formats = sorted([x for x in csc_module.get_output_colorspaces(src_format) if (x.find("RGB")<0 and x.find("BGR")<0)])
        if DEBUG:
            print("%s: yuv_formats(%s)=%s" % (csc_module, src_format, yuv_dst_formats))
        for dst_format in yuv_dst_formats:
            start = time.time()
            do_test_csc_rgb(csc_module, src_format, dst_format, w, h, pixels, count=count)
            end = time.time()
            if DEBUG:
                print("%s did %sx%s csc %s times in %.1fms" % (csc_module, w, h, count, end-start))
            mpps = float(w*h*count)/(end-start)
            dim = ("%sx%s" % (w,h)).rjust(10)
            info = ("%s to %s at %s" % (src_format.ljust(7), dst_format.ljust(7), dim)).ljust(40)
            print("%s: %s MPixels/s" % (info, int(mpps/1024/1024)))

def test_csc_rgb_all(csc_module, w, h):
    #some output planes we can verify:
    CHECKS = {
                ("BGRX", "YUV444P", 16, 16) : (("Y", 0, "5155585b5f6266696d7073777a7e8185888c8f9296999d"),
                                               ("U", 1, "5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a"),
                                               ("V", 2, "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1")),
                ("BGRX", "YUV422P", 32, 32) : (("Y", 0, "51585f666d737a81888f969da4aab1b87e848b9299a0a6ad343a41484f565c637d848b9299a0a7ad343a41484f565c6351585f666d737a81888f969da4aab1"),
                                               ("U", 1, "5a5a5a5a5a5a5a5a80808080cbcbcbcb80808080cbcbcbcb5b5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a80808080cbcbcbcb80808080cbcbcbcb5b5a5a5a5a5a5a"),
                                               ("V", 2, "a1a1a1a1a1a1a1a1313030308e8e8e8e303030308e8e8e8ea1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1313030308e8e8e8e303030308e8e8e8ea1a1a1a1a1a1a1")),
                ("BGRX", "YUV440P", 32, 32) : (("Y", 0, "5155585b5f6266696d7073777a7e8185888c8f9296999d"),
                                               ("U", 1, "6d6d6d6d6d6d6d6d93939393939393936d6d6d6d6d6d6d"),
                                               ("V", 2, "6868686868686868979898989898989868686868686868")),
              }
    for use_strings in (True, False):
        rgb_in = sorted([x for x in csc_module.get_input_colorspaces() if not x.endswith("P")])
        for src_format in rgb_in:
            dst_formats = sorted([x for x in csc_module.get_output_colorspaces(src_format) if x.startswith("YUV")])
            populate = len([cs for (cs,cd,cw,ch) in CHECKS.keys() if (cs==src_format and cd in dst_formats and cw==w and ch==h)])>0
            pixels = make_rgb_input(src_format, w, h, use_strings, populate=populate)
            for dst_format in dst_formats:
                spec = csc_module.get_spec(src_format, dst_format)
                if w<spec.min_w or h<spec.min_h:
                    print("skipping test %s to %s at %sx%s because dimensions are too small" % (src_format, dst_format, w, h))
                    continue
                checks = CHECKS.get((src_format, dst_format, w, h))
                ok = do_test_csc_rgb(csc_module, src_format, dst_format, w, h, pixels, checks)
                print("test_csc_rgb_all(%s, %s, %s) %s to %s, use_strings=%s, ok=%s" % (csc_module.get_type(), w, h, src_format, dst_format, use_strings, ok))


def do_test_csc_rgb(csc_module, src_format, dst_format, w, h, pixels, checks=(), count=1):
    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc = ColorspaceConverterClass()
    #print("%s()=%s" % (ColorspaceConverterClass, cc))
    cc.init_context(w, h, src_format, w, h, dst_format)
    if DEBUG:
        print("ColorspaceConverter=%s" % cc)
        print("    %s" % cc.get_info())
        print("do_test_csc_rgb() input pixels=%s" % dump_pixels(pixels))
    bpp = len(src_format)
    image = ImageWrapper(0, 0, w, h, pixels, src_format, 32, w*bpp, planes=ImageWrapper.PACKED)
    for _ in range(count):
        out = cc.convert_image(image)
    if DEBUG:
        print("do_test_csc_rgb() output=%s" % out)
    pixels = out.get_pixels()
    if dst_format.endswith("P"):
        assert out.get_planes()==ImageWrapper._3_PLANES, "expected 3 planes as output but got: %s in %s" % (out.get_planes(), out)
        assert len(pixels)==3, "expected 3 planes but found: %s" % len(pixels)
        assert len(out.get_rowstride())==3, "expected 3 rowstrides but got: %s" % str(out.get_rowstride())
    #for i in range(3):
    #    print("do_test_csc_rgb() plane data[%s]=%s" % (i, dump_pixels(pixels[i])))
    ok = True
    if checks:
        for plane, index, expected in checks:
            ok &= check_plane(plane, pixels[index], expected)
    cc.clean()
    return ok


#PLANAR:
def test_csc_planar(csc_module):
    print("")
    for w, h in TEST_SIZES:
        test_csc_planar_all(csc_module, w, h)
    for w, h in SIZES:
        perf_measure_planar(csc_module, w, h)


def test_csc_planar_all(csc_module, w, h):
    #get_subsampling_divs()
    e420 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x88, 0x0, 0xff, 0x0, 0x81, 0x0, 0xff, 0x0, 0x82])
    e422 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x86, 0x0, 0xff, 0x0, 0x84, 0x0, 0xff, 0x0, 0x84])
    e444 = bytearray([0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87, 0x0, 0xff, 0x0, 0x87])
    CHECKS = {
                ("YUV420P", "XRGB", 32, 32) : ((e420,)),
                ("YUV422P", "XRGB", 32, 32) : ((e422,)),
                ("YUV444P", "XRGB", 32, 32) : ((e444,)),
              }
    for use_strings in (True, False):
        planar_in = [x for x in csc_module.get_input_colorspaces() if x.startswith("YUV")]
        for src_format in sorted(planar_in):
            dst_formats = sorted([x for x in csc_module.get_output_colorspaces(src_format) if (not x.startswith("YUV") and not x.endswith("P"))])
            populate = len([cs for (cs,cd,cw,ch) in CHECKS.keys() if (cs==src_format and cd in dst_formats and cw==w and ch==h)])>0
            #populate = len([x for x in FMT_TO_EXPECTED_OUTPUT.keys() if x[0]==src_format and x[1] in dst_formats])>0
            strides, pixels = make_planar_input(src_format, w, h, use_strings, populate=populate)
            for dst_format in dst_formats:
                spec = csc_module.get_spec(src_format, dst_format)
                if w<spec.min_w or h<spec.min_h:
                    print("skipping test %s to %s at %sx%s because dimensions are too small" % (src_format, dst_format, w, h))
                    continue
                out_pixels = do_test_csc_planar(csc_module, src_format, dst_format, w, h, strides, pixels)
                if DEBUG:
                    print("test_csc_planar_all() %s to %s head of output pixels=%s" % (src_format, dst_format, dump_pixels(out_pixels[:128])))
                expected = CHECKS.get((src_format, dst_format))
                ok = check_plane(dst_format, out_pixels, expected)
                print("test_csc_planar_all(%s, %s, %s) %s to %s, use_strings=%s, ok=%s" % (csc_module.get_type(), w, h, src_format, dst_format, use_strings, ok))

def perf_measure_planar(csc_module, w=1920, h=1080):
    count = min(MAX_ITER, int(PERF_LOOP*1024*1024/(w*h)))
    for src_format in sorted(csc_module.get_input_colorspaces()):
        if src_format not in ("YUV420P", "YUV422P", "YUV444P"):
            continue
        strides, pixels = make_planar_input(src_format, w, h, populate=True)
        rgb_dst_formats = sorted([x for x in csc_module.get_output_colorspaces(src_format) if (x.find("YUV")<0 and not x.endswith("P"))])
        for dst_format in rgb_dst_formats:
            #print("make_planar_input(%s, %s, %s) strides=%s, len(pixels=%s", src_format, w, h, strides, len(pixels))
            start = time.time()
            do_test_csc_planar(csc_module, src_format, dst_format, w, h, strides, pixels, count=count)
            end = time.time()
            if DEBUG:
                print("%s did %sx%s csc %s times in %.1fms" % (csc_module, w, h, count, end-start))
            mpps = float(w*h*count)/(end-start)
            dim = ("%sx%s" % (w,h)).rjust(10)
            info = ("%s to %s at %s" % (src_format.ljust(7), dst_format.ljust(7), dim)).ljust(40)
            print("%s: %s MPixels/s" % (info, int(mpps/1024/1024)))


def do_test_csc_planar(csc_module, src_format, dst_format, w, h, strides, pixels, checks=(), count=1):
    assert len(pixels)==3, "this test only handles 3-plane pixels but we have %s" % len(pixels)
    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc = ColorspaceConverterClass()
    #print("%s()=%s" % (ColorspaceConverterClass, cc))
    cc.init_context(w, h, src_format, w, h, dst_format)
    if DEBUG:
        print("ColorspaceConverter=%s" % cc)
        for i in range(3):
            print("test_csc() plane[%s]=%s" % (i, dump_pixels(pixels[i])))
    image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, strides, planes=ImageWrapper._3_PLANES)
    for _ in range(count):
        out = cc.convert_image(image)
    if DEBUG:
        print("do_test_csc_planar() output=%s" % out)
    assert out is not None, "convert_image returned None!"
    assert out.get_planes()==ImageWrapper.PACKED, "output image %s is not in packed format: it has %s planes" % (out, out.get_planes())
    outw = out.get_width()
    assert out.get_rowstride()>=outw*3, "output stride is too small: expected at least 3*%s=%s, but got %s" % (outw, 3*outw, out.get_rowstride())
    #clone the pixels before the wrapper falls out of scope!
    out.clone_pixel_data()
    cc.clean()
    return out.get_pixels()


def test_csc_roundtrip(csc_module):
    src_formats = sorted(csc_module.get_input_colorspaces())
    src_formats = [x for x in src_formats if (x.find("RGB")>=0 or x.find("BGR")>=0) and len(x)==4]
    for src_format in src_formats:
        dst_formats = csc_module.get_output_colorspaces(src_format)
        dst_formats = [x for x in dst_formats if x=="YUV444P"]
        if not dst_formats:
            continue
        for dst_format in dst_formats:
            #can we convert back to src?
            if not src_format in csc_module.get_output_colorspaces(dst_format):
                continue
            for w, h in SIZES:
                spec1 = csc_module.get_spec(src_format, dst_format)
                spec2 = csc_module.get_spec(dst_format, src_format)
                if w<spec1.min_w or h<spec1.min_h or w<spec2.min_w or h<spec2.min_h:
                    continue
                try:
                    do_test_csc_roundtrip(csc_module, src_format, dst_format, w, h)
                    #print("rountrip %s/%s @ %sx%s passed" % (src_format, dst_format, w, h))
                except Exception, e:
                    print("FAILED %s/%s @ %sx%s: %s" % (src_format, dst_format, w, h, e))
                    raise


def do_test_csc_roundtrip(csc_module, src_format, dst_format, w, h):
    assert src_format.find("RGB")>=0 or src_format.find("BGR")>=0
    pixels = make_rgb_input(src_format, w, h, populate=True)
    stride = w*4
    #print(" input pixels: %s (%sx%s, stride=%s, stride*h=%s)" % (len(pixels), w, h, stride, stride*h))
    assert len(pixels)>=stride*h, "not enough pixels! (expected at least %s but got %s)" % (stride*h, len(pixels))
    image = ImageWrapper(0, 0, w, h, pixels, src_format, 24, stride, planes=ImageWrapper.PACKED)

    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc1 = ColorspaceConverterClass()
    cc1.init_context(w, h, src_format, w, h, dst_format)

    temp = cc1.convert_image(image)

    ColorspaceConverterClass = getattr(csc_module, "ColorspaceConverter")
    cc2 = ColorspaceConverterClass()
    cc2.init_context(w, h, dst_format, w, h, src_format)

    regen = cc2.convert_image(temp)
    assert regen

    #compare with original:
    rpixels = regen.get_pixels()
    info = "%s to %s and back @ %sx%s" % (src_format, dst_format, w, h)
    if src_format.find("RGB")>=0 or src_format.find("BGR")>=0:
        ib = max(src_format.find("X"), src_format.find("A"))
        check_plane(info, rpixels, pixels, tolerance=5, ignore_byte=ib)
    #else:
    #    for i in range(3):
    #        check_plane(info, rpixels[i], pixels[i], tolerance=5)
    #image.free()
    temp.free()
    regen.free()
    cc1.clean()
    cc2.clean()


def test_all(colorspace_converter):
    test_csc_rgb(colorspace_converter)
    test_csc_planar(colorspace_converter)
    test_csc_roundtrip(colorspace_converter)
