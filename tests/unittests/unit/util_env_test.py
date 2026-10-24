#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
from pathlib import Path
from threading import Lock
import warnings
import unittest
from unittest.mock import Mock, patch

from xpra.util import env
from xpra.util.env import (
    OSEnvContext,
    hasenv, unsetenv, set_environ,
    envint, envbool, envfloat,
    shellsub,
    decode_dict,
    first_time,
    IgnoreWarningsContext,
    ignorewarnings,
    SilenceWarningsContext,
    get_exec_env,
    save_env, get_saved_env, get_saved_env_var,
)

_TEST_VAR = "XPRA_TEST_UTIL_ENV"


class TestHasEnvUnsetenv(unittest.TestCase):

    def test_hasenv_present(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "1"
            self.assertTrue(hasenv(_TEST_VAR))

    def test_hasenv_absent(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            self.assertFalse(hasenv(_TEST_VAR))

    def test_unsetenv_removes(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "1"
            unsetenv(_TEST_VAR)
            self.assertFalse(hasenv(_TEST_VAR))

    def test_unsetenv_missing_is_noop(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            unsetenv(_TEST_VAR)   # must not raise


class TestSetEnviron(unittest.TestCase):

    def test_matches_target(self):
        with OSEnvContext():
            target = dict(os.environ)
            target.pop("PATH", None)
            target[_TEST_VAR] = "new"
            set_environ(target)
            self.assertEqual(dict(os.environ), target)

    def test_only_touches_differences(self):
        with OSEnvContext():
            os.environ[_TEST_VAR + "_DROP"] = "1"
            target = dict(os.environ)
            del target[_TEST_VAR + "_DROP"]
            target[_TEST_VAR] = "1"
            # `os.environ` calls the libc through the `os` module's `putenv` and `unsetenv`:
            with patch("os.putenv") as putenv, patch("os.unsetenv") as unset:
                set_environ(target)
            self.assertEqual(putenv.call_count, 1)
            self.assertEqual(unset.call_count, 1)
            self.assertEqual(dict(os.environ), target)


class TestEnvint(unittest.TestCase):

    def test_reads_integer(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "42"
            self.assertEqual(envint(_TEST_VAR), 42)

    def test_negative(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "-7"
            self.assertEqual(envint(_TEST_VAR, 0), -7)

    def test_missing_returns_default(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            self.assertEqual(envint(_TEST_VAR, 99), 99)

    def test_invalid_returns_default(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "notanint"
            self.assertEqual(envint(_TEST_VAR, 5), 5)


class TestEnvbool(unittest.TestCase):

    def _set(self, value):
        os.environ[_TEST_VAR] = value

    def test_true_values(self):
        for v in ("yes", "true", "on", "1", "YES", "True", "ON"):
            with OSEnvContext():
                self._set(v)
                self.assertTrue(envbool(_TEST_VAR), f"expected True for {v!r}")

    def test_false_values(self):
        for v in ("no", "false", "off", "0", "NO", "FALSE", "OFF"):
            with OSEnvContext():
                self._set(v)
                self.assertFalse(envbool(_TEST_VAR), f"expected False for {v!r}")

    def test_missing_returns_default(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            self.assertFalse(envbool(_TEST_VAR))
            self.assertTrue(envbool(_TEST_VAR, True))

    def test_invalid_returns_default(self):
        with OSEnvContext():
            self._set("maybe")
            self.assertFalse(envbool(_TEST_VAR, False))
            self.assertTrue(envbool(_TEST_VAR, True))


class TestEnvfloat(unittest.TestCase):

    def test_reads_float(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "3.14"
            self.assertAlmostEqual(envfloat(_TEST_VAR), 3.14)

    def test_integer_string(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "2"
            self.assertAlmostEqual(envfloat(_TEST_VAR), 2.0)

    def test_missing_returns_default(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            self.assertAlmostEqual(envfloat(_TEST_VAR, 1.5), 1.5)

    def test_invalid_returns_default(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "notafloat"
            self.assertAlmostEqual(envfloat(_TEST_VAR, 2.5), 2.5)


class TestShellsub(unittest.TestCase):

    def test_dollar_var(self):
        self.assertEqual(shellsub("$HOME/test", {"HOME": "/home/user"}), "/home/user/test")

    def test_braced_var(self):
        self.assertEqual(shellsub("${HOME}/test", {"HOME": "/home/user"}), "/home/user/test")

    def test_multiple_vars(self):
        result = shellsub("$A-$B", {"A": "hello", "B": "world"})
        self.assertEqual(result, "hello-world")

    def test_empty_subs(self):
        self.assertEqual(shellsub("no vars here", {}), "no vars here")

    def test_unknown_var_unchanged(self):
        self.assertEqual(shellsub("$UNKNOWN", {"OTHER": "x"}), "$UNKNOWN")


class TestDecodeDict(unittest.TestCase):

    def test_basic(self):
        d = decode_dict("KEY=value\nKEY2=value2\n")
        self.assertEqual(d, {"KEY": "value", "KEY2": "value2"})

    def test_value_with_equals(self):
        d = decode_dict("PATH=/usr/bin:/bin\n")
        self.assertEqual(d["PATH"], "/usr/bin:/bin")

    def test_lines_without_equals_ignored(self):
        d = decode_dict("no_equals_here\nKEY=val\n")
        self.assertNotIn("no_equals_here", d)
        self.assertEqual(d["KEY"], "val")

    def test_empty_input(self):
        self.assertEqual(decode_dict(""), {})

    def test_empty_value(self):
        d = decode_dict("EMPTY=\n")
        self.assertEqual(d["EMPTY"], "")


class TestFirstTime(unittest.TestCase):

    def test_first_call_returns_true(self):
        import uuid
        key = f"test-first-time-{uuid.uuid4()}"
        self.assertTrue(first_time(key))

    def test_second_call_returns_false(self):
        import uuid
        key = f"test-first-time-{uuid.uuid4()}"
        first_time(key)
        self.assertFalse(first_time(key))

    def test_different_keys_are_independent(self):
        import uuid
        key1 = f"test-first-time-{uuid.uuid4()}"
        key2 = f"test-first-time-{uuid.uuid4()}"
        self.assertTrue(first_time(key1))
        self.assertTrue(first_time(key2))
        self.assertFalse(first_time(key1))
        self.assertFalse(first_time(key2))


class TestIgnoreWarningsContext(unittest.TestCase):

    def test_suppresses_deprecation_warning(self):
        with IgnoreWarningsContext():
            warnings.warn("test deprecation", DeprecationWarning, stacklevel=1)
        # no exception means warning was suppressed

    def test_repr(self):
        self.assertIn("IgnoreWarnings", repr(IgnoreWarningsContext()))


class TestIgnorewarnings(unittest.TestCase):

    def test_calls_function(self):
        result = ignorewarnings(lambda: 42)
        self.assertEqual(result, 42)

    def test_passes_args(self):
        result = ignorewarnings(lambda a, b: a + b, 3, 4)
        self.assertEqual(result, 7)

    def test_suppresses_deprecation(self):
        def emit():
            warnings.warn("dep", DeprecationWarning, stacklevel=1)
        ignorewarnings(emit)   # must not propagate


class TestSilenceWarningsContext(unittest.TestCase):

    def test_suppresses_specified_category(self):
        with SilenceWarningsContext(DeprecationWarning):
            warnings.warn("test", DeprecationWarning, stacklevel=1)

    def test_repr(self):
        ctx = SilenceWarningsContext(DeprecationWarning)
        self.assertIsInstance(repr(ctx), str)

    def test_no_categories(self):
        with SilenceWarningsContext():
            pass  # should not raise


class TestGetExecEnv(unittest.TestCase):

    def test_returns_dict(self):
        env = get_exec_env()
        self.assertIsInstance(env, dict)

    def test_xpra_skip_ui_set(self):
        env = get_exec_env()
        self.assertEqual(env.get("XPRA_SKIP_UI"), "1")

    def test_removes_ls_colors(self):
        with OSEnvContext():
            os.environ["LS_COLORS"] = "rs=0:di=01;34"
            env = get_exec_env()
            self.assertNotIn("LS_COLORS", env)

    def test_keep_filter(self):
        with OSEnvContext():
            os.environ["XPRA_TEST_KEEP"] = "keep_me"
            os.environ["XPRA_TEST_DROP"] = "drop_me"
            env = get_exec_env(keep=("XPRA_TEST_KEEP",))
            self.assertIn("XPRA_TEST_KEEP", env)
            self.assertNotIn("XPRA_TEST_DROP", env)


class TestSavedEnv(unittest.TestCase):

    def test_save_and_get(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "saved_value"
            save_env()
            saved = get_saved_env()
            self.assertEqual(saved.get(_TEST_VAR), "saved_value")

    def test_get_saved_env_var(self):
        with OSEnvContext():
            os.environ[_TEST_VAR] = "myval"
            save_env()
            self.assertEqual(get_saved_env_var(_TEST_VAR), "myval")

    def test_get_saved_env_var_default(self):
        with OSEnvContext():
            os.environ.pop(_TEST_VAR, None)
            save_env()
            self.assertEqual(get_saved_env_var(_TEST_VAR, "fallback"), "fallback")

    def test_get_saved_env_returns_copy(self):
        save_env()
        env1 = get_saved_env()
        env1["MUTATED"] = "yes"
        env2 = get_saved_env()
        self.assertNotIn("MUTATED", env2)


class TestEnvironmentRestoration(unittest.TestCase):

    def test_script_wrapper_values_are_restored_and_removed(self):
        values = {"_PYTHON_WRAPPER_VARS": "PATH NEW ABSENT", "PATH": "bundle", "_PATH": "/bin",
                  "NEW": "bundle", "_NEW": "", "_ABSENT": "", "KEEP": "yes"}
        self.assertIs(env.restore_script_env(values), values)
        self.assertEqual(values, {"PATH": "/bin", "KEEP": "yes"})
        self.assertEqual(env.restore_script_env(values), values)

    def test_filter_patterns_and_unencodable_values(self):
        values = {"KEEP_ONE": "yes", "KEEP_TWO": "no", "DROP": "discard", "KEEP_BAD": "\udcff"}
        self.assertEqual(env.filter_env(values, remove=("KEEP_TWO",), keep=("KEEP_",)),
                         {"KEEP_BAD": "\udcff", "KEEP_ONE": "yes", "XPRA_SKIP_UI": "1", "XPRA_FORCE_COLOR_LOG": "1"})

    def test_failed_shell_substitution(self):
        value = Mock()
        value.__str__ = Mock(side_effect=ValueError("cannot format"))
        with self.assertRaisesRegex(ValueError, "failed to substitute"):
            shellsub("$VALUE", {"VALUE": value})

    def test_warning_options_are_respected(self):
        with patch.object(sys, "warnoptions", ["default"]):
            context = SilenceWarningsContext(DeprecationWarning)
            self.assertEqual(context.categories, ())
            with context:
                pass


class TestSourceEnvironment(unittest.TestCase):

    def test_shell_and_binary_output_decoding(self):
        cases = (
            (b"#!/bin/sh\n", b'{"EXPORTED":"value","":"discard"}', {"EXPORTED": "value", "STDERR_FLAG": "ok"}),
            (b"\x7fELF\0", b"EXPORTED=value\n=discard\n", {"EXPORTED": "value", "STDERR_FLAG": "ok"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "source-env"
            for header, output, expected in cases:
                filename.write_bytes(header)
                proc = Mock(returncode=0)
                proc.communicate.return_value = output, b"STDERR_FLAG=ok\n"
                with self.subTest(header=header), patch.object(env, "Popen", return_value=proc) as popen, \
                        patch("xpra.platform.paths.get_python_exec_command", return_value=["python3", "-c"]), \
                        patch("xpra.util.io.which", return_value="/bin/bash"):
                    self.assertEqual(env.env_from_sourcing(str(filename), include_unexported_variables=True), expected)
                    command = popen.call_args.args[0]
                    if header.startswith(b"#!"):
                        self.assertEqual(command[:2], ["/bin/bash", "-c"])
                        self.assertIn(f"set -a && . {filename}", command[2])
                    else:
                        self.assertEqual(command, [str(filename)])

    def test_sourcing_failures_and_malformed_output(self):
        with tempfile.TemporaryDirectory() as directory, patch("xpra.log.Logger"):
            filename = Path(directory) / "source-env"
            with patch.object(env, "Popen") as popen:
                self.assertEqual(env.env_from_sourcing(str(filename)), {})
                popen.assert_not_called()
            filename.write_text("#!/bin/sh\n")
            for output in (b"not json", b"\xff"):
                proc = Mock(returncode=1)
                proc.communicate.return_value = output, b"\xff"
                with self.subTest(output=output), patch.object(env, "Popen", return_value=proc):
                    self.assertEqual(env.env_from_sourcing(str(filename)), {})
            with patch.object(env, "Popen", side_effect=OSError("cannot start")):
                self.assertEqual(env.env_from_sourcing(str(filename)), {})
            proc = Mock(returncode=1)
            proc.communicate.side_effect = OSError("cannot read")
            with patch.object(env, "Popen", return_value=proc):
                self.assertEqual(env.env_from_sourcing(str(filename)), {})
            with patch("xpra.util.io.which", return_value=""), patch("builtins.open", side_effect=OSError("unreadable")), \
                    patch.object(env, "Popen", side_effect=OSError("missing")):
                self.assertEqual(env.env_from_sourcing("missing-command"), {})

    def test_source_list_skips_disabled_entries_and_continues_after_failure(self):
        with patch.object(env, "env_from_sourcing", side_effect=[ValueError("bad"), {"OK": "yes"}]) as source, \
                patch("xpra.log.Logger"):
            self.assertEqual(env.source_env(["", "no", "bad", "good"]), {"OK": "yes"})
            self.assertEqual([call.args[0] for call in source.call_args_list], ["bad", "good"])


class TestNumpyImportContext(unittest.TestCase):

    def test_lock_is_released_after_an_exception(self):
        lock = Mock()
        with patch.object(env, "numpy_import_lock", lock), patch("time.sleep"), \
                patch.dict(os.environ, {"XPRA_NUMPY_LOCK_SLEEP": "0"}):
            with self.assertRaisesRegex(ValueError, "callback failed"):
                with env.NumpyImportContext("test"):
                    self.assertEqual(os.environ["XPRA_NUMPY_IMPORT"], "1")
                    raise ValueError("callback failed")
            self.assertNotIn("XPRA_NUMPY_IMPORT", os.environ)
            lock.acquire.assert_called_once_with(blocking=False)
            lock.release.assert_called_once_with()

    def test_contended_nonblocking_lock_fails_without_releasing_the_owner(self):
        lock = Lock()
        lock.acquire()
        self.addCleanup(lock.release)
        with patch.object(env, "numpy_import_lock", lock), patch("xpra.log.Logger"):
            with self.assertRaisesRegex(RuntimeError, "already held"):
                with env.NumpyImportContext("owner"):
                    self.fail("the import context must not run")
        self.assertTrue(lock.locked())

    def test_subsystem_override_and_module_restoration(self):
        saved = object()
        with patch.dict(sys.modules, {"numpy": saved}), patch.dict(os.environ, {"XPRA_NUMPY": "0", "XPRA_OPENGL_NUMPY": "0"}):
            with env.numpy_import_context("OpenGL: renderer"):
                self.assertIsNone(sys.modules["numpy"])
            self.assertIs(sys.modules["numpy"], saved)
            os.environ["XPRA_OPENGL_NUMPY"] = "1"
            self.assertIsInstance(env.numpy_import_context("OpenGL: renderer"), env.NumpyImportContext)
        name = "_xpra_test_absent_module"
        with patch.dict(sys.modules):
            sys.modules.pop(name, None)
            with env.nomodule_context(name):
                self.assertIsNone(sys.modules[name])
            self.assertNotIn(name, sys.modules)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
