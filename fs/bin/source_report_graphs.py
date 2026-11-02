#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Render a saved evolution JSON report as SVG/PNG graphs and Markdown."""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from source_metrics import GROUPS, markdown_report, write_data


def render(report: dict, directory: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    snapshots = {s["commit"]: s for s in report["snapshots"]}
    tips = [snapshots[s["tip"]] for s in report["series"]]
    labels = [s["ref"] for s in report["series"]]
    colors = {"python": "#377eb8", "cython": "#ff7f00", "native": "#4daf4a"}
    graphs = []
    directory.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        fig.tight_layout()
        for extension in ("svg", "png"):
            fig.savefig(directory / f"{name}.{extension}", dpi=160, bbox_inches="tight")
        plt.close(fig)
        graphs.append(name)

    def number(value):
        return float("nan") if value is None else value

    def bars(ax, series, ylabel, title):
        width = .8 / len(series)
        for i, (name, values) in enumerate(series.items()):
            xs = [x - .4 + width / 2 + i * width for x in range(len(labels))]
            ax.bar(xs, [number(v) for v in values], width, label=name, color=colors.get(name))
            for x, value in zip(xs, values):
                if value is None:
                    ax.text(x, 0, "N/A", rotation=90, ha="center", va="bottom", fontsize=8)
        ax.set_xticks(range(len(labels)), labels)
        ax.set_xlim(-.5, len(labels) - .5)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.25)
        ax.legend()

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, key, ylabel in zip(axes, ("kloc", "files"), ("Estimated SLOC / 1,000", "Source files")):
        bars(ax, {g: [s["groups"][g][key] for s in tips] for g in GROUPS}, ylabel, "Branch tips")
    save(fig, "source-size")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    bars(axes[0], {"loader identities": [s["codecs"]["count"] for s in tips]}, "Implementations", "Codecs")
    bars(axes[1], {side: [s["subsystems"][side]["count"] for s in tips] for side in ("client", "server")},
         "Implementation modules", "Structural subsystems / mixins")
    save(fig, "capabilities")

    if any(len(series["commits"]) > 1 for series in report["series"]):
        fig, axes = plt.subplots(2, 2, figsize=(13, 8))
        for series in report["series"]:
            samples = [snapshots[c] for c in series["commits"]]
            dates = [datetime.fromisoformat(s["commit_date"]) for s in samples]
            values = ([sum(s["groups"][g]["kloc"] for g in GROUPS) for s in samples],
                      [sum(s["groups"][g]["files"] for g in GROUPS) for s in samples],
                      [number(s["codecs"]["count"]) for s in samples],
                      [number(s["coupling"]["cbo"]["median"]) for s in samples])
            for ax, ys in zip(axes.flat, values):
                ax.plot(dates, ys, marker=".", label=series["ref"])
        for ax, title in zip(axes.flat, ("Estimated KLOC", "Source files", "Codec implementations", "Static CBO median")):
            ax.set_title(title)
            ax.grid(alpha=.25)
            ax.legend(fontsize=8)
            ax.tick_params(axis="x", rotation=30)
        save(fig, "history")

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    for ax, key, title in zip(axes, ("files", "functions", "cbo"), ("File SLOC", "Function physical lines", "Static CBO")):
        series = {stat: [s["coupling"]["cbo"][stat] if key == "cbo" else s["sizes"][key][stat] for s in tips]
                  for stat in ("median", "p90", "max")}
        bars(ax, series, title, title + " distribution")
        if any(v and v > 0 for values in series.values() for v in values):
            ax.set_yscale("symlog", linthresh=1)
    save(fig, "distributions")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ax, kind in zip(axes, ("fan_in", "fan_out")):
        bars(ax, {stat: [s["coupling"][kind][stat] for s in tips] for stat in ("median", "p90", "max")},
             "Internal Python modules", kind.replace("_", " "))
    save(fig, "module-coupling")

    fig, axes = plt.subplots(len(tips), 1, figsize=(12, max(3, 2.8 * len(tips))), squeeze=False)
    for ax, label, snap in zip(axes.flat, labels, tips):
        rows = list(reversed(snap["churn"]["files"][:8]))
        names = [row["path"] for row in rows]
        additions = [row["additions"] for row in rows]
        deletions = [row["deletions"] for row in rows]
        ax.barh(names, additions, label="Added", color="#4daf4a")
        ax.barh(names, deletions, left=additions, label="Deleted", color="#e41a1c")
        ax.set_title(label + " — preceding 365 days (non-merge commits)")
        ax.set_xlabel("Changed source lines")
        ax.tick_params(axis="y", labelsize=8)
        ax.legend(fontsize=8)
    save(fig, "hotspots")

    if any("age" in s for s in tips):
        fig, ax = plt.subplots(figsize=(10, 5))
        bottom = [0.] * len(tips)
        bands = ("<1 year", "1–3 years", "3–5 years", "5–10 years", "10+ years")
        for band in bands:
            values = []
            for s in tips:
                age = s.get("age", {})
                values.append(age.get("bands", {}).get(band, 0) / age["count"] * 100 if age.get("count") else math.nan)
            ax.bar(labels, values, bottom=bottom, label=band)
            bottom = [a + b for a, b in zip(bottom, values)]
        ax.set_ylabel("% of analyzed source lines")
        ax.set_title("Age of surviving code (see coverage in report)")
        ax.legend()
        save(fig, "line-age")

    if report["survival"]:
        fig, ax = plt.subplots(figsize=(10, 5))
        for item in report["survival"]:
            points = item["points"]
            if points:
                ax.step([p["days"] / 365.25 for p in points], [100 * p["fraction"] for p in points],
                        where="post", label=item["label"] + " (" + item["status"] + ")")
        ax.axhline(50, color="gray", linestyle="--", linewidth=1)
        ax.set(xlabel="Years since baseline", ylabel="Surviving baseline source lines (%)", ylim=(0, 105), title="Historical code survival")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=8)
        save(fig, "survival")

    write_data(report, directory)
    (directory / "report.md").write_text(markdown_report(report, graphs))
    return graphs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Saved metrics.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.input.read_text())
        if report.get("schema_version") != 1 or not report.get("series"):
            raise ValueError("Expected a schema-version 1 evolution report with at least one series")
        render(report, args.output_dir)
    except (ImportError, OSError, ValueError, KeyError) as e:
        print(f"source graphs: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
