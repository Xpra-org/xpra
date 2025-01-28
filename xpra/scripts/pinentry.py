#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
from subprocess import Popen, PIPE
from collections.abc import Callable

from xpra.common import noerr
from xpra.util.env import envbool
from xpra.os_util import WIN32, OSX, POSIX
from xpra.util.io import use_gui_prompt, which
from xpra.util.system import is_gnome, is_kde
from xpra.util.str_fn import bytestostr
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS, InitExit
from xpra.exit_codes import ExitCode
from xpra.log import Logger

log = Logger("exec", "auth")

SKIP_UI: bool = envbool("XPRA_SKIP_UI", False)
PINENTRY: bool = envbool("XPRA_SSH_PINENTRY", POSIX and not OSX)


# pylint: disable=import-outside-toplevel


def get_pinentry_command(setting: str = "yes") -> str:
    log(f"get_pinentry_command({setting})")
    if setting.lower() in FALSE_OPTIONS:
        return ""

    def find_pinentry_bin() -> str:
        if is_gnome():
            return which("pinentry-gnome3")
        if is_kde():
            return which("pinentry-qt")
        return ""

    if setting.lower() in TRUE_OPTIONS:
        return find_pinentry_bin() or which("pinentry")
    if setting == "" or setting.lower() == "auto":
        # figure out if we should use it:
        if WIN32 or OSX:
            # not enabled by default on those platforms
            return ""
        return find_pinentry_bin()
    return setting


def popen_pinentry(pinentry_cmd: str):
    try:
        cmd = [pinentry_cmd]
        if log.is_debug_enabled():
            cmd.append("--debug")
        return Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except OSError as e:
        log(f"popen_pinentry({pinentry_cmd}) failed", exc_info=True)
        log.error(f"Error: failed to run {pinentry_cmd!r}")
        log.estr(e)
        return None


def run_pinentry(extra_args) -> int:
    messages = list(extra_args)

    def get_input():
        if not messages:
            return None
        return messages.pop(0)

    def process_output(message: str, line: bytes):
        if line.startswith(b"ERR "):
            log.error(f"Error: pinentry responded to {message!r} with:")
            log.error(" %s", line.rstrip(b"\n\r").decode())
        else:
            log(f"pinentry sent {line!r}")

    pinentry_cmd = get_pinentry_command() or "pinentry"
    proc = popen_pinentry(pinentry_cmd)
    if not proc:
        raise InitExit(ExitCode.UNSUPPORTED, "cannot run pinentry")
    return do_run_pinentry(proc, get_input, process_output)


def do_run_pinentry(proc, get_input: Callable, process_output: Callable) -> int:
    message = "connection"
    while proc.poll() is None:
        try:
            line = proc.stdout.readline()
            while process_output(message, line):
                "process_output should eventually return False or None"
            message = get_input()
            if message is None:
                break
            log(f"sending {message!r}")
            r = proc.stdin.write(f"{message}\n".encode())
            proc.stdin.flush()
            log(f"write returned: {r}")
        except OSError:
            log("error running pinentry", exc_info=True)
            break
    if proc.poll() is None:
        proc.terminate()
    noerr(proc.stdin.close)
    noerr(proc.stdout.close)
    noerr(proc.stderr.close)
    exitcode = proc.wait(1)
    if exitcode is None:
        log.warn("Warning: pinentry is still running")
        return -1
    log(f"pinentry ended: {proc.poll()}")
    return exitcode


def pinentry_getpin(pinentry_proc, title: str, description: str, pin_cb: Callable, err_cb: Callable) -> None:
    from urllib.parse import quote
    messages = [
        f"SETPROMPT {quote(title)}",
        f"SETDESC {quote(description)}:",
        "GETPIN",
    ]

    def get_input():
        if not messages:
            return None
        return messages.pop(0)

    def process_output(message: str, output: bytes):
        # log(f"process_output({message}, {output})")
        if message == "GETPIN":
            if output.startswith(b"S "):
                log("getpin message: %s", output[2:].decode())
                # ie: 'S PASSWORD_FROM_CACHE'
                return True  # read more data
            if output.startswith(b"D "):
                pin_value = output[2:].decode().rstrip("\n\r")
                from urllib.parse import unquote
                decoded = unquote(pin_value)
                pin_cb(decoded)
            else:
                err_cb(output.decode().rstrip("\n\r"))
        return False

    do_run_pinentry(pinentry_proc, get_input, process_output)


def run_pinentry_getpin(pinentry_cmd: str, title: str, description: str) -> str:
    proc = popen_pinentry(pinentry_cmd)
    if proc is None:
        return ""
    values: list[str] = []

    def rec(value=""):
        values.append(str(value))

    def err(value=None):
        log("getpin error: %s", value)

    try:
        pinentry_getpin(proc, title, description, rec, err)
    finally:
        noerr(proc.terminate)
    if not values:
        return ""
    return values[0]


def run_pinentry_confirm(pinentry_cmd: str, title: str, prompt: str) -> str:
    proc = popen_pinentry(pinentry_cmd)
    if proc is None:
        return ""
    messages = [
        # we can't use those as the response is multi-line:
        # "GETINFO flavor",
        # "GETINFO version",
        # "GETINFO pid",
    ]
    messages += [
        f"SETPROMPT {title}",
        f"SETDESC {prompt}",
        # "SETKEYINFO %c/%s"
    ]
    messages.append("CONFIRM")
    log("run_pinentry_confirm%s messages=%s", (pinentry_cmd, title, prompt), messages)

    def get_input():
        if not messages:
            return None
        return messages.pop(0)

    confirm_values = []

    def process_output(message, output):
        log("received %s for %s", output, message)
        if message == "CONFIRM":
            confirm_values.append(output.strip(b"\n\r"))

    do_run_pinentry(proc, get_input, process_output)
    if len(confirm_values) != 1:
        return ""
    return bytestostr(confirm_values[0])  # ie: "OK"


def force_focus() -> None:
    from xpra.platform.gui import force_focus as _force_focus
    _force_focus()


def dialog_pass(title: str = "Password Input", prompt: str = "enter password", icon: str = "") -> str:
    log("dialog_pass%s PINENTRY=%s", (title, prompt, icon), PINENTRY)
    if PINENTRY:
        pinentry_cmd = get_pinentry_command()
        if pinentry_cmd:
            return run_pinentry_getpin(pinentry_cmd, title, prompt)

    from xpra.gtk.dialogs.util import dialog_run, do_run_dialog

    def password_input_run() -> str:
        from xpra.gtk.dialogs.pass_dialog import PasswordInputDialogWindow
        dialog = PasswordInputDialogWindow(title, prompt, icon)
        return str(do_run_dialog(dialog))

    return str(dialog_run(password_input_run))


def dialog_confirm(title: str, prompt: str, qinfo=(), icon: str = "", buttons=(("OK", 1),)) -> int:
    from xpra.gtk.dialogs.util import dialog_run, do_run_dialog

    def confirm_run() -> int:
        from xpra.gtk.dialogs.confirm_dialog import ConfirmDialogWindow
        dialog = ConfirmDialogWindow(title, prompt, qinfo, icon, buttons)
        return do_run_dialog(dialog)

    return int(dialog_run(confirm_run))


def confirm(info=(), title: str = "Confirm Key", prompt: str = "Are you sure you want to continue connecting?") -> bool:
    log("confirm%s SKIP_UI=%s, PINENTRY=%s", (info, title, prompt), SKIP_UI, PINENTRY)
    if SKIP_UI:
        return False
    if PINENTRY:
        pinentry_cmd = get_pinentry_command()
        if pinentry_cmd:
            messages = list(info) + ["", prompt]
            return run_pinentry_confirm(pinentry_cmd, title, "%0A".join(messages)) == "OK"
    if use_gui_prompt():
        from xpra.platform.paths import get_icon_filename
        icon = get_icon_filename("authentication", "png") or ""
        NO_CODE = 199
        YES_CODE = 200
        code = dialog_confirm(title, prompt, info, icon, buttons=[("NO", NO_CODE), ("yes", YES_CODE)])
        log("dialog return code=%s", code)
        r = code == YES_CODE
        return r
    log("confirm%s will use stdin prompt", (info, title, prompt))
    prompt = "Are you sure you want to continue connecting (yes/NO)? "
    sys.stderr.write(os.linesep.join(info) + os.linesep + prompt)
    sys.stderr.flush()
    try:
        line = sys.stdin.readline().rstrip(os.linesep)
    except KeyboardInterrupt:
        sys.exit(128 + signal.SIGINT)
    return line.lower() in ("y", "yes")


def input_pass(prompt: str) -> str:
    if SKIP_UI:
        return ""
    if PINENTRY or use_gui_prompt():
        from xpra.platform.paths import get_icon_filename
        icon = get_icon_filename("authentication", "png") or ""
        log(f"input_pass({prompt}) using dialog")
        return dialog_pass("Password Input", prompt, icon)
    from getpass import getpass
    log(f"input_pass({prompt}) using getpass")
    try:
        return getpass(prompt)
    except KeyboardInterrupt:
        sys.exit(128 + signal.SIGINT)


def main() -> int:
    from xpra.platform import program_context
    with program_context("Pinentry-Dialog", "Pinentry Dialog"):
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        try:
            return dialog_confirm(*sys.argv[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main()
    sys.exit(v)
