#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock, patch

from xpra.exit_codes import ExitCode
from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.util.objects import typedict


class Owner:

    def __init__(self):
        self.hello_request_handlers = {}
        self._default_packet_handlers = {}
        # also stands in for the `network` subsystem:
        self.subsystems = {"network": self}
        self.send_disconnect = MagicMock()


class Proto:

    def __init__(self):
        self.max_packet_size = 16 * 1024
        self.abs_max_packet_size = 256 * 1024 * 1024
        self.sent = []

    def send_now(self, packet):
        self.sent.append(packet)


class PrintRequestTest(unittest.TestCase):

    def setUp(self):
        from xpra.server.subsystem.printer import PrinterServer
        self.owner = Owner()
        self.printer = PrinterServer(self.owner)
        self.printer.file_transfer.init_attributes("yes", "1M", "yes")
        self.printer.init_packet_handlers()

    def request(self, proto, size):
        handler = self.owner.hello_request_handlers["print"]
        self.assertTrue(handler(proto, typedict({"request": "print", "print": {"size": size}})))
        hello = proto.sent[-1]
        self.assertEqual(hello[0], "hello")
        return typedict(hello[1]["printer"])

    def test_request_then_file(self):
        proto = Proto()
        printer = self.request(proto, 512 * 1024)
        self.assertTrue(printer.boolget("ready"))
        # the hello reply makes room for the file:
        self.assertGreater(proto.max_packet_size, 512 * 1024)
        self.owner.send_disconnect.assert_not_called()
        handler = self.owner._default_packet_handlers["printer-file"]
        packet = Packet("printer-file", "doc.pdf", b"%PDF", "application/pdf")
        with patch.object(type(self.printer), "do_print_file", return_value=(ExitCode.OK, "sent to 1 client")) as print_file:
            handler(proto, packet)
        print_file.assert_called_once_with(packet)
        self.owner.send_disconnect.assert_called_once_with(proto, ConnectionMessage.DONE, "sent to 1 client")
        # only one file per request:
        self.owner.send_disconnect.reset_mock()
        with patch.object(type(self.printer), "do_print_file") as print_file:
            handler(proto, packet)
        print_file.assert_not_called()
        self.assertEqual(self.owner.send_disconnect.call_args.args[1], ConnectionMessage.PROTOCOL_ERROR)

    def test_print_failure(self):
        proto = Proto()
        self.request(proto, 100)
        handler = self.owner._default_packet_handlers["printer-file"]
        with patch.object(type(self.printer), "do_print_file", return_value=(ExitCode.REMOTE_ERROR, "no clients")):
            handler(proto, Packet("printer-file", "doc.pdf", b"%PDF"))
        self.owner.send_disconnect.assert_called_once_with(proto, ConnectionMessage.SERVER_ERROR, "no clients")

    def test_file_without_request(self):
        proto = Proto()
        with patch.object(type(self.printer), "do_print_file") as print_file:
            self.owner._default_packet_handlers["printer-file"](proto, Packet("printer-file", "doc.pdf", b"%PDF"))
        print_file.assert_not_called()
        self.assertEqual(self.owner.send_disconnect.call_args.args[1], ConnectionMessage.PROTOCOL_ERROR)

    def test_refused_requests(self):
        for size, code in (
            (0, ExitCode.PACKET_FAILURE),
            (2 * 1024 * 1024, ExitCode.FILE_TOO_BIG),
        ):
            with self.subTest(size=size):
                proto = Proto()
                printer = self.request(proto, size)
                self.assertFalse(printer.boolget("ready"))
                self.assertEqual(printer.intget("code"), code)
                self.assertEqual(proto.max_packet_size, 16 * 1024)
                self.assertEqual(self.owner.send_disconnect.call_args.args[1], ConnectionMessage.DONE)
        self.printer.file_transfer.printing = False
        self.assertEqual(self.request(Proto(), 100).intget("code"), ExitCode.UNSUPPORTED)


class PrintClientTest(unittest.TestCase):

    def make_client(self):
        from xpra.client.base.command import PrintClient
        client = PrintClient.__new__(PrintClient)
        client.filename = "doc.pdf"
        client.file_data = b"%PDF" * 10000
        client.command = ("application/pdf", "*", "title")
        client.file_sent = False
        client.exit_code = None
        client.send = MagicMock()
        client.quit = MagicMock()
        client.warn_and_quit = MagicMock()
        return client

    def test_hello_does_not_include_the_file(self):
        client = self.make_client()
        with patch("xpra.client.base.command.SendCommandConnectClient.make_hello", return_value={}):
            caps = client.make_hello()
        self.assertEqual(caps, {"request": "print", "print": {"size": 40000}})

    def test_send_file_when_ready(self):
        client = self.make_client()
        client.do_command(typedict({"printer": {"ready": True}}))
        args = client.send.call_args.args
        self.assertEqual(args[0], "printer-file")
        self.assertEqual(args[1], "doc.pdf")
        self.assertEqual(args[2].data, client.file_data)
        self.assertEqual(args[3:], client.command)
        client._process_connection_close(Packet("connection-close", ConnectionMessage.DONE.value, "sent"))
        client.quit.assert_called_once_with(ExitCode.OK)

    def test_refused(self):
        client = self.make_client()
        client.do_command(typedict({"printer": {"code": int(ExitCode.FILE_TOO_BIG), "info": "too large"}}))
        client.send.assert_not_called()
        self.assertEqual(client.warn_and_quit.call_args.args[0], ExitCode.FILE_TOO_BIG)

    def test_print_failed(self):
        client = self.make_client()
        client.do_command(typedict({"printer": {"ready": True}}))
        client._process_connection_close(Packet("connection-close", ConnectionMessage.SERVER_ERROR.value, "no clients"))
        self.assertEqual(client.warn_and_quit.call_args.args[0], ExitCode.FAILURE)


class PrinterLandlockTest(unittest.TestCase):

    def get_paths(self, printing="yes", env=None):
        from xpra.server.subsystem.printer import PrinterServer
        printer = PrinterServer(Owner())
        printer.file_transfer.init_attributes("no", "1M", printing)
        with patch.dict("os.environ", env or {}, clear=True):
            return printer.get_landlock_paths()

    def test_disabled(self):
        self.assertEqual(self.get_paths("no"), {})

    def test_default_socket(self):
        self.assertEqual(self.get_paths(), {"socket": ("/run/cups", )})

    def test_cups_server_socket(self):
        self.assertEqual(self.get_paths(env={"CUPS_SERVER": "/shared/cups/cups.sock"}), {"socket": ("/shared/cups", )})
        # a remote cups server does not use a socket path:
        self.assertEqual(self.get_paths(env={"CUPS_SERVER": "localhost:631"}), {"socket": ("/run/cups", )})


class PrinterDefinitionTest(unittest.TestCase):

    def setUp(self):
        try:
            from xpra.platform import pycups_printing
        except ImportError as e:
            raise unittest.SkipTest(f"pycups is not available: {e}") from None
        self.pycups = pycups_printing

    def add(self, definition):
        with patch.dict(self.pycups.UNPROBED_PRINTER_DEFS, clear=True):
            self.pycups.add_printer_def("application/pdf", definition)
            return dict(self.pycups.UNPROBED_PRINTER_DEFS)

    def test_driver(self):
        self.assertEqual(self.add("drv:///sample.drv/generic.ppd"), {"application/pdf": ["-m", "drv:///sample.drv/generic.ppd"]})

    def test_model(self):
        model = "lsb/usr/cupsfilters/Generic-PDF_Printer-PDF.ppd"
        self.assertEqual(self.add(model), {"application/pdf": ["-m", model]})

    def test_ppd_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".ppd") as f:
            self.assertEqual(self.add(f.name), {"application/pdf": ["-P", f.name]})

    def test_missing_ppd_file(self):
        self.assertEqual(self.add("/does/not/exist.ppd"), {})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
