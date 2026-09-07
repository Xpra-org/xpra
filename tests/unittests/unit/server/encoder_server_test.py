#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest
from time import monotonic, sleep
from threading import Event, current_thread
from unittest.mock import Mock

from xpra.os_util import POSIX
from xpra.util.io import pollwait
from unit.process_test_util import ProcessTestUtil, log

# the socket path must fit in `sockaddr_un.sun_path`:
MAX_SOCKET_PATH = 100
# the encoder server loads every codec on startup, which can be slow:
START_TIMEOUT = 60
ENCODE_TIMEOUT = 60


class EncoderServerTest(ProcessTestUtil):
    """
    Round-trip test for the `encoder` server mode:
    the `encode` client sends an image to the server and saves the encoded result.
    This is the only coverage for this server mode,
    which failed to start for a while without anything noticing.
    """

    def setUp(self):
        super().setUp()
        if not POSIX:
            self.skipTest("unix domain sockets are only used on posix")
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("python-pillow is required by the encoder server")
            return
        self.tmpdir = tempfile.mkdtemp(prefix="xpra-enc-")
        self.sockpath = os.path.join(self.tmpdir, "e.sock")
        if len(self.sockpath) > MAX_SOCKET_PATH:
            self.skipTest(f"the temporary directory path is too long for a unix socket: {self.tmpdir!r}")
            return
        self.image = os.path.join(self.tmpdir, "input.png")
        Image.new("RGB", (48, 32), (255, 0, 0)).save(self.image)
        self.server = None

    def tearDown(self):
        server = self.server
        self.server = None
        if server and server.poll() is None:
            server.terminate()
            pollwait(server, 10)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def start_encoder_server(self):
        cmd = self.get_xpra_cmd() + [
            "encoder",
            f"--bind={self.sockpath}",
            f"--socket-dirs={self.tmpdir}",
            "--daemon=no", "--systemd-run=no", "--mdns=no",
        ]
        self.server = self.run_command(cmd, cwd=self.tmpdir)
        start = monotonic()
        while monotonic() - start < START_TIMEOUT:
            if os.path.exists(self.sockpath):
                return
            if self.server.poll() is not None:
                self.show_proc_error(self.server, "the encoder server terminated")
            sleep(0.5)
        self.show_proc_error(self.server, f"no socket {self.sockpath!r} after {START_TIMEOUT} seconds")

    def encode(self, encoding: str) -> str:
        cmd = self.get_xpra_cmd() + [
            "encode", f"socket://{self.sockpath}", self.image,
            f"--encoding={encoding}",
        ]
        client = self.run_command(cmd, cwd=self.tmpdir)
        r = pollwait(client, ENCODE_TIMEOUT)
        if r != 0:
            self.show_proc_error(client, f"the encode client failed to encode as {encoding!r}, returned {r}")
        return os.path.join(self.tmpdir, f"input.{encoding}")

    def test_encode_jpeg(self):
        from PIL import Image
        self.start_encoder_server()
        save_as = self.encode("jpeg")
        assert os.path.exists(save_as), f"the encode client did not save {save_as!r}"
        with Image.open(save_as) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (48, 32))
        # the server must still be running, and able to serve a second client:
        assert self.server.poll() is None, f"the encoder server terminated: {self.server.poll()}"
        log("test_encode_jpeg() saved %r", save_as)


def stop_encode_thread(ss, gate: Event) -> None:
    gate.set()
    thread = ss.encode_thread
    if thread:
        # an end of queue marker may already have been posted, one more is harmless:
        ss.queue_encode(None)
        thread.join(10)


class EncoderServerCleanupTest(unittest.TestCase):
    """
    The encoders and the cuda device context are shared with the encode thread,
    so they can only be freed from it - and in that order.
    """

    def test_cleanup_source_order(self):
        from xpra.server.encoder.server import EncoderServer
        from xpra.server.source.client_connection import ClientConnection
        from xpra.server.source.encoding import EncodingsConnection

        events = []

        class FakeCudaContext:
            def free(self) -> None:
                events.append(("cuda context freed", current_thread().name))

        class FakeEncoder:
            def clean(self) -> None:
                events.append(("encoder cleaned", current_thread().name))

        ss = ClientConnection(Mock(), Mock(), Mock())
        ss.init_state()
        ss.uuid = "test-uuid"
        ss.cancel_recalculate_timer = Mock()
        ss.cuda_device_context = FakeCudaContext()
        ss.free_cuda_device_context = EncodingsConnection.free_cuda_device_context.__get__(ss)

        server = EncoderServer.__new__(EncoderServer)
        server.encoders = {ss.uuid: {1: FakeEncoder()}}
        server.get_subsystem = Mock(return_value=None)

        # hold the encode thread up, so that everything below is queued before any of it runs:
        gate = Event()
        ss.call_in_encode_thread(gate.wait)
        # the encode thread is not a daemon: it must be released even if an assertion fails below,
        # or it would keep the test process alive forever
        self.addCleanup(stop_encode_thread, ss, gate)

        server.cleanup_source(ss)
        self.assertEqual(server.encoders, {})
        self.assertEqual(events, [], "the encoders must not be cleaned from the calling thread")

        # `ClientConnectionMuxer.close()`, in mixin cleanup order:
        ss.close_event.set()
        EncodingsConnection.cleanup(ss)
        ss.cleanup()

        gate.set()
        ss.encode_thread.join(10)
        self.assertFalse(ss.encode_thread.is_alive())

        self.assertEqual([name for name, _ in events], ["encoder cleaned", "cuda context freed"])
        for name, thread_name in events:
            self.assertEqual(thread_name, "encode", f"{name!r} did not run in the encode thread")
        self.assertIsNone(ss.cuda_device_context)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
