# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import sleep
from typing import Any
from collections.abc import Sequence

from xpra.server.proxy.server import ProxyServer as _ProxyServer, get_proxy_env
from xpra.platform.paths import get_app_dir
from xpra.net.constants import SocketState
from xpra.util.env import envbool
from xpra.util.io import pollwait, which
from xpra.log import Logger

log = Logger("proxy")

PAEXEC = envbool("XPRA_PAEXEC", True)
SYSTEM_SESSION = envbool("XPRA_SYSTEM_SESSION", True)
TOKEN = envbool("XPRA_SYSTEM_TOKEN", False)
USE_VDD = envbool("XPRA_USE_VDD", True)


def exec_command(username: str, password: str, args: Sequence[str], exe: str, cwd: str, env: dict[str, str]):
    log("exec_command%s", (username, args, exe, cwd, env))
    # pylint: disable=import-outside-toplevel
    from xpra.platform.win32.lsa_logon_lib import logon_msv1, logon_msv1_s4u
    if TOKEN:
        logon_info = logon_msv1_s4u(username)
    else:
        logon_info = logon_msv1(username, password)
    log("logon(..)=%s", logon_info)
    from xpra.platform.win32.create_process_lib import (
        Popen,
        CREATIONINFO, CREATION_TYPE_LOGON,
        STARTF_USESHOWWINDOW,
        LOGON_WITH_PROFILE, CREATE_NEW_PROCESS_GROUP, STARTUPINFO,
    )
    creation_info = CREATIONINFO()
    creation_info.lpApplicationName = "Xpra"
    creation_info.lpUsername = username
    creation_info.lpPassword = password
    creation_info.lpDomain = os.environ.get("USERDOMAIN", "WORKGROUP")
    #creation_info.dwCreationType = CREATION_TYPE_TOKEN
    creation_info.dwCreationType = CREATION_TYPE_LOGON
    creation_info.dwLogonFlags = LOGON_WITH_PROFILE
    creation_info.dwCreationFlags = CREATE_NEW_PROCESS_GROUP
    creation_info.hToken = logon_info.Token
    log("creation_info=%s", creation_info)
    startupinfo = STARTUPINFO()
    startupinfo.dwFlags = STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # aka win32.con.SW_HIDE
    startupinfo.lpDesktop = "WinSta0\\Default"
    startupinfo.lpTitle = "Xpra-Shadow"

    from subprocess import PIPE
    proc = Popen(args, executable=exe,
                 stdout=PIPE, stderr=PIPE,
                 cwd=cwd, env=env,
                 startupinfo=startupinfo, creationinfo=creation_info)
    log("Popen(%s)=%s", args, proc)
    return proc


class ProxyServer(_ProxyServer):

    def __init__(self):
        super().__init__()
        # Parsec VDD state shared across all sessions on this proxy.
        # One device handle + keep-alive thread; each session gets its own slot.
        self._vdd_handle = None
        self._vdd_keepalive = None
        # Maps subprocess -> vdd slot so we can remove the display on exit.
        self._vdd_slots: dict[Any, int] = {}

    def cleanup(self) -> None:
        super().cleanup()
        self._vdd_cleanup()

    # ------------------------------------------------------------------
    # VDD helpers
    # ------------------------------------------------------------------

    def _vdd_open(self) -> bool:
        """Open the VDD device handle and start the keep-alive thread if not already done."""
        if self._vdd_handle is not None:
            return True
        # pylint: disable=import-outside-toplevel
        from xpra.platform.win32.parsecvdd import (
            query_device_status, DeviceStatus, open_device, VddKeepAlive,
        )
        status = query_device_status()
        if status != DeviceStatus.OK:
            log.warn("Warning: Parsec VDD driver not ready (status=%s), falling back to shadow", status.name)
            return False
        try:
            self._vdd_handle = open_device()
            self._vdd_keepalive = VddKeepAlive(self._vdd_handle)
            self._vdd_keepalive.start()
            log("VDD device opened: handle=%#x", self._vdd_handle.value)
            return True
        except Exception as e:
            log.warn("Warning: failed to open VDD device: %s", e)
            self._vdd_handle = None
            return False

    def _vdd_add(self) -> int:
        """Add a virtual display and return its slot index, or -1 on failure."""
        from xpra.platform.win32.parsecvdd import add_display, find_monitor_by_slot
        slot = add_display(self._vdd_handle)
        if slot < 0:
            log.warn("Warning: VDD add_display() failed")
            return -1
        # Give Windows a moment to enumerate the new adapter.
        for _ in range(10):
            if find_monitor_by_slot(slot):
                break
            sleep(0.5)
        else:
            log.warn("Warning: VDD slot %i added but monitor did not appear in EnumDisplayDevices", slot)
        log("VDD display added: slot=%i", slot)
        return slot

    def _vdd_remove(self, slot: int) -> None:
        """Remove the virtual display at *slot* if the device is still open."""
        if self._vdd_handle is None or slot < 0:
            return
        from xpra.platform.win32.parsecvdd import remove_display
        log("VDD removing display slot %i", slot)
        remove_display(self._vdd_handle, slot)

    def _vdd_cleanup(self) -> None:
        """Remove all active displays and close the device handle."""
        for slot in list(self._vdd_slots.values()):
            self._vdd_remove(slot)
        self._vdd_slots.clear()
        if self._vdd_keepalive:
            self._vdd_keepalive.stop()
            self._vdd_keepalive = None
        if self._vdd_handle:
            from xpra.platform.win32.parsecvdd import close_device
            close_device(self._vdd_handle)
            self._vdd_handle = None

    # ------------------------------------------------------------------
    # Session launch
    # ------------------------------------------------------------------

    def start_new_session(self, username: str, password: str, uid: int, gid: int,
                          sess_options: dict, displays=()) -> tuple[Any, str, str]:
        log("start_new_session%s", (username, "..", uid, gid, sess_options, displays))
        return self.start_win32_shadow(username, password, sess_options)

    def start_win32_shadow(self, username: str, password: str, sess_options: dict) -> tuple[Any, str, str]:
        log("start_win32_shadow%s", (username, "..", sess_options))
        app_dir = get_app_dir()
        paexec = app_dir + "\\paexec.exe"

        # ----------------------------------------------------------------
        # Decide whether to use VDD (shadow-device) or legacy shadow
        # ----------------------------------------------------------------
        vdd_slot = -1
        if USE_VDD and self._vdd_open():
            vdd_slot = self._vdd_add()

        if vdd_slot >= 0:
            # VDD path: no need for a pre-existing session or paexec
            shadow_command = app_dir + "\\Xpra-Shadow-Device.exe"
            named_pipe = f"{username.replace(' ', '_')}_vdd{vdd_slot}"
            cmd = [shadow_command, f"vdd:{vdd_slot}", f"--bind={named_pipe}"]
        else:
            # Legacy path: shadow the existing interactive session via paexec
            shadow_command = app_dir + "\\Xpra-Shadow.exe"
            named_pipe = username.replace(" ", "_")

            # pylint: disable=import-outside-toplevel
            from xpra.platform.win32.wtsapi import find_session
            session_info = find_session(username)
            if not session_info:
                with log.trap_error(f"Error: failed to logon as {username!r}"):
                    from xpra.platform.win32.desktoplogon_lib import logon
                    logon(username, password)

            wrap = []
            if PAEXEC and os.path.exists(paexec) and os.path.isfile(paexec):
                if not session_info:
                    session_info = find_session(username)
                if session_info:
                    log(f"found session {session_info} for {username!r}")
                    wrap = ["paexec.exe", "-i", str(session_info["SessionID"])]
                elif username.lower() == "administrator" and SYSTEM_SESSION:
                    log("using system session")
                    wrap = ["paexec.exe", "-x"]
                else:
                    log.warn("Warning: session not found for username '%s'", username)
            else:
                log.warn("Warning: starting without paexec, expect a black screen")

            cmd = wrap + [shadow_command, f"--bind={named_pipe}"]

        # ----------------------------------------------------------------
        # Common options
        # ----------------------------------------------------------------
        if sess_options.get("exit-with-client", None) is not False:
            cmd.append("--exit-with-client=yes")
        from xpra.log import debug_enabled_categories
        if debug_enabled_categories:
            cmd += ["-d", ",".join(tuple(debug_enabled_categories))]
        env = get_proxy_env()
        env["XPRA_REDIRECT_OUTPUT"] = "1"
        exe = which(cmd[0])

        # ----------------------------------------------------------------
        # Launch
        # ----------------------------------------------------------------
        if username.lower() == "administrator" and SYSTEM_SESSION and vdd_slot < 0:
            from subprocess import Popen
            proc = Popen(cmd, executable=exe)
        else:
            proc = exec_command(username, password, cmd, exe, app_dir, env)
        log("shadow subprocess: pid=%s cmd=%s", proc.pid, cmd)

        # ----------------------------------------------------------------
        # Poll until named pipe is live
        # ----------------------------------------------------------------
        from xpra.platform.win32.dotxpra import DotXpra
        dotxpra = DotXpra()
        for t in range(10):
            r = pollwait(proc, 1)
            if r is not None:
                log("pollwait=%s", r)
                try:
                    log("stdout=%s", proc.stdout.read())
                    log("stderr=%s", proc.stderr.read())
                except (OSError, AttributeError):
                    log("failed to read stdout/stderr of subprocess", exc_info=True)
                if vdd_slot >= 0:
                    self._vdd_remove(vdd_slot)
                if r != 0:
                    raise RuntimeError(f"shadow subprocess failed with exit code {r}")
                raise RuntimeError("shadow subprocess has already terminated")
            if t >= 4:
                state = dotxpra.get_display_state(named_pipe)
                log("get_display_state(%s)=%s", named_pipe, state)
                if state == SocketState.LIVE:
                    sleep(2)
                    break

        # ----------------------------------------------------------------
        # Track slot for cleanup when the process exits
        # ----------------------------------------------------------------
        if vdd_slot >= 0:
            self._vdd_slots[proc.pid] = vdd_slot

        def _on_shadow_exit(pid: int) -> None:
            slot = self._vdd_slots.pop(pid, -1)
            if slot >= 0:
                log("shadow process %i exited — removing VDD slot %i", pid, slot)
                self._vdd_remove(slot)

        from xpra.util.child_reaper import get_child_reaper
        get_child_reaper().add_process(
            proc, f"server-{username}", "xpra shadow", True, True,
            callback=lambda _proc: _on_shadow_exit(proc.pid),
        )
        return proc, f"named-pipe://{named_pipe}", named_pipe
