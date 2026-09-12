# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.aio.thread import ThreadedAsyncioLoop
from xpra.net.bytestreams import Connection
from xpra.util.str_fn import memoryview_to_bytes
from xpra.log import Logger

log = Logger("network", "ssh")


class SSHStreamConnection(Connection):
    """Expose AsyncSSH streams through Xpra's blocking connection API."""

    def __init__(self, threaded_loop: ThreadedAsyncioLoop, reader, writer, ssh_connection,
                 endpoint, info=None, options=None, process=None, extra_connections=()):
        super().__init__(endpoint, "ssh", info, options)
        self._threaded_loop = threaded_loop
        self._reader = reader
        self._writer = writer
        self._ssh_connection = ssh_connection
        self._process = process
        self._extra_connections = tuple(extra_connections)

    def __repr__(self) -> str:
        return f"asyncssh:{self.target}"

    async def _async_read(self, n: int) -> bytes:
        return await self._reader.read(n)

    def _sync_read(self, n: int) -> bytes:
        try:
            return self._threaded_loop.sync(self._async_read, n)
        except RuntimeError:
            if not self.active:
                return b""
            raise

    def read(self, n: int) -> bytes:
        return self._read(self._sync_read, n)

    async def _async_write(self, data: bytes) -> int:
        self._writer.write(data)
        await self._writer.drain()
        return len(data)

    def _sync_write(self, data: bytes) -> int:
        try:
            return self._threaded_loop.sync(self._async_write, data)
        except RuntimeError:
            if not self.active:
                return 0
            raise

    def write(self, buf, _packet_type: str = "") -> int:
        return self._write(self._sync_write, memoryview_to_bytes(buf))

    def set_timeout(self, timeout) -> None:
        # AsyncSSH owns the underlying non-blocking socket. The timeout is
        # retained for callers which inspect it, but it cannot be set there.
        self.timeout = timeout or 0

    async def _async_close(self) -> None:
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            log("closing asyncssh channel", exc_info=True)
        connection = self._ssh_connection
        if connection:
            connection.close()
            try:
                await connection.wait_closed()
            except Exception:
                log("closing asyncssh connection", exc_info=True)
        for extra in reversed(self._extra_connections):
            extra.close()
            try:
                await extra.wait_closed()
            except Exception:
                log("closing asyncssh tunnel connection", exc_info=True)

    def close(self) -> None:
        if not self.active:
            return
        super().close()
        self._threaded_loop.call(self._async_close())

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        connection = self._ssh_connection
        if connection:
            info["asyncssh"] = {
                "client-version": connection.get_extra_info("client_version", ""),
                "server-version": connection.get_extra_info("server_version", ""),
                "peername": connection.get_extra_info("peername", ()),
            }
        return info
