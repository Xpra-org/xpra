#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import logging
import threading
import unittest
import subprocess
from unittest.mock import Mock, patch

from xpra.util.env import OSEnvContext
from xpra.util import child_reaper
from xpra.util.child_reaper import get_child_reaper, reaper_cleanup, log


class TestChildReaper(unittest.TestCase):

    def test_exit_callbacks(self):
        for already_exited in (False, True):
            for ignore in (False, True):
                for forget in (False, True):
                    with self.subTest(already_exited=already_exited, ignore=ignore, forget=forget):
                        cr = self.new_reaper()
                        quit_callback = Mock()
                        cr._quit = quit_callback
                        proc = Mock(pid=12345)
                        proc.poll.return_value = 7 if already_exited else None
                        callback = Mock()
                        with patch.object(child_reaper.GLib, "idle_add") as idle_add:
                            info = cr.add_process(proc, "test", ["test"], ignore, forget, callback)
                            if not already_exited:
                                self.assertFalse(info.dead)
                                idle_add.assert_not_called()
                                proc.poll.return_value = 7
                                cr.poll()
                            self.assertTrue(info.dead)
                            self.assertEqual(info.returncode, 7)
                            self.assertIsNone(info.process)
                            self.assertIsNone(info.callback)
                            self.assertEqual(info in cr._proc_info, not forget)
                            idle_add.assert_called_once_with(callback, proc)
                            cr.poll()
                            cr.add_dead_pid(proc.pid)
                            cr.add_dead_process(info)
                            idle_add.assert_called_once_with(callback, proc)
                            idle_add.call_args.args[0](proc)
                            callback.assert_called_once_with(proc)
                            self.assertEqual(quit_callback.call_count, int(not ignore and not forget))

    def new_reaper(self):
        with patch.object(child_reaper.GLib, "timeout_add"):
            return child_reaper.ChildReaper()

    def wait_for_exit(self, proc):
        # wait for the process to exit, without reaping it:
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_registered_exit_status(self):
        cr = self.new_reaper()
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(7)"]) as proc:
            info = cr.add_process(proc, "test", "test", ignore=True)
            self.wait_for_exit(proc)
            with patch.object(child_reaper.GLib, "idle_add"):
                cr.reap()
            self.assertTrue(info.dead)
            self.assertEqual(info.returncode, 7)
            self.assertEqual(proc.wait(), 7)

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_pid_exit_status(self):
        cr = self.new_reaper()
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"]) as proc:
            self.wait_for_exit(proc)
            info = cr.add_pid(proc.pid, "test", "test", ignore=True)
            self.assertTrue(info.dead)
            self.assertEqual(info.returncode, 3)
            self.assertRaises(ChildProcessError, os.waitpid, proc.pid, os.WNOHANG)
            proc.returncode = 3

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_unregistered_child_status_not_stolen(self):
        # ie: the exec authentication module, before it has registered its `Popen`:
        cr = self.new_reaper()
        with subprocess.Popen(["false"]) as proc:
            self.wait_for_exit(proc)
            with patch.object(child_reaper.GLib, "timeout_add", return_value=1):
                cr.reap()
            self.assertEqual(proc.wait(), 1)

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_unregistered_child(self):
        cr = self.new_reaper()
        with subprocess.Popen(["false"]) as proc:
            self.wait_for_exit(proc)
            with patch.object(child_reaper.GLib, "timeout_add", return_value=1) as timeout_add:
                cr.reap()
            # left for its owner to collect, and we will try again later:
            timeout_add.assert_called_once()
            self.assertEqual(os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT).si_pid, proc.pid)
            cr._retry = 0
            # until the owner has had enough time:
            later = time.monotonic() + child_reaper.UNKNOWN_CHILD_DELAY
            with patch.object(child_reaper, "monotonic", return_value=later), patch.object(child_reaper, "log") as logger:
                cr.reap()
            self.assertIn(str(proc.pid), logger.warn.call_args_list[0].args[0])
            self.assertRaises(ChildProcessError, os.waitpid, proc.pid, os.WNOHANG)
            proc.returncode = 1

    @unittest.skipUnless(child_reaper.POSIX, "requires POSIX")
    def test_fallback_exit_status(self):
        # without `waitid`, a child exiting between `poll()` and `waitpid(-1)`:
        cr = self.new_reaper()
        cmd = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); sys.exit(7)"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
            info = cr.add_process(proc, "test", "test", ignore=True)
            real_poll = proc.poll
            polls = []

            def exit_after_poll():
                if polls:
                    return real_poll()
                polls.append(real_poll())
                proc.stdin.close()
                self.wait_for_exit(proc)
                return polls[0]

            with patch.object(proc, "poll", side_effect=exit_after_poll), \
                    patch.object(child_reaper, "HAS_WAITID", False), \
                    patch.object(child_reaper.GLib, "idle_add"):
                cr.check()
            self.assertEqual(polls, [None])
            self.assertTrue(info.dead)
            self.assertEqual(info.returncode, 7)
            self.assertEqual(proc.wait(), 7)

    def test_concurrent_death_handled_once(self):
        cr = self.new_reaper()
        proc = Mock(pid=23456)
        proc.poll.return_value = None
        callback = Mock()
        info = cr.add_process(proc, "test", "test", callback=callback)
        entered, release = threading.Event(), threading.Event()

        def slow_poll():
            entered.set()
            release.wait(timeout=5)
            return 0

        proc.poll.reset_mock()
        proc.poll.side_effect = slow_poll
        with patch.object(child_reaper.GLib, "idle_add") as idle_add:
            thread = threading.Thread(target=cr.poll, daemon=True)
            thread.start()
            self.assertTrue(entered.wait(timeout=5))
            other = threading.Thread(target=cr.poll, daemon=True)
            other.start()
            release.set()
            thread.join(timeout=5)
            other.join(timeout=5)
        self.assertTrue(info.dead)
        self.assertEqual(proc.poll.call_count, 1)
        idle_add.assert_called_once_with(callback, proc)

    def test_first_fast_child_quits(self):
        from xpra.server.subsystem import command
        server = Mock()
        server.get_child_env.return_value = {}
        ccs = command.ChildCommandServer(server)
        ccs.exit_with_children = True
        ccs.idle_add = Mock()
        cr = self.new_reaper()
        cr.set_quit_callback(ccs.reaper_exit)
        proc = Mock(pid=23457)
        proc.poll.return_value = 0
        with patch.object(child_reaper, "singleton", cr), patch.object(command, "Popen", return_value=proc), \
                patch.dict(os.environ, {"XPRA_SESSION_DIR": ""}):
            ccs.start_command("test", ["test"])
        ccs.idle_add.assert_called_once_with(server.clean_quit)

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_collected_by_another_thread(self):
        # another thread is in `Popen.wait()`, and collects the exit status before or during our check,
        # but does not record it until later:
        for when in ("before-poll", "before-waitid"):
            with self.subTest(when=when):
                cr = self.new_reaper()
                callback = Mock()
                with subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(7)"]) as proc:
                    info = cr.add_process(proc, "test", "test", ignore=True, callback=callback)
                    self.wait_for_exit(proc)
                    entered, go, collected, publish = (threading.Event() for _ in range(4))
                    real_try_wait = proc._try_wait

                    def try_wait(flags):
                        entered.set()
                        go.wait(timeout=5)
                        result = real_try_wait(flags)
                        collected.set()
                        publish.wait(timeout=5)
                        return result

                    real_waitid = os.waitid

                    def waitid(*args):
                        go.set()
                        self.assertTrue(collected.wait(timeout=5))
                        return real_waitid(*args)

                    with patch.object(proc, "_try_wait", side_effect=try_wait):
                        thread = threading.Thread(target=proc.wait, daemon=True)
                        thread.start()
                        self.assertTrue(entered.wait(timeout=5))
                        if when == "before-poll":
                            go.set()
                            self.assertTrue(collected.wait(timeout=5))
                        with patch.object(child_reaper.GLib, "timeout_add", return_value=1) as timeout_add, \
                                patch.object(child_reaper.os, "waitid", side_effect=waitid), \
                                patch.object(child_reaper.GLib, "idle_add") as idle_add:
                            cr.check()
                        self.assertTrue(collected.is_set())
                        self.assertFalse(info.dead)
                        timeout_add.assert_called_once()
                        publish.set()
                        thread.join(timeout=5)
                    self.assertEqual(proc.returncode, 7)
                    with patch.object(child_reaper.GLib, "idle_add") as idle_add:
                        timeout_add.call_args.args[1]()
                    self.assertTrue(info.dead)
                    self.assertEqual(info.returncode, 7)
                    idle_add.assert_called_once_with(callback, proc)

    @unittest.skipUnless(child_reaper.POSIX, "requires POSIX")
    def test_fallback_concurrent_poll(self):
        # without `waitid`, another thread polls the process
        # after `waitpid(-1)` has reaped it, but before we have saved its exit status:
        cr = self.new_reaper()
        cmd = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); sys.exit(7)"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
            info = cr.add_process(proc, "test", "test", ignore=True)
            real_poll = proc.poll
            polls = []

            def exit_after_poll():
                if polls:
                    return real_poll()
                polls.append(real_poll())
                proc.stdin.close()
                self.wait_for_exit(proc)
                return polls[0]

            real_waitpid = os.waitpid
            other_polls = []

            def waitpid(pid, options):
                result = real_waitpid(pid, options)
                if pid == -1 and result[0] == proc.pid:
                    thread = threading.Thread(target=lambda: other_polls.append(proc.poll()))
                    thread.start()
                    thread.join()
                return result

            with patch.object(proc, "poll", side_effect=exit_after_poll), \
                    patch.object(child_reaper, "HAS_WAITID", False), \
                    patch.object(child_reaper.os, "waitpid", side_effect=waitpid), \
                    patch.object(child_reaper.GLib, "idle_add"):
                cr.check()
            self.assertEqual(other_polls, [None])
            self.assertTrue(info.dead)
            self.assertEqual(info.returncode, 7)
            self.assertEqual(proc.wait(), 7)

    @unittest.skipUnless(child_reaper.POSIX, "requires POSIX")
    def test_fallback_busy_process(self):
        # without `waitid`, we must not reap anything while another thread is waiting for a registered process:
        cr = self.new_reaper()
        process = Mock(pid=os.getpid(), returncode=None)
        process.poll.return_value = None
        process._waitpid_lock = threading.Lock()
        cr.add_process(process, "test", "test", ignore=True)
        with process._waitpid_lock, patch.object(child_reaper, "HAS_WAITID", False), \
                patch.object(child_reaper.os, "waitpid") as waitpid, \
                patch.object(child_reaper.GLib, "timeout_add", return_value=1) as timeout_add:
            cr.reap()
        waitpid.assert_not_called()
        timeout_add.assert_called_once()

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid for synchronization")
    def test_fallback_during_registration(self):
        cr = self.new_reaper()
        entered, release = threading.Event(), threading.Event()
        errors, infos = [], []

        class RegisteringList(list):
            def append(self, info):
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("registration was not released")
                super().append(info)

        cr._proc_info = RegisteringList()
        cmd = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); sys.exit(7)"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
            def register():
                try:
                    infos.append(cr.add_process(proc, "test", cmd, ignore=True))
                except BaseException as e:
                    errors.append(e)

            thread = threading.Thread(target=register, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=5))
                proc.stdin.close()
                self.wait_for_exit(proc)
                with patch.object(child_reaper, "HAS_WAITID", False), \
                        patch.object(child_reaper.os, "waitpid", wraps=os.waitpid) as waitpid, \
                        patch.object(child_reaper.GLib, "timeout_add", return_value=1) as timeout_add:
                    cr.reap()
                    waitpid.assert_not_called()
                    timeout_add.assert_called_once()
            finally:
                release.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            if errors:
                raise errors[0]
            self.assertTrue(infos[0].dead)
            self.assertEqual(infos[0].returncode, 7)
            self.assertEqual(proc.wait(), 7)

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid")
    def test_waiter_during_pending_check(self):
        for when in ("during-pending-check", "after-pending-check"):
            with self.subTest(when=when):
                cr = self.new_reaper()
                callback, quit_callback = Mock(), Mock()
                cmd = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1); sys.exit(7)"]
                with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
                    info = cr.add_process(proc, "test", cmd, callback=callback)
                    cr.set_quit_callback(quit_callback)
                    start, collected, publish = (threading.Event() for _ in range(3))
                    errors = []
                    real_handle_status = proc._handle_exitstatus
                    real_waitid = os.waitid
                    real_lock = proc._waitpid_lock

                    def handle_status(status):
                        collected.set()
                        self.assertTrue(publish.wait(timeout=5))
                        real_handle_status(status)

                    def wait():
                        try:
                            self.assertTrue(start.wait(timeout=5))
                            self.assertEqual(proc.wait(), 7)
                        except BaseException as e:
                            errors.append(e)

                    def waitid(*args):
                        if when == "after-pending-check":
                            proc.stdin.close()
                            start.set()
                            self.assertTrue(collected.wait(timeout=5))
                        return real_waitid(*args)

                    def locked():
                        # Publish between the returncode read and the lock probe.
                        publish.set()
                        thread.join(timeout=5)
                        self.assertFalse(thread.is_alive())
                        return real_lock.locked()

                    lock = real_lock
                    with patch.object(proc, "_handle_exitstatus", side_effect=handle_status):
                        thread = threading.Thread(target=wait, daemon=True)
                        thread.start()
                        try:
                            if when == "during-pending-check":
                                proc.stdin.close()
                                start.set()
                                self.assertTrue(collected.wait(timeout=5))
                                lock = Mock(wraps=real_lock)
                                lock.locked.side_effect = locked
                            with patch.object(proc, "_waitpid_lock", lock), \
                                    patch.object(child_reaper.os, "waitid", side_effect=waitid), \
                                    patch.object(child_reaper.GLib, "timeout_add", return_value=1) as timeout_add, \
                                    patch.object(child_reaper.GLib, "idle_add") as idle_add:
                                try:
                                    cr.check()
                                finally:
                                    publish.set()
                                    thread.join(timeout=5)
                                self.assertFalse(thread.is_alive())
                                if errors:
                                    raise errors[0]
                                timeout_add.assert_called_once()
                                timeout_add.call_args.args[1]()
                                self.assertTrue(info.dead)
                                self.assertEqual(info.returncode, 7)
                                idle_add.assert_called_once_with(callback, proc)
                                quit_callback.assert_called_once()
                        finally:
                            proc.stdin.close()
                            start.set()
                            publish.set()
                            thread.join(timeout=5)

    def test_childreaper(self):
        for polling in (True, False):
            with OSEnvContext():
                os.environ["XPRA_USE_PROCESS_POLLING"] = str(int(polling))
                self.do_test_child_reaper()

    def do_test_child_reaper(self):
        # force reset singleton:
        child_reaper.singleton = None
        # no-op:
        reaper_cleanup()

        log.setLevel(logging.ERROR)
        cr = get_child_reaper()
        # one that exits before we add the process, one that takes longer:
        TEST_CHILDREN = (["echo"], ["sleep", "0.5"])
        count = 0
        for cmd in TEST_CHILDREN:
            cmd_info = " ".join(cmd)
            proc = subprocess.Popen(cmd)
            cr.add_process(proc, cmd_info, cmd_info, False, False, None)
            count += 1
            for _ in range(10):
                if not cr.check():
                    break
                time.sleep(0.1)
            # we can't check the returncode because it may not be set yet!
            # assert proc.poll() is not None, "%s process did not terminate?" % cmd_info
            assert cr.check() is False, "reaper did not notice that the '%s' process has terminated" % cmd_info
            i = cr.get_info()
            children = i.get("children").get("total")
            assert children == count, "expected %s children recorded, but got %s" % (count, children)

        # now check for the forget option:
        proc = subprocess.Popen(["sleep", "60"])
        procinfo = cr.add_process(proc, "sleep 60", "sleep 60", False, True, None)
        assert repr(procinfo)
        count +=1
        assert cr.check() is True, "sleep process terminated too quickly"
        i = cr.get_info()
        children = i.get("children").get("total")
        assert children == count, "expected %s children recorded, but got %s" % (count, children)
        # trying to claim it is dead when it is not:
        # (this will print some warnings)
        cr.add_dead_pid(proc.pid)
        proc.terminate()
        # now wait for the sleep process to exit:
        for _ in range(10):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None
        assert cr.check() is False, "sleep process did not terminate?"
        count -= 1
        i = cr.get_info()
        children = i.get("children").get("total")
        if children != count:
            raise Exception(f"expected the sleep process to have been forgotten ({count} children)"
                            f"but got {children} children instead in the reaper records")
        reaper_cleanup()
        # can run again:
        reaper_cleanup()
        # nothing for an invalid pid:
        assert cr.get_proc_info(-1) is None


def main():
    from xpra.os_util import WIN32
    if not WIN32:
        unittest.main()


if __name__ == '__main__':
    main()
