# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Source reports run independently of Xpra's runtime and optional libraries."""

import argparse
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[4] / "fs" / "bin"
sys.path.insert(0, str(SCRIPTS))
import source_metrics as metrics  # noqa: E402
from source_report import codec_names_from_loader, line_stats_for  # noqa: E402
import source_report_history as history  # noqa: E402


class AnalysisTest(unittest.TestCase):
    def test_historical_codec_expressions(self):
        examples = (
            ('ENC = "enc_a", "enc_b"\nALL_CODECS = tuple(set(ENC + ("dec_a",)))', ["dec_a", "enc_a", "enc_b"]),
            ('ENC: tuple = gfilt(f"enc_{x}" for x in ("a", "b"))\nALL_CODECS = filt(*set(ENC))', ["enc_a", "enc_b"]),
            ('ALL_CODECS = gfilt(autoprefix("enc", x) for x in ("nvenc", "a"))', ["enc_a", "nvenc"]),
        )
        for source, expected in examples:
            self.assertEqual(codec_names_from_loader(source, strict=True), expected)
        result = metrics.codec_counts({"xpra/codecs/loader.py": b'ALL_CODECS = ("enc_a",) + unknown()'})
        self.assertIsNone(result["count"])
        self.assertTrue(result["errors"])

    def test_scope_aliases_and_class_references(self):
        source = b'''from xpra.b import B as Alias
import xpra.b as other
class A(Alias):
    def make(self, value: Alias):
        return other.B()
class OnlyInheritance(Alias):
    pass
class Shadow:
    def make(self, Alias):
        return Alias()
class Local:
    def make(self):
        from xpra.b import B as Inner
        return Inner()
'''
        analyses = {"xpra.a": metrics.analyze_python(source, "xpra.a", False),
                    "xpra.b": metrics.analyze_python(b"from .a import A\nclass B: pass\n", "xpra.b", False)}
        result = metrics.coupling(analyses)
        classes = {row["name"]: row for row in result["classes"]}
        self.assertEqual(classes["xpra.a.A"]["targets"], ["xpra.b.B"])
        self.assertEqual(classes["xpra.a.OnlyInheritance"]["cbo"], 0)
        self.assertEqual(classes["xpra.a.Shadow"]["cbo"], 0)
        self.assertEqual(classes["xpra.a.Local"]["cbo"], 1)
        self.assertEqual(result["cycles"], [["xpra.a", "xpra.b"]])
        self.assertEqual(result["modules"][0]["fan_in"], 1)
        self.assertEqual(analyses["xpra.a"]["functions"][0]["lines"], 2)

    def test_line_masks_match_counting_convention(self):
        samples = {
            "x.py": b'# comment\n\n"""docstring\ntext\n"""\nx = 1 # trailing\n',
            "x.c": b'/* comment\n\nmore */ int x;\n// comment\nint y; /* inline */\n',
            "x.pyx": b'# comment\ncdef int x\n',
        }
        for path, data in samples.items():
            self.assertEqual(len(metrics.code_lines(path, data)), line_stats_for(path, data).sloc)

    def test_subsystem_architectures(self):
        result = metrics.subsystem_counts([
            "src/xpra/client/mixins/audio.py", "src/xpra/client/mixins/stub_client_mixin.py",
            "src/xpra/client/mixins/__init__.py", "src/xpra/server/server_base.py",
        ])
        self.assertEqual(result["client"]["count"], 1)
        self.assertEqual(result["client"]["architecture"], "mixins")
        self.assertIsNone(result["server"]["count"])

    def test_unsupported_syntax_and_timezone(self):
        self.assertTrue(metrics.analyze_python(b"print 'old syntax'\n", "xpra.old", False)["errors"])
        self.assertEqual(metrics.timestamp("2020-01-01T07:00:00+07:00"), metrics.timestamp("2020-01-01"))


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="xpra-metrics-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "-q", "-b", "master")
        self.cache = metrics.Cache()

    def git(self, *args, date="2020-01-01T00:00:00+00:00"):
        env = {**os.environ, "GIT_AUTHOR_NAME": "Metrics Test", "GIT_AUTHOR_EMAIL": "metrics@example.invalid",
               "GIT_COMMITTER_NAME": "Metrics Test", "GIT_COMMITTER_EMAIL": "metrics@example.invalid",
               "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        return subprocess.check_output(("git", "-C", str(self.repo), *args), env=env, stderr=subprocess.PIPE).decode().strip()

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, date="2020-01-01T00:00:00+00:00"):
        self.git("add", ".")
        self.git("commit", "-qm", "snapshot", date=date)
        return self.git("rev-parse", "HEAD")

    def test_age_survival_renames_edits_and_deletions(self):
        self.write("xpra/old.py", "alpha = 1\nbeta = 2\ngamma = 3\ndelta = 4\n")
        base = self.commit()
        self.git("mv", "xpra/old.py", "xpra/new.py")
        renamed = self.commit("2020-01-11T00:00:00+00:00")
        self.write("xpra/new.py", "alpha = 1\nbeta = 2\n")
        edited = self.commit("2020-01-21T00:00:00+00:00")
        alive = metrics.survival(self.repo, base, renamed, ("xpra",), self.cache)
        self.assertEqual(alive["status"], "not reached")
        self.assertEqual(alive["points"][-1]["fraction"], 1)
        half = metrics.survival(self.repo, base, edited, ("xpra",), self.cache)
        self.assertTrue(half["complete"], half)
        self.assertEqual(half["half_life_days"], 20)
        self.assertEqual(half["points"][-1]["fraction"], .5)
        age = metrics.line_age(self.repo, edited, metrics.timestamp("2020-01-21"),
                               {"xpra/new.py": (self.repo / "xpra/new.py").read_bytes()})
        self.assertEqual(age["median"], 20)
        self.assertEqual(age["count"], 2)
        (self.repo / "xpra/new.py").unlink()
        deleted = self.commit("2020-01-31T00:00:00+00:00")
        gone = metrics.survival(self.repo, base, deleted, ("xpra",), self.cache)
        self.assertEqual(gone["points"][-1]["fraction"], 0)
        self.assertEqual(gone["half_life_days"], 20)

    def test_snapshot_exports_scope_coverage_and_cache(self):
        self.write("src/xpra/a.py", "class A: pass\n")
        self.write("src/xpra/bad.py", "print 'old syntax'\n")
        self.write("src/xpra/native.c", "// comment\nint value;\n")
        self.write("src/xpra/types.pxd", "cdef int value\n")
        self.write("src/xpra/include.pxi", "cdef int another\n")
        self.write("src/xpra/codecs/loader.py", 'ALL_CODECS = tuple(set(("enc_test", "dec_test")))\n')
        self.write("tests/ignored.py", "ignored = True\n")
        commit = self.commit()
        self.write("src/xpra/untracked.py", "x = 1\n" * 100)
        self.write("src/xpra/a.py", "working_copy_change = True\n" * 100)
        args = argparse.Namespace(repo=str(self.repo), refs=["master"], paths=["xpra"], sample="tips", since="", until="",
                                  age=False, survival=[], cache_dir=str(self.repo / "cache"))
        result = metrics.collect_evolution(args)
        snap = result["snapshots"][0]
        self.assertEqual(snap["commit"], commit)
        self.assertEqual(snap["paths"], ("src/xpra",))
        self.assertEqual(snap["groups"]["python"]["sloc"], 3)
        self.assertEqual(snap["groups"]["cython"]["files"], 2)
        self.assertEqual(snap["groups"]["native"]["sloc"], 1)
        self.assertEqual(snap["coverage"]["parsed_python_files"], 2)
        self.assertFalse(snap["complete"])
        self.assertEqual(snap["codecs"]["count"], 2)
        rows = list(csv.DictReader(io.StringIO(metrics.csv_data(result))))
        self.assertEqual(int(rows[0]["python_sloc"]), snap["groups"]["python"]["sloc"])
        output = self.repo / "output"
        metrics.write_data(result, output)
        self.assertEqual(json.loads((output / "metrics.json").read_text())["schema_version"], 1)
        cache = metrics.Cache(str(self.repo / "other-cache"))
        cache.get_or_create("test", "key", lambda: {"value": 42})
        with patch.object(metrics, "git", side_effect=AssertionError("cache miss")):
            self.assertEqual(metrics.Cache(str(self.repo / "other-cache")).get_or_create("test", "key", lambda: self.fail()), {"value": 42})
        self.assertIn("Analysis coverage", metrics.markdown_report(result))

    def test_sampling_and_merge_churn(self):
        self.write("xpra/a.py", "a = 1\n")
        first = self.commit()
        self.git("tag", "v1.0")
        self.write("xpra/a.py", "a = 2\n")
        second = self.commit("2020-01-15T00:00:00+00:00")
        self.git("checkout", "-qb", "feature")
        self.write("xpra/b.py", "b = 3\n")
        feature = self.commit("2020-02-01T00:00:00+00:00")
        self.git("checkout", "-q", "master")
        self.git("merge", "--no-ff", "-qm", "merge", "feature", date="2020-03-01T00:00:00+00:00")
        tip = self.git("rev-parse", "HEAD")
        self.assertEqual(metrics.select_snapshots(self.repo, tip, "monthly"), [second, tip])
        self.assertEqual(metrics.select_snapshots(self.repo, tip, "quarterly"), [tip])
        self.assertEqual(metrics.select_snapshots(self.repo, tip, "tags"), [first, tip])
        self.assertEqual(metrics.select_snapshots(self.repo, tip, "monthly", "2020-02-01", "2020-02-28"), [tip])
        result = metrics.churn(self.repo, tip, metrics.timestamp("2020-03-01"), ("xpra",))
        rows = {row["path"]: row for row in result["files"]}
        self.assertEqual(rows["b.py"]["additions"], 1)
        self.assertEqual(rows["a.py"]["changes"], 2)
        with self.assertRaises(ValueError):
            metrics.survival(self.repo, feature, tip, ("xpra",), self.cache)

    def test_whitespace_survival_and_rename_churn(self):
        self.write("xpra/original.py", "alpha = 12345\nbeta = 23456\ngamma = 34567\n")
        base = self.commit()
        self.git("mv", "xpra/original.py", "xpra/renamed.py")
        self.commit("2020-01-05T00:00:00+00:00")
        self.write("xpra/renamed.py", "alpha    = 12345\nbeta    = 23456\ngamma    = 34567\n")
        end = self.commit("2020-01-10T00:00:00+00:00")
        result = metrics.survival(self.repo, base, end, ("xpra",), self.cache)
        self.assertEqual(result["points"][-1]["fraction"], 1)
        self.assertEqual(result["status"], "not reached")
        rows = metrics.churn(self.repo, end, metrics.timestamp("2020-01-10"), ("xpra",))["files"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "renamed.py")
        self.assertEqual(rows[0]["changes"], 3)

    def test_snapshot_cache_and_shallow_history(self):
        self.write("xpra/a.py", "x = 1\n")
        self.write("xpra/codecs/loader.py", 'ALL_CODECS = ("enc_test",)\n')
        commit = self.commit()
        directory = str(self.repo / "cache")
        metrics.snapshot(self.repo, commit, ("xpra",), False, metrics.Cache(directory))
        with patch.object(metrics, "read_blobs", side_effect=AssertionError("cache miss")):
            cached = metrics.snapshot(self.repo, commit, ("xpra",), False, metrics.Cache(directory))
            self.assertEqual(cached["commit"], commit)
        shallow = self.repo / "shallow"
        self.git("clone", "-q", "--depth=1", self.repo.as_uri(), str(shallow))
        args = argparse.Namespace(repo=str(shallow), age=True, survival=[])
        with self.assertRaisesRegex(ValueError, "shallow"):
            metrics.collect_evolution(args)

    def test_empty_baseline(self):
        self.write("xpra/empty.py", "# no code\n")
        base = self.commit()
        self.write("xpra/empty.py", "# still no code\n")
        end = self.commit("2020-02-01T00:00:00+00:00")
        result = metrics.survival(self.repo, base, end, ("xpra",), self.cache)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["points"], [])

    def test_legacy_defaults(self):
        self.write("xpra/a.py", "x = 1\n")
        self.commit()
        args = history.parse_args(["--repo", str(self.repo)])
        reports = history.reports_from_args(args)
        self.assertEqual(reports[0]["git"]["ref"], "HEAD")

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Matplotlib not installed")
    def test_headless_graphs(self):
        from source_report_graphs import render
        self.write("xpra/a.py", "class A: pass\n")
        self.write("xpra/codecs/loader.py", 'ALL_CODECS = ("enc_test",)\n')
        base = self.commit()
        self.write("xpra/a.py", "class A:\n    value = 1\n")
        self.commit("2020-02-01T00:00:00+00:00")
        args = argparse.Namespace(repo=str(self.repo), refs=["master"], paths=["xpra"], sample="monthly", since="", until="",
                                  age=True, survival=[f"{base}..master"], cache_dir="")
        report = metrics.collect_evolution(args)
        output = self.repo / "graphs"
        graphs = render(report, output)
        self.assertIn("history", graphs)
        self.assertIn("line-age", graphs)
        self.assertIn("survival", graphs)
        for name in graphs:
            self.assertIn("<svg", (output / f"{name}.svg").read_text())
            self.assertTrue((output / f"{name}.png").read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
