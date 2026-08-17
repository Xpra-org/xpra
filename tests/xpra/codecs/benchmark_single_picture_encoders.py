#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Measure picture encoder size, latency and end-to-end decoded quality.

The committed corpus deliberately separates sharp synthetic screen content
from continuous-tone imagery.  Every lossy result is decoded through Xpra's
own decoder before its SNR and PSNR are calculated.  Transparent fixtures are
fed to encoders as premultiplied BGRA, matching captured window pixels, and
their visible RGB quality is measured after compositing over black and white.
"""

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, TextIO

# Ensure the source tree's xpra package is importable when running as a script.
if not getattr(sys, "frozen", False):
    REPO_ROOT = Path(__file__).resolve().parents[3]
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
else:  # pragma: no cover - used by frozen test bundles
    REPO_ROOT = Path.cwd()

from PIL import Image

from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec
from xpra.net import compression
from xpra.util.objects import typedict


FIXTURE_DIR = REPO_ROOT / "tests" / "test-images" / "codec-benchmark"
DEFAULT_QUALITIES = (30, 50, 80, 100)
# These values exercise all four rungs of the AVIF speed curve introduced by #4998.
DEFAULT_SPEEDS = (20, 40, 60, 80)
DEFAULT_REPETITIONS = 5
DEFAULT_WARMUP = 1
VISIBLE_BACKGROUNDS = ((0, 0, 0), (255, 255, 255))


@dataclass(frozen=True)
class Fixture:
    name: str
    filename: str
    width: int
    height: int
    pixel_format: str
    pixels: bytes
    straight_rgba: bytes
    premultiplied_rgba: bytes
    content_types: tuple[str, ...]
    quality_metric: str
    has_alpha: bool
    pixel_sha256: str
    edge_mask: bytes

    @property
    def rowstride(self) -> int:
        return self.width * 4


@dataclass(frozen=True)
class CodecCase:
    name: str
    encoder: str
    encoding: str
    decoder: str
    alpha: str = "any"
    uses_quality: bool = True
    uses_speed: bool = True
    rgb_compressor: str = ""
    decoder_straight_alpha: bool = False


@dataclass(frozen=True)
class Result:
    scenario: str
    fixture: str
    content_types: tuple[str, ...]
    quality_metric: str
    has_alpha: bool
    width: int
    height: int
    encoder: str
    decoder: str
    requested_encoding: str
    encoding: str
    quality: int | None
    speed: int | None
    frames: int
    raw_bytes: int
    encoded_bytes: int
    compression_ratio: float
    bits_per_pixel: float
    encode_ms: float
    encode_p95_ms: float
    decode_ms: float
    decode_p95_ms: float
    rgb_snr_db: float
    rgb_psnr_db: float
    edge_psnr_db: float
    max_rgb_error: int
    edge_max_rgb_error: int
    alpha_psnr_db: float | None
    max_alpha_error: int | None
    alpha_exact: bool | None
    lossless: bool


CODEC_CASES = (
    CodecCase("rgb-raw", "enc_rgb", "rgb32", "", uses_quality=False, uses_speed=False),
    CodecCase("rgb-lz4", "enc_rgb", "rgb32", "", uses_quality=False, rgb_compressor="lz4"),
    CodecCase("rgb-zstd", "enc_rgb", "rgb32", "", uses_quality=False, rgb_compressor="zstd"),
    CodecCase("png", "enc_pillow", "png", "dec_pillow", uses_quality=False, decoder_straight_alpha=True),
    CodecCase("png-palette", "enc_pillow", "png/P", "dec_pillow", uses_quality=False,
              decoder_straight_alpha=True),
    CodecCase("png-grayscale", "enc_pillow", "png/L", "dec_pillow", uses_quality=False,
              decoder_straight_alpha=True),
    CodecCase("jpeg", "enc_jpeg", "jpeg", "dec_jpeg", alpha="opaque", uses_speed=False),
    CodecCase("jpega", "enc_jpeg", "jpega", "dec_jpeg", alpha="alpha", uses_speed=False),
    CodecCase("webp", "enc_webp", "webp", "dec_webp"),
    CodecCase("avif", "enc_avif", "avif", "dec_avif"),
    CodecCase("jph", "enc_jph", "jph", "dec_jph", alpha="opaque", uses_speed=False),
)


def int_list(value: str) -> tuple[int, ...]:
    values = tuple(dict.fromkeys(int(item.strip()) for item in value.split(",") if item.strip()))
    if not values or any(item < 0 or item > 100 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated values between 0 and 100")
    return values


def percentile95(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile without values")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def snr_db(signal: int, noise: int) -> float:
    if noise == 0:
        return math.inf
    if signal == 0:
        return -math.inf
    return 10 * math.log10(signal / noise)


def psnr_db(noise: int, samples: int) -> float:
    if noise == 0:
        return math.inf
    if samples <= 0:
        raise ValueError("PSNR requires at least one sample")
    return 10 * math.log10(255 * 255 / (noise / samples))


def rgb_energy(reference: bytes, candidate: bytes, mask: bytes | None = None) -> tuple[int, int, int, int]:
    if len(reference) != len(candidate) or len(reference) % 4:
        raise ValueError("RGBA buffers must have the same whole-pixel length")
    pixels = len(reference) // 4
    if mask is not None and len(mask) != pixels:
        raise ValueError("edge mask dimensions do not match the RGBA buffers")
    signal = noise = samples = maximum = 0
    for pixel in range(pixels):
        if mask is not None and not mask[pixel]:
            continue
        offset = pixel * 4
        for channel in range(3):
            value = reference[offset + channel]
            error = abs(value - candidate[offset + channel])
            signal += value * value
            noise += error * error
            maximum = max(maximum, error)
            samples += 1
    return signal, noise, samples, maximum


def alpha_energy(reference: bytes, candidate: bytes) -> tuple[int, int, int]:
    if len(reference) != len(candidate) or len(reference) % 4:
        raise ValueError("RGBA buffers must have the same whole-pixel length")
    noise = maximum = 0
    samples = len(reference) // 4
    for offset in range(3, len(reference), 4):
        error = abs(reference[offset] - candidate[offset])
        noise += error * error
        maximum = max(maximum, error)
    return noise, samples, maximum


def make_edge_mask(rgba: bytes, width: int, height: int) -> bytes:
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer dimensions do not match")
    luma = bytearray(width * height)
    for pixel in range(width * height):
        offset = pixel * 4
        red, green, blue = rgba[offset:offset + 3]
        luma[pixel] = (77 * red + 150 * green + 29 * blue) >> 8
    gradients: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            pixel = y * width + x
            right = luma[pixel + 1] if x + 1 < width else luma[pixel]
            below = luma[pixel + width] if y + 1 < height else luma[pixel]
            gradient = abs(luma[pixel] - right) + abs(luma[pixel] - below)
            gradients.append((gradient, pixel))
    edge_count = max(1, len(gradients) // 10)
    gradients.sort(reverse=True)
    mask = bytearray(width * height)
    for _gradient, pixel in gradients[:edge_count]:
        mask[pixel] = 1
    return bytes(mask)


def premultiply_rgba(rgba: bytes) -> bytes:
    if len(rgba) % 4:
        raise ValueError("RGBA buffer must have a whole-pixel length")
    premultiplied = bytearray(rgba)
    for offset in range(0, len(rgba), 4):
        alpha = rgba[offset + 3]
        for channel in range(3):
            premultiplied[offset + channel] = rgba[offset + channel] * alpha // 255
    return bytes(premultiplied)


def composite_rgba(premultiplied_rgba: bytes, background: tuple[int, int, int]) -> bytes:
    if len(premultiplied_rgba) % 4:
        raise ValueError("RGBA buffer must have a whole-pixel length")
    composite = bytearray(len(premultiplied_rgba))
    for offset in range(0, len(premultiplied_rgba), 4):
        alpha = premultiplied_rgba[offset + 3]
        inverse_alpha = 255 - alpha
        for channel in range(3):
            composite[offset + channel] = min(
                255, premultiplied_rgba[offset + channel] + background[channel] * inverse_alpha // 255,
            )
        composite[offset + 3] = 255
    return bytes(composite)


def visible_rgba(premultiplied_rgba: bytes) -> bytes:
    return b"".join(composite_rgba(premultiplied_rgba, background) for background in VISIBLE_BACKGROUNDS)


def pack_bgrx(rgba: bytes, has_alpha: bool) -> tuple[str, bytes]:
    rgba = premultiply_rgba(rgba) if has_alpha else rgba
    packed = bytearray(len(rgba))
    for offset in range(0, len(rgba), 4):
        packed[offset] = rgba[offset + 2]
        packed[offset + 1] = rgba[offset + 1]
        packed[offset + 2] = rgba[offset]
        packed[offset + 3] = rgba[offset + 3] if has_alpha else 0xFF
    return ("BGRA" if has_alpha else "BGRX"), bytes(packed)


def load_fixtures(directory: Path = FIXTURE_DIR) -> list[Fixture]:
    manifest_path = directory / "manifest.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("scenarios"), list):
        raise ValueError(f"invalid picture benchmark manifest: {manifest_path}")
    fixtures = []
    for entry in manifest["scenarios"]:
        path = directory / entry["file"]
        with Image.open(path) as source:
            image = source.convert("RGBA")
        rgba = image.tobytes()
        alpha_min, alpha_max = image.getchannel("A").getextrema()
        has_alpha = (alpha_min, alpha_max) != (255, 255)
        pixel_format, pixels = pack_bgrx(rgba, has_alpha)
        premultiplied_rgba = premultiply_rgba(rgba) if has_alpha else rgba
        quality_metric = entry["quality_metric"]
        if quality_metric not in ("rgb_psnr_db", "edge_psnr_db"):
            raise ValueError(f"invalid quality metric {quality_metric!r} for {entry['name']}")
        fixtures.append(Fixture(
            entry["name"], entry["file"], image.width, image.height,
            pixel_format, pixels, rgba, premultiplied_rgba, tuple(entry.get("content_types", ())),
            quality_metric, has_alpha, hashlib.sha256(rgba).hexdigest(),
            make_edge_mask(composite_rgba(premultiplied_rgba, (127, 127, 127)), image.width, image.height),
        ))
    return fixtures


def make_image(fixture: Fixture) -> ImageWrapper:
    return ImageWrapper(
        0, 0, fixture.width, fixture.height, fixture.pixels,
        fixture.pixel_format, 32, fixture.rowstride,
        planes=ImageWrapper.PACKED, thread_safe=True,
    )


def packet_bytes(data: Any) -> bytes:
    payload = getattr(data, "data", data)
    return payload if isinstance(payload, bytes) else bytes(payload)


def image_to_rgba(pixel_format: str, pixels: Any, width: int, height: int, rowstride: int) -> bytes:
    if pixel_format in ("L", "LA"):
        mode = pixel_format
    elif "A" in pixel_format:
        mode = "RGBA"
    else:
        mode = "RGB"
    image = Image.frombuffer(mode, (width, height), bytes(pixels), "raw", pixel_format, rowstride, 1)
    return image.convert("RGBA").tobytes()


def normalize_decoded_rgba(case: CodecCase, fixture: Fixture, rgba: bytes) -> bytes:
    if fixture.has_alpha and case.decoder_straight_alpha:
        return premultiply_rgba(rgba)
    return rgba


def decode_rgb(case: CodecCase, decoder: Any, coding: str, cdata: bytes,
               client_options: dict[str, Any], fixture: Fixture, rowstride: int) -> bytes:
    options = typedict(client_options | {
        "rgb_format": fixture.pixel_format,
        "has_alpha": fixture.has_alpha,
        "alpha": fixture.has_alpha,
    })
    if not case.decoder:
        raw: Any = cdata
        for compressor in ("lz4", "zstd"):
            if options.intget(compressor, 0):
                raw = compression.COMPRESSION[compressor].decompress(cdata)
                break
        pixel_format = options.strget("rgb_format", fixture.pixel_format)
        rgba = image_to_rgba(pixel_format, raw, fixture.width, fixture.height, rowstride)
        return normalize_decoded_rgba(case, fixture, rgba)
    if case.decoder == "dec_pillow":
        pixel_format, raw, width, height, decoded_stride = decoder.decompress(coding, cdata, options)
        rgba = image_to_rgba(pixel_format, raw, width, height, decoded_stride)
        return normalize_decoded_rgba(case, fixture, rgba)
    decoded = None
    try:
        if hasattr(decoder, "decompress_to_rgb"):
            decoded = decoder.decompress_to_rgb(cdata, options)
        else:
            decoded = decoder.decompress(cdata, options)
        rgba = image_to_rgba(
            decoded.get_pixel_format(), decoded.get_pixels(),
            decoded.get_width(), decoded.get_height(), decoded.get_rowstride(),
        )
        return normalize_decoded_rgba(case, fixture, rgba)
    finally:
        if decoded:
            decoded.free()


def settings(case: CodecCase, qualities: tuple[int, ...], speeds: tuple[int, ...]):
    quality_values: tuple[int | None, ...] = qualities if case.uses_quality else (None,)
    speed_values: tuple[int | None, ...] = speeds if case.uses_speed else (None,)
    for quality in quality_values:
        for speed in speed_values:
            yield quality, speed


def compatible(case: CodecCase, fixture: Fixture) -> bool:
    if case.alpha == "opaque" and fixture.has_alpha:
        return False
    if case.alpha == "alpha" and not fixture.has_alpha:
        return False
    return True


def encode_once(case: CodecCase, encoder: Any, fixture: Fixture,
                quality: int | None, speed: int | None) -> tuple[str, bytes, dict[str, Any], int, float]:
    image = make_image(fixture)
    options = typedict({
        "quality": 100 if quality is None else quality,
        "speed": 50 if speed is None else speed,
        "alpha": fixture.has_alpha,
        "content-types": fixture.content_types,
        "rgb_formats": (fixture.pixel_format,),
        "lz4": case.rgb_compressor == "lz4",
        "zstd": case.rgb_compressor == "zstd",
    })
    start = monotonic()
    try:
        result = encoder.encode(case.encoding, image, options)
    finally:
        elapsed = monotonic() - start
        image.free()
    if not result:
        raise RuntimeError(f"{case.encoder}:{case.encoding} returned no data")
    coding, data, client_options, width, height, rowstride, _bpp = result
    if (width, height) != (fixture.width, fixture.height):
        raise ValueError(f"encoder returned {width}x{height}, expected {fixture.width}x{fixture.height}")
    return coding, packet_bytes(data), dict(client_options), rowstride, elapsed


def benchmark_case(case: CodecCase, encoder: Any, decoder: Any, fixture: Fixture,
                   quality: int | None, speed: int | None,
                   repetitions: int, warmup: int) -> Result:
    for _ in range(warmup):
        coding, cdata, client_options, rowstride, _elapsed = encode_once(
            case, encoder, fixture, quality, speed,
        )
        decode_rgb(case, decoder, coding, cdata, client_options, fixture, rowstride)

    encoded = []
    encode_times = []
    for _ in range(repetitions):
        item = encode_once(case, encoder, fixture, quality, speed)
        encoded.append(item[:4])
        encode_times.append(item[4] * 1000)
    median_size = statistics.median(len(item[1]) for item in encoded)
    coding, cdata, client_options, rowstride = min(encoded, key=lambda item: abs(len(item[1]) - median_size))

    decode_times = []
    decoded_rgba = b""
    for _ in range(repetitions):
        start = monotonic()
        decoded_rgba = decode_rgb(case, decoder, coding, cdata, client_options, fixture, rowstride)
        decode_times.append((monotonic() - start) * 1000)
    if len(decoded_rgba) != len(fixture.premultiplied_rgba):
        raise ValueError(
            f"decoder produced {len(decoded_rgba)} RGBA bytes, expected {len(fixture.premultiplied_rgba)}",
        )

    reference_visible = visible_rgba(fixture.premultiplied_rgba)
    decoded_visible = visible_rgba(decoded_rgba)
    signal, noise, samples, maximum = rgb_energy(reference_visible, decoded_visible)
    _edge_signal, edge_noise, edge_samples, edge_maximum = rgb_energy(
        reference_visible, decoded_visible, fixture.edge_mask * len(VISIBLE_BACKGROUNDS),
    )
    alpha_psnr = None
    alpha_maximum = None
    alpha_exact = None
    if fixture.has_alpha:
        alpha_noise, alpha_samples, alpha_maximum = alpha_energy(fixture.premultiplied_rgba, decoded_rgba)
        alpha_psnr = psnr_db(alpha_noise, alpha_samples)
        alpha_exact = alpha_noise == 0
    encoded_size = len(cdata)
    raw_size = len(fixture.pixels)
    return Result(
        fixture.name, fixture.filename, fixture.content_types, fixture.quality_metric,
        fixture.has_alpha, fixture.width, fixture.height,
        case.name, case.decoder or "raw", case.encoding, coding,
        quality, speed, repetitions, raw_size, encoded_size,
        encoded_size / raw_size, encoded_size * 8 / (fixture.width * fixture.height),
        statistics.median(encode_times), percentile95(encode_times),
        statistics.median(decode_times), percentile95(decode_times),
        snr_db(signal, noise), psnr_db(noise, samples), psnr_db(edge_noise, edge_samples),
        maximum, edge_maximum, alpha_psnr, alpha_maximum, alpha_exact,
        decoded_rgba == fixture.premultiplied_rgba,
    )


def finite_quality(value: float | None) -> float:
    if value is None:
        return -math.inf
    if math.isinf(value):
        return 1.0e9 if value > 0 else -1.0e9
    return value


def dominates(left: Result, right: Result) -> bool:
    left_quality = finite_quality(getattr(left, left.quality_metric))
    right_quality = finite_quality(getattr(right, right.quality_metric))
    left_alpha = finite_quality(left.alpha_psnr_db) if left.has_alpha else 0
    right_alpha = finite_quality(right.alpha_psnr_db) if right.has_alpha else 0
    left_time = left.encode_ms + left.decode_ms
    right_time = right.encode_ms + right.decode_ms
    no_worse = all((
        left_quality >= right_quality,
        left_alpha >= right_alpha,
        left.encoded_bytes <= right.encoded_bytes,
        left_time <= right_time,
    ))
    strictly_better = any((
        left_quality > right_quality,
        left_alpha > right_alpha,
        left.encoded_bytes < right.encoded_bytes,
        left_time < right_time,
    ))
    return no_worse and strictly_better


def pareto_indices(results: list[Result]) -> set[int]:
    frontier = set()
    by_scenario: dict[str, list[int]] = {}
    for index, result in enumerate(results):
        by_scenario.setdefault(result.scenario, []).append(index)
    for indices in by_scenario.values():
        for candidate in indices:
            if not any(other != candidate and dominates(results[other], results[candidate]) for other in indices):
                frontier.add(candidate)
    return frontier


def json_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def result_dict(result: Result, pareto: bool = False) -> dict[str, Any]:
    return json_value(asdict(result) | {"pareto": pareto})


def write_json(results: list[Result], metadata: dict[str, Any], output: TextIO) -> None:
    frontier = pareto_indices(results)
    document = {
        "schema_version": 1,
        "benchmark": json_value(metadata),
        "results": [result_dict(result, index in frontier) for index, result in enumerate(results)],
    }
    json.dump(document, output, indent=2, allow_nan=False)
    output.write("\n")


def write_csv(results: list[Result], output: TextIO) -> None:
    frontier = pareto_indices(results)
    rows = [result_dict(result, index in frontier) for index, result in enumerate(results)]
    if not rows:
        return
    for row in rows:
        row["content_types"] = ",".join(row["content_types"])
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]))
    writer.writeheader()
    writer.writerows(rows)


def display_float(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    if math.isinf(value):
        return "lossless" if value > 0 else "-inf"
    return f"{value:.{decimals}f}"


def write_markdown(results: list[Result], output: TextIO) -> None:
    columns = (
        "Scenario", "Encoder", "Encoding", "Quality", "Speed", "Bytes", "bpp",
        "Encode ms", "Decode ms", "Visible RGB PSNR", "Visible edge PSNR", "Max visible error", "Alpha PSNR",
        "Pareto",
    )
    output.write("| " + " | ".join(columns) + " |\n")
    output.write("| " + " | ".join("---" for _column in columns) + " |\n")
    frontier = pareto_indices(results)
    for index, result in enumerate(results):
        values = (
            result.scenario, result.encoder, result.encoding,
            "-" if result.quality is None else str(result.quality),
            "-" if result.speed is None else str(result.speed),
            str(result.encoded_bytes), display_float(result.bits_per_pixel, 3),
            display_float(result.encode_ms), display_float(result.decode_ms),
            display_float(result.rgb_psnr_db), display_float(result.edge_psnr_db),
            str(result.max_rgb_error), display_float(result.alpha_psnr_db),
            "yes" if index in frontier else "",
        )
        output.write("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |\n")


def print_result(result: Result) -> None:
    quality = "-" if result.quality is None else str(result.quality)
    speed = "-" if result.speed is None else str(result.speed)
    print(
        f"{result.scenario:22} {result.encoder:13} {result.encoding:6} "
        f"q={quality:>3} s={speed:>3} {result.encoded_bytes:8} B "
        f"RGB={display_float(result.rgb_psnr_db):>8} dB "
        f"edge={display_float(result.edge_psnr_db):>8} dB "
        f"enc={result.encode_ms:7.2f} ms dec={result.decode_ms:7.2f} ms"
    )


def print_pareto_summary(results: list[Result]) -> None:
    frontier = pareto_indices(results)
    print("\nPareto frontier (quality up, payload/round-trip cost down)")
    for scenario in sorted({result.scenario for result in results}):
        print(f"\n{scenario}")
        rows = ((index, result) for index, result in enumerate(results)
                if result.scenario == scenario and index in frontier)
        for _index, result in sorted(rows, key=lambda item: (item[1].encoded_bytes, item[1].encode_ms)):
            metric = getattr(result, result.quality_metric)
            print(f"  {result.encoder:13} q={str(result.quality):>4} s={str(result.speed):>4} "
                  f"{result.encoded_bytes:8} B  {result.quality_metric}={display_float(metric)} dB  "
                  f"enc={result.encode_ms:.2f} ms dec={result.decode_ms:.2f} ms")


def codec_metadata(modules: dict[str, Any]) -> dict[str, Any]:
    info = {}
    for name, module in modules.items():
        if not module:
            continue
        try:
            info[name] = module.get_info()
        except Exception as error:
            info[name] = {"error": str(error)}
    return info


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=int_list, default=DEFAULT_QUALITIES)
    parser.add_argument("--speed", type=int_list, default=DEFAULT_SPEEDS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--fixtures", default="", help="comma-separated scenario filter")
    parser.add_argument("--encodings", default="", help="comma-separated encoding filter")
    parser.add_argument("--encoders", default="", help="comma-separated encoder/case filter")
    parser.add_argument("--limit", type=int, default=0, help="limit the number of corpus scenarios")
    parser.add_argument("--quick", action="store_true", help="run q=50/s=80 once without warm-up")
    parser.add_argument("--json", type=Path, help="write raw results and metadata as JSON")
    parser.add_argument("--csv", type=Path, help="write raw results as CSV")
    parser.add_argument("--markdown", type=Path, help="write results as a Markdown table")
    args = parser.parse_args(argv)
    if args.repetitions <= 0 or args.warmup < 0 or args.limit < 0:
        parser.error("repetitions must be positive; warmup and limit must not be negative")
    qualities = (50,) if args.quick else args.quality
    speeds = (80,) if args.quick else args.speed
    repetitions = 1 if args.quick else args.repetitions
    warmup = 0 if args.quick else args.warmup

    compression.init_all()
    fixtures = load_fixtures()
    fixture_filter = {item for item in args.fixtures.split(",") if item}
    if fixture_filter:
        fixtures = [fixture for fixture in fixtures if fixture.name in fixture_filter]
    if args.limit:
        fixtures = fixtures[:args.limit]
    if not fixtures:
        parser.error("no matching picture benchmark fixtures")

    encoding_filter = {item for item in args.encodings.split(",") if item}
    encoder_filter = {item for item in args.encoders.split(",") if item}
    cases = []
    for case in CODEC_CASES:
        encoding_selected = not encoding_filter or case.encoding in encoding_filter
        encoder_selected = not encoder_filter or case.name in encoder_filter
        encoder_selected = encoder_selected or case.encoder.removeprefix("enc_") in encoder_filter
        if encoding_selected and encoder_selected:
            cases.append(case)
    if not cases:
        parser.error("no matching picture codec cases")

    module_names = {case.encoder for case in cases} | {case.decoder for case in cases if case.decoder}
    modules: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for name in sorted(module_names):
        module = load_codec(name)
        modules[name] = module
        if not module:
            unavailable[name] = "codec unavailable"

    results = []
    for fixture in fixtures:
        print(f"\n{fixture.name}: {fixture.width}x{fixture.height} "
              f"content-types={fixture.content_types or ('unknown',)} alpha={fixture.has_alpha}")
        for case in cases:
            if not compatible(case, fixture):
                continue
            encoder = modules.get(case.encoder)
            decoder = modules.get(case.decoder) if case.decoder else None
            if not encoder or case.decoder and not decoder:
                continue
            if case.rgb_compressor and not compression.use(case.rgb_compressor):
                unavailable[case.name] = f"{case.rgb_compressor} compression unavailable"
                continue
            if case.encoding not in tuple(encoder.get_encodings()):
                unavailable[case.name] = f"{case.encoding} not exposed by {case.encoder}"
                continue
            if decoder and case.encoding not in tuple(decoder.get_encodings()):
                unavailable[case.name] = f"{case.encoding} not exposed by {case.decoder}"
                continue
            for quality, speed in settings(case, qualities, speeds):
                try:
                    result = benchmark_case(
                        case, encoder, decoder, fixture, quality, speed,
                        repetitions, warmup,
                    )
                except Exception as error:
                    unavailable[f"{fixture.name}/{case.name}/q{quality}/s{speed}"] = str(error)
                    print(f"skip {case.name} q={quality} s={speed}: {error}", file=sys.stderr)
                    continue
                results.append(result)
                print_result(result)

    if not results:
        print("no picture encoder benchmark results", file=sys.stderr)
        return 1
    print_pareto_summary(results)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qualities": qualities,
        "speeds": speeds,
        "repetitions": repetitions,
        "warmup": warmup,
        "fixture_filter": sorted(fixture_filter),
        "encoding_filter": sorted(encoding_filter),
        "encoder_filter": sorted(encoder_filter),
        "fixtures": [
            {
                "scenario": fixture.name,
                "file": fixture.filename,
                "width": fixture.width,
                "height": fixture.height,
                "content_types": fixture.content_types,
                "quality_metric": fixture.quality_metric,
                "has_alpha": fixture.has_alpha,
                "pixel_sha256": fixture.pixel_sha256,
            }
            for fixture in fixtures
        ],
        "codecs": codec_metadata(modules),
        "compression": compression.get_compression_caps(2),
        "alpha_quality": {
            "encoder_input": "premultiplied BGRA",
            "decoded_comparison": "premultiplied RGBA composited over black and white",
            "edge_detection_background": "50% gray",
        },
        "unavailable": unavailable,
    }
    if args.json:
        with args.json.open("w", encoding="utf-8") as json_file:
            write_json(results, metadata, json_file)
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as csv_file:
            write_csv(results, csv_file)
    if args.markdown:
        with args.markdown.open("w", encoding="utf-8") as markdown_file:
            write_markdown(results, markdown_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
