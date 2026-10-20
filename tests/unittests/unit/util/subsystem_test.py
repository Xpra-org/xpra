#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.scripts.config import InitExit
from xpra.util import subsystem as dispatch


class SubsystemDispatchTest(unittest.TestCase):

    def test_empty_mapping(self):
        self.assertIsNone(dispatch.call({}, "setup"))
        self.assertEqual(dispatch.merge({}, "get_info"), {})
        self.assertIsNone(dispatch.first_truthy({}, "parse_hello"))

    def test_call_order_and_arguments(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                calls = []
                subsystems = {
                    "first": SimpleNamespace(cleanup=lambda *args: calls.append(("first", args))),
                    "second": SimpleNamespace(cleanup=lambda *args: calls.append(("second", args))),
                }
                dispatch.call(subsystems, "cleanup", "source", 1, reverse=reverse)
                expected = [("first", ("source", 1)), ("second", ("source", 1))]
                self.assertEqual(calls, expected[::-1] if reverse else expected)

    def test_call_snapshots_subsystems(self):
        following = Mock()
        subsystems = {
            "first": SimpleNamespace(cleanup=lambda: subsystems.clear()),
            "second": SimpleNamespace(cleanup=following),
        }
        dispatch.call(subsystems, "cleanup")
        following.assert_called_once_with()
        self.assertEqual(subsystems, {})

    def test_missing_and_non_callable_methods(self):
        for operation in (dispatch.call, dispatch.merge, dispatch.first_truthy):
            with self.subTest(operation=operation.__name__):
                following = Mock(return_value={"ready": True})
                subsystems = {
                    "missing": SimpleNamespace(),
                    "non-callable": SimpleNamespace(method=1),
                    "following": SimpleNamespace(method=following),
                }
                with patch.object(dispatch, "log") as log:
                    result = operation(subsystems, "method", "source")
                following.assert_called_once_with("source")
                self.assertEqual(log.warn.call_count, 0 if operation is dispatch.first_truthy else 2)
                self.assertEqual(result, None if operation is dispatch.call else {"ready": True})

    def test_init_exit_propagates(self):
        for operation in (dispatch.call, dispatch.merge, dispatch.first_truthy):
            with self.subTest(operation=operation.__name__):
                error = InitExit(1, "startup failed")
                failing = Mock(side_effect=error)
                following = Mock()
                subsystems = {
                    "failing": SimpleNamespace(method=failing),
                    "following": SimpleNamespace(method=following),
                }
                with patch.object(dispatch, "log") as log, self.assertRaises(InitExit) as raised:
                    operation(subsystems, "method", "source")
                self.assertIs(raised.exception, error)
                failing.assert_called_once_with("source")
                following.assert_not_called()
                log.warn.assert_not_called()

    def test_ordinary_errors_warn_and_continue(self):
        for operation in (dispatch.call, dispatch.merge):
            with self.subTest(operation=operation.__name__):
                following = Mock(return_value={"ready": True})
                subsystems = {
                    "failing": SimpleNamespace(method=Mock(side_effect=ValueError("failed"))),
                    "following": SimpleNamespace(method=following),
                }
                with patch.object(dispatch, "log") as log:
                    result = operation(subsystems, "method", "source")
                following.assert_called_once_with("source")
                log.warn.assert_called_once()
                self.assertTrue(log.warn.call_args.kwargs["exc_info"])
                self.assertEqual(result, None if operation is dispatch.call else {"ready": True})

    def test_merge_nested_dictionaries(self):
        first = Mock(return_value={"feature": {"enabled": True, "shared": 1}})
        second = Mock(return_value={"feature": {"value": 2, "shared": 1}})
        subsystems = {
            "first": SimpleNamespace(get_info=first),
            "empty": SimpleNamespace(get_info=lambda *_args: {}),
            "none": SimpleNamespace(get_info=lambda *_args: None),
            "second": SimpleNamespace(get_info=second),
        }
        with patch.dict("os.environ", {"XPRA_DICTMERGE_WARNINGS": "0"}):
            result = dispatch.merge(subsystems, "get_info", "source")
        self.assertEqual(result, {"feature": {"enabled": True, "value": 2, "shared": 1}})
        first.assert_called_once_with("source")
        second.assert_called_once_with("source")

    def test_merge_conflict_propagates(self):
        following = Mock()
        subsystems = {
            "first": SimpleNamespace(get_info=lambda: {"value": 1}),
            "second": SimpleNamespace(get_info=lambda: {"value": 2}),
            "following": SimpleNamespace(get_info=following),
        }
        with patch.object(dispatch, "log") as log, self.assertRaisesRegex(ValueError, "Conflict"):
            dispatch.merge(subsystems, "get_info")
        following.assert_not_called()
        log.warn.assert_not_called()

    def test_first_truthy_short_circuits(self):
        result = {"error": "rejected"}
        first = Mock(return_value="")
        second = Mock(return_value=result)
        following = Mock()
        subsystems = {
            "first": SimpleNamespace(parse_hello=first),
            "second": SimpleNamespace(parse_hello=second),
            "following": SimpleNamespace(parse_hello=following),
        }
        self.assertIs(dispatch.first_truthy(subsystems, "parse_hello", "source"), result)
        first.assert_called_once_with("source")
        second.assert_called_once_with("source")
        following.assert_not_called()

    def test_first_truthy_no_match(self):
        subsystems = {
            "first": SimpleNamespace(parse_hello=lambda: ""),
            "second": SimpleNamespace(parse_hello=lambda: False),
        }
        self.assertIsNone(dispatch.first_truthy(subsystems, "parse_hello"))

    def test_first_truthy_error_propagates(self):
        error = ValueError("rejected")
        following = Mock()
        subsystems = {
            "failing": SimpleNamespace(parse_hello=Mock(side_effect=error)),
            "following": SimpleNamespace(parse_hello=following),
        }
        with patch.object(dispatch, "log") as log, self.assertRaises(ValueError) as raised:
            dispatch.first_truthy(subsystems, "parse_hello")
        self.assertIs(raised.exception, error)
        following.assert_not_called()
        log.warn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
