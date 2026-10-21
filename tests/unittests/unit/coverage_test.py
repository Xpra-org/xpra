#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unit import run as runner

try:
    import coverage
except ImportError:
    coverage = None


@unittest.skipUnless(coverage and runner.COVERAGE, "coverage.py is not installed")
class CoverageTest(unittest.TestCase):

    def test_children_keep_data_and_combine_source_and_install_paths(self):
        with tempfile.TemporaryDirectory(prefix="xpra-coverage-") as directory:
            root = Path(directory)
            unittests = root / "tests" / "unittests"
            unittests.mkdir(parents=True)
            rcfile = unittests / ".coveragerc"
            shutil.copy(Path(__file__).parents[1] / ".coveragerc", rcfile)
            source = root / "xpra"
            installed = root / "dist" / "site-packages" / "xpra"
            for package in (source, installed):
                package.mkdir(parents=True)
                (package / "__init__.py").write_text("")
                (package / "probe.py").write_text("def first():\n    return 1\n\ndef second():\n    return 2\n")
            script = unittests / "probe.py"
            script.write_text("import sys\nfrom xpra import probe\nassert getattr(probe, sys.argv[1])() in (1, 2)\n")
            with patch.dict(os.environ, {"XPRA_MODULE_DIR": str(installed), "COVERAGE_RCFILE": str(rcfile),
                                         "COVERAGE_FILE": str(unittests / ".coverage")}):
                command = runner.get_coverage_command(str(unittests))
                for package, function in ((source, "first"), (installed, "second")):
                    env = dict(os.environ, PYTHONPATH=str(package.parent))
                    with tempfile.TemporaryDirectory(dir=root) as cwd:
                        subprocess.run(command + [str(script), function], cwd=cwd, env=env, check=True, capture_output=True)
                cov = coverage.Coverage(config_file=str(rcfile), data_file=str(unittests / ".coverage"))
                cov.combine(data_paths=[str(unittests)], strict=True)
                files = cov.get_data().measured_files()
                self.assertEqual(files, {str(source / "__init__.py"), str(source / "probe.py")})
                self.assertEqual(cov.get_data().lines(str(source / "probe.py")), [1, 2, 4, 5])


if __name__ == "__main__":
    unittest.main()
