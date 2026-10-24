#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen, PIPE

from xpra.common import noerr
from xpra.os_util import gi_import
from xpra.util.env import envint, filter_env, get_saved_env
from xpra.util.io import stderr_print
from xpra.log import Logger, get_debug_args

SPLASH_EXIT_DELAY: int = envint("XPRA_SPLASH_EXIT_DELAY", 4)
SPLASH_KEEPALIVE_INTERVAL: int = max(0, envint("XPRA_SPLASH_KEEPALIVE_INTERVAL", 5))


def make_progress_process(title="Xpra") -> Popen | None:
    # start the splash subprocess using the saved environment,
    # not the new one which may point the X11 / Wayland display to our virtual one
    log = Logger("splash")
    env = filter_env(get_saved_env())
    env["XPRA_LOG_PREFIX"] = "splash: "
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    env["XPRA_SPLASH_KEEPALIVE_INTERVAL"] = str(SPLASH_KEEPALIVE_INTERVAL)
    from xpra.platform.paths import get_nodock_command
    cmd = get_nodock_command() + ["splash"]
    if debug_args := get_debug_args():
        cmd.append("--debug=%s" % (",".join(debug_args)))
    try:
        progress_process = Popen(cmd, stdin=PIPE, env=env)
        log("progress_process(%s, %s)=%s", cmd, env, progress_process)
    except OSError as e:
        stderr_print("Error launching 'splash' subprocess")
        stderr_print(f" {e}")
        return None
    from threading import Event, Lock
    keepalive_stop = Event()
    write_lock = Lock()

    def write_stdin(data: bytes) -> bool:
        with write_lock:
            stdin = progress_process.stdin
            if not stdin:
                return False
            try:
                stdin.write(data)
                stdin.flush()
            except (OSError, ValueError):
                log("write_stdin(%r)", data, exc_info=True)
                keepalive_stop.set()
                return False
        return True

    # always close stdin when terminating the splash screen process:
    progress_process.saved_terminate = progress_process.terminate

    def terminate(*args) -> None:
        keepalive_stop.set()
        with write_lock:
            stdin = progress_process.stdin
            log("terminate%s stdin=%s", args, stdin)
            if stdin:
                progress_process.stdin = None
                noerr(stdin.close)
        progress_process.saved_terminate()
        setattr(progress_process, "terminate", progress_process.saved_terminate)

    # override Popen.terminate()
    setattr(progress_process, "terminate", terminate)

    def progress(pct: int, text: str) -> None:
        poll = progress_process.poll()
        log("progress(%s, %r) poll=%s", pct, text, poll)
        if poll is not None:
            return
        from xpra.util.i18n import _
        text = _(text)
        write_stdin(("%i:%s\n" % (pct, text)).encode("utf8"))
        if pct == 100:
            # it should exit on its own, but just in case:
            glib = gi_import("GLib")
            glib.timeout_add(SPLASH_EXIT_DELAY * 1000 + 500, terminate)

    progress_process.progress = progress

    from xpra.util.child_reaper import get_child_reaper
    get_child_reaper().add_process(progress_process, "splash", cmd, ignore=True, forget=True)
    progress(0, title)
    progress(10, "initializing")
    if SPLASH_KEEPALIVE_INTERVAL > 0:
        def keepalive() -> None:
            while progress_process.poll() is None and not keepalive_stop.is_set():
                if not write_stdin(b"keepalive\n"):
                    return
                if keepalive_stop.wait(SPLASH_KEEPALIVE_INTERVAL):
                    return

        from xpra.util.thread import start_thread
        start_thread(keepalive, "splash-keepalive", daemon=True)
    return progress_process
