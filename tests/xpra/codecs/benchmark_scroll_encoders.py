#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Compare recent-scroll motion tuning on deterministic text and browser streams.

Pixels and colour conversion are prepared before timing. Each run starts with
eight idle frames, then scrolls, stops, jumps and stops long enough for the hint
to expire. Encoding time includes live reconfiguration; decoded luma PSNR is
measured separately. Run with PYTHONPATH=. from the repository root.
"""

import argparse
import importlib
import json
import math
import platform
import random
import statistics
from collections import defaultdict
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from xpra.codecs.image import ImageWrapper
from xpra.codecs.libyuv.converter import Converter
from xpra.util.objects import typedict


def make_document(width: int, height: int, scenario: str) -> Image.Image:
    dark = scenario == "text"
    image = Image.new("RGB", (width, height), "#20242a" if dark else "#fafbfc")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=16)
    snippets = (
        "def encode_frame(image, options):", "    quality = options.get('quality', 65)",
        "    for rectangle in damage_regions:", "        pixels = image.get_pixels()",
        "        record_scroll_event(window_id)", "    return encoder.compress_image(image, options)",
    )
    fixture = Path(__file__).resolve().parents[2] / "test-images/codec-benchmark/continuous-tone.png"
    with Image.open(fixture) as source:
        photo = source.convert("RGB").resize((width // 2, 120))
    rng = random.Random(20261104)
    for row, y in enumerate(range(12, height - 24, 24)):
        color = rng.choice(("#a8cf96", "#e3b17b", "#93b9e8", "#d59add")) if dark else "#253246"
        text = f"{row:04d}  {snippets[row % len(snippets)]}" if dark else f"Article {row:04d}: scrolling and video compression"
        draw.text((12, y), text, font=font, fill=color)
        if not dark and row % 12 == 3:
            image.paste(photo, (width // 3, y + 24))
    return image


def make_stream(width: int, height: int, scenario: str, frames: int):
    viewport = (64, 48, width - 16, height - 16)
    vw, vh = viewport[2] - viewport[0], viewport[3] - viewport[1]
    document = make_document(vw, vh + frames * 192, scenario)
    converter = Converter()
    converter.init_context(width, height, "BGRX", width, height, "YUV420P", typedict({"full-range": True}))
    stream = []
    offset = 0
    last_event = -1000
    try:
        for frame_no in range(frames):
            moving = 8 <= frame_no < 32 or 48 <= frame_no < 64
            if moving:
                offset += 12 if frame_no < 32 else (96, 192, 64, 128)[frame_no % 4]
                last_event = frame_no * 50
            age = frame_no * 50 - last_event
            frame = Image.new("RGB", (width, height), "#343a44")
            draw = ImageDraw.Draw(frame)
            draw.text((16, 16), f"Xpra scrolling benchmark: {scenario}", fill="white")
            frame.paste(document.crop((0, offset, vw, offset + vh)), viewport[:2])
            packed = ImageWrapper(0, 0, width, height, (frame.tobytes("raw", "BGRX"),), "BGRX", 24, width * 4)
            converted = converter.convert_image(packed)
            converted.set_timestamp(frame_no * 50 + 1)
            packed.free()
            stream.append((converted, age if 0 <= age < 1000 else None, moving))
    finally:
        converter.clean()
    return stream


def luma(image: ImageWrapper) -> np.ndarray:
    return np.ndarray((image.get_height(), image.get_width()), dtype=np.uint8,
                      buffer=image.get_plane(0), strides=(image.get_rowstride()[0], 1))


def measure(encoding: str, module, stream, width: int, height: int, quality: int, speed: int,
            tuning: int, scenario: str, threads: int | None) -> dict:
    if encoding == "h264":
        module.SCROLL_ME_RANGE = tuning
        decoder_module = importlib.import_module("xpra.codecs.openh264.decoder")
    else:
        module.SCROLL_CPUUSED_DELTA = tuning
        decoder_module = importlib.import_module("xpra.codecs.vpx.decoder")
    encoder = module.Encoder()
    decoder = decoder_module.Decoder()
    options = typedict({"quality": quality, "speed": speed, "content-types": (scenario,),
                       "b-frames": 0, "max-delayed": 0, "full-range": True})
    if threads is not None:
        options["threads"] = threads
    sizes, times, moving_sizes, moving_times = [], [], [], []
    phase_sizes, phase_times = defaultdict(list), defaultdict(list)
    error = samples = 0
    active_info = {}
    try:
        encoder.init_context(encoding, width, height, "YUV420P", options)
        decoder.init_context(encoding, width, height, "YUV420P", typedict())
        for frame_no, (image, age, moving) in enumerate(stream):
            frame_options = typedict(options)
            if tuning and age is not None:
                frame_options["scroll-age-ms"] = age
            start = perf_counter()
            data, client_options = encoder.compress_image(image, frame_options)
            elapsed = (perf_counter() - start) * 1000
            if frame_no == 8:
                active_info = encoder.get_info()
            if not data:
                raise RuntimeError(f"{encoding}: frame {frame_no} produced no data")
            decoded = decoder.decompress_image(data, typedict(client_options))
            if decoded is None:
                raise RuntimeError(f"{encoding}: frame {frame_no} could not be decoded")
            if frame_no >= 8:
                sizes.append(len(data))
                times.append(elapsed)
                phase = "smooth" if frame_no < 32 else "settling" if frame_no < 48 else "jump" if frame_no < 64 else "idle"
                phase_sizes[phase].append(len(data))
                phase_times[phase].append(elapsed)
                delta = luma(image).astype(np.int32) - luma(decoded)
                error += int(np.sum(delta * delta, dtype=np.int64))
                samples += width * height
                if moving:
                    moving_sizes.append(len(data))
                    moving_times.append(elapsed)
            decoded.free()
        info = encoder.get_info()
        return {
            "encoding": encoding, "quality": quality, "speed": speed, "tuning": tuning,
            "frames": len(sizes), "bytes": sum(sizes), "encode_ms": statistics.mean(times),
            "p95_ms": float(np.percentile(times, 95)), "moving_bytes": sum(moving_sizes),
            "moving_ms": statistics.mean(moving_times),
            "luma_psnr_db": 10 * math.log10(255 ** 2 * samples / error) if error else None,
            "active_me": active_info.get("params", {}).get("me", {}),
            "active_cpu_used": active_info.get("cpu-used"),
            "encoder_threads": info.get("params", {}).get("threads", info.get("max_threads")),
            "phases": {phase: {"bytes": sum(sizes), "encode_ms": statistics.mean(phase_times[phase])}
                       for phase, sizes in phase_sizes.items()},
            "final_me": info.get("params", {}).get("me", {}), "final_cpu_used": info.get("cpu-used"),
        }
    finally:
        decoder.clean()
        encoder.clean()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=448)
    parser.add_argument("--frames", type=int, default=96)
    parser.add_argument("--quality", default="65")
    parser.add_argument("--speed", default="50,80")
    parser.add_argument("--encodings", default="h264,vp8,vp9")
    parser.add_argument("--scenarios", default="text,browser")
    parser.add_argument("--x264-ranges", default="0,64")
    parser.add_argument("--vpx-deltas", default="0,2")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--threads", type=int, help="libvpx threads; omitted uses the encoder default")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.frames < 85 or args.width < 256 or args.height < 128 or args.width % 2 or args.height % 2:
        parser.error("use at least 85 frames, even width >=256 and even height >=128")
    results = []
    versions = {}
    for scenario in args.scenarios.split(","):
        stream = make_stream(args.width, args.height, scenario, args.frames)
        try:
            for encoding in args.encodings.split(","):
                module = importlib.import_module(f"xpra.codecs.{'x264' if encoding == 'h264' else 'vpx'}.encoder")
                versions[encoding] = module.get_version()
                tunings = [int(x) for x in (args.x264_ranges if encoding == "h264" else args.vpx_deltas).split(",")]
                for quality in map(int, args.quality.split(",")):
                    for speed in map(int, args.speed.split(",")):
                        for repeat in range(args.repeat):
                            order = tunings.copy()
                            random.Random(repeat).shuffle(order)
                            for tuning in order:
                                result = measure(encoding, module, stream, args.width, args.height, quality, speed,
                                                 tuning, scenario, args.threads)
                                result.update(scenario=scenario, repeat=repeat)
                                results.append(result)
                                print(json.dumps(result), flush=True)
        finally:
            for image, _age, _moving in stream:
                image.free()
    args.output.write_text(json.dumps({"host": platform.platform(), "versions": versions,
                                      "settings": vars(args) | {"output": str(args.output)}, "results": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
