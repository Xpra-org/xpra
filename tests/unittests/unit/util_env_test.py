#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import warnings
import unittest

from xpra.util.env import (
    OSEnvContext,
    hasenv, unsetenv,
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
        self.assertEqual(shellsub("$KEEP", None), "$KEEP")

    def test_bytes_string(self):
        result = shellsub(b"$VAR/path", {"VAR": "val"})
        self.assertEqual(result, b"val/path")

    def test_bytes_braced(self):
        result = shellsub(b"${VAR}/path", {"VAR": "val"})
        self.assertEqual(result, b"val/path")

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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
