#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Committed-source evolution metrics. No historical code is executed."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import sys
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from source_report import (
    DEFAULT_PATHS, SOURCE_EXTENSIONS, C_LIKE_EXTENSIONS, CODEC_ROLE_NAMES,
    codec_names_from_loader, git, git_text, line_stats_for, markdown_table,
    resolve_default_paths, path_matches, xpra_module_base,
)

METRIC_VERSION = 1
DEFAULT_REFS = ("v1.0.x", "v3.1.x", "v5.1.x", "v7.x", "master")
GROUPS = {"python": (".py",), "cython": (".pyx", ".pxd", ".pxi"), "native": (".c", ".h", ".cpp", ".m")}
DEFINITIONS = {
    "size": "Physical lines and estimated SLOC: nonblank, non-comment lines; Python docstrings count as code.",
    "scope": "Tracked regular source files in selected paths; other source extensions are reported separately.",
    "codecs": "Unique loader ALL_CODECS identities before platform filtering; not formats or installed libraries.",
    "subsystems": "Implementation modules in mixins/subsystem directories, excluding initializers and stubs; structural counts.",
    "cbo": "Static distinct internal class references per Python class; self and inheritance-only references excluded.",
    "imports": "Statically declared internal Python imports, including conditional and function-local imports.",
    "function_size": "Physical lines from def/async def through end_lineno, including nested bodies and docstrings.",
    "churn": "Source additions/deletions and file-change records during preceding 365 days, excluding merge commits; renames followed.",
    "age": "Snapshot committer time minus blamed committer time, in days, for estimated SLOC; whitespace ignored, moves detected.",
    "survival": "Fraction of baseline estimated SLOC still present along first-parent history; whitespace ignored, moves detected.",
    "limitations": "SLOC is a lexical estimate. AST metrics cover parseable .py only; dynamic imports/dispatch and inferred types are unresolved.",
}


def timestamp(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())


def distribution(values) -> dict[str, Any]:
    values = sorted(values)
    n = len(values)
    return {
        "count": n, "median": (values[(n - 1) // 2] + values[n // 2]) / 2 if n else None,
        "p90": values[math.ceil(n * .9) - 1] if n else None, "max": values[-1] if n else None,
    }


class Cache:
    def __init__(self, directory: str = ""):
        self.directory = Path(directory) if directory else None
        self.memory: dict[str, Any] = {}

    def get_or_create(self, kind: str, key: Any, create):
        digest = hashlib.sha256(json.dumps([METRIC_VERSION, kind, key], sort_keys=True).encode()).hexdigest()
        if digest in self.memory:
            return self.memory[digest]
        path = self.directory / kind / f"{digest}.json" if self.directory else None
        try:
            value = json.loads(path.read_text()) if path else None
        except (OSError, ValueError):
            value = None
        if value is None:
            value = create()
            # Incomplete results must be retryable rather than poisoning a cache.
            if path and not value.get("errors"):
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(value, sort_keys=True))
                temporary.replace(path)
        self.memory[digest] = value
        return value


def tree_files(repo: Path, commit: str, paths) -> tuple[tuple[str, ...], dict[str, str]]:
    records = git(repo, ("ls-tree", "-r", "-z", "--full-tree", commit)).split(b"\0")
    blobs = {}
    for record in records:
        if not record:
            continue
        metadata, filename = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        if kind == "blob" and mode in ("100644", "100755"):
            blobs[filename.decode("utf-8", "surrogateescape")] = oid
    resolved = resolve_default_paths(tuple(blobs), paths)
    return resolved, {p: oid for p, oid in blobs.items() if path_matches(p, resolved) and Path(p).suffix in SOURCE_EXTENSIONS}


def read_blobs(repo: Path, blobs: dict[str, str]) -> dict[str, bytes]:
    """One Git process for all files, preserving byte lengths and unusual filenames."""
    import subprocess
    oids = list(dict.fromkeys(blobs.values()))
    proc = subprocess.run(("git", "-C", str(repo), "cat-file", "--batch"),
                          input=("\n".join(oids) + "\n").encode(), capture_output=True, check=True)
    content, offset, data = {}, 0, proc.stdout
    for oid in oids:
        end = data.index(b"\n", offset)
        header = data[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"Cannot read blob {oid}: {header!r}")
        size = int(header[2])
        content[oid] = data[end + 1:end + 1 + size]
        offset = end + size + 2
    return {p: content[oid] for p, oid in blobs.items()}


def module_name(path: str) -> str:
    relative = xpra_module_base(path) or path
    parts = Path(relative).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("xpra", *parts)) if xpra_module_base(path) else ".".join(parts)


def dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


class PythonAnalysis(ast.NodeVisitor):
    def __init__(self, module: str, package: bool):
        self.module = module
        self.package = module if package else module.rpartition(".")[0]
        self.scopes: list[dict[str, str]] = [{}]
        self.owners: list[str] = []
        self.classes: dict[str, dict] = {}
        self.imports: set[str] = set()
        self.functions: list[dict] = []
        self.qualifiers: list[str] = []

    def resolve(self, name: str) -> str:
        first, _, rest = name.partition(".")
        for scope in reversed(self.scopes):
            if first in scope:
                value = scope[first]
                return value + (f".{rest}" if rest else "") if value else ""
        return ""

    def bind_definitions(self, body):
        for node in body:
            if isinstance(node, ast.ClassDef):
                self.scopes[-1][node.name] = ".".join((self.module, *self.qualifiers, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.scopes[-1][node.name] = ""
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.bind_import(node)

    def bind_import(self, node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.imports.add(alias.name)
                self.scopes[-1][alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        else:
            base = node.module or ""
            if node.level:
                parts = self.package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            for alias in node.names:
                target = f"{base}.{alias.name}" if base else alias.name
                self.imports.add(target)
                if alias.name != "*":
                    self.scopes[-1][alias.asname or alias.name] = target

    def visit_Import(self, node):
        self.bind_import(node)

    visit_ImportFrom = visit_Import

    def visit_ClassDef(self, node):
        name = ".".join((self.module, *self.qualifiers, node.name))
        self.scopes[-1][node.name] = name
        self.classes[name] = {"references": [], "unresolved": [], "bases": [self.resolve(dotted(x)) for x in node.bases]}
        self.owners.append(name)
        self.qualifiers.append(node.name)
        self.scopes.append({})
        self.bind_definitions(node.body)
        # Bases are tracked independently and do not contribute inheritance-only CBO.
        for item in (*node.decorator_list, *node.body):
            self.visit(item)
        self.scopes.pop()
        self.qualifiers.pop()
        self.owners.pop()

    def visit_FunctionDef(self, node):
        self.functions.append({"name": ".".join((*self.qualifiers, node.name)), "lines": node.end_lineno - node.lineno + 1})
        for item in (*node.decorator_list, *node.args.defaults, *[x for x in node.args.kw_defaults if x]):
            self.visit(item)
        self.qualifiers.append(node.name)
        args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        self.scopes.append({arg.arg: "" for arg in args})
        for arg in (node.args.vararg, node.args.kwarg):
            if arg:
                self.scopes[-1][arg.arg] = ""
        for item in (*args, node.returns):
            if item:
                self.visit(item)
        self.bind_definitions(node.body)
        for item in node.body:
            self.visit(item)
        self.scopes.pop()
        self.qualifiers.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and self.owners:
            self.reference(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.scopes[-1][node.id] = ""

    def visit_Attribute(self, node):
        name = dotted(node)
        if name and self.owners and isinstance(node.ctx, ast.Load):
            self.reference(name)
        self.generic_visit(node)

    def reference(self, name):
        target = self.resolve(name)
        record = self.classes[self.owners[-1]]
        record["references" if target else "unresolved"].append(target or name)


def analyze_python(data: bytes, module: str, package: bool) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(data)
        visitor = PythonAnalysis(module, package)
        visitor.bind_definitions(tree.body)
        visitor.visit(tree)
        return {"classes": visitor.classes, "imports": sorted(visitor.imports), "functions": visitor.functions, "errors": []}
    except (SyntaxError, ValueError, UnicodeError) as e:
        return {"classes": {}, "imports": [], "functions": [], "errors": [str(e)]}


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Kosaraju traversal, avoiding recursion limits on large histories."""
    seen, order = set(), []
    for start in sorted(graph):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend((other, False) for other in sorted(graph[node], reverse=True) if other not in seen)
    reverse = {node: set() for node in graph}
    for node, others in graph.items():
        for other in others:
            reverse[other].add(node)
    seen, result = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        stack, component = [start], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            stack.extend(reverse[node] - seen)
        if len(component) > 1:
            result.append(sorted(component))
    return sorted(result)


def coupling(analyses: dict[str, dict]) -> dict:
    classes = {name: record for analysis in analyses.values() for name, record in analysis["classes"].items()}
    class_rows = []
    for name, record in sorted(classes.items()):
        targets, unresolved = set(), set(record["unresolved"])
        for reference in record["references"]:
            candidate = reference
            while candidate and candidate not in classes:
                candidate = candidate.rpartition(".")[0]
            if candidate:
                targets.add(candidate)
            else:
                unresolved.add(reference)
        targets.discard(name)
        class_rows.append({"name": name, "cbo": len(targets), "targets": sorted(targets),
                           "bases": sorted(set(filter(None, record["bases"]))), "unresolved": sorted(unresolved)})
    graph = {name: set() for name in analyses}
    unresolved_imports = {}
    for name, analysis in analyses.items():
        unresolved_imports[name] = []
        for target in analysis["imports"]:
            candidate = target
            while candidate and candidate not in graph:
                candidate = candidate.rpartition(".")[0]
            if candidate and candidate != name:
                graph[name].add(candidate)
            elif not candidate:
                unresolved_imports[name].append(target)
    incoming = Counter(target for targets in graph.values() for target in targets)
    modules = [{"name": name, "fan_in": incoming[name], "fan_out": len(targets), "targets": sorted(targets),
                "unresolved_imports": unresolved_imports[name]} for name, targets in sorted(graph.items())]
    return {"cbo": distribution(row["cbo"] for row in class_rows), "classes": class_rows,
            "fan_in": distribution(row["fan_in"] for row in modules), "fan_out": distribution(row["fan_out"] for row in modules),
            "modules": modules, "cycles": cycles(graph)}


def subsystem_counts(files) -> dict:
    result = {}
    for side in ("client", "server"):
        names = {"mixins": [], "subsystem": []}
        for path in files:
            relative = xpra_module_base(path)
            parts = relative.split("/")
            if not parts or parts[0] != side or Path(path).suffix not in (".py", ".pyx"):
                continue
            stem = Path(path).stem
            if stem == "__init__" or "stub" in stem:
                continue
            for architecture in names:
                if architecture in parts[1:-1]:
                    names[architecture].append(relative)
        counts = {key: len(value) for key, value in names.items()}
        active = [key for key, value in counts.items() if value]
        result[side] = {"architecture": "+".join(active) or "pre-subsystem", "count": sum(counts.values()) if active else None,
                        "counts": counts, "modules": names}
    return result


def codec_counts(content: dict[str, bytes]) -> dict:
    loader = next((data for path, data in content.items() if xpra_module_base(path) == "codecs/loader.py"), None)
    errors, names = [], []
    if loader is None:
        errors.append("No codec loader in selected scope")
    else:
        try:
            names = codec_names_from_loader(loader.decode("utf-8"), strict=True)
            if not names:
                errors.append("ALL_CODECS could not be resolved")
        except (SyntaxError, ValueError, UnicodeError, TypeError) as e:
            errors.append(str(e))
    roles = {role: [] for role in ("encoder", "decoder", "converter", "filter", "capture", "other")}
    for name in names:
        if name.startswith("enc_") or name.startswith("nvenc"):
            role = "encoder"
        elif name.startswith("dec_") or name == "nvdec":
            role = "decoder"
        elif name.startswith("csc_"):
            role = "converter"
        elif name.startswith("filter_"):
            role = "filter"
        elif name in ("v4l2", "evdi", "drm", "nvfbc"):
            role = "capture"
        else:
            role = "other"
        roles[role].append(name)
    implementations = sorted(p for p in content if "codecs/" in p and Path(p).stem in CODEC_ROLE_NAMES)
    return {"count": len(names) if not errors else None, "names": names, "roles": roles,
            "implementation_files": implementations, "errors": errors}


def code_lines(path: str, data: bytes) -> set[int]:
    """Use the same lexical SLOC convention as source_report, retaining line numbers."""
    lines = data.decode("utf-8", "replace").splitlines()
    if Path(path).suffix not in C_LIKE_EXTENSIONS:
        prefix = "--" if Path(path).suffix == ".lua" else "#"
        return {i for i, line in enumerate(lines, 1) if line.strip() and not line.lstrip().startswith(prefix)}
    result, in_block = set(), False
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        code, i = [], 0
        while i < len(line):
            if in_block:
                end = line.find("*/", i)
                if end < 0:
                    break
                in_block, i = False, end + 2
                continue
            block, inline = line.find("/*", i), line.find("//", i)
            markers = [x for x in (block, inline) if x >= 0]
            if not markers:
                code.append(line[i:])
                break
            marker = min(markers)
            code.append(line[i:marker])
            if inline >= 0 and inline == marker:
                break
            in_block, i = True, marker + 2
        if "".join(code).strip():
            result.add(number)
    return result


def blame_lines(repo: Path, revision: str, path: str, reverse: bool = False):
    args = ["blame", "--line-porcelain", "--root", "-w", "-M", "-C"]
    if reverse:
        args.extend(("--reverse", "--first-parent"))
    args.extend((revision, "--", path))
    commit, number, date = "", 0, 0
    for line in git(repo, args).decode("utf-8", "replace").splitlines():
        if line.startswith("\t"):
            yield number, commit, date
        elif line.startswith("committer-time "):
            date = int(line.split()[1])
        else:
            fields = line.split()
            if len(fields) in (3, 4) and len(fields[0].lstrip("^")) in (40, 64):
                commit = fields[0].lstrip("^")
                number = int(fields[1] if reverse else fields[2])


def line_age(repo: Path, commit: str, at: int, content: dict[str, bytes]) -> dict:
    ages, errors = [], []
    expected = 0
    for path, data in content.items():
        selected = code_lines(path, data)
        expected += len(selected)
        try:
            ages.extend(max(0, (at - date) / 86400) for number, _, date in blame_lines(repo, commit, path) if number in selected)
        except RuntimeError as e:
            errors.append({"path": path, "error": str(e)})
    bands = {"<1 year": 0, "1–3 years": 0, "3–5 years": 0, "5–10 years": 0, "10+ years": 0}
    for age in ages:
        index = sum(age >= boundary for boundary in (365, 1095, 1825, 3650))
        bands[list(bands)[index]] += 1
    if len(ages) != expected and not errors:
        errors.append({"error": f"Blame returned {len(ages)} of {expected} source lines"})
    return {**distribution(ages), "bands": bands, "expected_lines": expected, "errors": errors, "complete": not errors}


def churn(repo: Path, commit: str, at: int, paths) -> dict:
    since = datetime.fromtimestamp(at, timezone.utc) - timedelta(days=365)
    scope = ("xpra", "src/xpra") if tuple(paths) == DEFAULT_PATHS else tuple(paths)
    raw = git(repo, ("log", "--reverse", "--no-merges", "--since-as-filter=" + since.isoformat(),
                     "--until=" + datetime.fromtimestamp(at, timezone.utc).isoformat(), "--format=", "--numstat", "-z", "-M",
                     commit, "--", *scope)).decode("utf-8", "surrogateescape").split("\0")
    rows: dict[str, dict] = {}
    i = 0
    while i < len(raw):
        record = raw[i].lstrip("\n")
        i += 1
        if not record:
            continue
        added, deleted, path = record.split("\t", 2)
        old = ""
        if not path:
            old, path = raw[i:i + 2]
            i += 2
        path = xpra_module_base(path) or path
        old = xpra_module_base(old) or old
        if Path(path).suffix not in SOURCE_EXTENSIONS:
            continue
        row = rows.setdefault(path, {"path": path, "additions": 0, "deletions": 0, "changes": 0})
        if old and old != path and old in rows:
            previous = rows.pop(old)
            for key in ("additions", "deletions", "changes"):
                row[key] += previous[key]
        if added != "-" and deleted != "-":
            row["additions"] += int(added)
            row["deletions"] += int(deleted)
        row["changes"] += 1
    return {"since": since.isoformat(), "days": 365,
            "files": sorted(rows.values(), key=lambda r: (-(r["additions"] + r["deletions"]), r["path"]))}


def snapshot(repo: Path, commit: str, paths, age: bool, cache: Cache) -> dict:
    def collect():
        print(f"Collecting {commit[:12]}", file=sys.stderr)
        resolved, blobs = tree_files(repo, commit, paths)
        content = read_blobs(repo, blobs)
        by_type, analyses, files, errors = {}, {}, [], []
        python_files = 0
        for path, data in content.items():
            suffix = Path(path).suffix
            stats = cache.get_or_create("lines", [blobs[path], suffix], lambda: vars(line_stats_for(path, data)))
            total = by_type.setdefault(suffix, {key: 0 for key in stats})
            for key, value in stats.items():
                total[key] += value
            files.append({"path": path, **stats})
            if suffix == ".py":
                python_files += 1
                module = module_name(path)
                analysis = cache.get_or_create(
                    "python", [blobs[path], module, path.endswith("/__init__.py")],
                    lambda: analyze_python(data, module, path.endswith("/__init__.py")),
                )
                if analysis["errors"]:
                    errors.append({"path": path, "metric": "python", "error": "; ".join(analysis["errors"])})
                else:
                    analyses[module] = analysis
        groups = {}
        for name, extensions in GROUPS.items():
            groups[name] = {key: sum(by_type.get(ext, {}).get(key, 0) for ext in extensions)
                            for key in ("files", "lines", "sloc")}
            groups[name]["kloc"] = groups[name]["sloc"] / 1000
        used = {extension for extensions in GROUPS.values() for extension in extensions}
        other = {extension: stats for extension, stats in by_type.items() if extension not in used}
        codecs = codec_counts(content)
        errors.extend({"metric": "codecs", "error": error} for error in codecs["errors"])
        at = int(git_text(repo, ("show", "-s", "--format=%ct", commit)))
        functions = [{"path": path, **fn} for path in content if Path(path).suffix == ".py"
                     for fn in analyses.get(module_name(path), {}).get("functions", [])]
        report = {
            "commit": commit, "commit_date": datetime.fromtimestamp(at, timezone.utc).isoformat(), "paths": resolved,
            "groups": groups, "other_extensions": other, "by_type": by_type, "codecs": codecs,
            "subsystems": subsystem_counts(content), "coupling": coupling(analyses),
            "sizes": {"files": distribution(row["sloc"] for row in files),
                      "functions": distribution(row["lines"] for row in functions),
                      "largest_files": sorted(files, key=lambda row: (-row["sloc"], row["path"]))[:20],
                      "largest_functions": sorted(functions, key=lambda row: (-row["lines"], row["path"]))[:20]},
            "coverage": {"python_files": python_files, "parsed_python_files": len(analyses),
                         "unsupported_files": [path for path in content if Path(path).suffix != ".py"],
                         "classes": sum(len(analysis["classes"]) for analysis in analyses.values())},
            "churn": churn(repo, commit, at, paths), "errors": errors,
        }
        if age:
            report["age"] = line_age(repo, commit, at, content)
            report["errors"].extend({"metric": "age", **error} for error in report["age"]["errors"])
        report["complete"] = not report["errors"]
        return report
    return cache.get_or_create("snapshots", [commit, list(paths), age], collect)


def select_snapshots(repo: Path, tip: str, sample: str, since: str = "", until: str = "") -> list[str]:
    history = [line.split() for line in git_text(repo, ("log", "--first-parent", "--reverse", "--format=%H %ct", tip)).splitlines()]
    first = timestamp(since) if since else float("-inf")
    last = timestamp(until) if until else float("inf")
    if first > last:
        raise ValueError("--since must precede --until")
    selected = []
    if sample == "tags":
        tags = git_text(repo, ("tag", "--list", "v[0-9]*")).splitlines()
        tagged = {git_text(repo, ("rev-parse", f"refs/tags/{tag}^{{commit}}")) for tag in tags}
        selected = [commit for commit, date in history if commit in tagged and first <= int(date) <= last]
    elif sample in ("monthly", "quarterly"):
        periods = {}
        for commit, date in history:
            if first <= int(date) <= last:
                dt = datetime.fromtimestamp(int(date), timezone.utc)
                period = (dt.year, dt.month if sample == "monthly" else (dt.month - 1) // 3)
                periods[period] = commit
        chosen = set(periods.values())
        selected = [commit for commit, _ in history if commit in chosen]
    return list(dict.fromkeys([*selected, tip]))


def survival(repo: Path, base: str, end: str, paths, cache: Cache) -> dict:
    def collect():
        chain = git_text(repo, ("rev-list", "--first-parent", "--reverse", end)).splitlines()
        if base not in chain:
            raise ValueError("Survival BASE must be on END's first-parent history")
        chain = chain[chain.index(base):]
        positions = {commit: i for i, commit in enumerate(chain)}
        dates = [int(line.split()[1]) for line in git_text(
            repo, ("log", "--first-parent", "--reverse", "--format=%H %ct", end)).splitlines() if line.split()[0] in positions]
        _, blobs = tree_files(repo, base, paths)
        content = read_blobs(repo, blobs)
        deaths, total, observed, errors = Counter(), 0, 0, []
        for path, data in content.items():
            selected = code_lines(path, data)
            total += len(selected)
            try:
                records = list(blame_lines(repo, f"{base}..{end}", path, reverse=True)) if base != end else []
                if base == end:
                    observed += len(selected)
                for number, last_commit, _ in records:
                    if number not in selected:
                        continue
                    observed += 1
                    last_index = positions[last_commit]
                    if last_index < len(chain) - 1:
                        deaths[last_index + 1] += 1
            except (RuntimeError, KeyError) as e:
                errors.append({"path": path, "error": str(e)})
        remaining, points, half_life = observed, [], None
        for index, commit in enumerate(chain):
            remaining -= deaths[index]
            if index in (0, len(chain) - 1) or deaths[index]:
                days = max(0, (dates[index] - dates[0]) / 86400)
                fraction = remaining / total if total else None
                points.append({"commit": commit, "days": days, "remaining_lines": remaining, "fraction": fraction})
                if total and fraction <= .5 and half_life is None:
                    half_life = days
        complete = not errors and observed == total
        return {"base": base, "end": end, "baseline_lines": total, "observed_lines": observed,
                "observation_days": max(0, (dates[-1] - dates[0]) / 86400),
                "half_life_days": half_life if complete else None,
                "status": "incomplete" if not complete else "empty" if not total else "reached" if half_life is not None else "not reached",
                "points": points if complete and total else [], "complete": complete, "errors": errors}
    return cache.get_or_create("survival", [base, end, list(paths)], collect)


def collect_evolution(args) -> dict:
    from source_report import resolve_repo
    repo = resolve_repo(args.repo)
    if (args.age or args.survival) and git_text(repo, ("rev-parse", "--is-shallow-repository")) == "true":
        raise ValueError("Lifetime analysis requires complete history; this repository is shallow")
    cache = Cache(args.cache_dir)
    # Pin every user-supplied ref before doing any collection.
    refs = args.refs or DEFAULT_REFS
    tips = [(ref, git_text(repo, ("rev-parse", "--verify", f"{ref}^{{commit}}"))) for ref in refs]
    ranges = []
    for value in args.survival:
        if value.count("..") != 1 or "..." in value:
            raise ValueError("--survival requires BASE..END")
        base, end = value.split("..")
        if not base or not end:
            raise ValueError("--survival requires explicit BASE and END")
        ranges.append((value, git_text(repo, ("rev-parse", "--verify", f"{base}^{{commit}}")),
                       git_text(repo, ("rev-parse", "--verify", f"{end}^{{commit}}"))))
    snapshots, series = {}, []
    for ref, tip in tips:
        commits = select_snapshots(repo, tip, args.sample, args.since, args.until)
        for commit in commits:
            if commit not in snapshots:
                snapshots[commit] = snapshot(repo, commit, tuple(args.paths), args.age, cache)
        series.append({"ref": ref, "tip": tip, "commits": commits})
    survival_reports = [{"label": label, **survival(repo, base, end, tuple(args.paths), cache)} for label, base, end in ranges]
    options = {"sample": args.sample, "since": args.since, "until": args.until, "age": args.age, "paths": args.paths}
    return {"schema_version": 1, "metric_version": METRIC_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
            "definitions": DEFINITIONS, "options": options,
            "series": series, "snapshots": list(snapshots.values()), "survival": survival_reports}


def flat_rows(report: dict) -> list[dict]:
    snapshots = {row["commit"]: row for row in report["snapshots"]}
    rows = []
    for series in report["series"]:
        for commit in series["commits"]:
            snap = snapshots[commit]
            row = {"ref": series["ref"], "commit": commit, "commit_date": snap["commit_date"], "is_tip": commit == series["tip"],
                   "complete": snap["complete"]}
            for group, stats in snap["groups"].items():
                row.update({f"{group}_{key}": value for key, value in stats.items()})
            row.update({"codecs": snap["codecs"]["count"], "client_subsystems": snap["subsystems"]["client"]["count"],
                        "server_subsystems": snap["subsystems"]["server"]["count"],
                        "cbo_median": snap["coupling"]["cbo"]["median"], "cbo_p90": snap["coupling"]["cbo"]["p90"],
                        "parsed_python_files": snap["coverage"]["parsed_python_files"], "python_files": snap["coverage"]["python_files"],
                        "median_age_days": snap.get("age", {}).get("median")})
            rows.append(row)
    return rows


def csv_data(report: dict) -> str:
    stream = io.StringIO(newline="")
    rows = flat_rows(report)
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return stream.getvalue()


def markdown_report(report: dict, graphs=()) -> str:
    tips = [row for row in flat_rows(report) if row["is_tip"]]
    headers = ("Ref", "Commit date", "Python KLOC", "Cython KLOC", "Native KLOC", "Codecs", "Client subsystems", "Server subsystems")
    rows = [(r["ref"], r["commit_date"][:10], *[round(r[f"{g}_kloc"], 2) for g in GROUPS],
             *[r[k] if r[k] is not None else "N/A" for k in ("codecs", "client_subsystems", "server_subsystems")]) for r in tips]
    lines = ["# Xpra codebase evolution", "", "[JSON data](metrics.json) · [CSV data](metrics.csv)", "", markdown_table(headers, rows)]
    for graph in graphs:
        lines.extend(("", f"![{graph.replace('-', ' ')}]({graph}.svg)", "", f"[PNG]({graph}.png)"))
    lines.extend(("", "## Methodology", ""))
    lines.extend(f"- **{key}**: {value}" for key, value in report["definitions"].items())
    lines.extend(("", "Branch bars compare tips as categories; history uses actual commit dates. N/A values are unavailable, not zero.",
                  "See JSON for individual identities, rankings, dependency cycles, analysis coverage, and errors.", "", "## Analysis coverage", ""))
    for snap in report["snapshots"]:
        coverage = snap["coverage"]
        lines.append(f"- `{snap['commit'][:12]}`: {coverage['parsed_python_files']}/{coverage['python_files']} Python files parsed; "
                     f"{len(coverage['unsupported_files'])} non-Python files excluded from AST metrics; {len(snap['errors'])} diagnostic(s).")
    for item in report["survival"]:
        half = f"{item['half_life_days']:.1f} days" if item["half_life_days"] is not None else item["status"]
        lines.extend(("", f"Survival `{item['label']}`: half-life **{half}**, observed for {item['observation_days']:.1f} days."))
    return "\n".join(lines) + "\n"


def write_data(report: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (directory / "metrics.csv").write_text(csv_data(report))
    (directory / "report.md").write_text(markdown_report(report))
