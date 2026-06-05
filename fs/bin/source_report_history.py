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
    parser.add_argument("refs", nargs="*", default=("HEAD",), help="Git refs to include")
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
    return parser.parse_args(argv)


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
        for ref in args.refs
    ]


def print_csv(reports: Sequence[dict[str, Any]]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(CSV_HEADERS)
    writer.writerows(summary_row(report) for report in reports)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
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
