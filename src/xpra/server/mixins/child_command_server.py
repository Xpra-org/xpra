# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.log import Logger
log = Logger("server")
log = Logger("exec")

from xpra.platform.features import COMMAND_SIGNALS
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.os_util import monotonic_time, OSX, WIN32
from xpra.util import envint, csv
from xpra.scripts.parsing import parse_env
from xpra.server import EXITING_CODE
from xpra.server.mixins.stub_server_mixin import StubServerMixin


TERMINATE_DELAY = envint("XPRA_TERMINATE_DELAY", 1000)/1000.0


"""
Mixin for servers that can handle file transfers and forwarded printers.
Printer forwarding is only supported on Posix servers with the cups backend script.
"""
class ChildCommandServer(StubServerMixin):

    def __init__(self):
        self.child_display = None
        self.start_commands = []
        self.start_child_commands = []
        self.start_after_connect = []
        self.start_child_after_connect = []
        self.start_on_connect = []
        self.start_child_on_connect = []
        self.exit_with_children = False
        self.start_after_connect_done = False
        self.start_new_commands = False
        self.start_env = []
        self.exec_cwd = None
        self.exec_wrapper = None
        self.terminate_children = False
        self.children_started = []
        self.child_reaper = None

    def init(self, opts):
        self.exit_with_children = opts.exit_with_children
        self.terminate_children = opts.terminate_children
        self.start_new_commands = opts.start_new_commands
        self.start_commands              = opts.start
        self.start_child_commands        = opts.start_child
        self.start_after_connect         = opts.start_after_connect
        self.start_child_after_connect   = opts.start_child_after_connect
        self.start_on_connect            = opts.start_on_connect
        self.start_child_on_connect      = opts.start_child_on_connect
        if opts.exec_wrapper:
            import shlex
            self.exec_wrapper = shlex.split(opts.exec_wrapper)
        self.child_reaper = getChildReaper()
        self.start_env = parse_env(opts.start_env)

    def threaded_setup(self):
        self.exec_start_commands()
        def set_reaper_callback():
            self.child_reaper.set_quit_callback(self.reaper_exit)
            self.child_reaper.check()
        self.idle_add(set_reaper_callback)

    def cleanup(self):
        if self.terminate_children and self._upgrading!=EXITING_CODE:
            self.terminate_children_processes()
        def noop():
            pass
        self.reaper_exit = noop
        reaper_cleanup()


    def get_server_features(self, _source):
        return {
            "start-new-commands"        : self.start_new_commands,
            "exit-with-children"        : self.exit_with_children,
            "server-commands-signals"   : COMMAND_SIGNALS,
            "server-commands-info"      : not WIN32 and not OSX,
            }


    def get_info(self, _proto):
        info = {
            "start"                     : self.start_commands,
            "start-child"               : self.start_child_commands,
            "start-after-connect"       : self.start_after_connect,
            "start-child-after-connect" : self.start_child_after_connect,
            "start-on-connect"          : self.start_on_connect,
            "start-child-on-connect"    : self.start_child_on_connect,
            "exit-with-children"        : self.exit_with_children,
            "start-after-connect-done"  : self.start_after_connect_done,
            "start-new"                 : self.start_new_commands,
            }
        for i,procinfo in enumerate(self.children_started):
            info[i] = procinfo.get_info()
        return {"commands": info}


    def get_child_env(self):
        #subclasses may add more items (ie: fakexinerama)
        env = os.environ.copy()
        env.update(self.start_env)
        if self.child_display:
            env["DISPLAY"] = self.child_display
        return env


    def get_full_child_command(self, cmd, use_wrapper=True):
        #make sure we have it as a list:
        if type(cmd) not in (list, tuple):
            import shlex
            cmd = shlex.split(str(cmd))
        if not use_wrapper or not self.exec_wrapper:
            return cmd
        return self.exec_wrapper + cmd


    def exec_start_commands(self):
        log("exec_start_commands() start=%s, start_child=%s", self.start_commands, self.start_child_commands)
        self._exec_commands(self.start_commands, self.start_child_commands)

    def exec_after_connect_commands(self):
        log("exec_after_connect_commands() start=%s, start_child=%s", self.start_after_connect, self.start_child_after_connect)
        self._exec_commands(self.start_after_connect, self.start_child_after_connect)

    def exec_on_connect_commands(self):
        log("exec_on_connect_commands() start=%s, start_child=%s", self.start_on_connect, self.start_child_on_connect)
        self._exec_commands(self.start_on_connect, self.start_child_on_connect)

    def _exec_commands(self, start_list, start_child_list):
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
            self.idle_add(self.guess_session_name, procs)

    def start_command(self, name, child_cmd, ignore=False, callback=None, use_wrapper=True, shell=False, **kwargs):
        log("start_command%s exec_wrapper=%s", (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), self.exec_wrapper)
        import subprocess
        env = self.get_child_env()
        try:
            real_cmd = self.get_full_child_command(child_cmd, use_wrapper)
            log("full child command(%s, %s)=%s", child_cmd, use_wrapper, real_cmd)
            proc = subprocess.Popen(real_cmd, stdin=subprocess.PIPE, env=env, shell=shell, cwd=self.exec_cwd, close_fds=True, **kwargs)
            procinfo = self.add_process(proc, name, real_cmd, ignore=ignore, callback=callback)
            log("pid(%s)=%s", real_cmd, proc.pid)
            if not ignore:
                log.info("started command '%s' with pid %s", " ".join(real_cmd), proc.pid)
            self.children_started.append(procinfo)
            return proc
        except OSError as e:
            log.error("Error spawning child '%s': %s\n" % (child_cmd, e))
            return None


    def add_process(self, process, name, command, ignore=False, callback=None):
        return self.child_reaper.add_process(process, name, command, ignore, callback=callback)

    def is_child_alive(self, proc):
        return proc is not None and proc.poll() is None

    def reaper_exit(self):
        log("reaper_exit() exit_with_children=%s", self.exit_with_children)
        if self.exit_with_children:
            log.info("all children have exited and --exit-with-children was specified, exiting")
            self.idle_add(self.clean_quit)

    def terminate_children_processes(self):
        cl = tuple(self.children_started)
        self.children_started = []
        log("terminate_children_processes() children=%s", cl)
        if not cl:
            return
        wait_for = []
        self.child_reaper.poll()
        for procinfo in cl:
            proc = procinfo.process
            name = procinfo.name
            if self.is_child_alive(proc):
                wait_for.append(procinfo)
                log("child command '%s' is still alive, calling terminate on %s", name, proc)
                try:
                    proc.terminate()
                except Exception as e:
                    log("failed to terminate %s: %s", proc, e)
                    del e
        if not wait_for:
            return
        log("waiting for child commands to exit: %s", wait_for)
        start = monotonic_time()
        while monotonic_time()-start<TERMINATE_DELAY and wait_for:
            self.child_reaper.poll()
            #this is called from the UI thread, we cannot sleep
            #sleep(1)
            wait_for = [procinfo for procinfo in wait_for if self.is_child_alive(procinfo.process)]
            log("still not terminated: %s", wait_for)
        log("done waiting for child commands")

    def guess_session_name(self, procs):
        if not procs:
            return
        #use the commands to define the session name:
        self.child_reaper.poll()
        cmd_names = []
        for proc in procs:
            proc_info = self.child_reaper.get_proc_info(proc.pid)
            if not proc_info:
                continue
            cmd = proc_info.command
            bcmd = os.path.basename(cmd[0])
            if bcmd not in cmd_names:
                cmd_names.append(bcmd)
        log("guess_session_name() commands=%s", cmd_names)
        if cmd_names:
            self.session_name = csv(cmd_names)


    def _process_start_command(self, proto, packet):
        log("start new command: %s", packet)
        if not self.start_new_commands:
            log.warn("Warning: received start-command request,")
            log.warn(" but the feature is currently disabled")
            return
        name, command, ignore = packet[1:4]
        proc = self.start_command(name, command, ignore)
        if len(packet)>=5:
            shared = packet[4]
            if proc and not shared:
                ss = self._server_sources.get(proto)
                assert ss
                log("adding filter: pid=%s for %s", proc.pid, proto)
                ss.add_window_filter("window", "pid", "=", proc.pid)
        log("process_start_command: proc=%s", proc)

    def _process_command_signal(self, _proto, packet):
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
        import signal
        sigval = getattr(signal, signame, None)
        if not sigval:
            log.error("Error: signal '%s' not found!", signame)
            return
        log.info("sending signal %s to pid %i", signame, pid)
        try:
            os.kill(pid, sigval)
        except Exception as e:
            log.error("Error sending signal '%s' to pid %i", signame, pid)
            log.error(" %s", e)


    def init_packet_handlers(self):
        if COMMAND_SIGNALS:
            self._authenticated_packet_handlers.update({
                "command-signal" : self._process_command_signal,
              })
        if self.start_new_commands:
            self._authenticated_ui_packet_handlers.update({
                "start-command" : self._process_start_command,
                })
