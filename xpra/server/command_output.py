# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Bounded output collection for one-shot command requests.

Only the collector touches pipe descriptors. ChildReaper owns process exit
tracking, and all request lifecycle callbacks run on the GLib main thread.
"""

import os
from threading import Event, Lock

from xpra.os_util import WIN32
from xpra.net.common import Packet
from xpra.net.constants import MAX_PACKET_SIZE
from xpra.util.child_reaper import get_child_reaper
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("exec")

CHUNK_SIZE = 64 * 1024
OUTPUT_LIMIT = min(1024 * 1024, max(0, (MAX_PACKET_SIZE - 4096) // 2))


def pipe_reader(pipe):
    fd = pipe.fileno()
    if not WIN32:
        os.set_blocking(fd, False)

        def read():
            try:
                return os.read(fd, CHUNK_SIZE)
            except BlockingIOError:
                return None
        return read

    # Anonymous Windows pipes cannot be selected, and Python 3.10 does not
    # support os.set_blocking() on them. Read only the bytes known to be ready.
    from ctypes import POINTER, WinError, byref, get_last_error
    from ctypes.wintypes import BOOL, DWORD, HANDLE, LPVOID
    from msvcrt import get_osfhandle
    from xpra.platform.win32.common import kernel32, ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [HANDLE, LPVOID, DWORD, POINTER(DWORD), POINTER(DWORD), POINTER(DWORD)]
    peek.restype = BOOL
    handle = get_osfhandle(fd)

    def read():
        available = DWORD()
        if not peek(handle, None, 0, None, byref(available), None):
            error = get_last_error()
            if error in (ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED):
                return b""
            raise WinError(error)
        if not available.value:
            return None
        return os.read(fd, min(CHUNK_SIZE, available.value))
    return read


class RunCommand:
    def __init__(self, subsystem, proto):
        self.subsystem = subsystem
        self.proto = proto
        self.proc = None
        self.returncode = None
        self.timer = 0
        self.output_done = False
        self.cancelled = False
        self.finished = Event()
        self.stopped = Event()
        self.lock = Lock()
        self.retaining = True
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.truncated = {"stdout": False, "stderr": False}

    def start(self, proc, wait_time: int) -> None:
        self.proc = proc
        self.subsystem._run_requests.add(self)
        self.timer = self.subsystem.timeout_add(wait_time, self.expire)
        start_thread(self.collect, f"command-output-{proc.pid}", daemon=True)

    def save(self, stream: str, data: bytes) -> None:
        with self.lock:
            if self.retaining:
                buffer = self.buffers[stream]
                remaining = OUTPUT_LIMIT - len(buffer)
                buffer.extend(data[:remaining])
                if len(data) > remaining:
                    self.truncated[stream] = True

    def collect(self) -> None:
        pipes = {"stdout": self.proc.stdout, "stderr": self.proc.stderr}
        try:
            readers = {name: pipe_reader(pipe) for name, pipe in pipes.items()}
            while readers and not self.stopped.is_set():
                final_drain = self.finished.is_set()
                got_data = False
                for name, read in tuple(readers.items()):
                    # Fairness during collection, and a bounded final drain if
                    # descendants continue writing after the command exits.
                    for _ in range(OUTPUT_LIMIT // CHUNK_SIZE + 1):
                        if self.stopped.is_set():
                            break
                        data = read()
                        if data is None:
                            break
                        if not data:
                            del readers[name]
                            break
                        got_data = True
                        self.save(name, data)
                if final_drain:
                    break
                if not got_data:
                    self.stopped.wait(0.01)
        except (OSError, ValueError):
            log.error("Error collecting command output for pid %s", self.proc.pid, exc_info=True)
            with self.lock:
                for name in pipes:
                    self.truncated[name] = True
        finally:
            for pipe in pipes.values():
                pipe.close()
            self.subsystem.idle_add(self.collected)

    def snapshot(self) -> dict:
        with self.lock:
            self.retaining = False
            result = {name: bytes(buffer) for name, buffer in self.buffers.items()}
            result.update({f"{name}-truncated": value for name, value in self.truncated.items()})
            for buffer in self.buffers.values():
                buffer.clear()
            return result

    def cancel_timer(self) -> None:
        if self.timer:
            self.subsystem.source_remove(self.timer)
            self.timer = 0

    def reply(self) -> None:
        self.cancel_timer()
        response = self.snapshot()
        response["pid"] = self.proc.pid
        if self.returncode is not None:
            response["returncode"] = self.returncode
        proto = self.proto
        self.proto = None
        if proto and not proto.is_closed():
            proto.send_now(Packet("hello", {"run_response": response}))

    def expire(self) -> bool:
        self.timer = 0
        get_child_reaper().poll()
        # The reaper's exit callback may still be queued on the main loop.
        if self.proc.returncode is not None:
            self.exited(self.proc)
        if self.proto:
            self.reply()
        return False

    def exited(self, proc) -> None:
        self.returncode = proc.returncode
        self.finished.set()
        if self.output_done:
            if self.proto:
                self.reply()
            self.subsystem._run_requests.discard(self)

    def collected(self) -> bool:
        self.output_done = True
        if self.returncode is not None or self.cancelled:
            if self.proto:
                self.reply()
            self.subsystem._run_requests.discard(self)
        return False

    def disconnect(self) -> None:
        self.proto = None
        self.cancel_timer()
        self.snapshot()

    def cleanup(self) -> None:
        self.cancelled = True
        self.disconnect()
        self.stopped.set()
