#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.net.control.common import (
    ArgsControlCommand,
    ControlCode,
    ControlCommand,
    ControlError,
    HelpCommand,
    parse_4intlist,
    parse_boolean_value,
    process_control_command,
)


class ControlCommonTest(unittest.TestCase):

    def test_parse_4intlist(self):
        self.assertEqual(parse_4intlist(""), [])
        self.assertEqual(parse_4intlist("(0,10,100,20)"), [[0, 10, 100, 20]])
        self.assertEqual(parse_4intlist("(1,2,3,4), (5,6,7,8)"), [[1, 2, 3, 4], [5, 6, 7, 8]])
        for invalid in ("garbage", "(1,2,3)", "(1,2,3,'4')", "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_4intlist(invalid)

    def test_boolean_and_argument_validation(self):
        self.assertIs(parse_boolean_value("yes"), True)
        self.assertIs(parse_boolean_value("OFF"), False)
        with self.assertRaises(ControlError):
            parse_boolean_value("maybe")
        command = ArgsControlCommand("add", run=lambda a, b: str(a + b), validation=(int, int), min_args=2, max_args=2)
        self.assertEqual(command.run("2", "3"), "5")
        for args in (("1",), ("1", "2", "3"), ("bad", "2")):
            with self.subTest(args=args), self.assertRaises(ControlError):
                command.run(*args)

    def test_help_and_dispatch(self):
        commands = {"hello": ControlCommand("hello", "a greeting", lambda name="world": f"hello {name}")}
        help_command = HelpCommand(commands)
        self.assertIn("hello", help_command.run())
        self.assertIn("a greeting", help_command.run("hello"))
        with self.assertRaises(ControlError):
            help_command.run("missing")

        protocol = SimpleNamespace(_conn=SimpleNamespace(options={"control": "yes"}))
        self.assertEqual(process_control_command(protocol, commands, "hello", "X"), (ControlCode.OK, "hello X"))
        self.assertEqual(process_control_command(protocol, commands, "missing")[0], ControlCode.INVALID)
        protocol._conn.options["control"] = "no"
        self.assertEqual(process_control_command(protocol, commands, "hello")[0], ControlCode.INVALID)

    def test_dispatch_errors_and_wildcard(self):
        protocol = SimpleNamespace(_conn=SimpleNamespace(options={"control": "yes"}))
        fallback = ControlCommand("*", run=lambda *args: ",".join(args))
        self.assertEqual(process_control_command(protocol, {"*": fallback}, "unknown", "a"), (ControlCode.OK, "a"))
        for error, code in ((ValueError("bad"), ControlCode.FAILED),
                            (ControlError("bad", code=ControlCode.INVALID), ControlCode.INVALID),
                            (RuntimeError("bad"), ControlCode.FAILED)):
            command = ControlCommand("fail", run=lambda error=error: (_ for _ in ()).throw(error))
            self.assertEqual(process_control_command(protocol, {"fail": command}, "fail")[0], code)


if __name__ == "__main__":
    unittest.main()
