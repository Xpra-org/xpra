# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import ConnectionTerminated, QuicEvent

from xpra.net.quic.congestion import get_congestion_control


class XpraQuicConnectionProtocol(QuicConnectionProtocol):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # why the connection ended, once it has:
        self.connection_terminated: ConnectionTerminated | None = None

    def quic_event_received(self, event: QuicEvent) -> None:
        # subclasses handle the events, and must call this method first
        super().quic_event_received(event)
        if isinstance(event, ConnectionTerminated):
            self.connection_terminated = event

    def transmit(self) -> None:
        super().transmit()
        quic = self.quic_connection
        if control := get_congestion_control(quic):
            # Incoming datagrams and recovery timers also finish with transmit(),
            # so queued bytes update even when the application writes no new data.
            control.update_pending_streams(quic)
