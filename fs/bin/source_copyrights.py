#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Generate the copyrights table for docs/Build/Source.md."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from source_report import (
    DEFAULT_PATHS,
    git_report,
    is_source_path,
    markdown_table,
    path_matches,
    resolve_default_paths,
    resolve_repo,
    source_for,
)


COPYRIGHT_RE = re.compile(
    r"^\s*(?:[#/*]+\s*)?copyright\s*(?:\([c]\))?\s*"
    r"(?:[-:;,]\s*)?"
    r"(?:(?:\d{4}(?:-\d{4})?)(?:\s*,\s*\d{4}(?:-\d{4})?)*)?\s*(.+?)\s*$",
    re.IGNORECASE,
)
SKIP_HOLDER_PREFIXES = (
    "the above copyright",
    "redistributions of source code",
    "redistributions in binary form",
    "this software is based",
    "permission is hereby granted",
    "notice, this list of conditions",
)
MAX_HEADER_LINES = 80


def normalize_holder(holder: str) -> str:
    holder = holder.strip()
    holder = holder.lstrip("-:;,. \t")
    holder = holder.rstrip("*/ \t.;,")
    if holder.lower().startswith("by "):
        holder = holder[3:].strip()
    holder = re.sub(r"^(?:\d{4}(?:-\d{4})?\s+)+", "", holder)
    holder = re.sub(r"\s+", " ", holder)
    return holder


def extract_holders(data: bytes) -> set[str]:
    holders = set()
    text = data.decode("utf-8", "replace")
    for line in text.splitlines()[:MAX_HEADER_LINES]:
        match = COPYRIGHT_RE.match(line)
        if not match:
            continue
        holder = normalize_holder(match.group(1))
        lowered = holder.lower()
        if not holder or lowered.startswith(SKIP_HOLDER_PREFIXES):
            continue
        holders.add(holder)
    return holders


def build_report(
    repo_path: str,
    ref: str = "HEAD",
    paths: Sequence[str] = DEFAULT_PATHS,
    worktree: bool = False,
    fresh_checkout: bool = False,
) -> dict[str, Any]:
    repo = resolve_repo(repo_path)
    source = source_for(repo, ref, worktree=worktree, fresh_checkout=fresh_checkout)
    try:
        files = source.list_files()
        resolved_paths = resolve_default_paths(files, paths)
        source_files = [
            path for path in files
            if path_matches(path, resolved_paths) and is_source_path(path, resolved_paths)
        ]
        counts: Counter[str] = Counter()
        holder_files: dict[str, set[str]] = defaultdict(set)
        missing = []
        for path in source_files:
            try:
                holders = extract_holders(source.read_file(path))
            except Exception as e:
                missing.append({"path": path, "error": str(e)})
                continue
            for holder in holders:
                counts[holder] += 1
                holder_files[holder].add(path)
        git_info = git_report(source.repo, "HEAD" if fresh_checkout else ref)
        if fresh_checkout:
            git_info["ref"] = ref
            git_info["requested_ref"] = ref
        holders = sorted(counts.items(), key=lambda item: (item[0].lower(), item[0]))
        return {
            "repo": str(repo),
            "paths": resolved_paths,
            "source_mode": source.label,
            "git": git_info,
            "tracked_source_files": len(source_files),
            "holders": [
                {
                    "holder": holder,
                    "file_count": count,
                    "files": sorted(holder_files[holder]),
                }
                for holder, count in holders
            ],
            "read_errors": missing,
        }
    finally:
        source.close()


def markdown_link(path: str) -> str:
    return f"[{path}]({path})"


def holder_rows(report: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows = []
    for item in report["holders"]:
        files = ""
        if item["file_count"] < 3:
            files = ", ".join(markdown_link(path) for path in item["files"])
        rows.append((item["holder"], item["file_count"], files))
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    return markdown_table(("Holder", "File Count", "Files"), holder_rows(report))


def render_text(report: dict[str, Any]) -> str:
    rows = holder_rows(report)
    holder_width = max([len("Holder"), *(len(holder) for holder, _, _ in rows)], default=len("Holder"))
    count_width = max([len("File Count"), *(len(f"{count:,}") for _, count, _ in rows)], default=len("File Count"))
    files_width = max([len("Files"), *(len(files) for _, _, files in rows)], default=len("Files"))
    lines = [
        f"{'Holder'.ljust(holder_width)}  {'File Count'.rjust(count_width)}  {'Files'.ljust(files_width)}",
        f"{'-' * holder_width}  {'-' * count_width}  {'-' * files_width}",
    ]
    for holder, count, files in rows:
        lines.append(f"{holder.ljust(holder_width)}  {f'{count:,}'.rjust(count_width)}  {files.ljust(files_width)}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Git repository to inspect")
    parser.add_argument("--ref", default="HEAD", help="Git ref to inspect")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=list(DEFAULT_PATHS),
        help="Tracked path prefixes to include. Defaults to xpra or src/xpra.",
    )
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="Read tracked files from the current worktree instead of the committed Git tree",
    )
    parser.add_argument(
        "--fresh-checkout",
        action="store_true",
        help="Analyze the ref from a temporary local clone checkout",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "text", "json"),
        default="markdown",
        help="Output format",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    report = build_report(
        repo_path=args.repo,
        ref=args.ref,
        paths=tuple(args.paths),
        worktree=args.worktree,
        fresh_checkout=args.fresh_checkout,
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.format == "text":
        print(render_text(report))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
