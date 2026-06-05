#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Generate source-code metrics from files tracked by Git."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".pyx", ".pxd", ".pxi",
    ".c", ".h", ".cpp", ".hpp", ".cxx", ".hxx", ".m", ".mm", ".cu", ".cuh",
    ".sh", ".bash", ".lua",
}
PYTHON_MODULE_EXTENSIONS = {".py", ".pyx"}
PYTHON_LIKE_EXTENSIONS = {".py", ".pyi", ".pyx", ".pxd", ".pxi"}
C_LIKE_EXTENSIONS = {".c", ".h", ".cpp", ".hpp", ".cxx", ".hxx", ".m", ".mm", ".cu", ".cuh"}
SCRIPT_EXTENSIONS = {".sh", ".bash"}
LUA_EXTENSIONS = {".lua"}
CODEC_ROLE_NAMES = {
    "api", "argb", "capture", "converter", "decoder", "drm", "encoder", "filter", "nvencode", "virtual",
}
DEFAULT_PATHS = ("xpra",)
BRANCH_DATE_OVERRIDES = {
    "v1.0.x": "2016",
    "v3.1.x": "2019",
    "v5.1.x": "2023",
}
TYPE_ORDER = {
    ".py": 0,
    ".pyx": 1,
    ".pxd": 2,
    ".pxi": 3,
    ".c": 4,
    ".h": 5,
    ".cpp": 6,
    ".hpp": 7,
    ".m": 8,
    ".mm": 9,
    ".sh": 10,
    ".bash": 11,
    ".lua": 12,
    "<none>": 99,
}


class GitCommandError(RuntimeError):
    def __init__(self, repo: Path, args: Sequence[str], stderr: bytes):
        self.repo = repo
        self.args = tuple(args)
        self.stderr = stderr.decode("utf-8", "replace").strip()
        super().__init__(f"git -C {repo} {' '.join(args)} failed: {self.stderr}")


@dataclass
class LineStats:
    files: int = 0
    bytes: int = 0
    lines: int = 0
    blank_lines: int = 0
    comment_lines: int = 0
    sloc: int = 0

    def add(self, other: "LineStats") -> None:
        self.files += other.files
        self.bytes += other.bytes
        self.lines += other.lines
        self.blank_lines += other.blank_lines
        self.comment_lines += other.comment_lines
        self.sloc += other.sloc


@dataclass(frozen=True)
class FileMetrics:
    path: str
    file_type: str
    bytes: int
    lines: int
    blank_lines: int
    comment_lines: int
    sloc: int


def git(repo: Path, args: Sequence[str], check: bool = True) -> bytes:
    proc = subprocess.run(
        ("git", "-C", str(repo), *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitCommandError(repo, args, proc.stderr)
    return proc.stdout


def git_text(repo: Path, args: Sequence[str], check: bool = True) -> str:
    return git(repo, args, check=check).decode("utf-8", "replace").strip()


def git_optional(repo: Path, args: Sequence[str]) -> str:
    proc = subprocess.run(
        ("git", "-C", str(repo), *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def resolve_repo(path: str) -> Path:
    repo = Path(path).resolve()
    root = git_text(repo, ("rev-parse", "--show-toplevel"))
    return Path(root)


def split0(data: bytes) -> list[str]:
    if not data:
        return []
    return [x.decode("utf-8", "surrogateescape") for x in data.rstrip(b"\0").split(b"\0")]


class FileSource:
    label = "tracked"

    def __init__(self, repo: Path, ref: str):
        self.repo = repo
        self.ref = ref

    def list_files(self) -> list[str]:
        raise NotImplementedError

    def read_file(self, path: str) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        """ CheckoutSource overrides this method """


class GitTreeSource(FileSource):
    label = "git-tree"

    def list_files(self) -> list[str]:
        return split0(git(self.repo, ("ls-tree", "-r", "-z", "--full-tree", "--name-only", self.ref)))

    def read_file(self, path: str) -> bytes:
        return git(self.repo, ("show", f"{self.ref}:{path}"))


class WorktreeSource(FileSource):
    label = "worktree"

    def list_files(self) -> list[str]:
        return split0(git(self.repo, ("ls-files", "-z")))

    def read_file(self, path: str) -> bytes:
        return (self.repo / path).read_bytes()


class CheckoutSource(WorktreeSource):
    label = "fresh-checkout"

    def __init__(self, repo: Path, ref: str):
        self.tempdir = tempfile.TemporaryDirectory(prefix="xpra-source-report-")
        checkout = Path(self.tempdir.name) / "repo"
        subprocess.run(
            ("git", "clone", "--quiet", "--no-checkout", str(repo), str(checkout)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        git(checkout, ("checkout", "--quiet", ref))
        super().__init__(checkout, "HEAD")
        self.requested_ref = ref

    def close(self) -> None:
        self.tempdir.cleanup()


def file_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return suffix or "<none>"


def path_matches(path: str, paths: Sequence[str]) -> bool:
    if not paths:
        return True
    return any(path == prefix.rstrip("/") or path.startswith(f"{prefix.rstrip('/')}/") for prefix in paths)


def default_path_candidates() -> tuple[str, ...]:
    return DEFAULT_PATHS + ("src/xpra",)


def resolve_default_paths(files: Sequence[str], paths: Sequence[str]) -> tuple[str, ...]:
    if tuple(paths) != DEFAULT_PATHS:
        return tuple(paths)
    for candidate in default_path_candidates():
        if any(path == candidate or path.startswith(f"{candidate}/") for path in files):
            return (candidate,)
    return DEFAULT_PATHS


def xpra_module_base(path: str) -> str:
    for prefix in ("xpra/", "src/xpra/"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return ""


def is_source_path(path: str, paths: Sequence[str]) -> bool:
    if not path_matches(path, paths):
        return False
    ftype = file_type(path)
    if ftype in SOURCE_EXTENSIONS:
        return True
    return ftype == "<none>" and path.startswith("fs/bin/")


def decode_source(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def line_stats_for(path: str, data: bytes) -> LineStats:
    ftype = file_type(path)
    text = decode_source(data)
    lines = text.splitlines()
    stats = LineStats(files=1, bytes=len(data), lines=len(lines))
    if ftype in C_LIKE_EXTENSIONS:
        add_c_like_line_stats(lines, stats)
    elif ftype in PYTHON_LIKE_EXTENSIONS or ftype in SCRIPT_EXTENSIONS or ftype == "<none>":
        add_prefix_comment_line_stats(lines, stats, "#")
    elif ftype in LUA_EXTENSIONS:
        add_prefix_comment_line_stats(lines, stats, "--")
    else:
        add_plain_line_stats(lines, stats)
    return stats


def add_plain_line_stats(lines: Sequence[str], stats: LineStats) -> None:
    for line in lines:
        if line.strip():
            stats.sloc += 1
        else:
            stats.blank_lines += 1


def add_prefix_comment_line_stats(lines: Sequence[str], stats: LineStats, prefix: str) -> None:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            stats.blank_lines += 1
        elif stripped.startswith(prefix):
            stats.comment_lines += 1
        else:
            stats.sloc += 1


def add_c_like_line_stats(lines: Sequence[str], stats: LineStats) -> None:
    in_block = False
    for line in lines:
        if not line.strip():
            stats.blank_lines += 1
            continue
        code = []
        i = 0
        while i < len(line):
            if in_block:
                end = line.find("*/", i)
                if end < 0:
                    i = len(line)
                else:
                    in_block = False
                    i = end + 2
                continue
            block = line.find("/*", i)
            inline = line.find("//", i)
            markers = [x for x in (block, inline) if x >= 0]
            if not markers:
                code.append(line[i:])
                break
            marker = min(markers)
            code.append(line[i:marker])
            if inline >= 0 and inline == marker:
                break
            in_block = True
            i = marker + 2
        if "".join(code).strip():
            stats.sloc += 1
        else:
            stats.comment_lines += 1


def modules_from_files(files: Iterable[str]) -> dict[str, Any]:
    module_names = []
    packages = []
    cython_modules = []
    python_modules = []
    for path in files:
        relative = xpra_module_base(path)
        if not relative:
            continue
        ftype = file_type(path)
        if ftype not in PYTHON_MODULE_EXTENSIONS:
            continue
        base = relative[: -len(ftype)]
        parts = base.split("/")
        if parts[-1] == "__init__":
            name = ".".join(("xpra", *parts[:-1]))
            packages.append(name)
        else:
            name = ".".join(("xpra", *parts))
            if ftype == ".pyx":
                cython_modules.append(name)
            else:
                python_modules.append(name)
        if name:
            module_names.append(name)
    return {
        "modules": len(set(module_names)),
        "packages": len(set(packages)),
        "python_modules": len(set(python_modules)),
        "cython_modules": len(set(cython_modules)),
        "sample": sorted(set(module_names))[:20],
    }


def codecs_from_files(files: Iterable[str], source: FileSource) -> dict[str, Any]:
    files = tuple(files)
    package_names = []
    top_level_packages = set()
    implementation_modules = []
    for path in files:
        relative = xpra_module_base(path)
        if not relative.startswith("codecs/"):
            continue
        if relative.endswith("/__init__.py") and relative != "codecs/__init__.py":
            package = ".".join(("xpra", *relative[: -len("/__init__.py")].split("/")))
            package_names.append(package)
            parts = relative.split("/")
            if len(parts) == 3:
                top_level_packages.add(package)
            continue
        ftype = file_type(path)
        if ftype in PYTHON_MODULE_EXTENSIONS:
            stem = Path(path).stem
            if stem in CODEC_ROLE_NAMES:
                implementation_modules.append(".".join(("xpra", *relative[: -len(ftype)].split("/"))))

    loader_codec_names = []
    loader_path = next((path for path in files if xpra_module_base(path) == "codecs/loader.py"), "")
    if loader_path:
        try:
            loader_codec_names = codec_names_from_loader(decode_source(source.read_file(loader_path)))
        except Exception as e:
            loader_codec_names = [f"error: {e}"]

    return {
        "packages": len(set(package_names)),
        "top_level_packages": len(top_level_packages),
        "implementation_modules": len(set(implementation_modules)),
        "loader_defined_codecs": len(set(x for x in loader_codec_names if not x.startswith("error: "))),
        "package_names": sorted(set(package_names)),
        "top_level_package_names": sorted(top_level_packages),
        "implementation_module_names": sorted(set(implementation_modules)),
        "loader_codec_names": sorted(set(loader_codec_names)),
    }


class LoaderCodecEvaluator(ast.NodeVisitor):
    """Small evaluator for the codec name constants in xpra/codecs/loader.py."""

    def __init__(self):
        self.env: dict[str, Any] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        value = self.eval_expr(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.env[target.id] = value

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value and isinstance(node.target, ast.Name):
            self.env[node.target.id] = self.eval_expr(node.value)

    def eval_expr(self, node: ast.AST, local_env: dict[str, Any] | None = None) -> Any:
        local_env = local_env or {}
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in local_env:
                return local_env[node.id]
            return self.env.get(node.id, ())
        if isinstance(node, ast.Tuple):
            return tuple(self.eval_expr(x, local_env) for x in node.elts)
        if isinstance(node, ast.List):
            return [self.eval_expr(x, local_env) for x in node.elts]
        if isinstance(node, ast.Set):
            return set(self.eval_expr(x, local_env) for x in node.elts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return tuple(self.eval_expr(node.left, local_env)) + tuple(self.eval_expr(node.right, local_env))
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self.eval_expr(x, local_env)) for x in node.values)
        if isinstance(node, ast.FormattedValue):
            return self.eval_expr(node.value, local_env)
        if isinstance(node, ast.GeneratorExp):
            return tuple(self.eval_generator(node, local_env))
        if isinstance(node, ast.Call):
            return self.eval_call(node, local_env)
        return ()

    def eval_call(self, node: ast.Call, local_env: dict[str, Any]) -> Any:
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        args = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                args.extend(tuple(self.eval_expr(arg.value, local_env)))
            else:
                args.append(self.eval_expr(arg, local_env))
        if name in ("filt", "gfilt"):
            if name == "gfilt" and len(args) == 1:
                return tuple(args[0])
            return tuple(args)
        if name == "autoprefix" and len(args) == 2:
            prefix, codec_name = str(args[0]), str(args[1])
            if codec_name.startswith(prefix) or codec_name.endswith(prefix):
                return codec_name.replace("-", "_")
            return f"{prefix}_{codec_name}".replace("-", "_")
        if name == "set" and len(args) == 1:
            return set(args[0])
        return ()

    def eval_generator(self, node: ast.GeneratorExp, local_env: dict[str, Any]) -> Iterable[Any]:
        if len(node.generators) != 1:
            return ()
        generator = node.generators[0]
        if not isinstance(generator.target, ast.Name):
            return ()
        values = self.eval_expr(generator.iter, local_env)
        for value in values:
            env = dict(local_env)
            env[generator.target.id] = value
            yield self.eval_expr(node.elt, env)


def codec_names_from_loader(loader_py: str) -> list[str]:
    tree = ast.parse(loader_py)
    evaluator = LoaderCodecEvaluator()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            evaluator.visit(node)
    names = evaluator.env.get("ALL_CODECS", ())
    return sorted(str(x) for x in names if isinstance(x, str))


def branch_for_ref(repo: Path, ref: str) -> str:
    if ref == "HEAD":
        branch = git_optional(repo, ("rev-parse", "--abbrev-ref", "HEAD"))
        return "" if branch == "HEAD" else branch
    if git_optional(repo, ("rev-parse", "--verify", "--quiet", f"refs/heads/{ref}")):
        return ref
    return ""


def infer_base(repo: Path, ref: str, base: str = "") -> tuple[str, str, str]:
    if base:
        commit = git_optional(repo, ("merge-base", base, ref))
        if commit:
            return base, commit, "explicit"
        return base, "", "explicit"

    candidates = []
    for candidate in ("origin/master", "origin/main", "upstream/master", "upstream/main", "master", "main"):
        candidates.append((candidate, "candidate"))
    branch = branch_for_ref(repo, ref)
    if branch:
        upstream = git_optional(repo, ("rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}"))
        if upstream and upstream not in {x[0] for x in candidates}:
            candidates.append((upstream, "upstream"))

    for candidate, reason in candidates:
        if not git_optional(repo, ("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")):
            continue
        base_commit = ""
        if reason == "upstream":
            base_commit = git_optional(repo, ("merge-base", "--fork-point", candidate, ref))
        if not base_commit:
            base_commit = git_optional(repo, ("merge-base", candidate, ref))
        if base_commit:
            return candidate, base_commit, reason
    return "", "", ""


def infer_branch_creation(repo: Path, ref: str, base_commit: str) -> tuple[str, str]:
    if not base_commit:
        return "", ""
    first_unique_commit = git_optional(repo, ("rev-list", "--reverse", "--max-count=1", f"{base_commit}..{ref}"))
    if first_unique_commit:
        return first_unique_commit, git_optional(repo, ("show", "-s", "--format=%cI", first_unique_commit))
    return base_commit, git_optional(repo, ("show", "-s", "--format=%cI", base_commit))


def git_report(repo: Path, ref: str, base: str = "") -> dict[str, Any]:
    commit = git_text(repo, ("rev-parse", "--verify", f"{ref}^{{commit}}"))
    branch = branch_for_ref(repo, ref)
    base_ref, base_commit, base_reason = infer_base(repo, ref, base)
    commits_since_base = None
    if base_commit:
        commits_since_base = int(git_text(repo, ("rev-list", "--count", f"{base_commit}..{ref}")))
    branch_creation_commit, branch_creation_date = infer_branch_creation(repo, ref, base_commit)
    override_ref = branch or ref
    if override_ref in BRANCH_DATE_OVERRIDES:
        branch_creation_date = BRANCH_DATE_OVERRIDES[override_ref]
    return {
        "ref": ref,
        "branch": branch,
        "commit": commit,
        "commit_short": commit[:12],
        "commit_date": git_text(repo, ("show", "-s", "--format=%cI", ref)),
        "branch_creation_commit": branch_creation_commit,
        "branch_creation_commit_short": branch_creation_commit[:12],
        "branch_creation_date": branch_creation_date,
        "describe": git_optional(repo, ("describe", "--always", "--tags", ref)),
        "total_commits": int(git_text(repo, ("rev-list", "--count", ref))),
        "base_ref": base_ref,
        "base_reason": base_reason,
        "base_commit": base_commit,
        "base_commit_short": base_commit[:12],
        "base_date": git_optional(repo, ("show", "-s", "--format=%cI", base_commit)) if base_commit else "",
        "commits_since_base": commits_since_base,
    }


def source_for(repo: Path, ref: str, worktree: bool = False, fresh_checkout: bool = False) -> FileSource:
    if fresh_checkout:
        return CheckoutSource(repo, ref)
    if worktree:
        if ref != "HEAD":
            raise ValueError("--worktree can only be used with --ref HEAD")
        return WorktreeSource(repo, ref)
    return GitTreeSource(repo, ref)


def build_report(
    repo: Path,
    ref: str = "HEAD",
    base: str = "",
    paths: Sequence[str] = DEFAULT_PATHS,
    worktree: bool = False,
    fresh_checkout: bool = False,
    top_files: int = 20,
) -> dict[str, Any]:
    source = source_for(repo, ref, worktree=worktree, fresh_checkout=fresh_checkout)
    try:
        files = source.list_files()
        resolved_paths = resolve_default_paths(files, paths)
        scoped_files = [path for path in files if path_matches(path, resolved_paths)]
        source_files = [path for path in scoped_files if is_source_path(path, resolved_paths)]
        by_type: dict[str, LineStats] = defaultdict(LineStats)
        totals = LineStats()
        file_metrics = []
        read_errors = []
        for path in source_files:
            try:
                data = source.read_file(path)
            except Exception as e:
                read_errors.append({"path": path, "error": str(e)})
                continue
            stats = line_stats_for(path, data)
            ftype = file_type(path)
            by_type[ftype].add(stats)
            totals.add(stats)
            file_metrics.append(FileMetrics(
                path=path,
                file_type=ftype,
                bytes=stats.bytes,
                lines=stats.lines,
                blank_lines=stats.blank_lines,
                comment_lines=stats.comment_lines,
                sloc=stats.sloc,
            ))
        top_source_files = sorted(file_metrics, key=lambda x: (x.sloc, x.lines, x.bytes), reverse=True)[:top_files]
        git_info = git_report(source.repo, "HEAD" if fresh_checkout else ref, base=base)
        if fresh_checkout:
            git_info["ref"] = ref
            git_info["requested_ref"] = ref
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo": str(repo),
            "source_mode": source.label,
            "paths": resolved_paths,
            "git": git_info,
            "tracked_files": {
                "repo": len(files),
                "scope": len(scoped_files),
                "source": len(source_files),
            },
            "totals": asdict(totals),
            "by_type": {
                ftype: asdict(stats)
                for ftype, stats in sorted(by_type.items(), key=lambda item: (TYPE_ORDER.get(item[0], 50), item[0]))
            },
            "modules": modules_from_files(files),
            "codecs": codecs_from_files(files, source),
            "top_source_files": [asdict(x) for x in top_source_files],
            "read_errors": read_errors,
        }
    finally:
        source.close()


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def short_date(value: str) -> str:
    if not value:
        return ""
    return value[:10]


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    widths = [len(x) for x in headers]
    values = [[fmt(x) for x in row] for row in rows]
    for row in values:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))
    out = ["  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))]
    out.append("  ".join("-" * widths[i] for i in range(len(headers))))
    out.extend("  ".join(row[i].rjust(widths[i]) if row[i].replace(",", "").isdigit() else row[i].ljust(widths[i])
                         for i in range(len(headers))) for row in values)
    return "\n".join(out)


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    align_right = []
    if rows:
        for column in zip(*rows):
            align_right.append(all(isinstance(value, int) for value in column))
    else:
        align_right = [False] * len(headers)
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join("---:" if right else "---" for right in align_right) + " |")
    for row in rows:
        out.append("| " + " | ".join(fmt(x) for x in row) + " |")
    return "\n".join(out)


def type_rows(report: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            ftype,
            stats["files"],
            stats["lines"],
            stats["sloc"],
            stats["blank_lines"],
            stats["comment_lines"],
            stats["bytes"],
        )
        for ftype, stats in report["by_type"].items()
    ]


def top_file_rows(report: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (item["path"], item["file_type"], item["lines"], item["sloc"], item["bytes"])
        for item in report["top_source_files"]
    ]


def summary_row(report: dict[str, Any]) -> tuple[Any, ...]:
    by_type = report["by_type"]
    py = by_type.get(".py", {})
    pyx = by_type.get(".pyx", {})
    git_info = report["git"]
    return (
        git_info["ref"],
        short_date(git_info["branch_creation_date"]),
        report["tracked_files"]["source"],
        report["totals"]["sloc"],
        py.get("files", 0),
        py.get("sloc", 0),
        pyx.get("files", 0),
        pyx.get("sloc", 0),
        report["modules"]["modules"],
        report["codecs"]["loader_defined_codecs"] or report["codecs"]["top_level_packages"],
        git_info["commits_since_base"],
    )


def render_text_report(report: dict[str, Any], details: bool = True) -> str:
    git_info = report["git"]
    lines = [
        "Xpra source report",
        f"repo: {report['repo']}",
        f"ref: {git_info['ref']}",
        f"branch date: {short_date(git_info['branch_creation_date'])}",
        f"mode: {report['source_mode']}",
        f"paths: {', '.join(report['paths']) or '(all)'}",
        f"tracked files in repo: {fmt(report['tracked_files']['repo'])}",
        f"tracked files in scope: {fmt(report['tracked_files']['scope'])}",
        f"source files in scope: {fmt(report['tracked_files']['source'])}",
        f"source sloc: {fmt(report['totals']['sloc'])}",
        f"source physical lines: {fmt(report['totals']['lines'])}",
        f"xpra modules: {fmt(report['modules']['modules'])}",
        f"xpra packages: {fmt(report['modules']['packages'])}",
        f"codec packages: {fmt(report['codecs']['packages'])}",
        f"top-level codec packages: {fmt(report['codecs']['top_level_packages'])}",
        f"loader-defined codecs: {fmt(report['codecs']['loader_defined_codecs'])}",
        f"commits since base: {fmt(git_info['commits_since_base'])}",
        f"base: {git_info['base_ref'] or '(not found)'} {git_info['base_commit_short']}",
    ]
    if details:
        lines.extend((
            "",
            table(("type", "files", "lines", "sloc", "blank", "comments", "bytes"), type_rows(report)),
            "",
            "largest source files by sloc",
            table(("path", "type", "lines", "sloc", "bytes"), top_file_rows(report)),
        ))
    return "\n".join(lines)


def render_summary_text(reports: Sequence[dict[str, Any]]) -> str:
    rows = [summary_row(report) for report in reports]
    return table(
        ("ref", "branch date", "files", "sloc", "py files", "py sloc", "pyx files", "pyx sloc",
         "modules", "codecs", "commits since base"),
        rows,
    )


def render_markdown_report(report: dict[str, Any], details: bool = True) -> str:
    git_info = report["git"]
    metadata = (
        ("Repository", report["repo"]),
        ("Ref", git_info["ref"]),
        ("Branch date", short_date(git_info["branch_creation_date"])),
        ("Mode", report["source_mode"]),
        ("Paths", ", ".join(report["paths"]) or "(all)"),
        ("Tracked files in repo", report["tracked_files"]["repo"]),
        ("Tracked files in scope", report["tracked_files"]["scope"]),
        ("Source files in scope", report["tracked_files"]["source"]),
        ("Source SLOC", report["totals"]["sloc"]),
        ("Source physical lines", report["totals"]["lines"]),
        ("Xpra modules", report["modules"]["modules"]),
        ("Xpra packages", report["modules"]["packages"]),
        ("Codec packages", report["codecs"]["packages"]),
        ("Top-level codec packages", report["codecs"]["top_level_packages"]),
        ("Loader-defined codecs", report["codecs"]["loader_defined_codecs"]),
        ("Commits since base", git_info["commits_since_base"]),
        ("Base", f"{git_info['base_ref'] or '(not found)'} {git_info['base_commit_short']}"),
    )
    lines = [
        "# Xpra Source Report",
        "",
        markdown_table(("Field", "Value"), metadata),
    ]
    if details:
        lines.extend((
            "",
            "## Source Files By Type",
            "",
            markdown_table(("Type", "Files", "Lines", "SLOC", "Blank", "Comments", "Bytes"), type_rows(report)),
            "",
            "## Largest Source Files By SLOC",
            "",
            markdown_table(("Path", "Type", "Lines", "SLOC", "Bytes"), top_file_rows(report)),
        ))
    return "\n".join(lines)


def render_summary_markdown(reports: Sequence[dict[str, Any]]) -> str:
    rows = [summary_row(report) for report in reports]
    return markdown_table(
        ("Ref", "Branch Date", "Files", "SLOC", "Py Files", "Py SLOC", "Pyx Files", "Pyx SLOC",
         "Modules", "Codecs", "Commits Since Base"),
        rows,
    )


def build_reports(args: argparse.Namespace) -> list[dict[str, Any]]:
    repo = resolve_repo(args.repo)
    return [
        build_report(
            repo=repo,
            ref=ref,
            base=args.base,
            paths=tuple(args.paths),
            worktree=args.worktree,
            fresh_checkout=args.fresh_checkout,
            top_files=args.top_files,
        )
        for ref in args.ref
    ]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Git repository to inspect")
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        help="Git ref to inspect. May be specified more than once. Defaults to HEAD.",
    )
    parser.add_argument("--base", default="", help="Base ref used for the branch commit count")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=list(DEFAULT_PATHS),
        help="Tracked path prefixes to include in file and line totals. Defaults to xpra.",
    )
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="Read tracked files from the current worktree instead of the committed Git tree",
    )
    parser.add_argument(
        "--fresh-checkout",
        action="store_true",
        help="Analyze each ref from a temporary local clone checkout",
    )
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Output format",
    )
    parser.add_argument("--summary", action="store_true", help="Only print the compact multi-ref summary")
    parser.add_argument("--top-files", type=int, default=20, help="Number of largest source files to show")
    args = parser.parse_args(argv)
    if not args.ref:
        args.ref = ["HEAD"]
    if args.worktree and args.fresh_checkout:
        parser.error("--worktree and --fresh-checkout are mutually exclusive")
    if args.worktree and args.ref != ["HEAD"]:
        parser.error("--worktree can only be used with --ref HEAD")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    reports = build_reports(args)
    if args.format == "json":
        payload: Any = reports[0] if len(reports) == 1 else reports
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.format == "markdown":
        if args.summary:
            print(render_summary_markdown(reports))
        else:
            if len(reports) > 1:
                print("## Summary")
                print()
                print(render_summary_markdown(reports))
                print()
            print("\n\n".join(render_markdown_report(report, details=True) for report in reports))
    else:
        if args.summary:
            print(render_summary_text(reports))
        else:
            if len(reports) > 1:
                print(render_summary_text(reports))
                print()
            print("\n\n".join(render_text_report(report, details=True) for report in reports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
