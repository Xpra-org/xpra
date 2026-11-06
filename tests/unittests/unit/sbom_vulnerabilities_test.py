#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "MSWindows" / "sbom_vulnerabilities.py"
DOC = """# Vulnerabilities

| CVE | Package | Severity | Issue | Upstream fix | Live | First xpra version | Fixed in xpra | Ticket | Notes |
|---|---|---|---|---|---|---|---|---|---|
| [CVE-2026-100](https://www.cve.org/CVERecord?id=CVE-2026-100) | python | High | Known issue | | 🔴 on | 1.0 | | | Keep this note |
| CVE-2026-101 | lib-off | Medium | Unused library | | off | 1.0 | | | Unreachable |

## Ignored packages

| Package | Reason |
|---|---|
| ignored-lib | Not shipped |
"""


def link(cve):
    return f"[{cve}](https://www.cve.org/CVERecord?id={cve})"


def match(vuln_id, package="python", related_cve=""):
    return {
        "artifact": {"name": package, "version": "3.14.8"},
        "vulnerability": {"id": vuln_id, "severity": "High", "description": "An issue in the bundled library."},
        "relatedVulnerabilities": [{"id": related_cve}] if related_cve else [],
    }


class SBOMVulnerabilitiesTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.doc = self.root / "CVE.md"
        self.doc.write_text(DOC)
        self.github_output = self.root / "github-output"

    def scan(self, variant, *matches):
        filename = self.root / f"{variant}.json"
        filename.write_text(json.dumps({"matches": matches}))
        return str(filename)

    def run_report(self, *args):
        self.github_output.write_text("")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--doc", str(self.doc), *args],
            env={**os.environ, "GITHUB_OUTPUT": str(self.github_output)},
            capture_output=True, text=True, check=True,
        )
        return result.stdout, self.github_output.read_text()

    def test_variants_deduplicate_cves_and_keep_packages_and_versions(self):
        light = self.scan("light", match("CVE-2026-100"), match("CVE-2026-101", "lib-off"),
                          match("GHSA-shared", related_cve="CVE-2026-200"), match("CVE-2026-300", "ignored-lib"))
        full = self.scan("full", match("CVE-2026-100", "full-python"), match("CVE-2026-200", "full-library"),
                         match("CVE-2026-201"), match("CVE-2026-300", "ignored-lib"))
        args = ("--variant-scan", "Xpra-Light", "1.0", light, "--variant-scan", "Xpra", "1.1", full)
        output, github_output = self.run_report(*args, "--update")
        first, second = output.split("## Xpra 1.1 (additional vulnerabilities)")
        self.assertTrue(first.startswith("## Xpra-Light 1.0\n"))
        self.assertIn("3 vulnerabilities: 3 high", first)
        self.assertIn("1 new, 1 live and 1 switched off", first)
        self.assertIn("1 more in ignored packages", first)
        self.assertIn(f"| {link('CVE-2026-200')} | full-library, python |", first)
        self.assertIn("| 1.0, 1.1 |", first)
        self.assertIn(f"| {link('CVE-2026-100')} | python, full-python |", first)
        self.assertIn("Keep this note", first)
        self.assertNotIn("GHSA-shared", output)
        self.assertNotIn(f"| {link('CVE-2026-101')} |", output)
        self.assertIn("1 new, 0 live and 0 switched off", second)
        self.assertIn("0 more in ignored packages", second)
        self.assertIn(f"| {link('CVE-2026-201')} |", second)
        self.assertNotIn("CVE-2026-100", second)
        self.assertNotIn("CVE-2026-200", second)
        self.assertEqual(github_output, "new=2\n")
        updated_doc = self.doc.read_text()
        self.assertEqual(updated_doc.count(f"| {link('CVE-2026-200')} |"), 1)
        self.assertIn(f"| {link('CVE-2026-200')} | full-library, python |", updated_doc)
        self.assertIn("| 1.0, 1.1 |", updated_doc)
        _, github_output = self.run_report(*args)
        self.assertEqual(github_output, "new=0\n")

    def test_identical_variants_have_no_additional_vulnerabilities(self):
        scan = self.scan("same", match("CVE-2026-200"))
        output, github_output = self.run_report(
            "--variant-scan", "Xpra-Light", "1.0", scan, "--variant-scan", "Xpra", "1.0", scan,
        )
        _, second = output.split("## Xpra 1.0 (additional vulnerabilities)")
        self.assertIn("0 vulnerabilities", second)
        self.assertNotIn("CVE-", second)
        self.assertEqual(output.count(f"| {link('CVE-2026-200')} |"), 1)
        self.assertEqual(github_output, "new=1\n")

    def test_ignored_light_match_does_not_hide_full_match(self):
        light = self.scan("light", match("CVE-2026-200", "ignored-lib"))
        full = self.scan("full", match("CVE-2026-200"), match("CVE-2026-300", "ignored-lib"))
        output, github_output = self.run_report(
            "--variant-scan", "Xpra-Light", "1.0", light, "--variant-scan", "Xpra", "1.0", full,
        )
        first, second = output.split("## Xpra 1.0 (additional vulnerabilities)")
        self.assertIn("0 vulnerabilities", first)
        self.assertIn("0 more in ignored packages", first)
        self.assertIn(f"| {link('CVE-2026-200')} | python |", second)
        self.assertIn("1 more in ignored packages", second)
        self.assertEqual(github_output, "new=1\n")

    def test_missing_or_invalid_full_scan_fails_before_reporting(self):
        light = self.scan("light", match("CVE-2026-200"))
        invalid = self.root / "invalid.json"
        invalid.write_text("not json")
        for filename in (self.root / "missing.json", invalid):
            with self.subTest(filename=filename), self.assertRaises(subprocess.CalledProcessError) as error:
                self.run_report("--variant-scan", "Xpra-Light", "1.0", light,
                                "--variant-scan", "Xpra", "1.0", str(filename))
            self.assertEqual(error.exception.stdout, "")
            self.assertEqual(self.github_output.read_text(), "")

    def test_legacy_scans_still_merge_without_variant_sections(self):
        light = self.scan("light", match("CVE-2026-200"))
        full = self.scan("full", match("CVE-2026-200", "full-library"), match("CVE-2026-201"))
        output, github_output = self.run_report("--scan", "1.0", light, "--scan", "1.1", full)
        self.assertTrue(output.startswith("2 vulnerabilities: 2 high\n"))
        self.assertIn("## New vulnerabilities\n", output)
        self.assertIn(f"| {link('CVE-2026-200')} | full-library, python |", output)
        self.assertEqual(output.count(f"| {link('CVE-2026-200')} |"), 1)
        self.assertEqual(github_output, "new=2\n")


if __name__ == "__main__":
    unittest.main()
