#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Event, Thread, current_thread
from unittest.mock import patch


class DialogsUtilTest(unittest.TestCase):

    @staticmethod
    def run_from_worker(run_fn):
        from xpra.gtk.dialogs import util

        callback_ready = Event()
        callbacks = []
        results = []
        errors = []

        def idle_add(callback):
            callbacks.append(callback)
            callback_ready.set()
            return 1

        def worker() -> None:
            try:
                results.append(util.dialog_run(run_fn))
            except BaseException as exc:
                errors.append(exc)

        with patch.object(util.GLib, "idle_add", side_effect=idle_add):
            thread = Thread(target=worker, name="dialog-test-worker")
            thread.start()
            if not callback_ready.wait(1):
                raise RuntimeError("dialog callback was not scheduled")
            callbacks.pop()()
            thread.join(1)
        if thread.is_alive():
            raise RuntimeError("dialog worker did not finish")
        return results, errors

    def test_dialog_run_uses_main_thread(self):
        results, errors = self.run_from_worker(lambda: current_thread().name)
        self.assertEqual(errors, [])
        self.assertEqual(results, [current_thread().name])

    def test_dialog_run_propagates_exceptions(self):
        expected = RuntimeError("dialog failed")

        def fail():
            raise expected

        results, errors = self.run_from_worker(fail)
        self.assertEqual(results, [])
        self.assertEqual(errors, [expected])

    def test_ssh_dialogs_reject_worker_thread(self):
        from xpra.gtk.dialogs.confirm_dialog import ConfirmDialogWindow
        from xpra.gtk.dialogs.pass_dialog import PasswordInputDialogWindow

        errors = []

        def worker() -> None:
            for dialog_class in (ConfirmDialogWindow, PasswordInputDialogWindow):
                try:
                    dialog_class.__init__(object())
                except BaseException as exc:
                    errors.append(exc)

        thread = Thread(target=worker, name="ssh-dialog-test-worker")
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(isinstance(exc, RuntimeError) for exc in errors))
        self.assertTrue(all("ssh-dialog-test-worker" in str(exc) for exc in errors))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
