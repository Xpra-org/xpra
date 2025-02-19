#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
import binascii
from contextlib import nullcontext

from xpra.util.objects import typedict
from xpra.util.str_fn import hexstr
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import get_subsampling_divs, get_plane_name
from xpra.codecs.checks import make_test_image
from xpra.codecs.video import getVideoHelper
from xpra.log import Logger, consume_verbose_argv

MAX_DELTA = 7

log = Logger("video")


def h2b(s) -> bytes:
    return binascii.unhexlify(s)


def cmpp(p1, p2, tolerance=MAX_DELTA) -> tuple[int, int, int] | None:
    # compare planes, tolerate a rounding difference
    l = min(len(p1), len(p2))
    for i in range(l):
        v1 = p1[i]
        v2 = p2[i]
        if abs(v2 - v1) > tolerance:
            return i, v1, v2
    return None


def maxdelta(p1, p2) -> int:
    # compare planes
    l = min(len(p1), len(p2))
    d = 0
    for i in range(l):
        v1 = p1[i]
        v2 = p2[i]
        d = max(d, abs(v2 - v1))
    return d


def zeroout(data, i: int, bpp: int):
    if i < 0:
        return data
    d = bytearray(data)
    p = 0
    while p < len(d):
        d[p + i] = 0
        p += bpp
    return d


TEST_IMAGES = {
    #    "codecs-image" : "/projects/xpra/docs/Build/graphs/codecs.png",
}

# samples as generated using the csc_colorspace_test:
# (studio-swing)
SAMPLE_YUV420P_IMAGES = {
    # colour name : (Y, U, V),
    "black": (0x00, 0x80, 0x80),
    "white": (0xFF, 0x80, 0x80),
    "blue": (0x29, 0xEF, 0x6E),
}
SAMPLE_NV12_IMAGES = {
    # colour name : (Y, UV),
    "black": (0x00, 0x80),
    "white": (0xFF, 0x80),
}
SAMPLE_RGBX_IMAGES = {
    "black": (0, 0, 0, 0xFF),
    "white": (0xFF, 0xFF, 0xFF, 0xFF),
    "blue": (0, 0, 0xFF, 0xFF),
    "grey": (0x80, 0x80, 0x80, 0xFF),
}
SAMPLE_BGRX_IMAGES = {
    "black": (0, 0, 0, 0xFF),
    "white": (0xFF, 0xFF, 0xFF, 0xFF),
    "blue": (0xFF, 0, 0, 0xFF),
    "grey": (0x80, 0x80, 0x80, 0xFF),
}
SAMPLE_XRGB_IMAGES = {
    "black": (0xFF, 0, 0, 0),
    "white": (0xFF, 0xFF, 0xFF, 0xFF),
    "blue": (0xFF, 0, 0, 0xFF),
    "grey": (0xFF, 0x80, 0x80, 0x80),
}
SAMPLE_IMAGES = {
    "YUV420P": SAMPLE_YUV420P_IMAGES,
    "YUV422P": SAMPLE_YUV420P_IMAGES,
    "YUV444P": SAMPLE_YUV420P_IMAGES,
    "NV12": SAMPLE_NV12_IMAGES,
    "RGB": SAMPLE_RGBX_IMAGES,
    "RGBX": SAMPLE_RGBX_IMAGES,
    "BGRA": SAMPLE_BGRX_IMAGES,
    "BGRX": SAMPLE_BGRX_IMAGES,
    "XRGB": SAMPLE_XRGB_IMAGES,
}

TEST_SIZES = (
    (128, 128),
    (512, 512),
    #(255, 257),
)


class Test_Roundtrip(unittest.TestCase):

    def test_all(self):
        vh = getVideoHelper()
        vh.enable_all_modules()
        vh.init()
        # info = vh.get_info()
        encodings = vh.get_encodings()
        decodings = vh.get_decodings()
        common = [x for x in encodings if x in decodings]
        options = {"max-delayed": 0}
        ctx = nullcontext()
        try:
            from xpra.codecs.nvidia.cuda.context import get_default_device_context
            ctx = get_default_device_context()
            options["cuda-device-context"] = ctx
        except (ImportError, RuntimeError):
            pass
        with ctx:
            for encoding in common:
                encs = vh.get_encoder_specs(encoding)
                decs = vh.get_decoder_specs(encoding)
                for in_csc, enc_specs in encs.items():
                    for enc_spec in enc_specs:
                        if enc_spec.codec_type.startswith("nv"):
                            #cuda context is not available?
                            continue
                        #find decoders for the output colorspaces the encoder will generate:
                        for out_csc in enc_spec.output_colorspaces:
                            for decoder_spec in decs.get(out_csc, ()):
                                #apply mask to sizes:
                                sizes = []
                                for width, height in TEST_SIZES:
                                    width = (width & enc_spec.width_mask)
                                    height = (height & enc_spec.height_mask)
                                    sizes.append((width, height))
                                self._test(encoding,
                                           enc_spec.codec_class,
                                           decoder_spec.codec_class,
                                           options,
                                           in_csc,
                                           out_csc,
                                           sizes)

    def _test(self, encoding, encoder_class, decoder_class, options, in_csc="YUV420P", out_csc="YUV420P",
              sizes=TEST_SIZES):
        sample_images = SAMPLE_IMAGES.get(in_csc)
        log(f"SAMPLE_IMAGES[{in_csc}]={sample_images}")
        if not sample_images:
            print(f"skipping {in_csc}: no test image available")
            return
        for width, height in sizes:
            for colour, pixeldata in sample_images.items():
                try:
                    self._test_data(encoding, encoder_class, decoder_class,
                                    options, in_csc, out_csc, colour,
                                    pixeldata, width, height)
                except Exception:
                    print(f"error with {colour} {encoding} image via {encoder_class} and {decoder_class}")
                    raise

    def _test_data(self, encoding, encoder_class, decoder_class,
                   options, in_csc="YUV420P", out_csc="YUV420P", colour="?",
                   pixeldata=None, width=128, height=128):
        log("test%s" % ((encoding, encoder_class, decoder_class, options, in_csc, out_csc, colour,
                         len(pixeldata), width, height),))
        encoder = encoder_class()
        options = typedict(options or {})
        options["quality"] = 100
        options["speed"] = 0
        options["dst-formats"] = (out_csc,)
        encoder.init_context(encoding, width, height, in_csc, options)
        in_image = make_test_image(in_csc, width, height, pixeldata)
        saved_pixels = in_image.get_pixels()
        in_image.clone_pixel_data()
        in_pixels = in_image.get_pixels()
        out = encoder.compress_image(in_image, options)
        if not out:
            raise RuntimeError(f"{encoder} failed to compress {in_image} with options {options}")
        cdata, client_options = out
        assert cdata
        # decode it:
        decoder = decoder_class()
        decoder.init_context(encoding, width, height, out_csc, options)
        out_image = decoder.decompress_image(cdata, typedict(client_options))
        if not out_image:
            raise ValueError("no image")
        if decoder.get_type() == "nvdec":
            # uses GPU pycuda DeviceAllocation buffers,
            # which we can't compare directly
            return
        out_pixels = out_image.get_pixels()

        out_csc = out_image.get_pixel_format()
        md = 0
        if in_csc.startswith("YUV") or in_csc == "NV12":
            nplanes = out_image.get_planes()
            if in_csc != out_csc:
                if out_csc == "NV12" or in_csc == "NV12":
                    log(f"only comparing Y plane for {in_csc} -> {out_csc} (not fully implemented)")
                    nplanes = 1
                else:
                    raise ValueError(f"YUV output colorspace {out_csc} differs from input colorspace {in_csc}")
            divs = get_subsampling_divs(in_csc)
            log(f"comparing {in_csc} and {out_csc}: {nplanes=}, {divs=} {out_image=} from {decoder=}")
            for i in range(nplanes):
                plane = get_plane_name(out_csc, i)
                # extract plane to compare:
                saved_pdata = saved_pixels[i]
                in_pdata = in_pixels[i]
                out_pdata = out_pixels[i]
                xdiv, ydiv = divs[i]
                in_stride = in_image.get_rowstride()[i]
                out_stride = out_image.get_rowstride()[i]
                # compare lines at a time since the rowstride may be different:
                for y in range(height // ydiv):
                    p1 = in_stride * y
                    p2 = p1 + width // xdiv
                    saved_rowdata = saved_pdata[p1:p2]
                    in_rowdata = in_pdata[p1:p2]
                    p1 = out_stride * y
                    p2 = p1 + width // xdiv
                    out_rowdata = out_pdata[p1:p2]
                    err = cmpp(saved_rowdata, in_rowdata)
                    if err:
                        index, v1, v2 = err
                        log.warn("the encoder unexpectedly modified the input buffer!")
                        log.warn(f"expected {hexstr(in_rowdata)}")
                        log.warn(f"but got  {hexstr(out_rowdata)}")
                        msg = " ".join((
                            f"expected {hex(v1)} but got {hex(v2)}",
                            f"for x={index}/{width}, y={y}/{height}, plane {plane} of {in_csc}",
                            f"with {encoding} encoded using {encoder_class}",
                        ))
                        raise Exception(msg)
                    err = cmpp(in_rowdata, out_rowdata)
                    if err:
                        index, v1, v2 = err
                        log.warn(f"encoder={encoder}")
                        log.warn(f"expected {hexstr(in_rowdata)}")
                        log.warn(f"but got  {hexstr(out_rowdata)}")
                        msg = " ".join((
                            f"expected {hex(v1)} but got {hex(v2)}",
                            f"for x={index}/{width}, y={y}/{height}, plane {plane} of {in_csc}",
                            f"with {encoding} encoded using {encoder_class} and decoded using {decoder_class}",
                        ))
                        raise Exception(msg)
                    md = max(md, maxdelta(in_rowdata, out_rowdata))
        elif in_image.get_planes() == ImageWrapper.PACKED:
            # verify the encoder hasn't modified anything:
            err = cmpp(saved_pixels, in_pixels)
            if err:
                index, v1, v2 = err
                log.warn("the encoder unexpectedly modified the input buffer!")
                msg = " ".join((
                    f"expected {hex(v1)} but got {hex(v2)}",
                    f"for {width}x{height} of {in_csc}",
                    f"with {encoding} encoded using {encoder_class}",
                ))
                raise Exception(msg)
            if in_csc == out_csc:
                compare = {"direct": out_image}
            else:
                log(f"RGB output colorspace {out_csc} differs from input colorspace {in_csc}")
                #find csc modules to convert to the input format:
                vh = getVideoHelper()
                csc_specs = vh.get_csc_specs(out_csc).get(in_csc)
                if not csc_specs:
                    log.warn(f"Warning: unable to convert {out_csc} output back to {in_csc} to compare")
                    return
                compare = {}
                for i, csc_spec in enumerate(csc_specs):
                    csc = csc_spec.codec_class()
                    csc.init_context(width, height, out_csc,
                                     width, height, in_csc, options)
                    rgb_image = csc.convert_image(out_image)
                    compare[f"{i} : {csc_spec.codec_type}"] = rgb_image
                    assert rgb_image
            # compare each output image with the input:
            for out_source, out_image in compare.items():
                out_csc = out_image.get_pixel_format()
                log(f"comparing {in_csc} with {out_csc} ({out_source})")
                out_pixels = out_image.get_pixels()
                in_stride = in_image.get_rowstride()
                out_stride = out_image.get_rowstride()
                in_width = width * len(in_csc)
                out_width = width * len(out_csc)
                assert in_width == out_width
                xi = in_csc.find("X")
                xo = out_csc.find("X")
                Bppi = len(in_csc)
                Bppo = len(out_csc)
                for y in range(height):
                    in_rowdata = zeroout(in_pixels[in_stride * y:in_stride * y + in_width], xi, Bppi)
                    out_rowdata = zeroout(out_pixels[out_stride * y:out_stride * y + out_width], xo, Bppo)
                    err = cmpp(in_rowdata, out_rowdata)
                    if err:
                        index, v1, v2 = err
                        pixel = in_csc[index % len(in_csc)]
                        log.warn(f"expected {hexstr(in_rowdata)}")
                        log.warn(f"but got  {hexstr(out_rowdata)}")
                        msg = " ".join((
                            f"expected {hex(v1)} but got {hex(v2)}",
                            f"for {pixel!r} x={index}/{width}, y={y}/{height} of {in_csc}",
                            f"with {encoding} encoded using {encoder_class} and decoded using {decoder_class}",
                        ))
                        raise Exception(msg)
                    md = max(md, maxdelta(in_rowdata, out_rowdata))
        else:
            raise ValueError(f"don't know how to compare {in_image}")
        log(f" max delta={md}")


def main():
    consume_verbose_argv(sys.argv, "video")
    unittest.main()


if __name__ == '__main__':
    main()
