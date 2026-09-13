#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 kogeler
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Exercise the real setup/Cython object graph without requiring OpenJPH."""

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


PLAN_PREFIX = "jph-build-plan="
JPH_PACKAGE = "xpra.codecs.jph."
COMMON_HEADER = "xpra/codecs/jph/jph_common.h"
ROLE_PATHS = {
    "encoder": ("xpra/codecs/jph/jph_encode.cpp", "xpra/codecs/jph/jph_encode.h"),
    "decoder": ("xpra/codecs/jph/jph_decode.cpp", "xpra/codecs/jph/jph_decode.h"),
}
HELPER_PATHS = (COMMON_HEADER, *ROLE_PATHS["encoder"], *ROLE_PATHS["decoder"])


def incremental_decision(extension):
    from distutils.command.build_ext import build_ext
    from distutils.ccompiler import new_compiler
    from setuptools import Distribution

    class RebuildRequested(Exception):
        pass

    # The extension is from actual setup + Cython, not a fabricated plan.
    # Enter the production native build_ext skip branch, but stop at the real
    # compiler's compile entry rather than running a compiler or native loader.
    command = build_ext(Distribution({"ext_modules": [extension]}))
    command.ensure_finalized()
    command.compiler = new_compiler()
    output = Path(command.get_ext_fullpath(extension.name))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"build-plan-only output marker")
    header = Path(COMMON_HEADER)
    original = header.stat()
    stamp = max(Path(path).stat().st_mtime_ns for path in (*extension.sources, *extension.depends, COMMON_HEADER))

    def needs_rebuild() -> bool:
        try:
            command.build_extension(extension)
        except RebuildRequested:
            return True
        return False

    try:
        os.utime(output, ns=(stamp + 10_000_000_000, stamp + 10_000_000_000))
        with patch.object(command.compiler, "compile", side_effect=RebuildRequested):
            unchanged = needs_rebuild()
            os.utime(header, ns=(original.st_atime_ns, stamp + 20_000_000_000))
            changed_header = needs_rebuild()
    finally:
        os.utime(header, ns=(original.st_atime_ns, original.st_mtime_ns))
        output.unlink()
    return {"unchanged": unchanged, "changed-header": changed_header}


def describe_setup(flags):
    # Run the actual option parser, extension registration and cythonize call.
    # --skip-build uses setup's own no-pkgconfig path, not fake declarations.
    # This observes object/dependency planning, never native linkage.
    sys.argv = [
        "setup.py", "build_ext", "--minimal", "--with-cython", "--without-codecs",
        "--without-server", "--without-client", "--without-shadow", "--without-x11", "--without-gtk_x11",
        "--without-rencodeplus", "--without-brotli", "--without-cityhash", "--without-qrencode",
        "--without-websockets", "--without-netdev", "--without-vsock", "--without-lz4", "--without-zstd",
        "--without-pam", "--without-sd_listen", "--without-proc", "--without-landlock", "--without-peercred",
        "--without-cython_shared", "--skip-build", *flags,
    ]
    setup = runpy.run_path("setup.py", run_name="xpra_build_plan")
    from distutils.ccompiler import new_compiler
    compiler = new_compiler()
    extensions = []
    for extension in setup["setup_options"]["ext_modules"]:
        if not extension.name.startswith(JPH_PACKAGE):
            continue
        extensions.append({
            "name": extension.name,
            "language": extension.language,
            "sources": extension.sources,
            "depends": extension.depends,
            "objects": compiler.object_filenames(extension.sources, output_dir="build/jph-objects"),
            "incremental": incremental_decision(extension),
        })
    print(PLAN_PREFIX + json.dumps({"compiler": compiler.compiler_type, "extensions": extensions}))


class JPHBuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[4]
        scratch = source / "build"
        scratch.mkdir(exist_ok=True)
        cls.temporary = TemporaryDirectory(prefix="jph-build-test-", dir=scratch)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.source = Path(cls.temporary.name) / "source"
        cls.source.mkdir()
        # No .git, installed tree, other test results, or operator data enters
        # the private setup invocation. Its generated files never touch source.
        for name in ("xpra", "fs"):
            shutil.copytree(source / name, cls.source / name, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.so", "*.pyd", "*.dll",
            ))
        for name in ("setup.py", "pyproject.toml", "MANIFEST.in", "README.md", "COPYING"):
            shutil.copy2(source / name, cls.source / name)
        cls.environment = os.environ.copy()
        cls.environment.pop("XPRA_EXTRA_BUILD_ARGS", None)
        cls.environment.update({
            "PYTHONPATH": str(cls.source),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NTHREADS": "0",
        })
        # Discard copied generated Cython files through the actual clean path.
        cls.run_setup("clean", "--minimal")
        cls.plans = {}
        for name, flags in (
                ("both", ("--with-jph",)),
                ("encoder", ("--with-jph_encoder",)),
                ("decoder", ("--with-jph_decoder",)),
        ):
            output = cls.run_process(str(Path(__file__).resolve()), "--describe-setup", *flags)
            lines = [line[len(PLAN_PREFIX):] for line in output.splitlines() if line.startswith(PLAN_PREFIX)]
            if len(lines) != 1:
                raise AssertionError(f"expected one real setup plan, got {lines!r}:\n{output}")
            cls.plans[name] = json.loads(lines[0])

    @classmethod
    def run_process(cls, *args):
        result = subprocess.run(
            (sys.executable, *args), cwd=cls.source, env=cls.environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=90, check=False,
        )
        if result.returncode:
            raise AssertionError(f"setup probe failed ({result.returncode}):\n{result.stdout}")
        return result.stdout

    @classmethod
    def run_setup(cls, *args):
        return cls.run_process("setup.py", *args)

    def test_parallel_extensions_own_distinct_objects(self):
        extensions = self.plans["both"]["extensions"]
        self.assertEqual({entry["name"] for entry in extensions}, {
            JPH_PACKAGE + "encoder", JPH_PACKAGE + "decoder",
        })
        owners = {}
        for extension in extensions:
            self.assertEqual(extension["language"], "c++")
            self.assertTrue(extension["objects"])
            for obj in extension["objects"]:
                owners.setdefault(obj, []).append(extension["name"])
        shared = {obj: names for obj, names in owners.items() if len(names) != 1}
        self.assertEqual(shared, {}, f"parallel extensions share writable compiler objects: {shared}")

    def test_role_sources_and_shared_header_remain_dependencies(self):
        for name, plan in self.plans.items():
            for extension in plan["extensions"]:
                with self.subTest(selection=name, extension=extension["name"]):
                    inputs = set(extension["sources"]) | set(extension["depends"])
                    role = extension["name"].removeprefix(JPH_PACKAGE)
                    self.assertTrue({COMMON_HEADER, *ROLE_PATHS[role]} <= inputs, inputs)
                    other = "decoder" if role == "encoder" else "encoder"
                    self.assertTrue(set(ROLE_PATHS[other]).isdisjoint(extension["sources"]))

    def test_common_header_change_reaches_native_incremental_build(self):
        for name, plan in self.plans.items():
            for extension in plan["extensions"]:
                with self.subTest(selection=name, extension=extension["name"]):
                    self.assertEqual(extension["incremental"], {"unchanged": False, "changed-header": True})

    def test_encoder_and_decoder_remain_independently_selectable(self):
        for name in ("encoder", "decoder"):
            with self.subTest(selection=name):
                self.assertEqual(
                    [entry["name"] for entry in self.plans[name]["extensions"]],
                    [JPH_PACKAGE + name],
                )

    def test_source_distribution_preserves_shared_inputs(self):
        expected = {
            name: (self.source / name).read_bytes() for name in (
                *HELPER_PATHS, "xpra/codecs/jph/encoder.pyx", "xpra/codecs/jph/decoder.pyx",
            )
        }
        self.run_setup("sdist", "--minimal", "--formats=gztar", "--dist-dir=archives")
        archives = tuple((self.source / "archives").glob("*.tar.gz"))
        self.assertEqual(len(archives), 1, archives)
        with tarfile.open(archives[0], "r:gz") as archive:
            for name, data in expected.items():
                with self.subTest(path=name):
                    self.assertEqual((self.source / name).read_bytes(), data, "clean modified handwritten input")
                    members = [member for member in archive.getmembers() if member.name.endswith("/" + name)]
                    self.assertEqual(len(members), 1, members)
                    self.assertTrue(members[0].isfile())
                    with archive.extractfile(members[0]) as stream:
                        self.assertEqual(stream.read(), data)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--describe-setup":
        describe_setup(sys.argv[2:])
    else:
        unittest.main()
