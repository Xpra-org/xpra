# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.platform.features import COMMAND_SIGNALS
from xpra.platform.paths import get_icon_filename
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.os_util import monotonic_time, load_binary_file, bytestostr, OSX, WIN32, POSIX
from xpra.util import envint, csv, envbool
from xpra.make_thread import start_thread
from xpra.scripts.parsing import parse_env, get_subcommands
from xpra.server.server_util import source_env
from xpra.server import EXITING_CODE
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("exec")
httplog = Logger("http")

TERMINATE_DELAY = envint("XPRA_TERMINATE_DELAY", 1000)/1000.0
MENU_RELOAD_DELAY = envint("XPRA_MENU_RELOAD_DELAY", 5)
EXPORT_XDG_MENU_DATA = envbool("XPRA_EXPORT_XDG_MENU_DATA", True)
HTTP_MENU = envbool("XPRA_EXPORT_HTTP_MENU_DATA", EXPORT_XDG_MENU_DATA)


def noicondata(menu_data):
    newdata = {}
    for k,v in menu_data.items():
        if k in ("IconData", b"IconData"):
            continue
        if isinstance(v, dict):
            newdata[k] = noicondata(v)
        else:
            newdata[k] = v
    return newdata


class ChildCommandServer(StubServerMixin):
    """
    Mixin for servers that can handle file transfers and forwarded printers.
    Printer forwarding is only supported on Posix servers with the cups backend script.
    """

    def __init__(self):
        self.child_display = None
        self.start_commands = []
        self.start_child_commands = []
        self.start_after_connect = []
        self.start_child_after_connect = []
        self.start_on_connect = []
        self.start_child_on_connect = []
        self.start_on_last_client_exit = []
        self.start_child_on_last_client_exit = []
        self.exit_with_children = False
        self.children_count = 0
        self.start_after_connect_done = False
        self.start_new_commands = False
        self.source_env = {}
        self.start_env = {}
        self.exec_cwd = None
        self.exec_wrapper = None
        self.terminate_children = False
        self.children_started = []
        self.child_reaper = None
        self.reaper_exit = self.reaper_exit_check
        self.watch_manager = None
        self.watch_notifier = None
        self.xdg_menu_reload_timer = None
        #does not belong here...
        if not hasattr(self, "_upgrading"):
            self._upgrading = False
        if not hasattr(self, "session_name"):
            self.session_name = ""

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
        self.start_on_last_client_exit   = opts.start_on_last_client_exit
        self.start_child_on_last_client_exit = opts.start_child_on_last_client_exit
        if opts.exec_wrapper:
            import shlex
            self.exec_wrapper = shlex.split(opts.exec_wrapper)
        self.child_reaper = getChildReaper()
        self.source_env = source_env(opts.source_start)
        self.start_env = parse_env(opts.start_env)

    def threaded_setup(self):
        self.exec_start_commands()
        def set_reaper_callback():
            self.child_reaper.set_quit_callback(self.reaper_exit)
            self.child_reaper.check()
        self.idle_add(set_reaper_callback)
        if POSIX and not OSX and self.start_new_commands and EXPORT_XDG_MENU_DATA:
            try:
                self.setup_menu_watcher()
            except Exception as e:
                log("threaded_setup()", exc_info=True)
                log.error("Error setting up menu watcher:")
                log.error(" %s", e)
            from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
            #start loading in a thread,
            #so server startup can complete:
            start_thread(load_xdg_menu_data, "load-xdg-menu-data", True)


    def setup_menu_watcher(self):
        try:
            import pyinotify
        except ImportError as e:
            log("setup_menu_watcher() cannot import pyinotify", exc_info=True)
            log.warn("Warning: cannot watch for application menu changes without pyinotify:")
            log.warn(" %s", e)
            return
        self.watch_manager = pyinotify.WatchManager()
        def menu_data_updated(create, pathname):
            log("menu_data_updated(%s, %s)", create, pathname)
            self.schedule_xdg_menu_reload()
        class EventHandler(pyinotify.ProcessEvent):
            def process_IN_CREATE(self, event):
                menu_data_updated(True, event.pathname)
            def process_IN_DELETE(self, event):
                menu_data_updated(False, event.pathname)
        mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  #@UndefinedVariable pylint: disable=no-member
        handler = EventHandler()
        self.watch_notifier = pyinotify.ThreadedNotifier(self.watch_manager, handler)
        self.watch_notifier.setDaemon(True)
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/share/applications:/usr/local/share/applications").split(":")
        watched = []
        for data_dir in data_dirs:
            menu_dir = os.path.join(data_dir, "applications")
            if not os.path.exists(menu_dir) or menu_dir in watched:
                continue
            wdd = self.watch_manager.add_watch(menu_dir, mask)
            watched.append(menu_dir)
            log("watch_notifier=%s, watch=%s", self.watch_notifier, wdd)
        self.watch_notifier.start()
        if watched:
            log.info("watching for applications menu changes in:")
            for wd in watched:
                log.info(" '%s'", wd)


    def cleanup(self):
        if self.terminate_children and self._upgrading!=EXITING_CODE:
            self.terminate_children_processes()
        def noop():
            pass
        self.reaper_exit = noop
        reaper_cleanup()
        xmrt = self.xdg_menu_reload_timer
        if xmrt:
            self.xdg_menu_reload_timer = None
            self.source_remove(xmrt)
        wn = self.watch_notifier
        if wn:
            self.watch_notifier = None
            wn.stop()
        watch_manager = self.watch_manager
        if watch_manager:
            self.watch_manager = None
            try:
                watch_manager.close()
            except OSError:
                log("error closing watch manager %s", watch_manager, exc_info=True)


    def get_server_features(self, _source) -> dict:
        return {
            "start-new-commands"        : self.start_new_commands,
            "exit-with-children"        : self.exit_with_children,
            "server-commands-signals"   : COMMAND_SIGNALS,
            "server-commands-info"      : not WIN32 and not OSX,
            "xdg-menu-update"           : POSIX and not OSX,
            }

    def get_http_scripts(self) -> dict:
        if not HTTP_MENU:
            return {}
        return {
            "/menu" : self.http_menu_request,
            "/menu-icon" : self.http_menu_icon_request,
            "/desktop-menu" : self.http_desktop_menu_request,
            }

    def http_menu_request(self, handler):
        def err(code=500):
            handler.send_response(code)
            return None
        xdg_menu = self._get_xdg_menu_data() or {}
        #from xpra.util import print_nested_dict
        #print_nested_dict(noicondata(xdg_menu))
        import json
        ji = json.dumps(noicondata(xdg_menu))
        return self.send_http_response(handler, ji, "application/json")

    def http_desktop_menu_request(self, handler):
        from xdg.DesktopEntry import DesktopEntry
        xsessions_dir = "%s/share/xsessions" % sys.prefix
        xdg_sessions = {}
        if os.path.exists(xsessions_dir):
            for f in os.listdir(xsessions_dir):
                filename = os.path.join(xsessions_dir, f)
                de = DesktopEntry(filename)
                try:
                    from xpra.platform.xposix.xdg_helper import load_xdg_entry
                    xdg_sessions[de.getName()] = load_xdg_entry(de)
                except Exception as e:
                    log("http_desktop_menu_request(%s)", handler, exc_info=True)
                    log.error("Error loading desktop entry '%s':", filename)
                    log.error(" %s", e)
        import json
        ji = json.dumps(noicondata(xdg_sessions))
        return self.send_http_response(handler, ji, "application/json")

    def http_menu_icon_request(self, handler):
        def err(code=500):
            handler.send_response(code)
            return None
        def invalid_path():
            httplog("invalid menu-icon request path '%s'", handler.path)
            return err()
        parts = handler.path.split("/menu-icon/", 1)
        #ie: "/menu-icon/a/b" -> ['', 'a/b']
        if len(parts)<2:
            return invalid_path()
        path = parts[1].split("/")
        #ie: "a/b" -> ['a', 'b']
        if len(path)<2:
            return invalid_path()
        xdg_menu = self._get_xdg_menu_data() or {}
        category_name, app_name = path[:2]
        category = xdg_menu.get(category_name)
        if not category:
            httplog("invalid menu category '%s'", category_name)
            return err()
        entries = category.get("Entries")
        if not entries:
            httplog("no entries for category '%s'", category_name)
            return err()
        app = entries.get(app_name)
        if not app:
            httplog("no matching application for '%s' in category '%s'",
                app_name, category_name)
            return err()
        icon_data = app.get("IconData")
        icon_type = app.get("IconType")
        mime_type = "application/octet-stream"
        if icon_type in ("png", "jpeg", "svg",):
            mime_type = "image/%s" % icon_type
        if not icon_data:
            icon_data = load_binary_file(get_icon_filename("transparent.png"))
            mime_type = "image/png"
        httplog("menu-icon for %s/%s : %i bytes of %s",
            category_name, app_name, len(icon_data or b""), mime_type)
        return self.send_http_response(handler, icon_data, mime_type)


    def _get_xdg_menu_data(self, force_reload=False):
        if not EXPORT_XDG_MENU_DATA:
            return None
        if not self.start_new_commands:
            return None
        if OSX:
            return None
        if POSIX:
            from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
            return load_xdg_menu_data(force_reload)
        if WIN32:
            from xpra.platform.win32.menu_helper import load_menu
            return load_menu()
        log.error("Error: unsupported platform!")
        return None

    def get_caps(self, source) -> dict:
        caps = {}
        if not source:
            return caps
        #don't assume we have a real ClientConnection object:
        if getattr(source, "wants_features", False) and getattr(source, "ui_client", False):
            caps["xdg-menu"] = {}
            if not source.xdg_menu_update:
                #we have to send it now:
                xdg_menu = self._get_xdg_menu_data()
                log("%i entries sent in hello", len(xdg_menu or ()))
                if xdg_menu:
                    l = len(str(xdg_menu))
                    #arbitrary: don't use more than half
                    #of the maximum size of the hello packet:
                    if l>2*1024*1024:
                        from xpra.platform.xposix.xdg_helper import remove_icons
                        xdg_menu = remove_icons(xdg_menu)
                        log.info("removed icons to reduce the size of the xdg menu data")
                        log.info("size reduced from %i to %i", l, len(str(xdg_menu)))
                    caps["xdg-menu"] = xdg_menu
            caps["subcommands"] = get_subcommands()
        return caps

    def send_initial_data(self, ss, caps, send_ui, share_count):
        if ss.xdg_menu_update:
            #this method may block if the menus are still being loaded,
            #so do it in a throw-away thread:
            start_thread(self.send_xdg_menu_data, "send-xdg-menu-data", True, (ss,))

    def send_xdg_menu_data(self, ss):
        if ss.is_closed():
            return
        xdg_menu = self._get_xdg_menu_data() or {}
        log("%i entries sent in initial data", len(xdg_menu))
        ss.send_setting_change("xdg-menu", xdg_menu)

    def schedule_xdg_menu_reload(self):
        xmrt = self.xdg_menu_reload_timer
        if xmrt:
            self.source_remove(xmrt)
        self.xdg_menu_reload_timer = self.timeout_add(MENU_RELOAD_DELAY*1000, self.xdg_menu_reload)

    def xdg_menu_reload(self):
        self.xdg_menu_reload_timer = None
        log("xdg_menu_reload()")
        xdg_menu = self._get_xdg_menu_data(True)
        for source in tuple(self._server_sources.values()):
            if source.xdg_menu_update:
                source.send_setting_change("xdg-menu", xdg_menu or {})
        return False

    def get_info(self, _proto) -> dict:
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
        md = self._get_xdg_menu_data()
        if md:
            info["start-menu"] = noicondata(md)
        for i,procinfo in enumerate(self.children_started):
            info[i] = procinfo.get_info()
        return {"commands": info}


    def last_client_exited(self):
        self._exec_commands(self.start_on_last_client_exit, self.start_child_on_last_client_exit)


    def get_child_env(self):
        #subclasses may add more items (ie: fakexinerama)
        env = super().get_child_env()
        env.update(self.source_env)
        env.update(self.start_env)
        if self.child_display:
            env["DISPLAY"] = self.child_display
        return env

    def get_full_child_command(self, cmd, use_wrapper=True) -> list:
        #make sure we have it as a list:
        cmd = super().get_full_child_command(cmd, use_wrapper)
        if not use_wrapper or not self.exec_wrapper:
            return cmd
        return self.exec_wrapper + cmd


    def exec_start_commands(self):
        log("exec_start_commands() start=%s, start_child=%s", self.start_commands, self.start_child_commands)
        self._exec_commands(self.start_commands, self.start_child_commands)

    def exec_after_connect_commands(self):
        log("exec_after_connect_commands() start=%s, start_child=%s",
            self.start_after_connect, self.start_child_after_connect)
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
        from subprocess import Popen
        env = self.get_child_env()
        log("start_command%s exec_wrapper=%s, exec_cwd=%s",
            (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), self.exec_wrapper, self.exec_cwd)
        real_cmd = []
        try:
            real_cmd = self.get_full_child_command(child_cmd, use_wrapper)
            log("full child command(%s, %s)=%s", child_cmd, use_wrapper, real_cmd)
            proc = Popen(real_cmd, env=env, shell=shell, cwd=self.exec_cwd, **kwargs)
            procinfo = self.add_process(proc, name, real_cmd, ignore=ignore, callback=callback)
            log("pid(%s)=%s", real_cmd, proc.pid)
            log.info("started command '%s' with pid %s", " ".join(bytestostr(x) for x in real_cmd), proc.pid)
            if not ignore:
                self.children_count += 1
            self.children_started.append(procinfo)
            return proc
        except (OSError, ValueError) as e:
            log("start_command%s", (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), exc_info=True)
            log.error("Error spawning child '%s':" % (child_cmd, ))
            if len(real_cmd)>1:
                log.error(" using command:")
                log.error(" %s", " ".join("'%s'" % x for x in real_cmd))
            log.error(" %s" % (e,))
            return None


    def add_process(self, process, name, command, ignore=False, callback=None):
        return self.child_reaper.add_process(process, name, command, ignore, callback=callback)

    def is_child_alive(self, proc) -> bool:
        return proc is not None and proc.poll() is None

    def reaper_exit_check(self):
        log("reaper_exit_check() exit_with_children=%s", self.exit_with_children)
        if self.exit_with_children and self.children_count:
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

    def guess_session_name(self, procs=None):
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
            if self.exec_wrapper:
                #strip exec wrapper
                l = len(self.exec_wrapper)
                if len(cmd)>l and cmd[:l]==self.exec_wrapper:
                    cmd = cmd[l:]
            elif len(cmd)>1 and cmd[0] in ("vglrun", "nohup",):
                cmd.pop(0)
            bcmd = os.path.basename(cmd[0])
            if bcmd not in cmd_names:
                cmd_names.append(bcmd)
        log("guess_session_name() commands=%s", cmd_names)
        if cmd_names:
            new_name = csv(cmd_names)
            if self.session_name!=new_name:
                self.session_name = new_name
                self.mdns_update()


    def _process_start_command(self, proto, packet):
        log("start new command: %s", packet)
        if not self.start_new_commands:
            log.warn("Warning: received start-command request,")
            log.warn(" but the feature is currently disabled")
            return
        name, command, ignore = packet[1:4]
        if isinstance(command, (list, tuple)):
            cmd = command
        else:
            cmd = command.decode("utf-8")
        proc = self.start_command(name.decode("utf-8"), cmd, ignore)
        if len(packet)>=5:
            shared = packet[4]
            if proc and not shared:
                ss = self.get_server_source(proto)
                assert ss
                log("adding filter: pid=%s for %s", proc.pid, proto)
                ss.add_window_filter("window", "pid", "=", proc.pid)
        log("process_start_command: proc=%s", proc)

    def _process_command_signal(self, _proto, packet):
        pid = packet[1]
        signame = bytestostr(packet[2])
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
        log("init_packet_handlers() COMMANDS_SIGNALS=%s, start new commands=%s",
            COMMAND_SIGNALS, self.start_new_commands)
        if COMMAND_SIGNALS:
            self.add_packet_handler("command-signal", self._process_command_signal, False)
        if self.start_new_commands:
            self.add_packet_handler("start-command", self._process_start_command)
