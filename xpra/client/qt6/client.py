#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import uuid
import signal
from time import monotonic
from collections.abc import Sequence
from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtNetwork import QTcpSocket
from PyQt6.QtWidgets import QApplication

from xpra import __version__
from xpra.exit_codes import ExitCode, ExitValue
from xpra.net.common import PacketType
from xpra.net.rencodeplus.rencodeplus import dumps, loads
from xpra.net.protocol.header import pack_header, unpack_header, FLAGS_RENCODEPLUS

from xpra.log import Logger

log = Logger("client")
netlog = Logger("network")


class Qt6Client:
    def __init__(self):
        self.windows: dict[int, Any] = {}
        self.socket = self.setup_socket()
        self.raw_packets = {}
        self.header = ()
        self.hello = {}
        self.focused = 0

    def setup_socket(self) -> QTcpSocket:
        socket = QTcpSocket()
        socket.disconnected.connect(self.socket_disconnected)
        socket.errorOccurred.connect(self.socket_error)
        socket.hostFound.connect(self.socket_hostfound)
        socket.stateChanged.connect(self.socket_statechanged)
        socket.readyRead.connect(self.socket_read)
        return socket

    def connect(self, host: str, port: int) -> None:
        log(f"connect({host}, {port})")
        self.socket.connectToHost(host, port)
        self.socket.connected.connect(self.socket_connected)

    def socket_error(self, *args) -> None:
        netlog(f"socket_error{args}")

    def socket_hostfound(self, *args) -> None:
        netlog(f"socket_hostfound{args}")

    def socket_statechanged(self, *args) -> None:
        netlog(f"socket_statechanged{args}")

    def socket_disconnected(self, *args) -> None:
        netlog(f"socket_disconnected{args}")
        self.quit(ExitCode.CONNECTION_LOST)

    def quit(self, exit_code: ExitValue):
        QApplication.exit(int(exit_code))

    def socket_connected(self, *args) -> None:
        netlog(f"socket_connected{args}")
        self.send_hello()

    def get_encodings(self) -> Sequence[str]:
        return "rgb", "png", "jpg", "webp"

    def send_hello(self) -> None:
        hello = {
            "version": __version__,
            "client_type": "qt6",
            "rencodeplus": True,
            "session-id": uuid.uuid4().hex,
            "windows": True,
            "keyboard": True,
            "mouse": True,
            "encodings": ("rgb32", "rgb24", "png", "jpg", "webp"),
            "network-state": False,  # tell older server that we don't have "ping"
        }
        self.send("hello", hello)

    def send(self, packet_type: str, *args) -> None:
        packet = (packet_type, *args)
        data = dumps(packet)
        header = pack_header(FLAGS_RENCODEPLUS, 0, 0, len(data))
        bin_packet = header+data
        self.socket.write(bin_packet)
        self.socket.flush()
        netlog(f"sent {packet_type!r}: {bin_packet!r}")

    def socket_read(self, *args) -> None:
        netlog(f"socket_read{args}")
        while avail := self.socket.bytesAvailable():
            need = 8 if not self.header else self.header[4]
            netlog(f" {need=}, available={avail}, header={self.header}")
            if avail < need:
                return
            if not self.header:
                assert need == 8 and avail >= 8
                header_bytes = self.socket.read(8)
                self.header = unpack_header(header_bytes)
                need = self.header[4]
                avail -= 8
            if avail < need:
                return
            packet_data = self.socket.read(need)
            netlog(f"read({need})={packet_data}")
            index = self.header[3]
            self.header = ()
            if index > 0:
                self.raw_packets[index] = packet_data
                continue
            packet = loads(packet_data)
            if self.raw_packets:
                packet = list(packet)
                for index, data in self.raw_packets.items():
                    packet[index] = data
                self.raw_packets = {}
            self.process_packet(packet)

    def process_packet(self, packet: PacketType) -> None:
        packet_type_fn_name = str(packet[0]).replace("-", "_")
        meth = getattr(self, f"_process_{packet_type_fn_name}", None)
        if not meth:
            netlog.warn(f"Warning: missing handler for {packet[0]!r}")
            netlog("packet=%r", packet)
            return
        meth(packet)

    def _process_hello(self, packet: PacketType) -> None:
        self.hello = packet[1]
        netlog.info("got hello from %s server" % self.hello.get("version", ""))

    def _process_setting_change(self, packet: PacketType) -> None:
        setting = packet[1]
        netlog.info(f"ignoring setting-change for {setting!r}")

    def _process_startup_complete(self, _packet: PacketType) -> None:
        netlog.info("client is connected")

    def _process_encodings(self, packet: PacketType) -> None:
        log(f"server encodings: {packet[1]}")

    def _process_new_window(self, packet: PacketType) -> None:
        self.new_window(packet)

    def _process_new_override_redirect(self, packet: PacketType) -> None:
        self.new_window(packet, True)

    def new_window(self, packet: PacketType, is_or=False) -> None:
        from xpra.client.qt6.window import ClientWindow
        wid, x, y, w, h = (int(item) for item in packet[1:6])
        metadata = packet[6]
        if is_or:
            metadata["override-redirect"] = is_or
        window = ClientWindow(self, wid, x, y, w, h, metadata)
        self.windows[wid] = window
        window.show()

    def _process_lost_window(self, packet: PacketType) -> None:
        wid = int(packet[1])
        window = self.windows.get(wid)
        if window:
            window.close()
            del self.windows[wid]

    def _process_raise_window(self, packet: PacketType) -> None:
        wid = int(packet[1])
        window = self.windows.get(wid)
        if window:
            window.raise_()

    def _process_draw(self, packet: PacketType) -> None:
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        window = self.windows.get(wid)
        now = monotonic()
        if window:
            message = ""
            window.draw(x, y, width, height, coding, data, rowstride)
            decode_time = int(1000 * (monotonic() - now))
        else:
            message = f"Warning: window {wid} not found"
            log.warn(message)
            decode_time = -1
        self.send("damage-sequence", packet_sequence, wid, width, height, decode_time, message)

    def _process_window_metadata(self, packet: PacketType) -> None:
        wid = packet[1]
        metadata = packet[2]
        log.info(f"window {wid}: {metadata}")

    def update_focus(self, wid=0) -> None:
        if self.focused == wid:
            return
        self.focused = wid

        def recheck_focus() -> None:
            if self.focused == wid:
                self.send("focus", wid, ())
        QTimer.singleShot(10, recheck_focus)

    def state_changed(self, state) -> None:
        log(f"state changed: {state}")
        if state == Qt.ApplicationState.ApplicationInactive:
            self.focused = 0
            self.send("focus", 0, ())


class XpraQt6Client(Qt6Client):
    """
    This class is just here to add the methods expected by the xpra.scripts.main script
    as these exist in the GTK3 client class.
    """

    def show_progress(self, pct: int, msg) -> None:
        log(f"show_progress({pct}, {msg})")

    def init(self, opts) -> None:
        """ we don't handle any options yet! """

    def init_ui(self, opts) -> None:
        """ we don't handle any options yet! """

    def cleanup(self) -> None:
        """ client classes must define this method """

    def make_protocol(self, conn):
        """
        Warnings:
            * this only works for plain `tcp` sockets
            * I couldn't figure out how to pass the existing socket file descriptor to QTcpSocket,
            so we re-open the connection instead...
        """
        from xpra.net.bytestreams import SocketConnection
        if not isinstance(conn, SocketConnection) or conn.socktype != "tcp":
            raise ValueError("only tcp socket connections are supported!")

        def connect():
            # self.socket.setSocketDescriptor(conn._socket.fileno())
            self.connect(*conn.remote)

        QTimer.singleShot(0, connect)

        class FakeProtocol:

            def start(self) -> None:
                log("FakeProtocol.start()")
                conn.close()
        return FakeProtocol()


def make_client() -> XpraQt6Client:
    app = QApplication([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    client = XpraQt6Client()
    app.applicationStateChanged.connect(client.state_changed)
    client.run = app.exec
    return client


def run_client(host: str, port: int) -> int:
    client = make_client()
    client.connect(host, port)
    return client.run()
