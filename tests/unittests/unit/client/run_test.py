#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class RunTest(unittest.TestCase):

    def test_subsystems_run_once(self):
        # the launcher starts the subsystems before connecting, and runs the client once connected:
        from xpra.client.base.client import XpraClientBase
        client = XpraClientBase()
        calls = []

        class Counter:
            @staticmethod
            def run() -> None:
                calls.append("run")
        client.subsystems = {"counter": Counter()}
        client.run_subsystems()
        client.run()
        client.run()
        self.assertEqual(calls, ["run"])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
