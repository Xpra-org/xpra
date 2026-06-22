#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Plot video encoder benchmark JSON as dependency-free SVG charts."""

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from html import escape
from pathlib import Path


METRICS = {
    "encode_ms": "Encode latency (ms)",
    "roundtrip_ms": "Round-trip latency (ms)",
    "csc_ms": "CSC latency (ms)",
}
WIDTH = 1400
HEIGHT = 680
PLOT_LEFT = 85
PLOT_TOP = 55
PLOT_RIGHT = 760
PLOT_BOTTOM = 610
ENCODER_HUES = (210, 15, 130, 280, 45, 335, 175, 75, 245, 105)
DASHES = ("", "8 4", "2 3", "10 3 2 3")


def load_results(filename: Path) -> list[dict]:
    with filename.open(encoding="utf-8") as input_file:
        document = json.load(input_file)
    if document.get("schema_version") != 1 or not isinstance(document.get("results"), list):
        raise ValueError(f"{filename} is not a video benchmark JSON document")
    return document["results"]


def color(encoder_index: int, quality: int) -> str:
    """Keep one hue per encoder and darken it as quality increases."""
    hue = ENCODER_HUES[encoder_index % len(ENCODER_HUES)]
    lightness = 84 - round(max(0, min(100, quality)) * 0.46)
    return f"hsl({hue} 72% {lightness}%)"


def finite_rows(rows: list[dict], metric: str) -> list[dict]:
    valid = []
    for row in rows:
        try:
            speed = float(row["speed"])
            value = float(row[metric])
            quality = int(row["quality"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(speed) and math.isfinite(value):
            valid.append(row | {"speed": speed, metric: value, "quality": quality})
    return valid


def tick_value(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def render_svg(encoding: str, rows: list[dict], metric: str) -> str:
    rows = finite_rows(rows, metric)
    if not rows:
        raise ValueError(f"no finite {metric} values for {encoding}")
    encoders = sorted({str(row["encoder"]) for row in rows})
    encoder_index = {encoder: index for index, encoder in enumerate(encoders)}
    pipelines_by_encoder = {
        encoder: sorted({str(row.get("pipeline", "")) for row in rows if row["encoder"] == encoder})
        for encoder in encoders
    }
    pipeline_index = {
        (encoder, pipeline): index
        for encoder, pipelines in pipelines_by_encoder.items()
        for index, pipeline in enumerate(pipelines)
    }
    series = defaultdict(list)
    for row in rows:
        key = str(row["encoder"]), str(row.get("pipeline", "")), int(row["quality"])
        series[key].append(row)
    canvas_height = max(HEIGHT, 115 + 20 * len(series))

    x_min = min(0.0, min(row["speed"] for row in rows))
    x_max = max(100.0, max(row["speed"] for row in rows))
    y_max = max(row[metric] for row in rows)
    y_max = max(0.001, y_max * 1.1)
    plot_width = PLOT_RIGHT - PLOT_LEFT
    plot_height = PLOT_BOTTOM - PLOT_TOP

    def sx(value: float) -> float:
        return PLOT_LEFT + (value - x_min) / (x_max - x_min) * plot_width

    def sy(value: float) -> float:
        return PLOT_BOTTOM - value / y_max * plot_height

    title = f"{encoding}: speed setting vs {METRICS[metric].lower()}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{canvas_height}" '
        f'viewBox="0 0 {WIDTH} {canvas_height}" role="img">',
        "<style>",
        "text { font-family: sans-serif; fill: #222; }",
        ".title { font-size: 22px; font-weight: bold; }",
        ".axis-label { font-size: 15px; font-weight: bold; }",
        ".tick, .legend { font-size: 12px; }",
        ".grid { stroke: #ddd; stroke-width: 1; }",
        ".axis { stroke: #333; stroke-width: 1.5; }",
        "</style>",
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text class="title" x="{PLOT_LEFT}" y="30">{escape(title)}</text>',
    ]

    for tick in range(0, 101, 20):
        x = sx(tick)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{PLOT_TOP}" x2="{x:.1f}" y2="{PLOT_BOTTOM}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{PLOT_BOTTOM + 20}" text-anchor="middle">{tick}</text>')
    for index in range(6):
        value = y_max * index / 5
        y = sy(value)
        parts.append(f'<line class="grid" x1="{PLOT_LEFT}" y1="{y:.1f}" x2="{PLOT_RIGHT}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{PLOT_LEFT - 10}" y="{y + 4:.1f}" text-anchor="end">{tick_value(value)}</text>')
    parts.extend((
        f'<line class="axis" x1="{PLOT_LEFT}" y1="{PLOT_BOTTOM}" x2="{PLOT_RIGHT}" y2="{PLOT_BOTTOM}"/>',
        f'<line class="axis" x1="{PLOT_LEFT}" y1="{PLOT_TOP}" x2="{PLOT_LEFT}" y2="{PLOT_BOTTOM}"/>',
        f'<text class="axis-label" x="{(PLOT_LEFT + PLOT_RIGHT) / 2:.1f}" y="{HEIGHT - 25}" '
        'text-anchor="middle">Speed setting</text>',
        f'<text class="axis-label" transform="translate(22 {(PLOT_TOP + PLOT_BOTTOM) / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle">{escape(METRICS[metric])}</text>',
        '<text class="axis-label" x="800" y="62">Encoder / quality</text>',
    ))

    legend_y = 88
    for encoder, pipeline, quality in sorted(series):
        points = sorted(series[(encoder, pipeline, quality)], key=lambda row: row["speed"])
        shade = color(encoder_index[encoder], quality)
        dash = DASHES[pipeline_index[(encoder, pipeline)] % len(DASHES)]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        coords = " ".join(f'{sx(row["speed"]):.1f},{sy(row[metric]):.1f}' for row in points)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{shade}" stroke-width="3"{dash_attr}/>')
        for row in points:
            parts.append(f'<circle cx="{sx(row["speed"]):.1f}" cy="{sy(row[metric]):.1f}" r="4" '
                         f'fill="{shade}" stroke="white" stroke-width="1"/>')
        parts.append(f'<line x1="800" y1="{legend_y - 4}" x2="832" y2="{legend_y - 4}" '
                     f'stroke="{shade}" stroke-width="3"{dash_attr}/>')
        label = f"{encoder}, q={quality}"
        if len(pipelines_by_encoder[encoder]) > 1:
            label += f", {pipeline}"
        parts.append(f'<text class="legend" x="840" y="{legend_y}">{escape(label)}</text>')
        legend_y += 20
    parts.append("</svg>\n")
    return "\n".join(parts)


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "encoding"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON produced by benchmark_video_encoders.py")
    parser.add_argument("--output-dir", type=Path, default=Path("codec-graphs"))
    parser.add_argument("--metric", choices=tuple(METRICS), default="encode_ms",
                        help="latency value to plot (default: encode_ms)")
    parser.add_argument("--encodings", default="", help="comma-separated encoding filter")
    args = parser.parse_args(argv)
    try:
        results = load_results(args.input)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        parser.error(str(e))
    selected = {value for value in args.encodings.split(",") if value}
    by_encoding = defaultdict(list)
    for row in results:
        encoding = str(row.get("encoding", ""))
        if encoding and (not selected or encoding in selected):
            by_encoding[encoding].append(row)
    if not by_encoding:
        print("no matching encoding results found", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for encoding, rows in sorted(by_encoding.items()):
        try:
            svg = render_svg(encoding, rows, args.metric)
        except ValueError as e:
            print(f"skip {encoding}: {e}", file=sys.stderr)
            continue
        output = args.output_dir / f"{safe_filename(encoding)}-{args.metric}.svg"
        output.write_text(svg, encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
