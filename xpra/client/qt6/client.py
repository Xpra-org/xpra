#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import uuid
from time import monotonic
from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QTcpSocket

from xpra import __version__
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

    def connect(self, host, port: int):
        self.socket.connectToHost(host, port)
        # self.socket.connectToHost(QHostAddress.SpecialAddress.LocalHost, 10000)
        self.socket.connected.connect(self.socket_connected)

    def socket_error(self, *args):
        netlog(f"socket_error{args}")

    def socket_hostfound(self, *args):
        netlog(f"socket_hostfound{args}")

    def socket_statechanged(self, *args):
        netlog(f"socket_statechanged{args}")

    def socket_disconnected(self, *args):
        netlog.warn(f"socket_disconnected{args}")

    def socket_connected(self, *args):
        netlog(f"socket_connected{args}")
        self.send_hello()

    def send_hello(self):
        hello = {
            "version": __version__,
            "client_type": "qt6",
            "rencodeplus": True,
            "session-id": uuid.uuid4().hex,
            "windows": True,
            "encodings": ("rgb32", "rgb24", ),
        }
        self.send("hello", hello)

    def send(self, packet_type: str, *args):
        packet = (packet_type, *args)
        data = dumps(packet)
        header = pack_header(FLAGS_RENCODEPLUS, 0, 0, len(data))
        bin_packet = header+data
        self.socket.write(bin_packet)
        self.socket.flush()
        netlog(f"sent {packet_type!r}: {bin_packet!r}")

    def socket_read(self, *args):
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

    def process_packet(self, packet):
        packet_type_fn_name = str(packet[0]).replace("-", "_")
        meth = getattr(self, f"_process_{packet_type_fn_name}", None)
        if not meth:
            netlog.warn(f"Warning: missing handler for {packet[0]!r}")
            netlog("packet=%r", packet)
            return
        meth(packet)

    def _process_hello(self, packet: tuple):
        self.hello = packet[1]
        netlog.info("got hello from %s server" % self.hello.get("version", ""))

    def _process_setting_change(self, packet: tuple):
        setting = packet[1]
        netlog.info(f"ignoring setting-change for {setting!r}")

    def _process_startup_complete(self, packet: tuple):
        netlog.info("client is connected")

    def _process_encodings(self, packet: tuple):
        log(f"server encodings: {packet[1]}")

    def _process_new_window(self, packet):
        from xpra.client.qt6.window import ClientWindow
        wid, x, y, w, h = (int(item) for item in packet[1:6])
        metadata = packet[6]
        window = ClientWindow(self, wid, x, y, w, h, metadata)
        self.windows[wid] = window
        window.show()
        self.send("map-window", wid, x, y, w, h)

    def _process_draw(self, packet):
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

    def update_focus(self, wid=0):
        if self.focused == wid:
            return
        self.focused = wid

        def recheck_focus():
            if self.focused == wid:
                self.send("focus", wid, ())
        QTimer.singleShot(10, recheck_focus)
