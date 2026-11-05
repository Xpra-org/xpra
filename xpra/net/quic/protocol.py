# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from aioquic.asyncio.protocol import QuicConnectionProtocol

from xpra.net.quic.congestion import get_congestion_control


class XpraQuicConnectionProtocol(QuicConnectionProtocol):

    def transmit(self) -> None:
        super().transmit()
        if control := get_congestion_control(self._quic):
            # Incoming datagrams and recovery timers also finish with transmit(),
            # so queued bytes update even when the application writes no new data.
            control.update_pending_streams(self._quic)
