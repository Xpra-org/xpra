#!/usr/bin/env python3
# ABOUTME: Harvests downstream forks and distro patch sets for changes that never
# ABOUTME: reached upstream, and ranks what is left for review.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Find downstream changes that were never submitted upstream.

Done by hand, this job is: open github's fork list, visit every fork that looks
alive, read its branches and commits, and try to remember which of those changes
are already upstream.  This script does all of that in one local git repository
and only asks for attention on what survives the filters:

1. ``discover`` - where are the downstream trees?  github forks (recursively,
   forks-of-forks included), a committed registry of non-github URLs
   (``downstream-sources.txt``: distro packaging repos, salsa, gitlab, codeberg),
   and optional forge searches.  Discovery may be noisy: anything that neither
   shares history with upstream nor carries patch files is dropped in step 3.

2. ``fetch`` - every tree becomes a refspec in *one* bare repo whose
   ``objects/info/alternates`` points at this working clone, so a fork costs only
   the objects it does not share with upstream - usually a few KB, not a clone.

3. ``scan`` - per downstream ref, ``git rev-list <ref> --not <every upstream
   ref>`` yields the commits that exist only downstream.  Those are then filtered:

   * ``git patch-id --stable`` against an index of *all* upstream commits, which
     catches rebased, cherry-picked or squashed copies of upstream work;
   * ``git apply --check --reverse`` against upstream master, which catches
     "upstream already has this change" however the patch was reshaped - a
     different author, different whitespace, a different commit message;
   * path and subject noise rules (fork CI, version bumps, readme edits).

   What is left is ranked, written out as ``.patch`` files plus a markdown
   report, and remembered in a state file, so the next run only shows what is
   new or not yet triaged.

What it cannot decide: whether upstream solved the same *problem* a different
way.  A change that was reimplemented rather than applied - rewritten on a
different layer, or half accepted and half declined - still looks like a
candidate, because no diff of the two trees can say otherwise.  That is what the
``triage`` verdicts are for: say ``rejected`` or ``merged`` once, with a note,
and it stays out of every later report.

Trees that do not share history with upstream (distro packaging repos) are
scanned in ``patchset`` mode instead: every ``*.patch``/``*.diff`` in the tip
tree goes through the same two "is this upstream already?" tests.  Forks that
keep their work as a tracked patch queue rather than as commits (kogeler/xpra)
get the same treatment for the patch files their commits add.

Usage:
    # everything: refresh the source list, fetch, report (first run ~5 minutes)
    python3 tests/scripts/find_downstream_changes.py

    # individual steps
    ... find_downstream_changes.py discover --since-days 365
    ... find_downstream_changes.py fetch --jobs 8
    ... find_downstream_changes.py scan --out /tmp/downstream

    # registry and triage
    ... find_downstream_changes.py sources                  # what is tracked
    ... find_downstream_changes.py sources --add https://example.org/xpra.git
    ... find_downstream_changes.py triage --list
    ... find_downstream_changes.py triage --reject ab12cd34 --note "not portable"

Nothing here writes to the working clone: the cache lives in
``~/.cache/xpra-downstream`` (override with ``--cache`` or
``$XPRA_DOWNSTREAM_CACHE``) and the report in ``<cache>/report/``.

A github token is optional; without one the github API allows 60 requests an
hour, which is enough for ~6000 forks since responses are cached on disk.
Set ``$GITHUB_TOKEN``/``$GH_TOKEN`` or pass ``--token`` to lift that.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = Path(os.environ.get("XPRA_DOWNSTREAM_CACHE") or "~/.cache/xpra-downstream").expanduser()
SOURCES_FILE = Path(__file__).resolve().parent / "downstream-sources.txt"
UPSTREAM_REPO = "Xpra-org/xpra"
# every upstream branch *and tag*, not just master: a fix may have landed on a
# stable branch only, and a tag may be the only thing left of a rewritten branch
UPSTREAM_GLOBS = ("--glob=refs/remotes/upstream/*", "--glob=refs/remotes/upstream-tags/*")
# commits by an upstream author that upstream does not have are almost always the
# other way round: our own view of upstream is behind, or a branch was rewritten
UPSTREAM_AUTHORS = re.compile(r"@xpra\.org$")
PATCH_SUFFIX = re.compile(r"\.(patch|diff)$")

# paths that never justify a candidate on their own:
# fork CI, editor/agent droppings, packaging version bumps, generated files
NOISE_PATHS = re.compile(r"""^(
    \.github/ | \.gitignore$ | \.gitattributes$ | \.gitmodules$ |
    \.idea/ | \.vscode/ | \.devcontainer/ | \.pre-commit-config\.yaml$ |
    AGENTS\.md$ | CLAUDE\.md$ | \.cursorrules$ | \.clinerules |
    README(\.md)?$ | MANIFEST(\.in)?$ |
    fork-maintenance/(?!cases/.*\.patch) |
    .*\.(pyc|so|o|log|png|jpg|gif|ico|mo|pdf)$
)""", re.X)
# subjects that are almost always downstream bookkeeping
NOISE_SUBJECTS = re.compile(r"""^(\s*
    (merge\b | revert\b | bump\b | release\b | version\b | wip\b | tmp\b | temp\b |
     update(d)?\s+(changelog|readme|version|submodule|from\s+upstream) |
     sync(ed|ing)?\s+(with|from)\s+upstream | rebase | initial\s+commit |
     \.{3} | fixup! | squash!)
)""", re.X | re.I)
# words that suggest a real defect was fixed (scored up)
FIX_WORDS = re.compile(r"\b(fix|crash|leak|segfault|sigsegv|hang|deadlock|regress\w*|race|"
                       r"overflow|underflow|broken|breaks|wrong|incorrect|corrupt\w*|"
                       r"workaround|work-around|error|fail\w*|missing|unable|invalid)\b", re.I)
# an upstream issue/PR reference: the change was probably already discussed upstream
ISSUE_REF = re.compile(r"(#\d{3,5}\b|github\.com/Xpra-org/xpra/(issues|pull)/\d+)")

AREAS = (
    ("source", re.compile(r"^xpra/.*\.(py|pyx|pxd|c|h|cpp|js|css|html)$")),
    ("tests", re.compile(r"^tests/")),
    ("packaging", re.compile(r"^(packaging/|debian/|.*\.spec$|PKGBUILD$|setup\.py$|pyproject\.toml$)")),
    ("docs", re.compile(r"^(docs/|.*\.md$)")),
    ("data", re.compile(r"^fs/")),
)


def area_of(path: str) -> str:
    for name, pattern in AREAS:
        if pattern.match(path):
            return name
    return "other"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def short(value: str, length: int = 10) -> str:
    return value[:length]


# --- git plumbing --------------------------------------------------------------

GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", GIT_CONFIG_NOSYSTEM="1",
               GIT_SSH_COMMAND="ssh -oBatchMode=yes -oStrictHostKeyChecking=accept-new")


def run(args: list[str], cwd: Path | None = None, stdin: str | bytes = "", check: bool = True,
        timeout: int = 600, env: dict | None = None) -> str:
    """run a command, return stdout as text (errors replaced, patches are not always utf8)"""
    if isinstance(stdin, str):
        stdin = stdin.encode()
    proc = subprocess.run(args, cwd=cwd, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, env=env or GIT_ENV)
    out = proc.stdout.decode("utf8", "replace")
    if check and proc.returncode:
        err = proc.stderr.decode("utf8", "replace").strip()
        raise RuntimeError(f"{' '.join(args[:6])} failed ({proc.returncode}): {err[:400]}")
    return out


def pipe(first: list[str], second: list[str], cwd: Path | None = None, timeout: int = 900) -> str:
    """first | second - used for `git log -p | git patch-id`, which must not buffer in python"""
    p1 = subprocess.Popen(first, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=GIT_ENV)
    p2 = subprocess.Popen(second, cwd=cwd, stdin=p1.stdout, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env=GIT_ENV)
    assert p1.stdout
    p1.stdout.close()
    out = p2.communicate(timeout=timeout)[0]
    p1.wait(timeout=30)
    return out.decode("utf8", "replace")


class Repo:
    """the bare cache repo that holds upstream plus every downstream tree"""

    def __init__(self, path: Path, upstream: str, upstream_url: str = ""):
        self.path = path
        self.upstream = upstream          # local clone: object cache, fetched offline
        self.upstream_url = upstream_url  # the real remote: the refs must not be stale

    def git(self, *args: str, **kw) -> str:
        return run(["git", *args], cwd=self.path, **kw)

    def setup(self) -> None:
        if not (self.path / "HEAD").exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "init", "--bare", "--quiet", str(self.path)])
            log(f"created cache repo {self.path}")
        # share the objects of the local clone instead of downloading upstream again
        local = Path(self.upstream)
        if local.is_dir():
            objects = run(["git", "rev-parse", "--git-path", "objects"], cwd=local).strip()
            alternates = self.path / "objects" / "info" / "alternates"
            line = str((local / objects).resolve()) + "\n"
            if not alternates.exists() or line not in alternates.read_text():
                alternates.parent.mkdir(parents=True, exist_ok=True)
                alternates.write_text(line)
        self.git("config", "gc.auto", "0")
        self.git("config", "fetch.prune", "true")

    def fetch_upstream(self) -> None:
        """refs from the real remote, objects from the local clone where possible

        Using the local clone alone is a trap: a working clone is usually behind on
        the branches nobody checks out, and every commit upstream already has but we
        have not fetched turns into a fake "downstream-only" commit.
        """
        # tags live in their own namespace: a working clone's refs/tags is shared by
        # every remote it has ever fetched, fork tags included, and one fork tag in
        # the upstream set hides that fork's whole branch
        stale = self.git("for-each-ref", "refs/tags/", "--format=delete %(refname)")
        if stale:
            self.git("update-ref", "--stdin", stdin=stale)
        branches = "+refs/heads/*:refs/remotes/upstream/*"
        tag_spec = "+refs/tags/*:refs/remotes/upstream-tags/*"
        # never prune: a branch that only exists in the local clone (work in progress)
        # or that upstream has deleted still tells us a change is not downstream work
        for source, refspecs in ((self.upstream, (branches,)),
                                 (self.upstream_url, (branches, tag_spec))):
            if not source:
                continue
            try:
                self.git("fetch", "--no-tags", "--quiet", source, *refspecs, timeout=900)
            except RuntimeError as e:
                log(f"upstream fetch from {source} failed: {str(e)[:160]}")
        tips = self.refs("refs/remotes/upstream/")
        tags = len(self.refs("refs/remotes/upstream-tags/"))
        log(f"upstream: {len(tips)} branches, {tags} tags, master at {short(tips.get('master', '?'))}")

    def ref_dates(self, prefix: str) -> dict[str, str]:
        """branch -> commit date, newest branch first"""
        out = self.git("for-each-ref", "--sort=-committerdate",
                       "--format=%(committerdate:short) %(refname)", prefix)
        dates = {}
        for line in out.splitlines():
            date, _, ref = line.partition(" ")
            dates[ref[len(prefix):]] = date
        return dates

    def refs(self, prefix: str) -> dict[str, str]:
        out = self.git("for-each-ref", "--format=%(objectname) %(refname)", prefix)
        found = {}
        for line in out.splitlines():
            sha, _, ref = line.partition(" ")
            found[ref[len(prefix):]] = sha
        return found


# --- the source registry -------------------------------------------------------

@dataclass
class Source:
    """one downstream tree: a git URL plus what we learned about it"""
    sid: str                       # short id, also the ref namespace: refs/remotes/f/<sid>/*
    url: str
    found_by: str = "registry"     # github-forks, registry, gitlab-search, ...
    kind: str = "unknown"          # fork (shares history) | patchset (does not) | unrelated
    pushed_at: str = ""
    note: str = ""
    fetched_at: str = ""
    status: str = ""               # "" = never fetched, ok, or an error message
    failures: int = 0
    retired: bool = False          # kept in the registry, skipped by fetch/scan

    @property
    def namespace(self) -> str:
        return f"refs/remotes/f/{self.sid}/"


def source_id(url: str) -> str:
    """github.com/user/xpra.git -> github/user, salsa.debian.org/bluca/xpra -> salsa/bluca"""
    clean = re.sub(r"^(https?://|git://|ssh://|git@)", "", url.rstrip("/"))
    clean = re.sub(r"\.git$", "", clean).replace(":", "/")
    parts = [p for p in clean.split("/") if p]
    host = parts[0].split(".")
    # the distinctive label of the host: github.com -> github, src.fedoraproject.org -> fedoraproject
    label = host[-2] if len(host) > 1 else host[0]
    if label in ("debian", "archlinux", "alpinelinux") and len(host) > 2:
        label = host[0]            # salsa.debian.org -> salsa, gitlab.archlinux.org -> gitlab
    owner = "/".join(parts[1:-1]) or parts[-1]
    tail = parts[-1]
    if tail not in ("xpra", "xpra.git") and len(parts) > 2:
        owner = f"{owner}/{tail}"
    return re.sub(r"[^a-zA-Z0-9._/-]", "-", f"{label}/{owner}")


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.sources: dict[str, Source] = {}
        if path.exists():
            for raw in json.loads(path.read_text()).get("sources", []):
                src = Source(**raw)
                self.sources[src.sid] = src

    def save(self) -> None:
        data = {"updated": utcnow().isoformat(timespec="seconds"),
                "sources": [vars(s) for s in sorted(self.sources.values(), key=lambda s: s.sid)]}
        self.path.write_text(json.dumps(data, indent=1, sort_keys=True))

    def add(self, url: str, found_by: str = "registry", pushed_at: str = "", note: str = "") -> tuple[Source, bool]:
        sid = source_id(url)
        existing = self.sources.get(sid)
        if existing:
            if pushed_at > existing.pushed_at:
                existing.pushed_at = pushed_at
            if note and not existing.note:
                existing.note = note
            return existing, False
        src = Source(sid=sid, url=url, found_by=found_by, pushed_at=pushed_at, note=note)
        self.sources[sid] = src
        return src, True

    def active(self) -> list[Source]:
        return [s for s in self.sources.values() if not s.retired and s.kind != "unrelated"]


# --- discovery -----------------------------------------------------------------

class WebCache:
    """on-disk cache of API responses, so re-running does not burn the rate limit"""

    def __init__(self, cache: Path, token: str = "", ttl: int = 6 * 3600):
        self.dir = cache / "api"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.ttl = ttl

    def json(self, url: str, ttl: int = 0) -> object:
        path = self.dir / (sha256(url.encode()).hexdigest()[:24] + ".json")
        ttl = ttl or self.ttl
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "xpra-downstream-harvester"}
        if self.token and "api.github.com" in url:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read().decode("utf8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf8", "replace")[:200]
            if e.code in (403, 429):
                raise RuntimeError(f"rate limited by {url.split('/')[2]}: {detail}") from None
            raise RuntimeError(f"HTTP {e.code} for {url}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"{url.split('/')[2]} unreachable: {e}") from None
        path.write_text(body)
        return json.loads(body)


def github_token(explicit: str = "") -> str:
    if explicit:
        return explicit
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:                                     # gh is not installed everywhere
        return run(["gh", "auth", "token"], timeout=20).strip()
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ""


def discover_github(registry: Registry, web: WebCache, repo: str, cutoff: datetime,
                    max_depth: int = 2, include_untouched: bool = False) -> None:
    """walk the fork tree of `repo`, skipping forks nobody ever pushed to"""
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(repo, 0)]
    found = added = skipped = 0
    while queue:
        parent, depth = queue.pop(0)
        if parent in seen:
            continue
        seen.add(parent)
        page = 1
        while True:
            url = f"https://api.github.com/repos/{parent}/forks?sort=newest&per_page=100&page={page}"
            try:
                forks = web.json(url)
            except RuntimeError as e:
                log(f"  github: {e}")
                return
            if not isinstance(forks, list) or not forks:
                break
            for fork in forks:
                found += 1
                name = fork["full_name"]
                pushed, created = fork.get("pushed_at") or "", fork.get("created_at") or ""
                # an untouched fork reports the parent's push time from the moment it was created
                untouched = bool(pushed and created and abs((parse_time(pushed) - parse_time(created)).total_seconds()) < 120)
                stale = bool(pushed) and parse_time(pushed) < cutoff
                if fork.get("archived") or stale or (untouched and not include_untouched):
                    skipped += 1
                elif registry.add(fork["clone_url"], "github-forks", pushed, name)[1]:
                    added += 1
                if fork.get("forks_count") and depth + 1 < max_depth and not stale:
                    queue.append((name, depth + 1))
            if len(forks) < 100:
                break
            page += 1
    log(f"github: {found} forks in the network, {added} new, {skipped} skipped (archived/stale/never pushed)")


def discover_registry_file(registry: Registry, path: Path) -> None:
    """the committed list of trees that github cannot tell us about"""
    if not path.exists():
        return
    added = 0
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        url, _, note = (part.strip() for part in line.partition(" "))
        added += registry.add(url, "registry", note=note)[1]
    log(f"registry file: {path.name}, {added} new")


# forge instances worth searching: distro packaging lives on these
GITLAB_INSTANCES = ("https://salsa.debian.org", "https://gitlab.archlinux.org",
                    "https://gitlab.alpinelinux.org", "https://gitlab.com")
GITEA_INSTANCES = ("https://codeberg.org",)


def discover_forges(registry: Registry, web: WebCache, term: str, cutoff: datetime) -> None:
    """keyword search on gitlab/gitea instances - noisy by design, the fetch step verifies"""
    added = 0
    for base in GITLAB_INSTANCES:
        url = f"{base}/api/v4/projects?search={term}&per_page=100&order_by=last_activity_at"
        try:
            projects = web.json(url)
        except RuntimeError as e:
            log(f"  {base}: {e}")
            continue
        for project in projects if isinstance(projects, list) else []:
            name = project.get("path", "")
            active = project.get("last_activity_at", "")
            if term not in name or (active and parse_time(active) < cutoff):
                continue
            added += registry.add(project["http_url_to_repo"], f"gitlab-search:{source_id(base)}",
                                  active, project.get("path_with_namespace", ""))[1]
    for base in GITEA_INSTANCES:
        url = f"{base}/api/v1/repos/search?q={term}&limit=50&sort=updated"
        try:
            result = web.json(url)
        except RuntimeError as e:
            log(f"  {base}: {e}")
            continue
        for project in (result or {}).get("data", []) if isinstance(result, dict) else []:
            active = project.get("updated_at", "")
            if term not in project.get("name", "") or (active and parse_time(active) < cutoff):
                continue
            added += registry.add(project["clone_url"], f"gitea-search:{source_id(base)}",
                                  active, project.get("full_name", ""))[1]
    log(f"forge searches: {added} new")


# --- fetching ------------------------------------------------------------------

def fetch_source(repo: Repo, src: Source, timeout: int) -> Source:
    try:
        repo.git("fetch", "--no-tags", "--prune", "--quiet", src.url,
                 f"+refs/heads/*:{src.namespace}*", timeout=timeout)
        src.status, src.failures, src.fetched_at = "ok", 0, utcnow().isoformat(timespec="seconds")
    except (RuntimeError, subprocess.SubprocessError) as e:
        src.failures += 1
        src.status = re.sub(r"\s+", " ", str(e))[:200]
        # gone for good: deleted repos and permission errors will not come back
        if src.failures >= 3 or re.search(r"not found|does not exist|Repository not found|403", src.status, re.I):
            src.retired = True
    return src


def classify(repo: Repo, src: Source, upstream_master: str) -> None:
    """fork (shares history with upstream) vs patchset (packaging tree) vs unrelated"""
    refs = repo.refs(src.namespace)
    if not refs:
        src.kind, src.retired = "unrelated", True
        src.note = (src.note + " [no branches]").strip()
        return
    for sha in refs.values():
        try:
            repo.git("merge-base", sha, upstream_master, timeout=60)
            src.kind = "fork"
            return
        except RuntimeError:
            continue
    # no shared history: a packaging tree, whose patches are the interesting part,
    # or something the discovery step picked up by name alone
    listing = repo.git("ls-tree", "-r", "--name-only", next(iter(refs.values()))).splitlines()
    packaging = [p for p in listing if re.search(r"(^|/)(debian/|PKGBUILD|.*\.spec|APKBUILD|.*\.ebuild)", p)]
    if packaging:
        src.kind = "patchset"
        if not any(PATCH_SUFFIX.search(p) for p in listing):
            src.note = (src.note + " [no patches yet]").strip()
    else:
        src.kind, src.retired = "unrelated", True
        src.note = (src.note + " [unrelated to xpra]").strip()


def fetch_all(repo: Repo, registry: Registry, jobs: int, timeout: int, limit: int = 0) -> None:
    upstream = repo.refs("refs/remotes/upstream/")
    master = upstream.get("master") or next(iter(upstream.values()))
    todo = [s for s in registry.active() if not s.retired]
    if limit:
        todo = sorted(todo, key=lambda s: s.pushed_at, reverse=True)[:limit]
    log(f"fetching {len(todo)} sources with {jobs} jobs")
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for src in pool.map(lambda s: fetch_source(repo, s, timeout), todo):
            done += 1
            if src.status == "ok":
                if src.kind in ("unknown", ""):
                    classify(repo, src, master)
                refs = len(repo.refs(src.namespace))
                log(f"  [{done}/{len(todo)}] {src.sid:<40} {src.kind:<9} {refs} branches")
            else:
                log(f"  [{done}/{len(todo)}] {src.sid:<40} FAILED {'(retired)' if src.retired else ''} {src.status[:80]}")
            registry.save()


# --- "is this already upstream?" -----------------------------------------------

class UpstreamIndex:
    """patch-id -> upstream commit, for every commit on every upstream branch

    `git patch-id --stable` hashes the diff without line numbers, so a downstream
    commit that is a rebase, a cherry-pick or a squash-free copy of upstream work
    hashes the same and is dropped.  Kept on disk and updated incrementally: a
    full build of xpra's 38k commits takes ~30s, an update takes seconds.
    """

    def __init__(self, repo: Repo, path: Path):
        self.repo = repo
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.tips: dict[str, str] = data.get("tips", {})
        self.ids: dict[str, str] = data.get("ids", {})

    def update(self) -> None:
        tips = self.repo.refs("refs/remotes/upstream/")
        if tips == self.tips and self.ids:
            log(f"upstream patch-id index: {len(self.ids)} entries (up to date)")
            return
        args = ["git", "log", "-p", "--no-merges", "--full-history"]
        if self.ids and self.tips:
            args += list(tips.values()) + ["--not", *self.tips.values()]
        else:
            args += list(UPSTREAM_GLOBS)
        started = time.time()
        out = pipe(args, ["git", "patch-id", "--stable"], cwd=self.repo.path)
        new = 0
        for line in out.splitlines():
            patch_id, _, commit = line.partition(" ")
            if patch_id and patch_id not in self.ids:
                self.ids[patch_id] = commit.strip()
                new += 1
        self.tips = tips
        self.path.write_text(json.dumps({"tips": self.tips, "ids": self.ids}))
        log(f"upstream patch-id index: {len(self.ids)} entries (+{new} in {time.time() - started:.0f}s)")

    def find(self, patch_id: str) -> str:
        return self.ids.get(patch_id, "")


class AlreadyApplied:
    """does a patch reverse-apply to an upstream branch?  then upstream has it

    This is the filter that patch-id cannot be: it still recognises the change
    when the patch was reshaped on the way upstream - rewritten commit message,
    different author, whitespace fixed, hunks split.  Only the resulting tree
    matters.  Checked against master and the stable branches, index-only, so no
    worktree is needed.
    """

    def __init__(self, repo: Repo, cache: Path, branches: tuple[str, ...] = ("master",)):
        self.repo = repo
        self.envs: dict[str, dict] = {}
        available = repo.refs("refs/remotes/upstream/")
        for branch in branches:
            if branch not in available:
                continue
            index = cache / f"index-{branch.replace('/', '-')}"
            env = dict(GIT_ENV, GIT_INDEX_FILE=str(index))
            run(["git", "read-tree", f"refs/remotes/upstream/{branch}"], cwd=repo.path, env=env)
            self.envs[branch] = env

    def check(self, patch: str) -> str:
        """returns the upstream branch that already contains the change, or ''"""
        if not patch.strip():
            return ""
        for branch, env in self.envs.items():
            for extra in ([], ["-C1"]):          # strict, then tolerant about context
                args = ["git", "apply", "--cached", "--check", "--reverse", *extra, "-"]
                proc = subprocess.run(args, cwd=self.repo.path, input=patch.encode("utf8", "replace"),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      env=env, timeout=120)
                if proc.returncode == 0:
                    return branch
        return ""


# --- candidates ----------------------------------------------------------------

@dataclass
class Candidate:
    key: str                                    # patch-id when we have one, else a content hash
    sid: str
    url: str
    kind: str                                   # commit | patch-queue | patchset
    subject: str = ""
    author: str = ""
    email: str = ""
    date: str = ""
    body: str = ""
    sha: str = ""
    path: str = ""                              # the patch file, for patch-queue/patchset
    blob: str = ""                              # its blob, to read it back later
    refs: list[str] = field(default_factory=list)
    files: list[tuple[str, int, int]] = field(default_factory=list)
    carriers: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    score: int = 0
    patch_file: str = ""

    @property
    def lines(self) -> int:
        return sum(added + removed for _, added, removed in self.files)

    @property
    def areas(self) -> dict[str, int]:
        counted: dict[str, int] = {}
        for path, added, removed in self.files:
            counted[area_of(path)] = counted.get(area_of(path), 0) + added + removed
        return counted


@dataclass
class Stats:
    refs: int = 0
    unique_commits: int = 0
    upstream_patchid: int = 0
    already_applied: int = 0
    noise: int = 0
    upstream_author: int = 0
    divergent: list[str] = field(default_factory=list)
    active_refs: list[str] = field(default_factory=list)
    candidates: int = 0


def commit_details(repo: Repo, shas: list[str]) -> dict[str, dict]:
    """author/date/subject/body and the numstat for a batch of commits, in two calls"""
    if not shas:
        return {}
    stdin = "\n".join(shas)
    fmt = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b"
    out = repo.git("log", "--no-walk=unsorted", "--stdin", f"--format={fmt}", stdin=stdin)
    details: dict[str, dict] = {}
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f")
        if len(parts) < 6:
            continue
        sha, author, email, date, subject, body = parts[:6]
        details[sha.strip()] = {"author": author, "email": email, "date": date,
                                "subject": subject.strip(), "body": body.strip(), "files": []}
    out = repo.git("log", "--no-walk=unsorted", "--stdin", "--format=%x1e%H", "--numstat", "--no-renames",
                   stdin=stdin)
    for record in out.split("\x1e"):
        lines = [line for line in record.splitlines() if line.strip()]
        if not lines:
            continue
        sha = lines[0].strip()
        entry = details.get(sha)
        if entry is None:
            continue
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, removed, path = parts
            entry["files"].append((path, int(added) if added.isdigit() else 0,
                                   int(removed) if removed.isdigit() else 0))
    return details


def patch_ids_of(repo: Repo, shas: list[str], tmp: Path) -> dict[str, str]:
    """sha -> patch-id, in one pass: `git log -p | git patch-id` over a sha list"""
    if not shas:
        return {}
    listing = tmp / "shas.txt"
    listing.write_text("\n".join(shas) + "\n")
    script = f'git log --no-walk=unsorted -p --stdin < {listing} | git patch-id --stable'
    out = run(["sh", "-c", script], cwd=repo.path, timeout=900)
    found: dict[str, str] = {}
    for line in out.splitlines():
        patch_id, _, commit = line.partition(" ")
        if commit.strip():
            found[commit.strip()] = patch_id
    return found


def noise_reason(subject: str, files: list[tuple[str, int, int]]) -> str:
    if not files:
        return "no file changes"
    paths = [path for path, _, _ in files]
    if all(NOISE_PATHS.match(path) for path in paths):
        return "only fork bookkeeping paths"
    has_source = any(area_of(path) == "source" for path in paths)
    if NOISE_SUBJECTS.match(subject) and not has_source:
        return "bookkeeping subject"
    return ""


def text_patch(repo: Repo, sha: str) -> str:
    return repo.git("format-patch", "-1", "--stdout", "--no-signature", "--no-renames", sha, check=False)


@dataclass
class Context:
    repo: Repo
    index: UpstreamIndex
    applied: AlreadyApplied
    tmp: Path
    max_commits: int = 150
    max_patch_lines: int = 20000
    # upstream ships .patch files of its own (packaging/rpm/patches): not candidates
    upstream_patch_blobs: set[str] = field(default_factory=set)
    upstream_authors: re.Pattern = UPSTREAM_AUTHORS


def diffstat(content: str) -> list[tuple[str, int, int]]:
    """what `git log --numstat` gives for a commit, read out of a patch file instead

    Attribution matters: a patch whose added lines all land on the first file it
    mentions looks like a test-only change when the first file is a test.
    """
    counts: dict[str, list[int]] = {}
    current = removed_from = ""
    for line in content.splitlines():
        if line.startswith("--- "):
            removed_from = line[4:].split("\t")[0].strip()
            removed_from = re.sub(r"^a/", "", removed_from)
            continue
        if line.startswith("+++ "):
            name = re.sub(r"^b/", "", line[4:].split("\t")[0].strip())
            current = removed_from if name == "/dev/null" else name
            if current and current != "/dev/null":
                counts.setdefault(current, [0, 0])
            continue
        if not current or line.startswith(("@@", "diff ", "index ", "new file", "deleted file",
                                           "old mode", "new mode", "similarity ", "rename ",
                                           "Binary files", "GIT binary")):
            continue
        if line.startswith("+"):
            counts[current][0] += 1
        elif line.startswith("-"):
            counts[current][1] += 1
    return [(name, added, removed) for name, (added, removed) in counts.items()]


def patch_candidate(ctx: Context, src: Source, path: str, content: str, refs: list[str],
                    stats: Stats, blob: str = "") -> Candidate | None:
    """evaluate one *.patch/*.diff file carried by a downstream tree"""
    if not content.strip() or content.count("\n") > ctx.max_patch_lines:
        return None
    patch_id = ""
    out = run(["git", "patch-id", "--stable"], cwd=ctx.repo.path, stdin=content.encode("utf8", "replace"),
              check=False)
    if out.strip():
        patch_id = out.split()[0]
    if patch_id and ctx.index.find(patch_id):
        stats.upstream_patchid += 1
        return None
    if ctx.applied.check(content):
        stats.already_applied += 1
        return None
    files = diffstat(content)
    subject = date = author = email = ""
    for line in content.splitlines()[:40]:
        if line.startswith("Subject: ") and not subject:
            subject = re.sub(r"^\[PATCH[^]]*]\s*", "", line[9:]).strip()
        elif line.startswith("Date: ") and not date:
            try:                               # git-format-patch header, RFC 2822
                from email.utils import parsedate_to_datetime
                date = parsedate_to_datetime(line[6:].strip()).isoformat()
            except (TypeError, ValueError):
                date = ""
        elif line.startswith("From: ") and "@" in line and not email:
            author, _, rest = line[6:].strip().partition("<")
            author, email = author.strip(), rest.rstrip(">").strip()
    # `cases/<slug>/fix.patch` says nothing; the directory it sits in does
    name = os.path.basename(path)
    if re.match(r"^(fix|patch|diff|\d+)\.(patch|diff)$", name):
        name = "/".join(Path(path).parts[-2:])
    return Candidate(key=patch_id or sha256(content.encode("utf8", "replace")).hexdigest()[:40],
                     sid=src.sid, url=src.url, kind="patchset" if src.kind == "patchset" else "patch-queue",
                     subject=subject or name, path=path, blob=blob, refs=refs, files=files,
                     author=author, email=email, date=date,
                     body=content[:400] if not subject else "")


def scan_patch_files(ctx: Context, src: Source, stats: Stats,
                     paths: dict[str, set[str]] | None = None) -> list[Candidate]:
    """the *.patch/*.diff files a downstream tree carries - where distro fixes live

    `paths` is the per-branch set to look at, as collected from a fork's own
    commits; packaging trees (no shared history) pass None and get their whole tip
    tree walked, newest branch first, one candidate per patch *name* - dist-git and
    salsa keep a branch per release, all carrying variations of the same series.
    """
    found: dict[str, Candidate] = {}
    seen_blobs: dict[str, str] = {}
    seen_paths: dict[str, Candidate] = {}
    # newest branch first: its version of a patch is the one worth reading
    for name, ref_date in ctx.repo.ref_dates(src.namespace).items():
        ref = f"{src.namespace}{name}"
        if paths is None:
            listing = ctx.repo.git("ls-tree", "-r", "--format=%(objectname) %(path)", ref, check=False)
            entries = [(blob, path) for blob, _, path in
                       (line.partition(" ") for line in listing.splitlines())
                       if PATCH_SUFFIX.search(path)]
        else:
            entries = []
            for path in sorted(paths.get(name, ())):
                blob = ctx.repo.git("rev-parse", "--quiet", "--verify", f"{ref}:{path}", check=False).strip()
                if blob:
                    entries.append((blob, path))
        for blob, path in entries:
            if blob in ctx.upstream_patch_blobs:
                continue
            if blob in seen_blobs:             # the same patch on another branch
                carrier = found.get(seen_blobs[blob])
                if carrier and name not in carrier.refs:
                    carrier.refs.append(name)
                continue
            if path in seen_paths:             # an older release's version of it
                if name not in seen_paths[path].refs:
                    seen_paths[path].refs.append(name)
                seen_blobs[blob] = seen_paths[path].key
                continue
            content = ctx.repo.git("cat-file", "blob", blob, check=False)
            candidate = patch_candidate(ctx, src, path, content, [name], stats, blob)
            seen_blobs[blob] = candidate.key if candidate else ""
            if candidate:
                candidate.date = candidate.date or f"{ref_date}T00:00:00+00:00"
                found.setdefault(candidate.key, candidate)
                seen_paths[path] = candidate
    stats.candidates += len(found)
    return list(found.values())


def scan_fork(ctx: Context, src: Source, stats: Stats) -> tuple[list[Candidate], dict[str, set[str]]]:
    """the commits that exist only downstream, minus everything upstream already has

    Also returns the *.patch files those commits touch, per branch: a fork that
    keeps its work as a tracked patch queue (kogeler/xpra) changes no source file
    at all, and the patches it adds are read by scan_patch_files().
    """
    unique: dict[str, list[str]] = {}
    refs = ctx.repo.refs(src.namespace)
    stats.refs = len(refs)
    for name, sha in sorted(refs.items()):
        shas = ctx.repo.git("rev-list", "--no-merges", "--reverse", sha,
                            "--not", *UPSTREAM_GLOBS).split()
        if len(shas) > ctx.max_commits:
            stats.divergent.append(f"{src.sid} {name}: {len(shas)} commits")
            shas = shas[-ctx.max_commits:]     # keep the newest, they rebase forward
        if shas:
            stats.active_refs.append(name)
        for commit in shas:
            unique.setdefault(commit, []).append(name)
    stats.unique_commits = len(unique)
    if not unique:
        return [], {}
    ids = patch_ids_of(ctx.repo, list(unique), ctx.tmp)
    details = commit_details(ctx.repo, list(unique))
    candidates = []
    patch_paths: dict[str, set[str]] = {}
    for sha, names in unique.items():
        patch_id = ids.get(sha, "")
        if patch_id and ctx.index.find(patch_id):
            stats.upstream_patchid += 1
            continue
        detail = details.get(sha)
        if not detail:
            continue
        files = detail["files"]
        for path, _, _ in files:
            if PATCH_SUFFIX.search(path):
                for name in names:
                    patch_paths.setdefault(name, set()).add(path)
        if ctx.upstream_authors.search(detail["email"]):
            stats.upstream_author += 1
            continue
        if noise_reason(detail["subject"], files):
            stats.noise += 1
            continue
        # a patch-queue commit carries no source change of its own: the tip-tree
        # scan reads the patches it adds, so do not report the commit as well
        if files and all(PATCH_SUFFIX.search(path) or NOISE_PATHS.match(path) for path, _, _ in files):
            stats.noise += 1
            continue
        patch = text_patch(ctx.repo, sha)
        if ctx.applied.check(patch):
            stats.already_applied += 1
            continue
        candidates.append(Candidate(key=patch_id or sha, sid=src.sid, url=src.url, kind="commit",
                                    subject=detail["subject"], author=detail["author"],
                                    email=detail["email"], date=detail["date"], body=detail["body"],
                                    sha=sha, refs=names, files=files))
    stats.candidates += len(candidates)
    return candidates, patch_paths


# --- ranking -------------------------------------------------------------------

def score_candidate(candidate: Candidate, now: datetime) -> None:
    """rank by "how likely is this a real fix that upstream wants?" - transparently

    Every term lands in candidate.signals so a low rank can be argued with.
    """
    score = 0
    signals = []
    areas = candidate.areas
    source = areas.get("source", 0)
    if source:
        points = min(20, 4 + source // 8)
        score += points
        signals.append(f"+{points} {source} source lines")
    else:
        score -= 6
        signals.append(f"-6 no source change ({', '.join(sorted(areas)) or 'none'})")
    if candidate.carriers:
        points = min(12, 4 * len(candidate.carriers))
        score += points
        signals.append(f"+{points} carried by {len(candidate.carriers) + 1} trees")
    text = f"{candidate.subject}\n{candidate.body}"
    if FIX_WORDS.search(text):
        score += 6
        signals.append("+6 describes a defect")
    if ISSUE_REF.search(text):
        score -= 6
        signals.append("-6 mentions an upstream issue/PR (may be proposed already)")
    if len(candidate.body) > 200:
        score += 2
        signals.append("+2 explained at length")
    if candidate.lines > 2000:
        score -= 8
        signals.append(f"-8 {candidate.lines} lines: too big to cherry-pick")
    if candidate.kind == "patchset":
        score += 3
        signals.append("+3 distro patch (shipped to users)")
    if candidate.email.endswith("@xpra.org"):
        score -= 10
        signals.append("-10 upstream author")
    if candidate.date:
        try:
            age = (now - parse_time(candidate.date)).days
        except ValueError:
            age = 0
        if age < 180:
            score += 3
            signals.append("+3 recent")
        elif age > 730:
            score -= 4
            signals.append(f"-4 {age // 365} years old")
    candidate.score = score
    candidate.signals = signals


def group_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """one entry per distinct change: the same patch in five forks is one review"""
    grouped: dict[str, Candidate] = {}
    for candidate in candidates:
        first = grouped.get(candidate.key)
        if first is None:
            grouped[candidate.key] = candidate
            continue
        label = candidate.sid + (f" {candidate.refs[0]}" if candidate.refs else "")
        if label not in first.carriers:
            first.carriers.append(label)
        # prefer the entry that has a real commit to cherry-pick
        if first.kind != "commit" and candidate.kind == "commit":
            candidate.carriers = first.carriers
            grouped[candidate.key] = candidate
    return merge_by_subject(list(grouped.values()))


def merge_by_subject(candidates: list[Candidate]) -> list[Candidate]:
    """second pass: one fork rebased the other, so the patch-ids differ but the
    commit message does not.  Only for subjects long enough to be distinctive."""
    by_subject: dict[str, Candidate] = {}
    kept = []
    for candidate in candidates:
        subject = re.sub(r"[^a-z0-9]+", " ", candidate.subject.lower()).strip()
        if len(subject) < 20:
            kept.append(candidate)
            continue
        first = by_subject.get(subject)
        if first is None:
            by_subject[subject] = candidate
            kept.append(candidate)
            continue
        label = candidate.sid + (f" {candidate.refs[0]}" if candidate.refs else "")
        if label not in first.carriers:
            first.carriers.append(label)
    return kept


def limit_per_source(candidates: list[Candidate], cap: int) -> tuple[list[Candidate], dict[str, int]]:
    """a fork with 400 own commits would drown the report: keep its best `cap`"""
    kept: list[Candidate] = []
    counts: dict[str, int] = {}
    hidden: dict[str, int] = {}
    for candidate in candidates:               # already sorted best first
        counts[candidate.sid] = counts.get(candidate.sid, 0) + 1
        if cap and counts[candidate.sid] > cap:
            hidden[candidate.sid] = hidden.get(candidate.sid, 0) + 1
            continue
        kept.append(candidate)
    return kept, hidden


# --- state ---------------------------------------------------------------------

VERDICTS = ("new", "todo", "rejected", "merged")


class State:
    """what we have already looked at, so a re-run is quiet"""

    def __init__(self, path: Path):
        self.path = path
        self.keys: dict[str, dict] = json.loads(path.read_text()).get("keys", {}) if path.exists() else {}

    def save(self) -> None:
        self.path.write_text(json.dumps({"keys": self.keys}, indent=1, sort_keys=True))

    def see(self, candidate: Candidate) -> bool:
        """record the candidate, return True if this is the first time we see it"""
        now = utcnow().isoformat(timespec="seconds")
        entry = self.keys.get(candidate.key)
        if entry is None:
            self.keys[candidate.key] = {"verdict": "new", "first_seen": now, "last_seen": now,
                                        "subject": candidate.subject[:120], "source": candidate.sid}
            return True
        entry["last_seen"] = now
        entry.setdefault("subject", candidate.subject[:120])
        return False

    def verdict(self, key: str) -> str:
        return (self.keys.get(key) or {}).get("verdict", "new")

    def set_verdict(self, key: str, verdict: str, note: str = "") -> bool:
        matches = [k for k in self.keys if k.startswith(key)]
        if len(matches) != 1:
            return False
        entry = self.keys[matches[0]]
        entry["verdict"] = verdict
        if note:
            entry["note"] = note
        return True


# --- report --------------------------------------------------------------------

def write_patches(candidates: list[Candidate], ctx: Context, out: Path) -> None:
    patches = out / "patches"
    patches.mkdir(parents=True, exist_ok=True)
    for stale in patches.glob("*.patch"):      # the numbering changes every run
        stale.unlink()
    for number, candidate in enumerate(candidates, 1):
        name = re.sub(r"[^a-zA-Z0-9]+", "-", f"{candidate.sid}-{short(candidate.sha or candidate.key, 8)}")
        path = patches / f"{number:03}-{name.strip('-')}.patch"
        if candidate.sha:
            content = text_patch(ctx.repo, candidate.sha)
        elif candidate.blob:
            content = ctx.repo.git("cat-file", "blob", candidate.blob, check=False)
        else:
            content = ""
        path.write_text(content, errors="replace")
        candidate.patch_file = str(path)


def commands_for(candidate: Candidate) -> list[str]:
    branch = candidate.refs[0] if candidate.refs else "master"
    if candidate.kind == "commit":
        return [f"git fetch {candidate.url} {branch}",
                f"git show {short(candidate.sha, 12)}",
                f"git cherry-pick {short(candidate.sha, 12)}"]
    return [f"git apply --check -3 {candidate.patch_file or candidate.path}",
            f"# from {candidate.url} ({branch}: {candidate.path})"]


def write_report(candidates: list[Candidate], stats: dict[str, Stats], registry: Registry,
                 state: State, ctx: Context, out: Path, new_keys: set[str],
                 hidden: dict[str, int]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    master = ctx.repo.refs("refs/remotes/upstream/").get("master", "?")
    totals = Stats()
    for source_stats in stats.values():
        totals.refs += source_stats.refs
        totals.unique_commits += source_stats.unique_commits
        totals.upstream_patchid += source_stats.upstream_patchid
        totals.already_applied += source_stats.already_applied
        totals.upstream_author += source_stats.upstream_author
        totals.noise += source_stats.noise
        totals.divergent += source_stats.divergent
    kinds = [src.kind for src in registry.active() if src.status == "ok"]
    lines = [
        "# Downstream changes that are not upstream",
        "",
        f"generated {utcnow().strftime('%Y-%m-%d %H:%M')}Z against upstream master {short(master, 12)}",
        "",
        f"* sources scanned: **{len(stats)}** "
        f"({kinds.count('fork')} forks, {kinds.count('patchset')} packaging trees), "
        f"{totals.refs} branches",
        f"* downstream-only commits found: **{totals.unique_commits}**",
        f"* dropped: {totals.upstream_patchid} identical patch-id to an upstream commit, "
        f"{totals.already_applied} already applied upstream (reverse-apply), "
        f"{totals.upstream_author} written by an upstream author, "
        f"{totals.noise} bookkeeping/noise",
        f"* left to review: **{len(candidates)}** distinct changes, "
        f"**{len(new_keys)}** new since the last run",
        "",
        "## Ranked candidates",
        "",
        "| # | score | source | change | files | lines | state |",
        "|--:|------:|--------|--------|------:|------:|-------|",
    ]
    for number, candidate in enumerate(candidates, 1):
        mark = "**new**" if candidate.key in new_keys else state.verdict(candidate.key)
        subject = candidate.subject.replace("|", "/")[:70]
        lines.append(f"| {number} | {candidate.score} | {candidate.sid} | {subject} "
                     f"| {len(candidate.files)} | {candidate.lines} | {mark} |")
    lines += ["", "## Details", ""]
    for number, candidate in enumerate(candidates, 1):
        lines += [f"### {number}. {candidate.subject or '(no subject)'}", ""]
        where = f"[{candidate.sid}]({candidate.url})"
        lines.append(f"* score **{candidate.score}** &nbsp; key `{short(candidate.key, 12)}` "
                     f"&nbsp; kind `{candidate.kind}`")
        lines.append(f"* from {where}, branch(es): {', '.join(candidate.refs) or '?'}")
        if candidate.author:
            lines.append(f"* {candidate.author} <{candidate.email}>, {candidate.date[:10]}, "
                         f"commit `{short(candidate.sha, 12)}`")
        if candidate.path:
            lines.append(f"* patch file: `{candidate.path}`")
        if candidate.carriers:
            lines.append(f"* also carried by: {', '.join(candidate.carriers)}")
        lines.append(f"* ranking: {'; '.join(candidate.signals)}")
        lines += ["", "```", *(f"{path} (+{added} -{removed})" for path, added, removed in candidate.files[:20]), "```", ""]
        if candidate.body:
            body = "\n".join(f"> {line}" for line in candidate.body.splitlines()[:12] if line.strip())
            if body:
                lines += [body, ""]
        lines += ["```sh", *commands_for(candidate), "```", ""]
        if candidate.patch_file:
            lines += [f"patch saved as `{candidate.patch_file}`", ""]
    if totals.divergent:
        lines += ["## Divergent branches", "",
                  "too far from upstream to read commit by commit - diff the whole branch instead:", ""]
        for entry in sorted(totals.divergent):
            lines.append(f"* {entry}")
        lines.append("")
    lines += ["## Per source", "",
              "| source | kind | branches | only-downstream | dropped | candidates | not shown | last push |",
              "|--------|------|---------:|----------------:|--------:|-----------:|----------:|-----------|"]
    for sid, source_stats in sorted(stats.items(), key=lambda kv: -kv[1].candidates):
        src = registry.sources[sid]
        dropped = sum((source_stats.upstream_patchid, source_stats.already_applied,
                       source_stats.upstream_author, source_stats.noise))
        lines.append(f"| [{sid}]({src.url}) | {src.kind} | {source_stats.refs} "
                     f"| {source_stats.unique_commits} | {dropped} | {source_stats.candidates} "
                     f"| {hidden.get(sid, 0)} | {src.pushed_at[:10]} |")
    failed = [src for src in registry.sources.values() if src.status and src.status != "ok"]
    if failed:
        lines += ["", "## Unreachable", ""]
        for src in sorted(failed, key=lambda s: s.sid):
            lines.append(f"* {src.sid} ({'retired' if src.retired else 'will retry'}): {src.status[:120]}")
    report = out / "report.md"
    report.write_text("\n".join(lines) + "\n")
    (out / "candidates.json").write_text(json.dumps(
        [dict(vars(candidate), new=candidate.key in new_keys) for candidate in candidates], indent=1))
    return report


# --- commands ------------------------------------------------------------------

def open_repo(args) -> tuple[Repo, Registry]:
    cache = Path(args.cache).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    url = args.upstream_url or f"https://github.com/{args.repo}.git"
    repo = Repo(cache / "net.git", args.upstream, url)
    repo.setup()
    return repo, Registry(cache / "sources.json")


def cmd_discover(args, repo: Repo, registry: Registry) -> int:
    cutoff = utcnow() - timedelta(days=args.since_days)
    web = WebCache(Path(args.cache).expanduser(), github_token(args.token))
    log(f"discovering downstream trees active since {cutoff:%Y-%m-%d}")
    discover_registry_file(registry, Path(args.sources_file))
    if not args.no_github:
        discover_github(registry, web, args.repo, cutoff, args.depth, args.include_untouched)
    if args.forges:
        discover_forges(registry, web, "xpra", cutoff)
    registry.save()
    active = registry.active()
    log(f"registry: {len(active)} active sources, {len(registry.sources) - len(active)} retired")
    return 0


def cmd_fetch(args, repo: Repo, registry: Registry) -> int:
    repo.fetch_upstream()
    fetch_all(repo, registry, args.jobs, args.fetch_timeout, args.limit)
    registry.save()
    return 0


def cmd_scan(args, repo: Repo, registry: Registry) -> int:
    cache = Path(args.cache).expanduser()
    tmp = cache / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    index = UpstreamIndex(repo, cache / "upstream-patchids.json")
    index.update()
    upstream_refs = repo.refs("refs/remotes/upstream/")
    branches = tuple(b for b in (args.branch or ["master", "stable"]) if b in upstream_refs)
    applied = AlreadyApplied(repo, tmp, branches)
    log(f"already-applied check against: {', '.join(branches)}")
    ctx = Context(repo=repo, index=index, applied=applied, tmp=tmp, max_commits=args.max_commits,
                  upstream_authors=re.compile(args.upstream_authors))
    for branch in branches:
        for line in repo.git("ls-tree", "-r", "--format=%(objectname) %(path)",
                             f"refs/remotes/upstream/{branch}").splitlines():
            blob, _, path = line.partition(" ")
            if PATCH_SUFFIX.search(path):
                ctx.upstream_patch_blobs.add(blob)
    state = State(cache / "state.json")
    todo = [s for s in registry.active() if s.status == "ok"]
    if args.source:
        todo = [s for s in todo if args.source in s.sid]
    log(f"scanning {len(todo)} sources")
    found: list[Candidate] = []
    stats: dict[str, Stats] = {}
    for number, src in enumerate(todo, 1):
        source_stats = Stats()
        candidates: list[Candidate] = []
        try:
            if src.kind == "fork":
                commits, patch_paths = scan_fork(ctx, src, source_stats)
                candidates += commits + scan_patch_files(ctx, src, source_stats, patch_paths)
            else:
                candidates += scan_patch_files(ctx, src, source_stats)
        except (RuntimeError, subprocess.SubprocessError) as e:
            log(f"  [{number}/{len(todo)}] {src.sid:<40} error: {str(e)[:120]}")
            continue
        stats[src.sid] = source_stats
        found += candidates
        if candidates or source_stats.unique_commits:
            log(f"  [{number}/{len(todo)}] {src.sid:<40} {source_stats.unique_commits:>4} only-downstream "
                f"-> {len(candidates)} candidates")
    found = group_candidates(found)
    now = utcnow()
    for candidate in found:
        score_candidate(candidate, now)
    new_keys = {candidate.key for candidate in found if state.see(candidate)}
    state.save()
    if not args.all:
        found = [c for c in found if state.verdict(c.key) not in ("rejected", "merged")]
    found.sort(key=lambda c: (-c.score, c.sid))
    found, hidden = limit_per_source(found, args.max_per_source)
    if args.top:
        found = found[:args.top]
    out = Path(args.out).expanduser() if args.out else cache / "report"
    write_patches(found, ctx, out)
    report = write_report(found, stats, registry, state, ctx, out, new_keys, hidden)
    log("")
    log(f"{len(found)} candidates ({len(new_keys)} new) -> {report}")
    for candidate in found[:args.summary]:
        mark = "NEW " if candidate.key in new_keys else "    "
        log(f"  {mark}{candidate.score:>3}  {candidate.sid:<34} {candidate.subject[:72]}")
    return 0


def cmd_sources(args, repo: Repo, registry: Registry) -> int:
    if args.add:
        src, added = registry.add(args.add, "manual", note=args.note)
        registry.save()
        log(f"{'added' if added else 'already present'}: {src.sid} -> {src.url}")
        return 0
    if args.retire:
        matches = [s for s in registry.sources.values() if args.retire in s.sid]
        for src in matches:
            src.retired = True
        registry.save()
        log(f"retired {len(matches)} sources")
        return 0
    rows = sorted(registry.sources.values(), key=lambda s: (s.retired, s.kind, s.sid))
    log(f"{len(rows)} sources in {registry.path}")
    for src in rows:
        if args.retired_too or not src.retired:
            flag = "retired" if src.retired else src.status or "never fetched"
            log(f"  {src.sid:<42} {src.kind:<9} {src.pushed_at[:10]:<11} {flag[:60]}")
    return 0


def cmd_triage(args, repo: Repo, registry: Registry) -> int:
    state = State(Path(args.cache).expanduser() / "state.json")
    if args.list:
        for key, entry in sorted(state.keys.items(), key=lambda kv: kv[1].get("verdict", "")):
            if args.verdict and entry.get("verdict") != args.verdict:
                continue
            log(f"  {short(key, 12)}  {entry.get('verdict', 'new'):<9} {entry.get('source', ''):<30} "
                f"{entry.get('subject', '')[:60]}")
        return 0
    for verdict in VERDICTS:
        for key in getattr(args, verdict) or []:
            if state.set_verdict(key, verdict, args.note):
                log(f"{short(key, 12)} -> {verdict}")
            else:
                log(f"{key}: no single match in the state file")
    state.save()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help=f"cache directory (default {DEFAULT_CACHE})")
    parser.add_argument("--upstream", default=str(ROOT),
                        help="local upstream clone, used as an object cache (default: this repo)")
    parser.add_argument("--upstream-url", default="",
                        help="upstream remote to fetch refs from (default: https://github.com/<repo>.git)")
    parser.add_argument("--repo", default=UPSTREAM_REPO, help="github repository whose forks to walk")
    sub = parser.add_subparsers(dest="command")

    def add_discover_args(p):
        p.add_argument("--since-days", type=int, default=730, help="ignore trees with no push since")
        p.add_argument("--depth", type=int, default=2, help="how deep to walk forks-of-forks")
        p.add_argument("--include-untouched", action="store_true", help="keep forks nobody ever pushed to")
        p.add_argument("--no-github", action="store_true", help="skip the github fork list")
        p.add_argument("--forges", action="store_true", help="also keyword-search gitlab/codeberg instances")
        p.add_argument("--sources-file", default=str(SOURCES_FILE), help="registry of non-github trees")
        p.add_argument("--token", default="", help="github token (default: $GITHUB_TOKEN or gh auth token)")

    def add_fetch_args(p):
        p.add_argument("--jobs", type=int, default=6, help="parallel fetches")
        p.add_argument("--fetch-timeout", type=int, default=300, help="seconds per fetch")
        p.add_argument("--limit", type=int, default=0, help="only fetch the N most recently pushed")

    def add_scan_args(p):
        p.add_argument("--out", default="", help="report directory (default <cache>/report)")
        p.add_argument("--source", default="", help="only scan sources whose id contains this")
        p.add_argument("--branch", action="append", help="upstream branch(es) for the already-applied check")
        p.add_argument("--max-commits", type=int, default=150, help="per branch, before calling it divergent")
        p.add_argument("--max-per-source", type=int, default=15, help="candidates to show per tree")
        p.add_argument("--upstream-authors", default=UPSTREAM_AUTHORS.pattern,
                       help="emails whose commits cannot be downstream contributions")
        p.add_argument("--top", type=int, default=0, help="only report the N best candidates")
        p.add_argument("--summary", type=int, default=25, help="how many lines to print at the end")
        p.add_argument("--all", action="store_true", help="include candidates triaged away")

    run_parser = sub.add_parser("run", help="discover, fetch and scan (the default)")
    for add in (add_discover_args, add_fetch_args, add_scan_args):
        add(run_parser)
    add_discover_args(sub.add_parser("discover", help="refresh the list of downstream trees"))
    add_fetch_args(sub.add_parser("fetch", help="fetch every registered tree"))
    add_scan_args(sub.add_parser("scan", help="report what is not upstream"))
    sources = sub.add_parser("sources", help="show or edit the registry")
    sources.add_argument("--add", default="", help="add a git URL")
    sources.add_argument("--note", default="", help="note to store with it")
    sources.add_argument("--retire", default="", help="retire sources whose id contains this")
    sources.add_argument("--retired-too", action="store_true", help="list retired sources as well")
    triage = sub.add_parser("triage", help="record what you decided about a candidate")
    triage.add_argument("--list", action="store_true", help="list everything seen so far")
    triage.add_argument("--verdict", default="", choices=("", *VERDICTS), help="filter --list")
    for verdict in VERDICTS:
        triage.add_argument(f"--{verdict}", action="append", help=f"mark these keys as {verdict}")
    triage.add_argument("--note", default="", help="note to store with the verdict")

    commands = {"run", "discover", "fetch", "scan", "sources", "triage"}
    argv = list(sys.argv[1:] if argv is None else argv)
    if not commands & set(argv):                # bare invocation: do the whole job
        argv.append("run")
    args = parser.parse_args(argv)
    command = args.command
    repo, registry = open_repo(args)
    if command == "run":
        return cmd_discover(args, repo, registry) or cmd_fetch(args, repo, registry) or \
            cmd_scan(args, repo, registry)
    return {"discover": cmd_discover, "fetch": cmd_fetch, "scan": cmd_scan,
            "sources": cmd_sources, "triage": cmd_triage}[command](args, repo, registry)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
