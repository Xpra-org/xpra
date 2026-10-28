#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Generate compact source metric history tables for Git refs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from source_report import (
    DEFAULT_PATHS,
    build_report,
    render_summary_markdown,
    render_summary_text,
    resolve_repo,
    summary_row,
)


CSV_HEADERS = (
    "ref", "branch_date", "files", "sloc", "py_files", "py_sloc", "pyx_files", "pyx_sloc",
    "modules", "codecs", "commits_since_base",
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("refs", nargs="*", help="Git refs to include (legacy: HEAD; evolution: five major branches)")
    parser.add_argument("--repo", default=".", help="Git repository to inspect")
    parser.add_argument("--base", default="", help="Base ref used for branch commit counts")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=list(DEFAULT_PATHS),
        help="Tracked path prefixes to include in file and line totals. Defaults to xpra.",
    )
    parser.add_argument(
        "--fresh-checkout",
        action="store_true",
        help="Analyze each ref from a temporary local clone checkout",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "text", "csv", "json"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument("--evolution", action="store_true", help="Collect versioned evolution metrics instead of the legacy summary")
    parser.add_argument("--sample", choices=("tips", "tags", "monthly", "quarterly"), default="tips")
    parser.add_argument("--since", default="", help="Earliest history sample (ISO date, UTC)")
    parser.add_argument("--until", default="", help="Latest history sample (ISO date, UTC); tips are always included")
    parser.add_argument("--age", action="store_true", help="Include expensive source-line age analysis")
    parser.add_argument("--survival", action="append", default=[], metavar="BASE..END", help="Include a historical survival curve; repeatable")
    parser.add_argument("--cache-dir", default="", help="Reusable analysis cache directory")
    parser.add_argument("--output-dir", default="", help="Write metrics.json, metrics.csv, and report.md")
    args = parser.parse_args(argv)
    if args.evolution and args.fresh_checkout:
        parser.error("--evolution reads committed objects directly; --fresh-checkout is a legacy option")
    if args.evolution and args.base:
        parser.error("--base is a legacy branch-count option; use --survival BASE..END for evolution lifetime analysis")
    if not args.evolution and (args.sample != "tips" or args.age or args.survival or args.output_dir or args.since or args.until or args.cache_dir):
        parser.error("history, lifetime, cache, and output-directory options require --evolution")
    return args


def reports_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    repo = resolve_repo(args.repo)
    return [
        build_report(
            repo=repo,
            ref=ref,
            base=args.base,
            paths=tuple(args.paths),
            fresh_checkout=args.fresh_checkout,
            top_files=0,
        )
        for ref in args.refs or ("HEAD",)
    ]


def print_csv(reports: Sequence[dict[str, Any]]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(CSV_HEADERS)
    writer.writerows(summary_row(report) for report in reports)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if args.evolution:
        from source_metrics import collect_evolution, csv_data, markdown_report, write_data
        try:
            report = collect_evolution(args)
            if args.output_dir:
                write_data(report, Path(args.output_dir))
            if args.format == "json":
                print(json.dumps(report, indent=2, sort_keys=True))
            elif args.format == "csv":
                print(csv_data(report), end="")
            else:
                print(markdown_report(report), end="")
        except (RuntimeError, ValueError, OSError) as e:
            print(f"source evolution: {e}", file=sys.stderr)
            return 1
        return 0
    reports = reports_from_args(args)
    if args.format == "json":
        print(json.dumps(reports, indent=2, sort_keys=True))
    elif args.format == "csv":
        print_csv(reports)
    elif args.format == "text":
        print(render_summary_text(reports))
    else:
        print(render_summary_markdown(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
