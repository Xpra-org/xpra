#!/usr/bin/env python3
"""Format an Xpra Markdown changelog entry for package changelogs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


HEADING_RE = re.compile(r"^## \[([^\]]+)\] ([0-9]{4}-[0-9]{2}-[0-9]{2})$", re.M)
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def find_section(text: str, version: str | None) -> tuple[str, str, str]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        raise SystemExit("no release headings found")
    for index, match in enumerate(matches):
        release_version = match.group(1)
        if version is not None and release_version != version:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return release_version, match.group(2), text[start:end].strip("\n")
    raise SystemExit(f"release {version!r} not found")


def strip_links(line: str) -> str:
    return LINK_RE.sub(r"\1", line)


def format_section(section: str, output_format: str) -> str:
    lines: list[str] = []
    for raw_line in section.splitlines():
        line = strip_links(raw_line.rstrip())
        if line.startswith("* "):
            text = line[2:]
            prefix = "- " if output_format == "rpm" else "  * "
            lines.append(f"{prefix}{text}")
        elif line.startswith("    * "):
            text = line[6:]
            prefix = "   " if output_format == "rpm" else "    "
            lines.append(f"{prefix}{text}")
        elif not line:
            continue
        else:
            lines.append(line)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("changelog", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--format", choices=("rpm", "debian"), required=True)
    args = parser.parse_args()

    text = args.changelog.read_text(encoding="utf-8")
    _, _, section = find_section(text, args.version)
    print(format_section(section, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
