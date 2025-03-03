# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import shlex
import signal
import os.path
from time import monotonic
from subprocess import Popen
from typing import Any
from collections.abc import Callable

from xpra.platform.features import COMMAND_SIGNALS
from xpra.util.child_reaper import getChildReaper, ProcInfo
from xpra.common import noop
from xpra.os_util import OSX, WIN32, gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer
from xpra.util.env import envint, restore_script_env
from xpra.net.common import PacketType
from xpra.util.thread import start_thread
from xpra.scripts.parsing import parse_env, get_subcommands
from xpra.server.util import source_env, write_pid
from xpra.server import ServerExitMode
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("exec")

TERMINATE_DELAY = envint("XPRA_TERMINATE_DELAY", 1000) / 1000.0


class ChildCommandServer(StubServerMixin):
    """
    Mixin for servers that start subcommands,
    ie "--start=xterm"
    """

    PREFIX = "command"

    def __init__(self):
        self.child_display: str = ""
        self.start_commands = []
        self.start_late_commands = []
        self.start_child_commands = []
        self.start_child_late_commands = []
        self.start_after_connect = []
        self.start_after_connect_done = False
        self.start_child_after_connect = []
        self.start_on_connect = []
        self.start_child_on_connect = []
        self.start_on_last_client_exit = []
        self.start_child_on_last_client_exit = []
        self.exit_with_children: bool = False
        self.children_count: int = 0
        self.start_after_connect_done: bool = False
        self.start_new_commands: bool = False
        self.source_env: dict[str, str] = {}
        self.start_env: dict[str, str] = {}
        self.exec_cwd: str = os.getcwd()
        self.exec_wrapper: list[str] = []
        self.terminate_children: bool = False
        self.children_started: list[ProcInfo] = []
        self.child_reaper = None
        self.reaper_exit: Callable = self.reaper_exit_check
        # does not belong here...
        if not hasattr(self, "_exit_mode"):
            self._exit_mode = None
        if not hasattr(self, "session_name"):
            self.session_name: str = ""
        self.menu_provider = None
        # wait for main loop to run
        # and ensure that we don't run `late_start()` more than once,
        # even if __init__ is called multiple times:
        if not getattr(self, "late_start_requested", False):
            self.late_start_requested: bool = True
            GLib.idle_add(self.late_start)

    def late_start(self) -> None:
        def do_late_start():
            # wait for all threaded init to complete
            self.wait_for_threaded_init()
            self.exec_start_late_commands()

        start_thread(do_late_start, "command-late-start", daemon=True)

    def init(self, opts) -> None:
        self.exit_with_children = opts.exit_with_children
        self.terminate_children = opts.terminate_children
        self.start_new_commands = opts.start_new_commands
        self.start_commands = opts.start
        self.start_late_commands = opts.start_late
        self.start_child_commands = opts.start_child
        self.start_child_late_commands = opts.start_child_late
        self.start_after_connect = opts.start_after_connect
        self.start_child_after_connect = opts.start_child_after_connect
        self.start_on_connect = opts.start_on_connect
        self.start_child_on_connect = opts.start_child_on_connect
        self.start_on_last_client_exit = opts.start_on_last_client_exit
        self.start_child_on_last_client_exit = opts.start_child_on_last_client_exit
        if opts.exec_wrapper:
            self.exec_wrapper = shlex.split(opts.exec_wrapper)
        self.child_reaper = getChildReaper()
        self.source_env = source_env(opts.source_start)
        self.start_env = parse_env(opts.start_env)
        if self.start_new_commands:
            # may already have been initialized by servercore:
            from xpra.server.menu_provider import get_menu_provider
            self.menu_provider = self.menu_provider or get_menu_provider()
            self.menu_provider.on_reload.append(self.send_updated_menu)

    def threaded_setup(self) -> None:
        self.exec_start_commands()

        def set_reaper_callback():
            self.child_reaper.set_quit_callback(self.reaper_exit)
            self.child_reaper.check()

        GLib.idle_add(set_reaper_callback)

    def cleanup(self) -> None:
        if self.terminate_children and self._exit_mode not in (ServerExitMode.UPGRADE, ServerExitMode.EXIT):
            self.terminate_children_processes()
        # during cleanup, just ignore the reaper exit callback:
        self.reaper_exit = noop
        if self.menu_provider:
            self.menu_provider.cleanup()

    def get_server_features(self, _source) -> dict[str, Any]:
        return {
            "start-new-commands": self.start_new_commands,
            "exit-with-children": self.exit_with_children,
            "server-commands-signals": COMMAND_SIGNALS,
            "server-commands-info": not WIN32 and not OSX,
        }

    def _get_xdg_menu_data(self) -> dict[str, Any] | None:
        if not self.start_new_commands:
            return None
        assert self.menu_provider
        return self.menu_provider.get_menu_data()

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if not source:
            return caps
        # don't assume we have a real ClientConnection object:
        wants = getattr(source, "wants", [])
        if "features" in wants and getattr(source, "ui_client", False):
            caps["xdg-menu"] = {}
            caps["subcommands"] = get_subcommands()
        return caps

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        self.exec_on_connect_commands()

    def send_initial_data(self, ss, caps: typedict, send_ui: bool, share_count: int) -> None:
        xdg_menu = getattr(ss, "xdg_menu", False)
        log(f"send_initial_data(..) {xdg_menu=}")
        if not xdg_menu:
            return
        # this method may block if the menus are still being loaded,
        # so do it in a throw-away thread:
        start_thread(self.send_xdg_menu_data, "send-xdg-menu-data", True, (ss,))

    def send_xdg_menu_data(self, ss) -> None:
        if ss.is_closed():
            return
        xdg_menu = self._get_xdg_menu_data() or {}
        self.do_send_xdg_menu_data(ss, xdg_menu)

    def do_send_xdg_menu_data(self, ss, xdg_menu):
        if ss.is_closed():
            return
        if not getattr(ss, "send_setting_change", False):
            return
        if not getattr(ss, "xdg_menu", False):
            return
        ss.send_setting_change("xdg-menu", xdg_menu)
        log(f"{len(xdg_menu)} menu data entries sent to {ss}")

    def send_updated_menu(self, xdg_menu) -> None:
        log("send_updated_menu(%s)", Ellipsizer(xdg_menu))
        for source in tuple(self._server_sources.values()):
            self.do_send_xdg_menu_data(source, xdg_menu)

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[Any, Any] = {
            "start": self.start_commands,
            "start-late": self.start_late_commands,
            "start-child": self.start_child_commands,
            "start-child-late": self.start_child_late_commands,
            "start-after-connect": self.start_after_connect,
            "start-child-after-connect": self.start_child_after_connect,
            "start-on-connect": self.start_on_connect,
            "start-child-on-connect": self.start_child_on_connect,
            "exit-with-children": self.exit_with_children,
            "start-after-connect-done": self.start_after_connect_done,
            "start-new": self.start_new_commands,
            "source-env": self.source_env,
            "start-env": self.start_env,
        }
        mp = self.menu_provider
        if mp:
            info.update(
                {
                    "start-menu": mp.get_menu_data(remove_icons=True, wait=False) or {},
                    "start-desktop-menu": mp.get_desktop_sessions(remove_icons=True) or {},
                }
            )
        for i, procinfo in enumerate(self.children_started):
            info[i] = procinfo.get_info()
        cinfo: dict[str, Any] = {ChildCommandServer.PREFIX: info}
        return cinfo

    def last_client_exited(self) -> None:
        self._exec_commands(self.start_on_last_client_exit, self.start_child_on_last_client_exit)

    def get_child_env(self) -> dict[str, str]:
        # subclasses may add more
        env = restore_script_env(super().get_child_env())
        env.update(self.source_env)
        env.update(self.start_env)
        if self.child_display:
            env["DISPLAY"] = self.child_display
        return env

    def get_full_child_command(self, cmd, use_wrapper=True) -> list[str]:
        # make sure we have it as a list:
        cmd = super().get_full_child_command(cmd, use_wrapper)
        if not use_wrapper or not self.exec_wrapper:
            return cmd
        return self.exec_wrapper + cmd

    def exec_start_late_commands(self) -> None:
        log("exec_start_late_commands() start-late=%s, start_child=%s",
            self.start_late_commands, self.start_child_late_commands)
        self._exec_commands(self.start_late_commands, self.start_child_late_commands)

    def exec_start_commands(self) -> None:
        log("exec_start_commands() start=%s, start_child=%s", self.start_commands, self.start_child_commands)
        self._exec_commands(self.start_commands, self.start_child_commands)

    def exec_after_connect_commands(self) -> None:
        log("exec_after_connect_commands() start=%s, start_child=%s",
            self.start_after_connect, self.start_child_after_connect)
        self._exec_commands(self.start_after_connect, self.start_child_after_connect)

    def exec_on_connect_commands(self) -> None:
        log("exec_on_connect_commands() start_after_connect_done=%s", self.start_after_connect_done)
        if not self.start_after_connect_done:  # pylint: disable=access-member-before-definition
            self.start_after_connect_done = True
            self.exec_after_connect_commands()
        log("exec_on_connect_commands() start=%s, start_child=%s", self.start_on_connect, self.start_child_on_connect)
        self._exec_commands(self.start_on_connect, self.start_child_on_connect)

    def _exec_commands(self, start_list, start_child_list) -> None:
        started = []
        if start_list:
            for x in start_list:
                if x:
                    proc = self.start_command(x, x, ignore=True)
                    if proc:
                        started.append(proc)
        if start_child_list:
            for x in start_child_list:
                if x:
                    proc = self.start_command(x, x, ignore=False)
                    if proc:
                        started.append(proc)
        procs = tuple(x for x in started if x is not None)
        if not self.session_name:
            GLib.idle_add(self.guess_session_name, procs)

    def start_command(self, name: str, child_cmd, ignore: bool = False, callback: Callable | None = None,
                      use_wrapper: bool = True, shell: bool = False, **kwargs):
        env = self.get_child_env()
        log("start_command%s exec_wrapper=%s, exec_cwd=%s",
            (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), self.exec_wrapper, self.exec_cwd)
        real_cmd = []
        cmd_str = None
        try:
            real_cmd = self.get_full_child_command(child_cmd, use_wrapper)
            log("full child command(%s, %s)=%s", child_cmd, use_wrapper, real_cmd)
            cmd_str = " ".join(real_cmd)
            # pylint: disable=consider-using-with
            proc = Popen(real_cmd, env=env, shell=shell, cwd=self.exec_cwd, **kwargs)
            procinfo = self.add_process(proc, name, real_cmd, ignore=ignore, callback=callback)
            is_ibus_daemon = real_cmd[0] == "ibus-daemon"
            cmd_info = "ibus-daemon" if is_ibus_daemon else cmd_str
            log.info(f"started command `{cmd_info}` with pid {proc.pid}")
            if not ignore:
                self.children_count += 1
            self.children_started.append(procinfo)
            session_dir = os.environ.get("XPRA_SESSION_DIR")
            if session_dir and not procinfo.dead:
                pidname = name.split(" ")[0]
                if pidname.find(os.sep) >= 0:
                    pidname = pidname.split(os.sep)[-1]
                pidfile = os.path.join(session_dir, f"{pidname}.pid")
                if not os.path.exists(pidfile):
                    procinfo.pidfile = pidfile
                    procinfo.pidinode = write_pid(pidfile, procinfo.pid)
                log(f"pidfile({name})={pidfile}, inode={procinfo.pidinode}, pid={procinfo.pid}")
            return proc
        except (OSError, ValueError) as e:
            log("start_command%s", (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), exc_info=True)
            log.error(f"Error spawning child {child_cmd!r}")
            if len(real_cmd) > 1:
                log.error(" using command:")
                log.error(f" `{cmd_str}`")
            log.error(f" {e}")
            return None

    def add_process(self, process, name: str, command, ignore: bool = False,
                    callback: Callable | None = None) -> ProcInfo:
        return self.child_reaper.add_process(process, name, command, ignore, callback=callback)

    @staticmethod
    def is_child_alive(proc) -> bool:
        return proc is not None and proc.poll() is None

    def reaper_exit_check(self) -> None:
        log(f"reaper_exit_check() exit_with_children={self.exit_with_children}")
        if self.exit_with_children and self.children_count:
            log.info("all children have exited and --exit-with-children was specified, exiting")
            GLib.idle_add(self.clean_quit)

    def terminate_children_processes(self) -> None:
        cl = tuple(self.children_started)
        self.children_started = []
        log(f"terminate_children_processes() children={cl}")
        if not cl:
            return
        wait_for = []
        self.child_reaper.poll()
        for procinfo in cl:
            proc = procinfo.process
            name = procinfo.name
            if self.is_child_alive(proc):
                wait_for.append(procinfo)
                log(f"child command {name!r} is still alive, calling terminate on {proc}")
                try:
                    proc.terminate()
                except Exception as e:
                    log(f"failed to terminate {proc}: {e}")
                    del e
        if not wait_for:
            return
        log(f"waiting for child commands to exit: {wait_for}")
        start = monotonic()
        while monotonic() - start < TERMINATE_DELAY and wait_for:
            self.child_reaper.poll()
            # this is called from the UI thread, we cannot sleep
            # sleep(1)
            wait_for = [procinfo for procinfo in wait_for if self.is_child_alive(procinfo.process)]
            log(f"still not terminated: {wait_for}")
        log("done waiting for child commands")

    def guess_session_name(self, procs=None) -> None:
        if not procs:
            return
        from xpra.scripts.server import IBUS_DAEMON_COMMAND  # pylint: disable=import-outside-toplevel
        if IBUS_DAEMON_COMMAND:
            ibus_daemon_cmd = shlex.split(IBUS_DAEMON_COMMAND)[0] or "ibus-daemon"
        else:
            ibus_daemon_cmd = ""
        # use the commands to define the session name:
        self.child_reaper.poll()
        cmd_names = []
        for proc in procs:
            proc_info = self.child_reaper.get_proc_info(proc.pid)
            if not proc_info:
                continue
            cmd = proc_info.command
            if self.exec_wrapper:
                # strip exec wrapper
                l = len(self.exec_wrapper)
                if len(cmd) > l and cmd[:l] == self.exec_wrapper:
                    cmd = cmd[l:]
            elif len(cmd) > 1 and cmd[0] in ("vglrun", "nohup",):
                cmd.pop(0)
            if ibus_daemon_cmd and cmd[0] == ibus_daemon_cmd:
                continue
            bcmd = os.path.basename(cmd[0])
            if bcmd not in cmd_names:
                cmd_names.append(bcmd)
        log(f"guess_session_name() commands={cmd_names}")
        if cmd_names:
            new_name = csv(cmd_names)
            if self.session_name != new_name:
                self.session_name = new_name
                self.mdns_update()

    def _process_start_command(self, proto, packet: PacketType) -> None:
        self._process_command_start(proto, packet)

    def _process_command_start(self, proto, packet: PacketType) -> None:
        log(f"start new command: {packet}")
        if not self.start_new_commands:
            log.warn("Warning: received start-command request,")
            log.warn(" but the feature is currently disabled")
            return
        name = str(packet[1])
        command = packet[2]
        ignore = bool(packet[3])
        cmd: str | tuple
        if isinstance(command, (list, tuple)):
            cmd = tuple(command)
        else:
            cmd = str(command)
        proc = self.start_command(name, cmd, ignore)
        if len(packet) >= 5:
            shared = packet[4]
            if proc and not shared:
                ss = self.get_server_source(proto)
                assert ss
                log(f"adding filter: pid={proc.pid} for {proto}")
                ss.add_window_filter("window", "pid", "=", proc.pid)
        log(f"process_start_command: proc={proc}")

    def _process_command_signal(self, _proto, packet: PacketType) -> None:
        pid = packet[1]
        signame = packet[2]
        if signame not in COMMAND_SIGNALS:
            log.warn("Warning: invalid signal received: '%s'", signame)
            return
        procinfo = self.child_reaper.get_proc_info(pid)
        if not procinfo:
            log.warn("Warning: command not found for pid %i", pid)
            return
        if procinfo.returncode is not None:
            log.warn("Warning: command for pid %i has already terminated", pid)
            return
        sigval = getattr(signal, signame, None)
        if not sigval:
            log.error(f"Error: signal {signame!r} not found!")
            return
        log.info(f"sending signal {signame!r} to pid {pid}")
        try:
            os.kill(pid, sigval)
        except Exception as e:
            log.error(f"Error sending signal {signame!r} to pid {pid}")
            log.estr(e)

    def init_packet_handlers(self) -> None:
        log("init_packet_handlers() COMMANDS_SIGNALS=%s, start new commands=%s",
            COMMAND_SIGNALS, self.start_new_commands)
        if COMMAND_SIGNALS:
            self.add_packets("command-signal")
        if self.start_new_commands:
            self.add_packets(f"{ChildCommandServer.PREFIX}-start")
            self.add_legacy_alias("start-command", f"{ChildCommandServer.PREFIX}-start")
