#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Characterize video encoder speed/quality trade-offs on a fixed stream.

This is deliberately a benchmark rather than a pass/fail unit test: encoded
size and latency depend on the codec build, hardware and machine load.
"""

import argparse
import csv
import math
import statistics
import sys
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic

from xpra.codecs.image import ImageWrapper
from xpra.codecs.video import getVideoHelper
from xpra.util.objects import typedict


RGB_FORMAT = "BGRX"


@dataclass(frozen=True)
class Result:
    encoding: str
    encoder: str
    decoder: str
    pipeline: str
    quality: int
    speed: int
    frames: int
    bytes: int
    bytes_per_frame: float
    snr_db: float
    psnr_db: float
    csc_ms: float
    encode_ms: float
    roundtrip_ms: float


def int_list(value: str) -> tuple[int, ...]:
    values = tuple(dict.fromkeys(int(x.strip()) for x in value.split(",") if x.strip()))
    if not values or any(x < 0 or x > 100 for x in values):
        raise argparse.ArgumentTypeError("expected comma-separated values between 0 and 100")
    return values


def make_frame(width: int, height: int, frame_no: int) -> ImageWrapper:
    """Generate deterministic BGRX containing gradients, edges and motion."""
    pixels = bytearray(width * height * 4)
    box_w = max(8, width // 5)
    box_h = max(8, height // 5)
    bx = (frame_no * 13) % (width + box_w) - box_w
    by = (frame_no * 7) % (height + box_h) - box_h
    p = 0
    for y in range(height):
        for x in range(width):
            checker = 48 if ((x // 16) ^ (y // 16)) & 1 else 0
            b = (x * 255 // max(1, width - 1) + checker) & 0xff
            g = (y * 255 // max(1, height - 1) + frame_no * 3) & 0xff
            r = ((x + y) * 127 // max(1, width + height - 2) + checker) & 0xff
            if bx <= x < bx + box_w and by <= y < by + box_h:
                b, g, r = 20, 230, 250
            pixels[p:p + 4] = bytes((b, g, r, 255))
            p += 4
    return ImageWrapper(0, 0, width, height, bytes(pixels), RGB_FORMAT, 32,
                        width * 4, planes=ImageWrapper.PACKED, thread_safe=True)


def rgb_energy(reference: ImageWrapper, candidate: ImageWrapper) -> tuple[int, int]:
    """Return RGB signal and error energy, ignoring row padding and X."""
    ref = reference.get_pixels()
    got = candidate.get_pixels()
    ref_stride = reference.get_rowstride()
    got_stride = candidate.get_rowstride()
    width = reference.get_width()
    height = reference.get_height()
    signal = noise = 0
    for y in range(height):
        ro = y * ref_stride
        go = y * got_stride
        for x in range(width):
            rp = ro + x * 4
            gp = go + x * 4
            for channel in range(3):
                a = ref[rp + channel]
                delta = a - got[gp + channel]
                signal += a * a
                noise += delta * delta
    return signal, noise


def snr_db(signal: int, noise: int) -> float:
    if noise == 0:
        return math.inf
    return 10 * math.log10(signal / noise)


def psnr_db(noise: int, samples: int) -> float:
    if noise == 0:
        return math.inf
    return 10 * math.log10(255 * 255 / (noise / samples))


def cpu_spec(specs):
    for spec in specs or ():
        if spec.codec_type not in ("nvdec",) and not spec.codec_type.startswith("cuda"):
            return spec
    return None


def clean(obj) -> None:
    if obj:
        try:
            obj.clean()
        except Exception:
            pass


def packet_bytes(data) -> bytes:
    payload = getattr(data, "data", data)
    return payload if isinstance(payload, bytes) else bytes(payload)


def benchmark_pipeline(encoding, enc_spec, dec_spec, fcsc_spec, bcsc_spec,
                       width, height, frames, warmup, quality, speed, base_options) -> Result:
    options = typedict(base_options | {
        "quality": quality,
        "speed": speed,
        "max-delayed": 0,
        "b-frames": 0,
        "dst-formats": list(enc_spec.output_colorspaces),
    })
    csc_options = typedict({"full-range": enc_spec.full_range})
    encoder = enc_spec.codec_class()
    decoder = dec_spec.codec_class()
    fcsc = fcsc_spec.codec_class() if fcsc_spec else None
    bcsc = bcsc_spec.codec_class() if bcsc_spec else None
    measured_sizes = []
    csc_times = []
    encode_times = []
    roundtrip_times = []
    signal = noise = decoded_count = 0
    pending = []
    try:
        if fcsc:
            fcsc.init_context(width, height, RGB_FORMAT, width, height,
                              enc_spec.input_colorspace, csc_options)
        if bcsc:
            bcsc.init_context(width, height, dec_spec.input_colorspace, width, height,
                              RGB_FORMAT, csc_options)
        encoder.init_context(encoding, width, height, enc_spec.input_colorspace, options)
        decoder.init_context(encoding, width, height, dec_spec.input_colorspace, options)
        for frame_no in range(frames + warmup):
            source = make_frame(width, height, frame_no)
            start = monotonic()
            converted = fcsc.convert_image(source) if fcsc else source
            after_csc = monotonic()
            encoded = encoder.compress_image(converted, options)
            after_encode = monotonic()
            if converted is not source:
                converted.free()
            if not encoded or not encoded[0]:
                source.free()
                continue
            data, client_options = encoded
            pending.append((frame_no, source, start, len(packet_bytes(data)),
                            after_csc - start, after_encode - after_csc))
            decoded = decoder.decompress_image(packet_bytes(data), typedict(client_options))
            if decoded is None:
                continue
            source_no, reference, frame_start, data_size, csc_time, encode_time = pending.pop(0)
            before_bcsc = monotonic()
            rgb = bcsc.convert_image(decoded) if bcsc else decoded
            end = monotonic()
            if source_no >= warmup:
                measured_sizes.append(data_size)
                # Include both RGB->encoder and decoder->RGB conversion.
                csc_times.append((csc_time + (end - before_bcsc if bcsc else 0)) * 1000)
                encode_times.append(encode_time * 1000)
                roundtrip_times.append((end - frame_start) * 1000)
                s, n = rgb_energy(reference, rgb)
                signal += s
                noise += n
                decoded_count += 1
            if rgb is not decoded:
                rgb.free()
            decoded.free()
            reference.free()
        if not measured_sizes or not decoded_count:
            raise RuntimeError("pipeline produced no measured decoded frames")
        samples = decoded_count * width * height * 3
        return Result(
            encoding, enc_spec.codec_type, dec_spec.codec_type,
            f"{RGB_FORMAT}->{enc_spec.input_colorspace}->{dec_spec.input_colorspace}->{RGB_FORMAT}",
            quality, speed, decoded_count, sum(measured_sizes),
            statistics.mean(measured_sizes), snr_db(signal, noise), psnr_db(noise, samples),
            statistics.mean(csc_times), statistics.mean(encode_times),
            statistics.mean(roundtrip_times),
        )
    finally:
        for _frame_no, source, _start, _size, _csc_time, _encode_time in pending:
            source.free()
        clean(decoder)
        clean(encoder)
        clean(bcsc)
        clean(fcsc)


def discover_pipelines(helper, width: int, height: int, encodings: set[str], encoders: set[str]):
    for encoding in helper.get_encodings():
        if encodings and encoding not in encodings:
            continue
        decoder_specs = helper.get_decoder_specs(encoding)
        for input_csc, encoder_specs in helper.get_encoder_specs(encoding).items():
            fcsc = None
            if input_csc != RGB_FORMAT:
                fcsc = cpu_spec(helper.get_csc_specs(RGB_FORMAT).get(input_csc))
                if not fcsc:
                    continue
            for enc_spec in encoder_specs:
                if encoders and enc_spec.codec_type not in encoders:
                    continue
                for output_csc in enc_spec.output_colorspaces:
                    dec_spec = cpu_spec(decoder_specs.get(output_csc))
                    if not dec_spec:
                        continue
                    bcsc = None
                    if output_csc != RGB_FORMAT:
                        bcsc = cpu_spec(helper.get_csc_specs(output_csc).get(RGB_FORMAT))
                        if not bcsc:
                            continue
                    specs = tuple(x for x in (enc_spec, dec_spec, fcsc, bcsc) if x)
                    width_mask = 0xffff
                    height_mask = 0xffff
                    for spec in specs:
                        width_mask &= spec.width_mask
                        height_mask &= spec.height_mask
                    if width == (width & width_mask) and height == (height & height_mask):
                        yield encoding, enc_spec, dec_spec, fcsc, bcsc


def print_result(result: Result) -> None:
    quality = "lossless" if math.isinf(result.psnr_db) else f"{result.psnr_db:5.1f} dB"
    snr = "lossless" if math.isinf(result.snr_db) else f"{result.snr_db:5.1f} dB"
    print(f"{result.encoding:6} {result.encoder:10} {result.pipeline:34} "
          f"q={result.quality:3} s={result.speed:3}  {result.bytes_per_frame:9.0f} B/f  "
          f"SNR={snr:>9} PSNR={quality:>9}  enc={result.encode_ms:7.2f} ms  "
          f"e2e={result.roundtrip_ms:7.2f} ms")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", default="640x360", help="frame size (default: 640x360)")
    parser.add_argument("--frames", type=int, default=30, help="measured frames per run")
    parser.add_argument("--warmup", type=int, default=3, help="unmeasured warm-up frames")
    parser.add_argument("--quality", type=int_list, default=(20, 50, 80, 100))
    parser.add_argument("--speed", type=int_list, default=(20, 50, 80, 100))
    parser.add_argument("--encodings", default="", help="comma-separated encoding filter")
    parser.add_argument("--encoders", default="", help="comma-separated codec_type filter")
    parser.add_argument("--csv", type=Path, help="write raw results as CSV")
    args = parser.parse_args(argv)
    try:
        width, height = (int(x) for x in args.size.lower().split("x", 1))
    except ValueError as e:
        parser.error(f"invalid size {args.size!r}: {e}")
    if width <= 0 or height <= 0 or args.frames <= 0 or args.warmup < 0:
        parser.error("size and frames must be positive; warmup must not be negative")

    helper = getVideoHelper()
    helper.enable_all_modules()
    helper.init()
    base_options = {}
    context = nullcontext()
    try:
        from xpra.codecs.nvidia.cuda.context import get_default_device_context
        context = get_default_device_context()
        base_options["cuda-device-context"] = context
    except (ImportError, RuntimeError):
        pass

    filters = ({x for x in args.encodings.split(",") if x},
               {x for x in args.encoders.split(",") if x})
    pipelines = list(discover_pipelines(helper, width, height, *filters))
    if not pipelines:
        print("no compatible encoder/decoder/CSC pipelines found", file=sys.stderr)
        return 1
    results = []
    with context:
        for pipeline in pipelines:
            encoding, enc_spec, dec_spec, _fcsc, _bcsc = pipeline
            for quality in args.quality:
                for speed in args.speed:
                    try:
                        result = benchmark_pipeline(*pipeline, width, height,
                                                    args.frames, args.warmup,
                                                    quality, speed, base_options)
                    except Exception as e:
                        print(f"skip {encoding}/{enc_spec.codec_type}/{dec_spec.codec_type} "
                              f"q={quality} s={speed}: {e}", file=sys.stderr)
                        continue
                    results.append(result)
                    print_result(result)
    if args.csv and results:
        with args.csv.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=tuple(asdict(results[0])))
            writer.writeheader()
            writer.writerows(asdict(result) for result in results)
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
