# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Callable

from xpra.os_util import gi_import
from xpra.scripts.pinentry import log
from xpra.util.thread import is_main_thread

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")


def do_run_dialog(dialog: Gtk.Dialog) -> int:
    from xpra.platform.gui import force_focus
    try:
        force_focus()
        dialog.show()
        return dialog.run()
    finally:
        dialog.hide()
        dialog.close()


def dialog_run(run_fn: Callable) -> str | int:
    log("dialog_run(%s) is_main_thread=%s, main_level=%i", run_fn, is_main_thread(), Gtk.main_level())
    if is_main_thread() or Gtk.main_level() == 0:
        return run_fn()
    log("dialog_run(%s) main_depth=%s", run_fn, GLib.main_depth())
    # do a little dance if we're not running in the main thread:
    # block this thread and wait for the main thread to run the dialog
    from threading import Event
    e = Event()
    code = []

    def main_thread_run():
        log("main_thread_run() calling %s", run_fn)
        try:
            code.append(run_fn())
        finally:
            e.set()

    GLib.idle_add(main_thread_run)
    log("dialog_run(%s) waiting for main thread to run", run_fn)
    e.wait()
    log("dialog_run(%s) code=%s", run_fn, code)
    return code[0]
