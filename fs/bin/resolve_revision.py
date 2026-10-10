#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Resolve a package revision string like `7.0-r44000` back to the git commit it was built from.

This reverses `get_vcs_props()` in `add_build_info.py`:
* builds from `master` use the first-parent commit count plus 5014,
* builds from any other branch use the distance to the nearest tag (`git describe`).
The version found in `xpra/__init__.py` at the candidate commit must match the version given.

The argument can also be a whole package filename, ie:
`xpra-6.5.5-r90-1.fc44.x86_64.rpm` or `Xpra-x86_64_7.0-r44000.exe`
"""

import re
import sys
from subprocess import run
from argparse import ArgumentParser

MASTER_OFFSET = 5014
VERSION_FILES = ("xpra/__init__.py", "src/xpra/__init__.py")
VERSION_RE = re.compile(r"""^\+?__version__\s*=\s*["']([^"']+)["']""")
# some versions use: `__version_info__ = (6, 0)`
VERSION_INFO_RE = re.compile(r"^\+?__version_info__\s*=\s*\(([\d,\s]+)\)")
REVISION_RE = re.compile(r"(\d+(?:\.\d+)*)-r(\d+)")


def git(*args: str, check=True) -> str:
    proc = run(("git", ) + args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"'git {' '.join(args)}' failed: {proc.stderr.strip()}")
    return proc.stdout if proc.returncode == 0 else ""


def ref_exists(ref: str) -> bool:
    return bool(git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False))


def parse_version(line: str) -> str:
    m = VERSION_RE.match(line)
    if m:
        return m.group(1)
    m = VERSION_INFO_RE.match(line)
    if m:
        return ".".join(x.strip() for x in m.group(1).split(",") if x.strip())
    return ""


def get_version(commit: str) -> str:
    for path in VERSION_FILES:
        for line in git("show", f"{commit}:{path}", check=False).splitlines():
            version = parse_version(line)
            if version:
                return version
    return ""


def first_parent_versions(ref: str) -> "list[tuple[str, str]]":
    """
    returns the first-parent history of `ref`, oldest first, with the xpra version at each commit
    """
    bumps: dict[str, str] = {}
    commit = ""
    log = git("log", "--first-parent", "--format=commit %H", "-p", "-U0", ref, "--", *VERSION_FILES)
    for line in log.splitlines():
        if line.startswith("commit "):
            commit = line[7:]
            continue
        version = parse_version(line) if line.startswith("+") else ""
        if version:
            bumps[commit] = version
    history = []
    version = ""
    for commit in git("rev-list", "--first-parent", "--reverse", ref).split():
        version = bumps.get(commit, version)
        history.append((commit, version))
    return history


def resolve_master(ref: str, version: str, revision: int) -> "list[str]":
    count = revision - MASTER_OFFSET
    if count <= 0:
        return []
    commits = git("rev-list", "--first-parent", "--reverse", ref).split()
    if count > len(commits):
        return []
    commit = commits[count - 1]
    return [commit] if get_version(commit) == version else []


def resolve_describe(ref: str, version: str, revision: int) -> "list[str]":
    candidates = [commit for commit, cversion in first_parent_versions(ref) if cversion == version]
    if not candidates:
        return []
    found = []
    # describe them in batches to keep the command line short:
    for i in range(0, len(candidates), 256):
        batch = candidates[i:i + 256]
        out = git("describe", "--long", "--tags", "--always", *batch).splitlines()
        for commit, desc in zip(batch, out):
            # ie: v6.5.4-90-gf8a235474a
            parts = desc.rsplit("-", 2)
            if len(parts) == 3 and parts[1] == str(revision):
                found.append(commit)
    return found


def main(argv: "list[str]") -> int:
    parser = ArgumentParser(description="resolve an xpra 'X.Y.Z-rNNNNN' revision string to a git commit")
    parser.add_argument("revision", help="revision string, ie: '7.0-r44000', or a package filename containing one")
    parser.add_argument("--remote", default="origin", help="git remote to search, in addition to local branches")
    parser.add_argument("--ref", action="append", default=[], help="additional branch or ref to search")
    args = parser.parse_args(argv[1:])

    m = REVISION_RE.search(args.revision)
    if not m:
        print(f"cannot find a revision string of the form 'X.Y.Z-rNNNNN' in {args.revision!r}", file=sys.stderr)
        return 2
    version = m.group(1)
    revision = int(m.group(2))

    # stable branches are named `v6.5.x`, older ones `v6.x`:
    vparts = version.split(".")
    branches = [f"v{'.'.join(vparts[:2])}.x", f"v{vparts[0]}.x"] + args.ref
    master_refs = ["master"]
    if args.remote:
        master_refs.append(f"{args.remote}/master")
        branches += [f"{args.remote}/{branch}" for branch in branches]

    results: dict[str, list[str]] = {}

    def add(commits: "list[str]", how: str) -> None:
        for commit in commits:
            results.setdefault(commit, []).append(how)

    for ref in master_refs:
        if ref_exists(ref):
            add(resolve_master(ref, version, revision), f"{ref} (first-parent count + {MASTER_OFFSET})")
    for ref in dict.fromkeys(branches):
        if ref_exists(ref):
            add(resolve_describe(ref, version, revision), f"{ref} (commits since tag)")

    if not results:
        print(f"no commit found for version {version} revision {revision}", file=sys.stderr)
        print(" (local branches may be lagging, try 'git fetch')", file=sys.stderr)
        return 1
    if len(results) > 1:
        print(f"warning: {len(results)} commits match version {version} revision {revision}", file=sys.stderr)
    for commit, hows in results.items():
        print(git("log", "-1", "--format=%H %ad %s", "--date=short", commit).strip())
        for how in hows:
            print(f"    found via {how}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
