#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import math
import unittest
import binascii
from contextlib import nullcontext

try:
    import numpy
except ImportError:
    numpy = None

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


def plane_energy(p1, p2, Bpp: int = 1) -> tuple[int, int]:
    # sum of squared signal and squared error (noise),
    # comparing samples of `Bpp` bytes each (16-bit samples are little-endian):
    n = min(len(p1), len(p2)) // Bpp
    dtype = numpy.uint8 if Bpp == 1 else numpy.uint16
    a1 = numpy.frombuffer(bytes(p1[:n * Bpp]), dtype=dtype).astype(numpy.int64)
    a2 = numpy.frombuffer(bytes(p2[:n * Bpp]), dtype=dtype).astype(numpy.int64)
    signal = int((a1 * a1).sum())
    noise = int(((a2 - a1) ** 2).sum())
    return signal, noise


def snr_db(signal: int, noise: int) -> float:
    # signal-to-noise ratio in decibels:
    if noise <= 0:
        return float("inf")
    return 10 * math.log10(signal / noise)


def _texture_plane(stride: int, rows: int, Bpp: int, depth: int) -> bytes:
    # a deterministic XOR texture (multi-frequency: edges and gradients),
    # masked to the bit depth, so lossy compression has real detail to lose:
    samples = stride // Bpp
    mask = (1 << depth) - 1
    xx = numpy.arange(samples, dtype=numpy.int64).reshape(1, samples)
    yy = numpy.arange(rows, dtype=numpy.int64).reshape(rows, 1)
    dtype = numpy.uint8 if Bpp == 1 else numpy.uint16
    return ((xx ^ yy) & mask).astype(dtype).tobytes()


def make_textured_image(pixel_format: str, w: int, h: int):
    # reuse make_test_image for the correct plane geometry,
    # then replace the (flat) plane buffers with a textured pattern:
    image = make_test_image(pixel_format, w, h, ())
    strides = image.get_rowstride()
    if image.get_planes() == ImageWrapper.PACKED:
        image.set_pixels(_texture_plane(strides, h, 1, 8))
        return image
    try:
        depth = int(pixel_format.split("P")[1])     # ie: YUV420P10 -> 10
    except (IndexError, ValueError):
        depth = 8
    Bpp = (depth + 7) // 8
    pixels = list(image.get_pixels())
    for i, plane in enumerate(pixels):
        rows = len(plane) // strides[i]
        pixels[i] = _texture_plane(strides[i], rows, Bpp, depth)
    image.set_pixels(tuple(pixels))
    return image


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
# 10-bit samples (0..0x3FF), stored as 16-bit little-endian by make_test_image.
# These are the 8-bit studio-swing values scaled up by 4 (<<2):
SAMPLE_YUV420P10_IMAGES = {
    # colour name : (Y, U, V),
    "black": (0x000, 0x200, 0x200),
    "white": (0x3FC, 0x200, 0x200),
    "blue": (0x0A4, 0x3BC, 0x1B8),
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
    "YUV420P10": SAMPLE_YUV420P10_IMAGES,
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
    # odd dimensions: only tested for codecs that accept them as-is;
    # codecs requiring even dimensions skip this size (see the masking below):
    (255, 257),
)


class Test_Roundtrip(unittest.TestCase):

    def test_all(self):
        # high quality: verify the roundtrip is within MAX_DELTA
        self._run_all(quality=100, verify=True)

    def test_lossy_snr(self):
        # at low quality the roundtrip is lossy and would exceed MAX_DELTA,
        # so instead of verifying we present the signal-to-noise ratio:
        if numpy is None:
            self.skipTest("numpy is required to compute the signal-to-noise ratio")
        for quality in (10, 50):
            results = self._run_all(quality=quality, verify=False)
            self.assertTrue(results, f"no codecs exercised at quality={quality}%")
            print(f"\nsignal-to-noise ratio at quality={quality}%:")
            for key in sorted(results):
                encoding, codec_type, csc, size = key
                signal, noise = results[key]
                label = f"{encoding} {codec_type} {csc} {size}"
                value = "lossless" if noise <= 0 else f"{snr_db(signal, noise):5.1f} dB"
                print(f"  {label:54} : {value}")

    def _run_all(self, quality: int = 100, verify: bool = True) -> dict:
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
        results: dict = {}
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
                                #only test a size that the codec accepts as-is:
                                #a codec may require even dimensions (mask 0xFFFE),
                                #in which case the odd test size (255x257) is skipped
                                #rather than silently masked to a different even size:
                                width_mask = enc_spec.width_mask & decoder_spec.width_mask
                                height_mask = enc_spec.height_mask & decoder_spec.height_mask
                                sizes = [(width, height) for width, height in TEST_SIZES
                                         if width == (width & width_mask) and height == (height & height_mask)]
                                self._test(encoding,
                                           enc_spec.codec_class,
                                           decoder_spec.codec_class,
                                           options,
                                           in_csc,
                                           out_csc,
                                           sizes,
                                           quality=quality,
                                           verify=verify,
                                           codec_type=enc_spec.codec_type,
                                           results=results)
        return results

    def _test(self, encoding, encoder_class, decoder_class, options, in_csc="YUV420P", out_csc="YUV420P",
              sizes=TEST_SIZES, quality=100, verify=True, codec_type="", results=None):
        sample_images = SAMPLE_IMAGES.get(in_csc)
        log(f"SAMPLE_IMAGES[{in_csc}]={sample_images}")
        if not sample_images:
            print(f"skipping {in_csc}: no test image available")
            return
        # high quality verifies each flat colour sample;
        # the lossy SNR path uses a single textured image instead:
        colours = list(sample_images.items()) if verify else [("textured", None)]
        for width, height in sizes:
            signal = noise = 0
            for colour, pixeldata in colours:
                try:
                    s, n = self._test_data(encoding, encoder_class, decoder_class,
                                           options, in_csc, out_csc, colour,
                                           pixeldata, width, height,
                                           quality=quality, verify=verify)
                except Exception:
                    print(f"error with {colour} {encoding} image via {encoder_class} and {decoder_class}")
                    raise
                signal += s
                noise += n
            if results is not None:
                #accumulate the signal-to-noise energy over all the test colours:
                key = (encoding, codec_type, f"{in_csc}->{out_csc}", f"{width}x{height}")
                rsignal, rnoise = results.get(key, (0, 0))
                results[key] = (rsignal + signal, rnoise + noise)

    def test_rgb_roundtrip_snr(self):
        # exercise the full pipeline, including colorspace conversion on both ends:
        #   RGB -> (csc) -> YUV -> encode -> decode -> YUV -> (csc) -> RGB
        # the chain is lossy (chroma subsampling + lossy codec), so instead of
        # verifying exact values we report the signal-to-noise ratio:
        if numpy is None:
            self.skipTest("numpy is required to compute the signal-to-noise ratio")
        for quality in (100, 50):
            results = self._run_rgb(quality=quality)
            self.assertTrue(results, f"no RGB roundtrips exercised at quality={quality}%")
            print(f"\nRGB -> YUV -> encode -> decode -> YUV -> RGB "
                  f"signal-to-noise ratio at quality={quality}%:")
            for key in sorted(results):
                encoding, enc_type, dec_type, csc, size = key
                snr = results[key]
                label = f"{encoding} {enc_type}/{dec_type} {csc} {size}"
                value = "lossless" if snr == float("inf") else f"{snr:5.1f} dB"
                print(f"  {label:62} : {value}")

    def _run_rgb(self, quality: int = 100, rgb_format: str = "BGRX") -> dict:
        vh = getVideoHelper()
        vh.enable_all_modules()
        vh.init()
        encodings = vh.get_encodings()
        decodings = vh.get_decodings()
        common = [x for x in encodings if x in decodings]
        base_options = {"max-delayed": 0}
        ctx = nullcontext()
        try:
            from xpra.codecs.nvidia.cuda.context import get_default_device_context
            ctx = get_default_device_context()
            base_options["cuda-device-context"] = ctx
        except (ImportError, RuntimeError):
            pass

        def first_cpu_spec(specs):
            # skip GPU csc modules: they need a cuda context and GPU buffers,
            # which don't apply to the CPU images used here:
            for spec in specs or ():
                if not spec.codec_type.startswith("nv"):
                    return spec
            return None

        results: dict = {}
        with ctx:
            for encoding in common:
                encs = vh.get_encoder_specs(encoding)
                decs = vh.get_decoder_specs(encoding)
                for in_csc, enc_specs in encs.items():
                    # this pipeline starts from RGB, so we only want encoders
                    # whose input is a YUV colorspace we can convert RGB into:
                    if not (in_csc.startswith("YUV") or in_csc == "NV12"):
                        continue
                    fcsc = first_cpu_spec(vh.get_csc_specs(rgb_format).get(in_csc))
                    if not fcsc:
                        continue
                    for enc_spec in enc_specs:
                        if enc_spec.codec_type.startswith("nv"):
                            continue
                        for out_csc in enc_spec.output_colorspaces:
                            bcsc = first_cpu_spec(vh.get_csc_specs(out_csc).get(rgb_format))
                            if not bcsc:
                                continue
                            for decoder_spec in decs.get(out_csc, ()):
                                if decoder_spec.codec_type.startswith("nv"):
                                    continue
                                # only test a size that every stage accepts as-is
                                # (a stage may require even dimensions: mask 0xFFFE):
                                width_mask = enc_spec.width_mask & decoder_spec.width_mask & fcsc.width_mask & bcsc.width_mask
                                height_mask = enc_spec.height_mask & decoder_spec.height_mask & fcsc.height_mask & bcsc.height_mask
                                for width, height in TEST_SIZES:
                                    if width != (width & width_mask) or height != (height & height_mask):
                                        continue
                                    signal, noise = self._test_rgb_data(
                                        encoding, enc_spec.codec_class, decoder_spec.codec_class,
                                        fcsc, bcsc, base_options, rgb_format,
                                        in_csc, out_csc, width, height,
                                        quality=quality, full_range=enc_spec.full_range)
                                    key = (encoding, enc_spec.codec_type, decoder_spec.codec_type,
                                           f"{rgb_format}->{in_csc}->{out_csc}", f"{width}x{height}")
                                    results[key] = snr_db(signal, noise)
        return results

    def _csc_image(self, csc_spec, image, src_format, dst_format, width, height, options):
        csc = csc_spec.codec_class()
        csc.init_context(width, height, src_format, width, height, dst_format, options)
        out_image = csc.convert_image(image)
        csc.clean()
        if not out_image:
            raise RuntimeError(f"{csc_spec} failed to convert {src_format} to {dst_format}")
        return out_image

    def _test_rgb_data(self, encoding, encoder_class, decoder_class,
                       fcsc, bcsc, base_options, rgb_format,
                       in_csc, out_csc, width, height, quality=100, full_range=True):
        log("test_rgb%s" % ((encoding, encoder_class, decoder_class, rgb_format,
                             in_csc, out_csc, width, height, quality),))
        enc_options = typedict(base_options or {})
        enc_options["quality"] = quality
        enc_options["speed"] = 0
        enc_options["dst-formats"] = (out_csc,)
        # both colorspace conversions must agree on the range so they cancel out:
        csc_options = typedict({"full-range": full_range})
        # 1. textured RGB source image (a flat colour would roundtrip near-losslessly):
        src_image = make_textured_image(rgb_format, width, height)
        src_stride = src_image.get_rowstride()
        src_pixels = bytes(src_image.get_pixels())
        # 2. RGB -> YUV (csc step before the encoder):
        yuv_image = self._csc_image(fcsc, src_image, rgb_format, in_csc, width, height, csc_options)
        # 3. encode the YUV image:
        encoder = encoder_class()
        encoder.init_context(encoding, width, height, in_csc, enc_options)
        out = encoder.compress_image(yuv_image, enc_options)
        if not out:
            raise RuntimeError(f"{encoder} failed to compress {yuv_image} with options {enc_options}")
        cdata, client_options = out
        assert cdata
        # 4. decode back to YUV:
        decoder = decoder_class()
        decoder.init_context(encoding, width, height, out_csc, enc_options)
        yuv_out = decoder.decompress_image(cdata, typedict(client_options))
        if not yuv_out:
            raise ValueError("no image from decoder")
        # 5. YUV -> RGB (csc step on the way out):
        rgb_out = self._csc_image(bcsc, yuv_out, out_csc, rgb_format, width, height, csc_options)
        # 6. compare the RGB images, ignoring the unused 'X' channel:
        out_pixels = rgb_out.get_pixels()
        out_stride = rgb_out.get_rowstride()
        xi = rgb_format.find("X")
        Bpp = len(rgb_format)
        row_bytes = width * Bpp
        signal = noise = 0
        for y in range(height):
            in_row = zeroout(src_pixels[src_stride * y:src_stride * y + row_bytes], xi, Bpp)
            out_row = zeroout(out_pixels[out_stride * y:out_stride * y + row_bytes], xi, Bpp)
            s, n = plane_energy(in_row, out_row)
            signal += s
            noise += n
        return signal, noise

    def _test_data(self, encoding, encoder_class, decoder_class,
                   options, in_csc="YUV420P", out_csc="YUV420P", colour="?",
                   pixeldata=None, width=128, height=128, quality=100, verify=True):
        log("test%s" % ((encoding, encoder_class, decoder_class, options, in_csc, out_csc, colour,
                         len(pixeldata or ()), width, height),))
        encoder = encoder_class()
        options = typedict(options or {})
        options["quality"] = quality
        options["speed"] = 0
        options["dst-formats"] = (out_csc,)
        encoder.init_context(encoding, width, height, in_csc, options)
        if verify:
            in_image = make_test_image(in_csc, width, height, pixeldata)
        else:
            # lossy mode: use a textured image so the loss is measurable:
            in_image = make_textured_image(in_csc, width, height)
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
            return 0, 0
        out_pixels = out_image.get_pixels()

        out_csc = out_image.get_pixel_format()
        md = 0
        # signal-to-noise energy accumulated when not verifying (lossy mode):
        signal = noise = 0
        if in_csc.startswith("YUV") or in_csc == "NV12":
            nplanes = out_image.get_planes()
            if in_csc != out_csc:
                if out_csc == "NV12" or in_csc == "NV12":
                    log(f"only comparing Y plane for {in_csc} -> {out_csc} (not fully implemented)")
                    nplanes = 1
                else:
                    raise ValueError(f"YUV output colorspace {out_csc} differs from input colorspace {in_csc}")
            divs = get_subsampling_divs(in_csc)
            try:
                depth = int(in_csc.split("P")[1])       # ie: YUV420P10 -> 10
            except (IndexError, ValueError):
                depth = 8
            Bpp = (depth + 7) // 8                       # 8-bit -> 1, 10-bit -> 2
            log(f"comparing {in_csc} and {out_csc}: {nplanes=}, {divs=}, {Bpp=} {out_image=} from {decoder=}")
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
                    p2 = p1 + (width // xdiv) * Bpp
                    saved_rowdata = saved_pdata[p1:p2]
                    in_rowdata = in_pdata[p1:p2]
                    p1 = out_stride * y
                    p2 = p1 + (width // xdiv) * Bpp
                    out_rowdata = out_pdata[p1:p2]
                    if not verify:
                        #lossy: accumulate signal/noise instead of comparing:
                        s, n = plane_energy(in_rowdata, out_rowdata, Bpp)
                        signal += s
                        noise += n
                        continue
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
            if verify:
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
                    return signal, noise
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
                    if not verify:
                        #lossy: accumulate signal/noise instead of comparing:
                        s, n = plane_energy(in_rowdata, out_rowdata)
                        signal += s
                        noise += n
                        continue
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
        return signal, noise


def main():
    consume_verbose_argv(sys.argv, "video")
    unittest.main()


if __name__ == '__main__':
    main()
