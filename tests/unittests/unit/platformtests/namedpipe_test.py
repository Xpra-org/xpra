#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Stress and multi-process tests for the win32 named pipe transport.
All tests are skipped on non-Windows platforms.
"""

import os
import sys
import time
import queue as _queue
import threading
import unittest
import multiprocessing

WIN32 = sys.platform == "win32"

# ---------------------------------------------------------------------------
# Module-level helpers — must be at module level for multiprocessing pickling
# ---------------------------------------------------------------------------


def _read_exactly(conn, n: int) -> bytes:
    """Read exactly *n* bytes, looping over multiple partial reads."""
    buf = b""
    while len(buf) < n:
        chunk = conn.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _mp_echo_client(pipe_name: str, payload: bytes, result_q, timeout: int = 15) -> None:
    """Subprocess worker: connect, write *payload*, read it back, report result."""
    try:
        from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
        handle = connect_to_namedpipe(pipe_name, timeout=timeout)
        conn = NamedPipeConnection(pipe_name, handle, {})
        conn.write(payload, "test")
        received = b""
        while len(received) < len(payload):
            chunk = conn.read(len(payload) - len(received))
            if not chunk:
                break
            received += chunk
        conn.close()
        result_q.put(("ok", received))
    except Exception as e:
        result_q.put(("error", str(e)))


def _mp_burst_client(pipe_name: str, num_messages: int, msg_size: int, result_q, timeout: int = 60) -> None:
    """Subprocess worker: send *num_messages* messages of *msg_size* bytes, read echoes."""
    try:
        from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
        handle = connect_to_namedpipe(pipe_name, timeout=timeout)
        conn = NamedPipeConnection(pipe_name, handle, {})
        msg = (bytes(range(256)) * (msg_size // 256 + 1))[:msg_size]
        total_sent = 0
        total_received = 0
        for _ in range(num_messages):
            conn.write(msg, "test")
            total_sent += msg_size
            received = b""
            while len(received) < msg_size:
                chunk = conn.read(msg_size - len(received))
                if not chunk:
                    break
                received += chunk
            total_received += len(received)
        conn.close()
        result_q.put(("ok", total_sent, total_received))
    except Exception as e:
        result_q.put(("error", str(e)))


# ---------------------------------------------------------------------------
# In-process helpers
# ---------------------------------------------------------------------------

_pipe_serial = 0
_pipe_serial_lock = threading.Lock()


def _unique_pipe(tag: str = "") -> str:
    global _pipe_serial
    with _pipe_serial_lock:
        _pipe_serial += 1
        serial = _pipe_serial
    suffix = ("-%s" % tag) if tag else ""
    return r"\\.\pipe\xpra-np-test-%d-%d%s" % (os.getpid(), serial, suffix)


class _EchoServer:
    """Minimal in-process echo server built on NamedPipeListener."""

    def __init__(self, pipe_name: str):
        from xpra.platform.win32.namedpipes.listener import NamedPipeListener
        self.pipe_name = pipe_name
        self._conns: list = []
        self._threads: list = []
        self._lock = threading.Lock()
        self.connection_count = 0
        self.listener = NamedPipeListener(pipe_name, self._on_connect)

    def start(self) -> None:
        self.listener.start()
        # brief pause so the listener thread enters WaitForSingleObject before clients try
        time.sleep(0.08)

    def _on_connect(self, socktype: str, listener, pipe_handle) -> None:
        from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
        conn = NamedPipeConnection(self.pipe_name, pipe_handle, {})
        with self._lock:
            self._conns.append(conn)
            self.connection_count += 1
        t = threading.Thread(target=self._echo_loop, args=(conn,), daemon=True)
        with self._lock:
            self._threads.append(t)
        t.start()

    def _echo_loop(self, conn) -> None:
        # Use a write queue so the reader and writer run on separate threads.
        # Without this a large-payload echo deadlocks: both sides wait for the
        # other to drain the pipe buffer before they can make progress.
        write_q: _queue.Queue = _queue.Queue()

        def writer() -> None:
            while True:
                data = write_q.get()
                if data is None:
                    break
                try:
                    conn.write(data, "echo")
                except Exception:
                    break

        wt = threading.Thread(target=writer, daemon=True)
        wt.start()
        try:
            while True:
                data = conn.read(65536)
                if not data:
                    break
                write_q.put(data)
        except Exception:
            pass
        finally:
            write_q.put(None)
        wt.join(timeout=10)

    def stop(self) -> None:
        self.listener.stop()
        # Unblock any pending WaitForSingleObject by connecting then immediately closing
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe
            from xpra.platform.win32.common import CloseHandle
            h = connect_to_namedpipe(self.pipe_name, timeout=3)
            CloseHandle(h)
        except Exception:
            pass
        self.listener.join(timeout=8)
        with self._lock:
            for conn in self._conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._conns.clear()


# ---------------------------------------------------------------------------
# Basic / single-client tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "win32 named pipes only available on Windows")
class TestNamedPipeBasic(unittest.TestCase):

    def _server(self, tag: str = "") -> _EchoServer:
        s = _EchoServer(_unique_pipe(tag))
        s.start()
        return s

    def _client(self, pipe_name: str, timeout: int = 5):
        from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
        handle = connect_to_namedpipe(pipe_name, timeout=timeout)
        return NamedPipeConnection(pipe_name, handle, {})

    def test_listener_starts_and_is_alive(self):
        s = self._server("alive")
        try:
            self.assertTrue(s.listener.is_alive())
        finally:
            s.stop()

    def test_single_echo(self):
        s = self._server("echo")
        try:
            conn = self._client(s.pipe_name)
            payload = b"hello named pipe!"
            conn.write(payload, "test")
            result = _read_exactly(conn, len(payload))
            conn.close()
            self.assertEqual(result, payload)
        finally:
            s.stop()

    def test_binary_payload_all_bytes(self):
        """All 256 byte values survive the round-trip unchanged."""
        s = self._server("binary")
        try:
            conn = self._client(s.pipe_name)
            payload = bytes(range(256))
            conn.write(payload, "test")
            result = _read_exactly(conn, 256)
            conn.close()
            self.assertEqual(result, payload)
        finally:
            s.stop()

    def test_large_payload_exceeds_bufsize(self):
        """Payload larger than BUFSIZE (65536) is chunked transparently."""
        s = self._server("large")
        try:
            conn = self._client(s.pipe_name)
            # 256 KB — four times BUFSIZE
            payload = bytes(range(256)) * 1024
            conn.write(payload, "test")
            result = _read_exactly(conn, len(payload))
            conn.close()
            self.assertEqual(len(result), len(payload))
            self.assertEqual(result, payload)
        finally:
            s.stop()

    def test_get_info_reports_type_and_closed(self):
        s = self._server("info")
        try:
            conn = self._client(s.pipe_name)
            info = conn.get_info()
            self.assertEqual(info.get("type"), "named-pipe")
            self.assertFalse(info.get("closed", True))
            conn.close()
            info2 = conn.get_info()
            self.assertTrue(info2.get("closed"))
        finally:
            s.stop()

    def test_double_close_is_safe(self):
        """Closing an already-closed connection must not raise."""
        s = self._server("dblclose")
        try:
            conn = self._client(s.pipe_name)
            conn.write(b"x", "test")
            _read_exactly(conn, 1)
            conn.close()
            conn.close()  # second close must not raise
        finally:
            s.stop()

    def test_client_disconnect_does_not_crash_server(self):
        """Client closing mid-session causes the server echo loop to exit cleanly."""
        s = self._server("cliclose")
        try:
            conn = self._client(s.pipe_name)
            conn.write(b"ping", "test")
            _read_exactly(conn, 4)
            conn.close()
            time.sleep(0.15)
            # If the server echo thread had crashed, s.listener would still be alive;
            # verify the listener is still running (not dead from an unhandled exception)
            self.assertTrue(s.listener.is_alive())
        finally:
            s.stop()

    def test_listener_stop_exits_thread(self):
        """stop() causes the listener thread to exit within a reasonable time."""
        from xpra.platform.win32.namedpipes.listener import NamedPipeListener
        from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe
        from xpra.platform.win32.common import CloseHandle

        pipe_name = _unique_pipe("stop")
        closed_handles = []

        def on_connect(socktype, listener, pipe_handle):
            closed_handles.append(pipe_handle)
            CloseHandle(pipe_handle)

        listener = NamedPipeListener(pipe_name, on_connect)
        listener.start()
        time.sleep(0.08)
        self.assertTrue(listener.is_alive())

        listener.stop()
        # Unblock the pending WaitForSingleObject by connecting
        try:
            h = connect_to_namedpipe(pipe_name, timeout=3)
            CloseHandle(h)
        except Exception:
            pass
        listener.join(timeout=8)
        self.assertFalse(listener.is_alive(), "Listener thread did not stop in time")


# ---------------------------------------------------------------------------
# Concurrent / multi-thread tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "win32 named pipes only available on Windows")
class TestNamedPipeConcurrent(unittest.TestCase):

    def _server(self, tag: str = "") -> _EchoServer:
        s = _EchoServer(_unique_pipe(tag))
        s.start()
        return s

    def test_sequential_connections(self):
        """30 sequential connect → write → echo → close cycles on the same pipe."""
        s = self._server("seq")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            for i in range(30):
                payload = ("seq%04d" % i).encode() * 8
                handle = connect_to_namedpipe(s.pipe_name, timeout=8)
                conn = NamedPipeConnection(s.pipe_name, handle, {})
                conn.write(payload, "test")
                result = _read_exactly(conn, len(payload))
                conn.close()
                self.assertEqual(result, payload, "mismatch at iteration %d" % i)
        finally:
            s.stop()

    def test_concurrent_clients_8_threads(self):
        """8 threads each open a connection and exchange data simultaneously."""
        s = self._server("conc8")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            NUM = 8
            results: dict = {}
            errors: list = []
            lock = threading.Lock()

            def client_thread(idx: int) -> None:
                try:
                    payload = ("client-%04d-" % idx).encode() * 64
                    handle = connect_to_namedpipe(s.pipe_name, timeout=15)
                    conn = NamedPipeConnection(s.pipe_name, handle, {})
                    conn.write(payload, "test")
                    received = _read_exactly(conn, len(payload))
                    conn.close()
                    with lock:
                        results[idx] = (received == payload)
                except Exception as e:
                    with lock:
                        errors.append("client %d: %s" % (idx, e))

            threads = [threading.Thread(target=client_thread, args=(i,), daemon=True) for i in range(NUM)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

            self.assertFalse(errors, "Thread errors: %s" % errors)
            self.assertEqual(len(results), NUM, "Not all clients completed")
            for idx, ok in results.items():
                self.assertTrue(ok, "Data mismatch for client %d" % idx)
        finally:
            s.stop()

    def test_burst_messages_single_connection(self):
        """One connection, 300 back-to-back write/read rounds."""
        s = self._server("burst")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            handle = connect_to_namedpipe(s.pipe_name, timeout=5)
            conn = NamedPipeConnection(s.pipe_name, handle, {})
            msg = b"." * 512
            for i in range(300):
                conn.write(msg, "test")
                result = _read_exactly(conn, len(msg))
                self.assertEqual(result, msg, "mismatch at message %d" % i)
            conn.close()
        finally:
            s.stop()

    def test_concurrent_10_threads(self):
        """10 threads connect and exchange data simultaneously — checks for races / deadlocks."""
        s = self._server("conc10")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            NUM = 10
            ok_count = [0]
            errors: list = []
            lock = threading.Lock()

            def worker(idx: int) -> None:
                try:
                    payload = (b"t%04d" % idx) * 100
                    handle = connect_to_namedpipe(s.pipe_name, timeout=20)
                    conn = NamedPipeConnection(s.pipe_name, handle, {})
                    conn.write(payload, "test")
                    received = _read_exactly(conn, len(payload))
                    conn.close()
                    with lock:
                        if received == payload:
                            ok_count[0] += 1
                        else:
                            errors.append("data mismatch for worker %d" % idx)
                except Exception as e:
                    with lock:
                        errors.append("worker %d: %s" % (idx, e))

            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(NUM)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            self.assertFalse(errors, str(errors))
            self.assertEqual(ok_count[0], NUM)
        finally:
            s.stop()

    def test_concurrent_read_write_on_single_connection(self):
        """One connection: writer and reader run on separate threads simultaneously."""
        s = self._server("rw-split")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            payload = b"rw-interleaved" * 512  # 7 KB
            handle = connect_to_namedpipe(s.pipe_name, timeout=5)
            conn = NamedPipeConnection(s.pipe_name, handle, {})

            received_parts: list = []
            read_done = threading.Event()
            read_error: list = []

            def reader() -> None:
                try:
                    total = 0
                    while total < len(payload):
                        chunk = conn.read(len(payload) - total)
                        if not chunk:
                            break
                        received_parts.append(chunk)
                        total += len(chunk)
                except Exception as e:
                    read_error.append(str(e))
                finally:
                    read_done.set()

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            conn.write(payload, "test")
            read_done.wait(timeout=10)
            conn.close()
            t.join(timeout=5)

            self.assertFalse(read_error, "Reader error: %s" % read_error)
            received = b"".join(received_parts)
            self.assertEqual(received, payload)
        finally:
            s.stop()


# ---------------------------------------------------------------------------
# True multi-process tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "win32 named pipes only available on Windows")
class TestNamedPipeMultiprocess(unittest.TestCase):
    """Each test spawns one or more subprocesses as pipe clients."""

    def _server(self, tag: str = "") -> _EchoServer:
        s = _EchoServer(_unique_pipe(tag))
        s.start()
        return s

    def _run_clients(self, target, args_list, per_proc_timeout: int = 20) -> list:
        """Launch len(args_list) subprocesses, each running target(*args), and collect results."""
        q: multiprocessing.Queue = multiprocessing.Queue()
        procs = []
        for args in args_list:
            p = multiprocessing.Process(target=target, args=(*args, q))
            p.start()
            procs.append(p)
        for p in procs:
            p.join(timeout=per_proc_timeout)
            if p.is_alive():
                p.terminate()
                self.fail("Subprocess did not finish in time")
        results = []
        for _ in range(len(args_list)):
            try:
                results.append(q.get(timeout=3))
            except Exception:
                break
        return results

    def test_single_subprocess_echo(self):
        """One subprocess connects, sends data, reads echo, reports success."""
        s = self._server("mp-single")
        try:
            payload = b"multiprocess hello " * 50
            results = self._run_clients(_mp_echo_client, [(s.pipe_name, payload)])
            self.assertEqual(len(results), 1)
            status, *rest = results[0]
            self.assertEqual(status, "ok", "subprocess error: %s" % rest)
            self.assertEqual(rest[0], payload)
        finally:
            s.stop()

    def test_four_subprocess_clients_concurrent(self):
        """Four subprocesses connect concurrently; each gets its own echo back."""
        s = self._server("mp-4")
        try:
            NUM = 4
            payload = b"concurrent-mp-payload" * 20
            args_list = [(s.pipe_name, payload)] * NUM
            results = self._run_clients(_mp_echo_client, args_list, per_proc_timeout=25)
            self.assertEqual(len(results), NUM, "Expected %d results, got %d" % (NUM, len(results)))
            for i, (status, *rest) in enumerate(results):
                self.assertEqual(status, "ok", "subprocess %d error: %s" % (i, rest))
                self.assertEqual(rest[0], payload, "data mismatch for subprocess %d" % i)
        finally:
            s.stop()

    def test_subprocess_burst_100_messages(self):
        """Subprocess sends 100 × 1 KB messages and expects all echoed back."""
        s = self._server("mp-burst")
        try:
            results = self._run_clients(_mp_burst_client, [(s.pipe_name, 100, 1024)], per_proc_timeout=60)
            self.assertEqual(len(results), 1)
            status, *rest = results[0]
            self.assertEqual(status, "ok", "burst error: %s" % rest)
            sent, received = rest
            self.assertEqual(sent, received, "sent %d, received only %d" % (sent, received))
        finally:
            s.stop()

    def test_subprocess_large_payload(self):
        """Subprocess sends a 256 KB payload and expects it echoed back intact."""
        s = self._server("mp-large")
        try:
            payload = bytes(range(256)) * 1024  # 256 KB
            results = self._run_clients(_mp_echo_client, [(s.pipe_name, payload)], per_proc_timeout=30)
            self.assertEqual(len(results), 1)
            status, *rest = results[0]
            self.assertEqual(status, "ok", "large-payload subprocess error: %s" % rest)
            self.assertEqual(rest[0], payload)
        finally:
            s.stop()

    def test_mixed_subprocess_and_thread_clients(self):
        """Two subprocesses AND two threads connect simultaneously."""
        s = self._server("mp-mixed")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            payload = b"mixed-client-data" * 15

            # Launch subprocesses
            q: multiprocessing.Queue = multiprocessing.Queue()
            procs = []
            for _ in range(2):
                p = multiprocessing.Process(target=_mp_echo_client, args=(s.pipe_name, payload, q))
                p.start()
                procs.append(p)

            # Also launch threads
            thread_results: list = []
            thread_errors: list = []
            lock = threading.Lock()

            def thread_client(idx: int) -> None:
                try:
                    handle = connect_to_namedpipe(s.pipe_name, timeout=15)
                    conn = NamedPipeConnection(s.pipe_name, handle, {})
                    conn.write(payload, "test")
                    received = _read_exactly(conn, len(payload))
                    conn.close()
                    with lock:
                        thread_results.append(received == payload)
                except Exception as e:
                    with lock:
                        thread_errors.append("thread %d: %s" % (idx, e))

            threads = [threading.Thread(target=thread_client, args=(i,), daemon=True) for i in range(2)]
            for t in threads:
                t.start()

            for p in procs:
                p.join(timeout=20)
            for t in threads:
                t.join(timeout=20)

            # Check subprocess results
            mp_results = []
            for _ in range(2):
                try:
                    mp_results.append(q.get(timeout=3))
                except Exception:
                    break
            self.assertEqual(len(mp_results), 2, "Expected 2 subprocess results")
            for status, *rest in mp_results:
                self.assertEqual(status, "ok", "subprocess error: %s" % rest)
                self.assertEqual(rest[0], payload)

            # Check thread results
            self.assertFalse(thread_errors, str(thread_errors))
            self.assertEqual(len(thread_results), 2)
            self.assertTrue(all(thread_results))
        finally:
            s.stop()


# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(WIN32, "win32 named pipes only available on Windows")
class TestNamedPipeStress(unittest.TestCase):

    def _server(self, tag: str = "") -> _EchoServer:
        s = _EchoServer(_unique_pipe(tag))
        s.start()
        return s

    def test_50_sequential_connections(self):
        """50 sequential connect/echo/close cycles; verifies pipe handle recycling."""
        s = self._server("stress-seq")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            payload = b"stress-sequential" * 20
            for i in range(50):
                handle = connect_to_namedpipe(s.pipe_name, timeout=10)
                conn = NamedPipeConnection(s.pipe_name, handle, {})
                conn.write(payload, "test")
                got = _read_exactly(conn, len(payload))
                conn.close()
                self.assertEqual(got, payload, "mismatch at connection %d" % i)
        finally:
            s.stop()

    def test_many_messages_increasing_size(self):
        """Single connection, payloads doubling from 64 B to 128 KB."""
        s = self._server("stress-sizes")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            handle = connect_to_namedpipe(s.pipe_name, timeout=5)
            conn = NamedPipeConnection(s.pipe_name, handle, {})
            size = 64
            while size <= 131072:  # 128 KB
                payload = bytes(i & 0xFF for i in range(size))
                conn.write(payload, "test")
                got = _read_exactly(conn, size)
                self.assertEqual(got, payload, "mismatch at size %d" % size)
                size *= 2
            conn.close()
        finally:
            s.stop()

    def test_8_threads_repeated_connections(self):
        """8 threads, each making 5 sequential connections — 40 total connections."""
        s = self._server("stress-thrd")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            NUM_THREADS = 8
            CONNS_PER_THREAD = 5
            ok_count = [0]
            errors: list = []
            lock = threading.Lock()

            def worker(idx: int) -> None:
                try:
                    payload = (b"w%04d" % idx) * 50
                    for _ in range(CONNS_PER_THREAD):
                        handle = connect_to_namedpipe(s.pipe_name, timeout=15)
                        conn = NamedPipeConnection(s.pipe_name, handle, {})
                        conn.write(payload, "test")
                        received = _read_exactly(conn, len(payload))
                        conn.close()
                        if received != payload:
                            with lock:
                                errors.append("data mismatch in worker %d" % idx)
                            return
                    with lock:
                        ok_count[0] += 1
                except Exception as e:
                    with lock:
                        errors.append("worker %d: %s" % (idx, e))

            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(NUM_THREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            self.assertFalse(errors, str(errors))
            self.assertEqual(ok_count[0], NUM_THREADS)
        finally:
            s.stop()

    def test_8_subprocess_clients_concurrent(self):
        """8 subprocesses hit the server at the same time."""
        s = self._server("stress-mp8")
        try:
            NUM = 8
            payload = b"stress-mp-concurrent" * 10
            q: multiprocessing.Queue = multiprocessing.Queue()
            procs = []
            for _ in range(NUM):
                p = multiprocessing.Process(target=_mp_echo_client, args=(s.pipe_name, payload, q))
                p.start()
                procs.append(p)
            for p in procs:
                p.join(timeout=30)
                if p.is_alive():
                    p.terminate()
                    self.fail("subprocess did not finish")
            results = []
            for _ in range(NUM):
                try:
                    results.append(q.get(timeout=3))
                except Exception:
                    break
            self.assertEqual(len(results), NUM, "Got %d results, expected %d" % (len(results), NUM))
            for i, (status, *rest) in enumerate(results):
                self.assertEqual(status, "ok", "subprocess %d error: %s" % (i, rest))
                self.assertEqual(rest[0], payload)
        finally:
            s.stop()

    def test_connection_count_matches_connections_made(self):
        """Verify the server's connection counter matches the number of clients."""
        s = self._server("stress-count")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            N = 10
            for _ in range(N):
                handle = connect_to_namedpipe(s.pipe_name, timeout=5)
                conn = NamedPipeConnection(s.pipe_name, handle, {})
                conn.write(b"hi", "test")
                _read_exactly(conn, 2)
                conn.close()
            time.sleep(0.1)
            self.assertEqual(s.connection_count, N)
        finally:
            s.stop()

    def test_server_handles_abrupt_client_termination(self):
        """Client closes without reading — server write may fail, must not crash."""
        s = self._server("stress-abrupt")
        try:
            from xpra.platform.win32.namedpipes.connection import connect_to_namedpipe, NamedPipeConnection
            for _ in range(5):
                handle = connect_to_namedpipe(s.pipe_name, timeout=5)
                conn = NamedPipeConnection(s.pipe_name, handle, {})
                # write something so server tries to echo, then close before reading
                conn.write(b"abort", "test")
                conn.close()
                time.sleep(0.05)
            # Listener thread must still be alive after abrupt disconnects
            self.assertTrue(s.listener.is_alive())
        finally:
            s.stop()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
