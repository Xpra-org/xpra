#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import argparse
import os
import sys
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from time import monotonic
from typing import Any

# Ensure the source tree's xpra package is importable when running as a script
# (not needed in frozen cx_Freeze builds where modules are bundled)
if not getattr(sys, "frozen", False):
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from PIL import Image, ImageDraw, ImageFont

from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec
from xpra.net import compression
from xpra.util.objects import typedict

N = 10
QUALITYS_LOSSY = (1, 50, 99, 100)
QUALITYS_LOSSLESS = (100,)
SPEED = 100

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    RESAMPLE_LANCZOS = Image.LANCZOS


@dataclass(frozen=True)
class CorpusImage:
    label: str
    width: int
    height: int
    pixel_format: str
    pixels: bytes
    has_alpha: bool

    @property
    def stride(self) -> int:
        return self.width * len(self.pixel_format)


@dataclass(frozen=True)
class BenchmarkResult:
    scenario: str
    label: str
    codec: str
    encoding: str
    quality: int | None
    width: int
    height: int
    mps: float
    ratio: float
    compressed_size: int
    raw_size: int
    extra: str = ""


def load_monospace_font(size: int):
    candidates = (
        "/usr/share/fonts/gnu-free/FreeMono.ttf",
        "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    )
    for font_file in candidates:
        if os.path.exists(font_file):
            try:
                return ImageFont.truetype(font_file, size)
            except OSError:
                pass
    return ImageFont.load_default()


def draw_terminal_scene(base_size=(1024, 768)) -> Image.Image:
    w, h = base_size
    img = Image.new("RGBA", (w, h), (10, 12, 14, 255))
    draw = ImageDraw.Draw(img)
    font = load_monospace_font(max(12, min(w, h) // 32))
    line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + 4

    # Simple terminal-like layout with a status bar and mixed-color text.
    draw.rectangle((0, 0, w - 1, 28), fill=(22, 24, 28, 255))
    draw.text((14, 6), "xpra", font=font, fill=(112, 214, 120, 255))
    draw.text((72, 6), "benchmark corpus", font=font, fill=(210, 210, 210, 255))
    draw.rectangle((0, h - 24, w - 1, h - 1), fill=(22, 24, 28, 255))

    lines = [
        ("antoine@host", "/home/antoine/projects/xpra", "$ python3 -m unittest", (130, 210, 255, 255)),
        ("antoine@host", "/home/antoine/projects/xpra", "$ git status --short", (130, 210, 255, 255)),
        ("", "", "M xpra/codecs/checks.py", (120, 220, 140, 255)),
        ("", "", "M tests/xpra/codecs/benchmark_single_picture_encoders.py", (120, 220, 140, 255)),
        ("", "", "?? docs/images/screenshots/*.png", (255, 210, 120, 255)),
        ("", "", "?? fs/share/xpra/icons/authentication.png", (255, 210, 120, 255)),
        ("", "", "error: transparency preserved", (255, 110, 110, 255)),
        ("", "", "warning: skip only incompatible pairs", (255, 190, 90, 255)),
    ]
    y = 40
    while y + line_h < h - 28:
        for left, middle, right, color in lines:
            if left:
                draw.text((14, y), left, font=font, fill=(90, 180, 255, 255))
                x = 14 + draw.textlength(left, font=font) + 10
                draw.text((x, y), middle, font=font, fill=(220, 220, 220, 255))
                x += draw.textlength(middle, font=font) + 10
                draw.text((x, y), right, font=font, fill=color)
            else:
                draw.text((14, y), right, font=font, fill=color)
            y += line_h
            if y + line_h >= h - 28:
                break
        if y + line_h >= h - 28:
            break
    # Add a few bright blocks so tiny resizes still have text-like structure.
    for x in range(0, w, max(24, w // 24)):
        draw.line((x, 32, x, h - 28), fill=(30, 34, 40, 255), width=1)
    return img


def rgba_to_pixel_bytes(rgba: Image.Image, pixel_format: str) -> bytes:
    raw = rgba.tobytes()
    if pixel_format == "RGB":
        out = bytearray((len(raw) // 4) * 3)
        dst = 0
        for src in range(0, len(raw), 4):
            out[dst:dst + 3] = raw[src:src + 3]
            dst += 3
        return bytes(out)
    if pixel_format == "RGBX":
        out = bytearray(len(raw))
        dst = 0
        for src in range(0, len(raw), 4):
            out[dst:dst + 4] = raw[src:src + 3] + b"\xff"
            dst += 4
        return bytes(out)
    if pixel_format == "BGRA":
        out = bytearray(len(raw))
        dst = 0
        for src in range(0, len(raw), 4):
            out[dst:dst + 4] = bytes((raw[src + 2], raw[src + 1], raw[src], raw[src + 3]))
            dst += 4
        return bytes(out)
    raise ValueError(f"unsupported pixel format {pixel_format!r}")


def make_text_image(width: int, height: int) -> Image.Image:
    base = draw_terminal_scene()
    return base.resize((width, height), RESAMPLE_LANCZOS)


def load_corpus() -> list[CorpusImage]:
    repo_root = Path(__file__).resolve().parents[3]

    for size in ((499, 316), (13, 6), (250, 12)):
        label = f"xterm:{size[0]}x{size[1]}"
        img = make_text_image(*size)
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A").getextrema()
        has_alpha = alpha != (255, 255)
        pixel_format = "BGRA" if has_alpha else "RGB"
        pixels = rgba_to_pixel_bytes(rgba, pixel_format)
        yield CorpusImage(label, size[0], size[1], pixel_format, pixels, has_alpha)

    corpus_paths = [
        repo_root / "fs/share/icons/xpra.png",
        repo_root / "fs/share/xpra/icons/authentication.png",
    ]
    corpus_paths.extend(Path(p) for p in glob(str(repo_root / "docs/images/screenshots/*.png")))
    corpus_paths.extend(Path(p) for p in glob(str(repo_root / "docs/images/*.png")))
    for path in sorted({p.resolve() for p in corpus_paths}):
        if not path.exists():
            continue
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
        alpha = rgba.getchannel("A").getextrema()
        has_alpha = alpha != (255, 255)
        pixel_format = "BGRA" if has_alpha else "RGB"
        pixels = rgba_to_pixel_bytes(rgba, pixel_format)
        rel = path.relative_to(repo_root)
        yield CorpusImage(str(rel), rgba.width, rgba.height, pixel_format, pixels, has_alpha)


def scenario_for(spec: CorpusImage) -> str:
    if spec.label.startswith("xterm:"):
        return "text"
    if spec.label.startswith("fs/share/"):
        return "icons-alpha" if spec.has_alpha else "icons"
    if spec.label.startswith("docs/images/screenshots/"):
        return "screenshots"
    if spec.label.startswith("docs/images/"):
        return "docs-images"
    return "other"


def make_image(spec: CorpusImage) -> ImageWrapper:
    return ImageWrapper(
        0, 0, spec.width, spec.height,
        spec.pixels, spec.pixel_format, len(spec.pixel_format) * 8, spec.stride,
        planes=ImageWrapper.PACKED, thread_safe=True,
    )


def packet_bytes(data: Any) -> bytes:
    if data is None:
        return b""
    payload = getattr(data, "data", data)
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, memoryview):
        return payload.tobytes()
    return bytes(payload)


def benchmark_rgb_lz4(spec: CorpusImage) -> tuple[int, float, int]:
    try:
        compressor = compression.get_compressor("lz4")
    except Exception as e:
        raise RuntimeError(f"lz4 compressor is unavailable: {e}") from e
    raw = spec.pixels
    size = len(raw)
    start = monotonic()
    compressed_size = 0
    for _ in range(N):
        _level, cdata = compressor(raw, 1)
        compressed_size = len(cdata)
    end = monotonic()
    return compressed_size, end - start, size


def benchmark_encoder(module, encoding: str, spec: CorpusImage, options: dict[str, Any]) -> tuple[int, float, int, dict[str, Any]]:
    image = make_image(spec)
    size = len(spec.pixels)
    client_options: dict[str, Any] = {}
    compressed_size = 0
    start = monotonic()
    for _ in range(N):
        result = module.encode(encoding, image, typedict(options))
        if not result:
            raise RuntimeError(f"{module}.{encoding} returned no data for {spec.label}")
        cdata = result[1]
        client_options = result[2]
        compressed_size = len(packet_bytes(cdata))
    end = monotonic()
    return compressed_size, end - start, size, client_options


def print_result(label: str, codec: str, encoding: str, spec: CorpusImage, compressed_size: int, duration: float, raw_size: int,
                 quality: int | None = None, extra: str = "") -> None:
    mps = (spec.width * spec.height * N) / duration / 1024 / 1024 if duration > 0 else 0.0
    ratio = 100.0 * compressed_size / raw_size if raw_size else 0.0
    qstr = "-" if quality is None else str(quality)
    suffix = f"  {extra}" if extra else ""
    print(f"{label:28} {codec:10} {encoding:10} q={qstr:>3} {spec.width:5}x{spec.height:<5} {mps:9.1f} MPixels/s  {compressed_size:8} B  {ratio:6.2f}%{suffix}")


def family_key(result: BenchmarkResult) -> tuple[str, str]:
    return result.codec, result.encoding


def best_rows_by_family(rows: list[BenchmarkResult], metric) -> list[BenchmarkResult]:
    best: dict[tuple[str, str], BenchmarkResult] = {}
    for row in rows:
        key = family_key(row)
        current = best.get(key)
        if current is None or metric(row) < metric(current):
            best[key] = row
    return list(best.values())


def print_summary(results: list[BenchmarkResult], title: str, predicate) -> None:
    if not results:
        return
    print(f"\n{title}")
    scenarios = sorted({r.scenario for r in results})
    for scenario in scenarios:
        rows = [r for r in results if r.scenario == scenario and predicate(r)]
        if not rows:
            continue
        print(f"\n{scenario}")
        print("  best size")
        size_rows = best_rows_by_family(rows, lambda x: (x.ratio, -x.mps, x.quality or -1))
        for r in sorted(size_rows, key=lambda x: (x.ratio, -x.mps, x.codec, x.encoding, x.quality or -1))[:5]:
            q = "-" if r.quality is None else str(r.quality)
            print(f"    {r.codec:10} {r.encoding:10} q={q:>3}  {r.ratio:6.2f}%  {r.mps:9.1f} MPixels/s")
        print("  best speed")
        speed_rows = best_rows_by_family(rows, lambda x: (-x.mps, x.ratio, x.quality or -1))
        for r in sorted(speed_rows, key=lambda x: (-x.mps, x.ratio, x.codec, x.encoding, x.quality or -1))[:5]:
            q = "-" if r.quality is None else str(r.quality)
            print(f"    {r.codec:10} {r.encoding:10} q={q:>3}  {r.mps:9.1f} MPixels/s  {r.ratio:6.2f}%")

    print()


def is_practical_high_quality(result: BenchmarkResult) -> bool:
    return result.quality is None or result.quality >= 99


def is_low_quality(result: BenchmarkResult) -> bool:
    return result.scenario != "text" and result.quality is not None and result.quality <= 50


def qualities_for(scenario: str, codec_name: str, encoding: str) -> tuple[int, ...]:
    if scenario == "text":
        return QUALITYS_LOSSLESS
    if codec_name == "pillow" and encoding in ("png", "png/L", "png/P"):
        return QUALITYS_LOSSLESS
    return QUALITYS_LOSSY


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Benchmark single picture encoders on a mixed image corpus.")
    parser.add_argument("--limit", type=int, default=0, help="limit the number of corpus images processed")
    args = parser.parse_args(argv)

    compression.init_all()

    codec_specs = [
        ("rgb+lz4", None),
        ("pillow", load_codec("enc_pillow")),
        ("webp", load_codec("enc_webp")),
        ("jpeg", load_codec("enc_jpeg")),
        ("avif", load_codec("enc_avif")),
        ("jph", load_codec("enc_jph")),
    ]

    corpus = list(load_corpus())
    if args.limit > 0:
        corpus = corpus[:args.limit]

    if not corpus:
        raise RuntimeError("no benchmark images were discovered")

    results: list[BenchmarkResult] = []
    for spec in corpus:
        scenario = scenario_for(spec)
        alpha = "alpha" if spec.has_alpha else "opaque"
        print(f"\n{spec.label}  {spec.width}x{spec.height}  {alpha}  {spec.pixel_format}")
        for codec_name, module in codec_specs:
            if codec_name == "rgb+lz4":
                try:
                    compressed_size, duration, raw_size = benchmark_rgb_lz4(spec)
                except Exception as e:
                    print(f"{codec_name:10} skipped: {e}")
                    continue
                mps = (spec.width * spec.height * N) / duration / 1024 / 1024 if duration > 0 else 0.0
                ratio = 100.0 * compressed_size / raw_size if raw_size else 0.0
                print_result(spec.label, codec_name, "lz4", spec, compressed_size, duration, raw_size, quality=None)
                results.append(BenchmarkResult(scenario, spec.label, codec_name, "lz4", None, spec.width, spec.height, mps, ratio, compressed_size, raw_size))
                continue

            if not module:
                print(f"{codec_name:10} skipped: codec unavailable")
                continue

            encodings = tuple(module.get_encodings())
            for encoding in encodings:
                for quality in qualities_for(scenario, codec_name, encoding):
                    try:
                        compressed_size, duration, raw_size, client_options = benchmark_encoder(
                            module, encoding, spec, {
                                "quality": quality,
                                "speed": SPEED,
                                "alpha": True,
                            },
                        )
                    except Exception as e:
                        print(f"{codec_name:10} {encoding:10} q={quality:<3} skipped: {e}")
                        continue
                    extra = ""
                    if client_options:
                        extra = str(client_options)
                    print_result(spec.label, codec_name, encoding, spec, compressed_size, duration, raw_size, quality=quality, extra=extra)
                    mps = (spec.width * spec.height * N) / duration / 1024 / 1024 if duration > 0 else 0.0
                    ratio = 100.0 * compressed_size / raw_size if raw_size else 0.0
                    results.append(BenchmarkResult(scenario, spec.label, codec_name, encoding, quality, spec.width, spec.height, mps, ratio, compressed_size, raw_size, extra=extra))
    print_summary(results, "Summary: practical quality (q>=99)", is_practical_high_quality)
    print_summary(results, "Summary: low quality (q<=50)", is_low_quality)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
