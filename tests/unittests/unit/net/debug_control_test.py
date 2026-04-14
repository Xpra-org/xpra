#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestDebugControl(unittest.TestCase):

    def _dc(self):
        from xpra.net.control.debug import DebugControl
        return DebugControl()

    def test_no_args_returns_help(self):
        dc = self._dc()
        result = dc.run()
        assert isinstance(result, str)
        assert "debug" in result.lower()

    def test_status(self):
        dc = self._dc()
        result = dc.run("status")
        assert isinstance(result, str)
        assert "logging" in result.lower()

    def test_mark_no_message(self):
        dc = self._dc()
        result = dc.run("mark")
        assert isinstance(result, str)
        assert "mark" in result.lower()

    def test_mark_with_message(self):
        dc = self._dc()
        result = dc.run("mark", "hello", "world")
        assert isinstance(result, str)
        assert "mark" in result.lower()

    def test_enable_known_category(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        result = dc.run("enable", "util")
        assert isinstance(result, str)
        # clean up
        dc.run("disable", "util")

    def test_disable_known_category(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        result = dc.run("disable", "util")
        assert isinstance(result, str)

    def test_enable_restricted_category(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        from xpra.log import RESTRICTED_DEBUG_CATEGORIES
        dc = self._dc()
        if CONTROL_DEBUG >= 2 or not RESTRICTED_DEBUG_CATEGORIES:
            return
        cat = next(iter(RESTRICTED_DEBUG_CATEGORIES))
        result = dc.run("enable", cat)
        assert "restricted" in result.lower() or "Warning" in result, repr(result)

    def test_enable_missing_args_raises(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        from xpra.net.control.common import ControlError
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        with self.assertRaises(ControlError):
            dc.run("enable")

    def test_unknown_verb_raises(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        from xpra.net.control.common import ControlError
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        with self.assertRaises(ControlError):
            dc.run("not-a-verb", "category")

    def test_add_backtrace(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        result = dc.run("add-backtrace", "test-expr")
        assert "test-expr" in result
        # clean up
        dc.run("remove-backtrace", "test-expr")

    def test_remove_backtrace(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        dc.run("add-backtrace", "test-expr2")
        result = dc.run("remove-backtrace", "test-expr2")
        assert "test-expr2" in result

    def test_add_regex(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        result = dc.run("add-regex", "test.*pattern")
        assert isinstance(result, str)
        dc.run("remove-regex", "test.*pattern")

    def test_remove_regex(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        dc.run("add-regex", "another.*pattern")
        result = dc.run("remove-regex", "another.*pattern")
        assert isinstance(result, str)

    def test_enable_plus_separated(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG <= 0:
            return
        # "+" separator for multiple categories
        result = dc.run("enable", "network+ssl")
        assert isinstance(result, str)
        dc.run("disable", "network+ssl")

    def test_control_debug_restricted(self):
        from xpra.net.control.debug import CONTROL_DEBUG
        dc = self._dc()
        if CONTROL_DEBUG > 0:
            return
        # when CONTROL_DEBUG <= 0, any enable/disable beyond "mark" is restricted
        result = dc.run("enable", "util")
        assert "restricted" in result.lower()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
