#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Summarize grype JSON reports as markdown,
# using `docs/Build/CVE.md` to tell which vulnerabilities are new and which ones have been switched off,
# and to skip the packages listed in its ignored packages table:
# python3 sbom_vulnerabilities.py --scan 6.5.5-r0 grype.json [--scan 7.0-r42750 grype-beta.json] [--update]
# Use `--variant-scan VARIANT XPRA_VERSION GRYPE_JSON` to report variants in order,
# listing each vulnerability only in the first variant which contains it.
# `--update` adds the new vulnerabilities to `docs/Build/CVE.md`.
# The number of new vulnerabilities is written to `$GITHUB_OUTPUT` as `new`.

import os
import re
import sys
import argparse

CVE_DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "Build", "CVE.md")

CVE_DOC_URL = "https://xpra-org.github.io/xpra/Build/CVE.html"

SEVERITIES = ("Critical", "High", "Medium", "Low", "Negligible", "Unknown")

# "on" stands out in the rendered table, "off" is the exception:
LIVE_ON = "🔴 on"
LIVE_OFF = "off"

COLUMNS = ("CVE", "Package", "Severity", "Issue", "Upstream fix", "Live", "First xpra version", "Fixed in xpra", "Ticket", "Notes")


def load_matches(filename: str) -> dict[str, dict]:
    import json
    with open(filename) as f:
        report = json.load(f)
    matches: dict[str, dict] = {}
    for match in report.get("matches", ()):
        artifact = match["artifact"]
        vuln = match["vulnerability"]
        # prefer the CVE id over the GHSA id:
        vuln_id = vuln["id"]
        for related in match.get("relatedVulnerabilities", ()):
            if related["id"].startswith("CVE-") and not vuln_id.startswith("CVE-"):
                vuln_id = related["id"]
        m = matches.setdefault(vuln_id, {
            "id": vuln_id,
            "packages": {},
            "severity": vuln.get("severity", "Unknown"),
            "description": vuln.get("description", ""),
            "fixed": "",
        })
        m["packages"][artifact["name"]] = artifact["version"]
        if not m["description"]:
            m["description"] = vuln.get("description", "")
        if not m["fixed"]:
            m["fixed"] = get_fix_version(artifact["version"], vuln.get("fix", {}).get("versions", ()))
    return matches


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version))


def get_fix_version(installed: str, versions: list[str]) -> str:
    # the fix versions cover every upstream branch, ie: "8.14.3", "8.16.2", "8.20.2", "8.23.0"
    # use the first one after the version we ship:
    newer = sorted((v for v in versions if version_key(v) > version_key(installed)), key=version_key)
    return newer[0] if newer else ", ".join(versions)


def cve_key(cve: str) -> tuple:
    # numerical order: "CVE-2026-1584" before "CVE-2026-12891", other identifiers last:
    m = re.match(r"CVE-(\d+)-(\d+)$", cve)
    if m:
        return 0, int(m.group(1)), int(m.group(2)), ""
    return 1, 0, 0, cve


def escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def summarize(description: str, limit: int = 160) -> str:
    # the first sentences, enough to skip "A flaw was found in gnutls.", at most `limit` characters:
    sentences = re.split(r"(?<=\.)\s+(?=[A-Z])", " ".join(description.split()))
    text = ""
    for sentence in sentences:
        text = f"{text} {sentence}".strip()
        if len(text) >= 80:
            break
    if len(text) > limit:
        text = text[:limit - 3].rsplit(" ", 1)[0] + "..."
    return escape(text)


def split_row(line: str) -> list[str]:
    # split on unescaped pipes, ignoring the leading and trailing ones:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [cell.strip() for cell in cells[1:-1]]


def load_doc(filename: str) -> tuple[list[str], list[str], dict[str, dict[str, str]]]:
    """
    returns the lines before the table, the lines after it, and the table rows indexed by vulnerability id
    """
    with open(filename) as f:
        lines = f.read().splitlines()
    header = next(i for i, line in enumerate(lines) if split_row(line)[:1] == ["CVE"])
    columns = split_row(lines[header])
    end = header + 2
    rows: dict[str, dict[str, str]] = {}
    while end < len(lines) and lines[end].startswith("|"):
        cells = split_row(lines[end])
        row = dict(zip(columns, cells))
        rows[row["CVE"]] = row
        end += 1
    return lines[:header], lines[end:], rows


def load_ignored(lines: list[str]) -> set[str]:
    """
    the packages listed in the `| Package | Reason |` table
    """
    ignored: set[str] = set()
    in_table = False
    for line in lines:
        if not line.startswith("|"):
            in_table = False
            continue
        cells = split_row(line)
        if cells[:2] == ["Package", "Reason"]:
            in_table = True
        elif in_table and cells and not cells[0].startswith("---"):
            ignored.add(cells[0].strip("`"))
    return ignored


def format_row(row: dict[str, str]) -> str:
    return "| " + " | ".join(row.get(column, "") for column in COLUMNS) + " |"


def save_doc(filename: str, before: list[str], after: list[str], rows: dict[str, dict[str, str]]) -> None:
    lines = list(before)
    lines.append(format_row({column: column for column in COLUMNS}))
    lines.append("|" + "|".join("---" for _ in COLUMNS) + "|")
    for cve in sorted(rows, key=cve_key):
        lines.append(format_row(rows[cve]))
    lines += after
    with open(filename, "w") as f:
        f.write("\n".join(lines) + "\n")


def new_row(m: dict, versions: list[str]) -> dict[str, str]:
    return {
        "CVE": m["id"],
        "Package": ", ".join(sorted(m["packages"])),
        "Severity": m["severity"],
        "Issue": summarize(m["description"]),
        "Upstream fix": escape(m["fixed"]),
        "Live": LIVE_ON,
        "First xpra version": ", ".join(versions),
    }


def update_row(row: dict[str, str], m: dict) -> None:
    # only the columns we fill in automatically, the others are edited by hand:
    packages = [x.strip() for x in row.get("Package", "").split(",") if x.strip()]
    packages += [x for x in sorted(m["packages"]) if x not in packages]
    row["Package"] = ", ".join(packages)
    if not row.get("Upstream fix"):
        row["Upstream fix"] = escape(m["fixed"])


def is_live(row: dict[str, str]) -> bool:
    return row.get("Live", "").split()[-1:] != [LIVE_OFF]


def severity_index(severity: str) -> int:
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return len(SEVERITIES)


def table(rows: list[dict[str, str]]) -> list[str]:
    lines = [format_row({column: column for column in COLUMNS}), "|" + "|".join("---" for _ in COLUMNS) + "|"]
    for row in sorted(rows, key=lambda row: (severity_index(row["Severity"]), cve_key(row["CVE"]))):
        lines.append(format_row(row))
    return lines


def report(matches: dict[str, dict], versions: dict[str, list[str]], rows: dict[str, dict[str, str]],
           skipped: set[str], heading_level: int = 2) -> list[str]:
    new = [new_row(m, versions[vuln_id]) for vuln_id, m in matches.items() if vuln_id not in rows]
    known = []
    for vuln_id, m in matches.items():
        if vuln_id in rows:
            row = rows[vuln_id].copy()
            update_row(row, m)
            known.append(row)
    live = [row for row in known if is_live(row)]
    off = len(known) - len(live)

    counts = ", ".join(
        f"{count} {severity.lower()}" for severity in SEVERITIES
        if (count := sum(1 for m in matches.values() if m["severity"] == severity))
    )
    lines = [
        f"{len(matches)} {'vulnerability' if len(matches) == 1 else 'vulnerabilities'}" + (f": {counts}" if counts else ""),
        "",
        f"{len(new)} new, {len(live)} live and {off} switched off in [CVE.md]({CVE_DOC_URL}),"
        f" {len(skipped - set(matches))} more in ignored packages.",
    ]
    if new:
        lines += ["", f"{'#' * heading_level} New vulnerabilities", ""] + table(new)
    if live:
        lines += ["", "<details><summary>Live vulnerabilities</summary>", ""] + table(live) + ["", "</details>"]
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="summarize grype reports for the xpra SBOMs")
    scans = parser.add_mutually_exclusive_group(required=True)
    scans.add_argument("--scan", nargs=2, action="append", metavar=("XPRA_VERSION", "GRYPE_JSON"),
                       help="the xpra version of the SBOM and the grype JSON report for it")
    scans.add_argument("--variant-scan", nargs=3, action="append", metavar=("VARIANT", "XPRA_VERSION", "GRYPE_JSON"),
                       help="report variants in order, showing each CVE once and merging affected packages across variants")
    parser.add_argument("--doc", default=CVE_DOC, help="the markdown document recording the vulnerabilities")
    parser.add_argument("--update", action="store_true", help="add the new vulnerabilities to the document")
    args = parser.parse_args(argv[1:])

    before, after, rows = load_doc(args.doc)
    ignored = load_ignored(before + after)
    # Merge all scans before reporting so shared CVEs retain every affected package and version.
    matches: dict[str, dict] = {}
    versions: dict[str, list[str]] = {}
    skipped: set[str] = set()
    groups: list[tuple[str, set[str], set[str]]] = []
    scan_args = args.variant_scan or [("", version, filename) for version, filename in args.scan]
    for variant, xpra_version, filename in scan_args:
        scan_ids: set[str] = set()
        scan_skipped: set[str] = set()
        for vuln_id, m in load_matches(filename).items():
            for package in ignored & set(m["packages"]):
                del m["packages"][package]
            if not m["packages"]:
                scan_skipped.add(vuln_id)
                continue
            scan_ids.add(vuln_id)
            if vuln_id in matches:
                matches[vuln_id]["packages"].update(m["packages"])
            else:
                matches[vuln_id] = m
            if xpra_version not in versions.setdefault(vuln_id, []):
                versions[vuln_id].append(xpra_version)
        skipped.update(scan_skipped)
        groups.append((f"{variant} {xpra_version}", scan_ids, scan_skipped))

    if args.variant_scan:
        lines = []
        seen: set[str] = set()
        seen_skipped: set[str] = set()
        for index, (title, scan_ids, scan_skipped) in enumerate(groups):
            group_matches = {vuln_id: matches[vuln_id] for vuln_id in scan_ids - seen}
            group_skipped = scan_skipped - matches.keys() - seen_skipped
            suffix = " (additional vulnerabilities)" if index else ""
            lines += [f"## {escape(title)}{suffix}", ""]
            lines += report(group_matches, versions, rows, group_skipped, heading_level=3) + [""]
            seen.update(scan_ids)
            seen_skipped.update(group_skipped)
    else:
        lines = report(matches, versions, rows, skipped)
    print("\n".join(lines))

    new = [new_row(m, versions[vuln_id]) for vuln_id, m in matches.items() if vuln_id not in rows]
    if args.update and new:
        for vuln_id, m in matches.items():
            if vuln_id in rows:
                update_row(rows[vuln_id], m)
        for row in new:
            rows[row["CVE"]] = row
        save_doc(args.doc, before, after, rows)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"new={len(new)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
