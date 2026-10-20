#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from unittest.mock import patch, MagicMock

from xpra.server.source import printer
from xpra.server.source.printer import PrinterConnection


def setup_printer(name: str, props: dict, hostname="host") -> tuple:
    pc = PrinterConnection()
    pc.init_state()
    pc.hostname = hostname
    pycups_printing = MagicMock()
    with patch.dict(sys.modules, {"xpra.platform.pycups_printing": pycups_printing}):
        pc.setup_printer(name, props, {})
    add_printer = pycups_printing.add_printer
    add_printer.assert_called_once()
    return add_printer.call_args.args


class PrinterConnectionTest(unittest.TestCase):

    def test_info_is_single_line(self):
        args = setup_printer("printer", {"printer-info": "Laser\x1b[2J\nDescription\u202e" + "x" * 1000})
        info = args[2]
        self.assertTrue(info.startswith("Laser[2J Description"))
        self.assertTrue(info.isprintable())
        self.assertLessEqual(len(info), printer.MAX_PRINTER_INFO)

    def test_too_many_printers(self):
        pc = PrinterConnection()
        pc.init_state()
        pc.machine_id = "not-this-machine"
        pc.uuid = "client-uuid"
        pc.unix_socket_paths = ()
        printers = {f"printer{i}": {} for i in range(printer.MAX_PRINTERS * 4)}
        with patch.object(pc, "setup_printer") as setup:
            pc.set_printers(printers, (), ())
        names = [call.args[0] for call in setup.call_args_list]
        self.assertEqual(names, [f"printer{i}" for i in range(printer.MAX_PRINTERS)])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
