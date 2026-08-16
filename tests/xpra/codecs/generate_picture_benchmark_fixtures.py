#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Generate the deterministic corpus used by the picture encoder benchmark."""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "test-images" / "codec-benchmark"


def mix(a: int, b: int, numerator: int, denominator: int) -> int:
    return (a * (denominator - numerator) + b * numerator) // denominator


def pseudo_glyph(char: str) -> tuple[int, ...]:
    """Return a stable 5x7 pseudo-font glyph without relying on system fonts."""
    if char == " ":
        return (0,) * 7
    value = ord(char)
    rows = []
    for y in range(7):
        bits = ((value * 0x45D9F3B + y * 0x9E3779B1) >> (y % 5)) & 0x1F
        if y in (0, 6):
            bits ^= (value >> (y // 6)) & 0x1F
        rows.append(bits or 0x04)
    return tuple(rows)


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
              fill: tuple[int, int, int, int], scale: int = 2) -> None:
    x0, y0 = xy
    x = x0
    for char in text:
        for y, row in enumerate(pseudo_glyph(char.upper())):
            for column in range(5):
                if row & (1 << (4 - column)):
                    left = x + column * scale
                    top = y0 + y * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=fill)
        x += 6 * scale


def code_fixture() -> Image.Image:
    width, height = 640, 360
    image = Image.new("RGBA", (width, height), (31, 34, 40, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, 30), fill=(48, 52, 62, 255))
    draw.rectangle((0, 31, 70, height - 1), fill=(38, 41, 49, 255))
    draw_text(draw, (12, 8), "XPRA CODEC BENCHMARK", (215, 220, 232, 255), 2)
    colors = ((198, 120, 221, 255), (97, 175, 239, 255), (152, 195, 121, 255),
              (229, 192, 123, 255), (224, 108, 117, 255), (171, 178, 191, 255))
    lines = (
        "DEF SELECT ENCODING QUALITY SPEED", "IF CONTENT TYPE SCREEN RETURN WEBP",
        "FOR CODEC IN JPEG AVIF JPH", "SCORE SIZE LATENCY EDGE QUALITY",
        "WINDOW DAMAGE REGION WIDTH HEIGHT", "ASSERT DECODED PIXELS MATCH",
        "RESULT BYTES PER PIXEL PSNR", "# SHARP COLOURED GLYPH EDGES",
    )
    y = 44
    line = 1
    while y < height - 18:
        draw_text(draw, (12, y), f"{line:02d}", (100, 108, 124, 255), 2)
        text = lines[(line - 1) % len(lines)]
        draw_text(draw, (84, y), text, colors[(line - 1) % len(colors)], 2)
        y += 24
        line += 1
    draw.line((70, 31, 70, height - 1), fill=(70, 76, 90, 255))
    return image


def terminal_fixture() -> Image.Image:
    width, height = 640, 360
    image = Image.new("RGBA", (width, height), (8, 11, 13, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, 28), fill=(25, 29, 34, 255))
    draw.ellipse((12, 9, 22, 19), fill=(238, 93, 83, 255))
    draw.ellipse((30, 9, 40, 19), fill=(244, 190, 79, 255))
    draw.ellipse((48, 9, 58, 19), fill=(98, 199, 107, 255))
    draw_text(draw, (230, 7), "TERMINAL", (190, 196, 202, 255), 2)
    prompts = (
        ("USER HOST XPRA $ GIT STATUS", (126, 207, 101, 255)),
        ("M XPRA CODECS WEBP ENCODER", (229, 192, 123, 255)),
        ("M XPRA CODECS AVIF ENCODER", (229, 192, 123, 255)),
        ("RUN PICTURE BENCHMARK QUICK", (97, 175, 239, 255)),
        ("ENCODE JPEG 640 X 360", (198, 120, 221, 255)),
        ("SNR 31 DB EDGE 28 DB", (86, 182, 194, 255)),
        ("WARNING OPTIONAL CODEC SKIPPED", (224, 108, 117, 255)),
    )
    y = 42
    row = 0
    while y < height - 20:
        text, color = prompts[row % len(prompts)]
        draw_text(draw, (14, y), text, color, 2)
        y += 25
        row += 1
    draw.rectangle((14, height - 17, 23, height - 3), fill=(216, 222, 233, 255))
    return image


def browser_fixture() -> Image.Image:
    width, height = 800, 450
    image = Image.new("RGBA", (width, height), (241, 244, 248, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, 38), fill=(49, 54, 63, 255))
    draw.rounded_rectangle((80, 8, 690, 30), radius=10, fill=(232, 235, 240, 255))
    draw_text(draw, (104, 12), "LOCALHOST XPRA METRICS", (65, 71, 82, 255), 2)
    draw.rectangle((24, 62, 210, 426), fill=(255, 255, 255, 255), outline=(205, 211, 220, 255))
    for index, label in enumerate(("OVERVIEW", "QUALITY", "LATENCY", "PAYLOAD", "SETTINGS")):
        top = 80 + index * 54
        if index == 1:
            draw.rounded_rectangle((34, top - 8, 198, top + 25), radius=5, fill=(225, 236, 255, 255))
        draw_text(draw, (48, top), label, (61, 93, 148, 255), 2)
    draw_text(draw, (245, 68), "ENCODER EFFICIENCY", (35, 43, 58, 255), 3)
    cards = ((245, 112, 410, 210, (83, 143, 230, 255)),
             (430, 112, 595, 210, (80, 190, 143, 255)),
             (615, 112, 776, 210, (225, 142, 74, 255)))
    for index, (left, top, right, bottom, color) in enumerate(cards):
        draw.rounded_rectangle((left, top, right, bottom), radius=8,
                               fill=(255, 255, 255, 255), outline=(207, 214, 224, 255))
        draw.rectangle((left, top, right, top + 8), fill=color)
        draw_text(draw, (left + 14, top + 26), ("PSNR", "BYTES", "TIME")[index], color, 2)
        draw_text(draw, (left + 14, top + 58), ("38 DB", "24 KB", "7 MS")[index], (37, 44, 56, 255), 2)
    draw.rounded_rectangle((245, 230, 776, 426), radius=8,
                           fill=(255, 255, 255, 255), outline=(207, 214, 224, 255))
    points = (0, 18, 31, 42, 65, 73, 98, 112, 145, 161, 180)
    graph = []
    for index, point in enumerate(points):
        graph.append((270 + index * 47, 390 - point))
    draw.line(graph, fill=(83, 143, 230, 255), width=4, joint="curve")
    for x, y in graph:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(83, 143, 230, 255))
    return image


def desktop_fixture() -> Image.Image:
    width, height = 800, 450
    image = Image.new("RGBA", (width, height), (44, 94, 132, 255))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (35 + 35 * y // height, 80 + 45 * x // width,
                            125 + 60 * (x + y) // (width + height), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, 25), fill=(24, 28, 34, 255))
    draw_text(draw, (12, 6), "APPLICATIONS", (235, 238, 242, 255), 2)
    draw_text(draw, (655, 6), "12 34 WIFI", (235, 238, 242, 255), 2)
    draw.rounded_rectangle((82, 64, 610, 383), radius=7, fill=(239, 241, 244, 255), outline=(24, 29, 36, 255))
    draw.rectangle((83, 65, 609, 94), fill=(50, 56, 67, 255))
    draw_text(draw, (104, 72), "FILES HOME PROJECTS", (225, 230, 237, 255), 2)
    for row in range(4):
        for column in range(5):
            left = 110 + column * 92
            top = 125 + row * 59
            color = (73 + column * 20, 116 + row * 22, 179 - row * 16, 255)
            draw.rounded_rectangle((left, top, left + 42, top + 35), radius=4, fill=color)
            draw_text(draw, (left - 2, top + 40), f"FILE {row}{column}", (49, 55, 64, 255), 1)
    draw.rounded_rectangle((240, 411, 558, 444), radius=12, fill=(25, 29, 36, 255))
    for index in range(8):
        left = 258 + index * 36
        draw.rounded_rectangle((left, 417, left + 24, 438), radius=4,
                               fill=(80 + index * 16, 155 - index * 8, 205 - index * 10, 255))
    return image


def continuous_fixture() -> Image.Image:
    width, height = 640, 360
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    centers = ((105, 100, 120, (235, 158, 92)), (410, 165, 190, (71, 135, 170)),
               (520, 60, 95, (230, 210, 156)))
    for y in range(height):
        for x in range(width):
            r = 38 + 72 * y // height
            g = 78 + 85 * y // height
            b = 112 + 72 * (height - y) // height
            for cx, cy, radius, color in centers:
                distance = math.isqrt((x - cx) * (x - cx) + (y - cy) * (y - cy))
                if distance < radius:
                    weight = radius - distance
                    r = mix(r, color[0], weight, radius)
                    g = mix(g, color[1], weight, radius)
                    b = mix(b, color[2], weight, radius)
            noise = ((x * 1103515245 + y * 12345 + x * y * 97) >> 12) & 15
            pixels[x, y] = (min(255, r + noise - 7), min(255, g + noise - 7),
                            min(255, b + noise - 7), 255)
    return image


def alpha_fixture() -> Image.Image:
    width = height = 128
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for radius in range(58, 10, -1):
        alpha = 40 + (58 - radius) * 4
        color = (55 + radius * 2, 105 + radius, 225 - radius, min(255, alpha))
        draw.ellipse((64 - radius, 64 - radius, 64 + radius, 64 + radius), fill=color)
    draw.rounded_rectangle((26, 38, 102, 91), radius=9, fill=(245, 248, 252, 220), outline=(25, 47, 79, 255), width=2)
    draw_text(draw, (36, 55), "XPRA", (34, 82, 146, 255), 2)
    return image


GENERATORS = {
    "screen-code.png": code_fixture,
    "screen-terminal.png": terminal_fixture,
    "screen-browser.png": browser_fixture,
    "screen-desktop.png": desktop_fixture,
    "continuous-tone.png": continuous_fixture,
    "alpha-ui.png": alpha_fixture,
}


def check_manifest(output_dir: Path) -> None:
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    filenames = {entry["file"] for entry in manifest["scenarios"]}
    missing = filenames.difference(GENERATORS)
    if missing:
        raise ValueError(f"manifest refers to unknown generated fixtures: {sorted(missing)}")


def generate(output_dir: Path, check: bool) -> int:
    if not check:
        output_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    for filename, make_image in GENERATORS.items():
        expected = make_image()
        path = output_dir / filename
        if check:
            try:
                with Image.open(path) as existing:
                    actual = existing.convert("RGBA")
                if actual.size != expected.size or actual.tobytes() != expected.tobytes():
                    failures.append(filename)
            except OSError:
                failures.append(filename)
        else:
            expected.save(path, format="PNG", compress_level=9)
            print(path)
    if check:
        check_manifest(output_dir)
        if failures:
            print("fixture mismatch: " + ", ".join(failures), file=sys.stderr)
            return 1
        print(f"verified {len(GENERATORS)} picture benchmark fixtures")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--check", action="store_true", help="compare committed fixtures with generated pixels")
    args = parser.parse_args(argv)
    return generate(args.output_dir, args.check)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
