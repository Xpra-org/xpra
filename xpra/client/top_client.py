# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import curses
import signal
import traceback
from subprocess import Popen, PIPE
try:
    from subprocess import DEVNULL # py3k
except ImportError:
    DEVNULL = open(os.devnull, 'wb')
from datetime import datetime, timedelta

from xpra.version_util import caps_to_version
from xpra.util import noerr,typedict, std, envint, csv, engs, repr_ellipsized
from xpra.os_util import (
    platform_name, get_machine_id,
    bytestostr, monotonic_time,
    POSIX, SIGNAMES,
    )
from xpra.exit_codes import EXIT_STR
from xpra.make_thread import start_thread
from xpra.client.gobject_client_base import MonitorXpraClient
from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_nodock_command
from xpra.simple_stats import std_unit
from xpra.common import GRAVITY_STR
from xpra.log import Logger

log = Logger("gobject", "client")

REFRESH_RATE = envint("XPRA_REFRESH_RATE", 1)
CURSES_LOG = os.environ.get("XPRA_CURSES_LOG")

WHITE = 0
GREEN = 1
YELLOW = 2
RED = 3

EXIT_KEYS = (ord("q"), ord("Q"))
PAUSE_KEYS = (ord("p"), ord("P"))
SIGNAL_KEYS = {
    3 : signal.SIGINT,
    26 : signal.SIGSTOP,
    }


def get_title():
    from xpra.version_util import full_version_str
    return "Xpra top %s" % full_version_str()

def curses_init():
    stdscr = curses.initscr()
    stdscr.keypad(True)
    stdscr.nodelay(True)
    stdscr.clear()
    curses.noecho()
    curses.raw()
    curses.start_color()
    curses.use_default_colors()
    #for i in range(0, curses.COLORS):
    #    curses.init_pair(i+1, i, -1)
    curses.init_pair(WHITE, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(RED, curses.COLOR_RED, curses.COLOR_BLACK)
    return stdscr

def curses_clean(stdscr):
    if not stdscr:
        return
    stdscr.keypad(False)
    curses.nocbreak()
    curses.echo()
    curses.endwin()

def curses_err(stdscr, e):
    if CURSES_LOG:
        with open(CURSES_LOG, "ab") as f:
            f.write(b"%s\n" % e)
            f.write(traceback.format_exc().encode())
        return
    stdscr.addstr(0, 0, str(e))
    for i, l in enumerate(traceback.format_exc().split("\n")):
        try:
            stdscr.addstr(i+1, 0, l)
        except Exception:
            pass

def box(stdscr, x, y, w, h, ul, ur, ll, lr):
    stdscr.hline(y, x, curses.ACS_HLINE, w-1)               #@UndefinedVariable
    stdscr.hline(y + h - 1, x, curses.ACS_HLINE, w - 1)     #@UndefinedVariable
    stdscr.vline(y, x, curses.ACS_VLINE, h)                 #@UndefinedVariable
    stdscr.vline(y, x + w -1, curses.ACS_VLINE, h)          #@UndefinedVariable
    stdscr.addch(y, x, ul)
    stdscr.addch(y, x + w - 1, ur)
    stdscr.addch(y + h - 1, x, ll)
    stdscr.addch(y + h - 1, x + w - 1, lr)


class TopClient:

    def __init__(self, conn, opts):
        self.stdscr = None
        self.socket_dirs = opts.socket_dirs
        self.socket_dir = opts.socket_dir
        self.position = 0
        self.selected_session = None
        self.message = None
        self.exit_code = None
        self.dotxpra = DotXpra(self.socket_dir, self.socket_dirs)
        self.last_getch = 0
        self.psprocess = {}
        self.setup_connection(conn)

    def setup_connection(self, conn):
        self.stdscr = curses_init()
        self.update_screen()

    def run(self):
        self.setup()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self.signal_handler)
        self.update_loop()
        self.cleanup()
        return self.exit_code

    def signal_handler(self, signum, *_args):
        self.exit_code = 128+signum

    def setup(self):
        self.stdscr = curses_init()
        curses.cbreak()

    def cleanup(self):
        scr = self.stdscr
        if scr:
            curses.nocbreak()
            scr.erase()
            curses_clean(scr)
            self.stdscr = None

    def update_loop(self):
        while self.exit_code is None:
            self.update_screen()
            elapsed = int(1000*monotonic_time()-self.last_getch)
            delay = max(100, min(1000, 1000-elapsed))//100
            curses.halfdelay(delay)
            try:
                v = self.stdscr.getch()
            except Exception:
                v = -1
            self.last_getch = int(1000*monotonic_time())
            if v in EXIT_KEYS:
                self.exit_code = 0
            if v in SIGNAL_KEYS:
                self.exit_code = 128+SIGNAL_KEYS[v]
            if v==258:    #down arrow
                self.position += 1
            elif v==259:    #up arrow
                self.position = max(self.position-1, 0)
            elif v==10 and self.selected_session:
                self.show_selected_session()
            elif v in (ord("s"), ord("S")):
                self.run_subcommand("stop")
            elif v in (ord("a"), ord("A")):
                self.run_subcommand("attach")
            elif v in (ord("d"), ord("D")):
                self.run_subcommand("detach")

    def show_selected_session(self):
        #show this session:
        try:
            self.cleanup()
            env = os.environ.copy()
            #we only deal with local sessions, should be fast:
            env["XPRA_CONNECT_TIMEOUT"] = "3"
            proc = self.do_run_subcommand("top", env=env)
            if not proc:
                self.message = monotonic_time(), "failed to execute subprocess", curses.color_pair(RED)
                return
            exit_code = proc.wait()
            txt = "top subprocess terminated"
            attr = 0
            if exit_code!=0:
                attr = curses.color_pair(RED)
                txt += " with error code %i" % exit_code
                if exit_code in EXIT_STR:
                    txt += " (%s)" % EXIT_STR.get(exit_code, "").replace("_", " ")
                elif (exit_code-128) in SIGNAMES:   #pylint: disable=superfluous-parens
                    txt += " (%s)" % SIGNAMES[exit_code-128]
            self.message = monotonic_time(), txt, attr
        finally:
            self.setup()

    def run_subcommand(self, subcommand):
        return self.do_run_subcommand(subcommand, stdout=DEVNULL, stderr=DEVNULL)

    def do_run_subcommand(self, subcommand, **kwargs):
        cmd = get_nodock_command()+[subcommand, self.selected_session]
        try:
            return Popen(cmd, **kwargs)
        except Exception:
            return None


    def update_screen(self):
        self.stdscr.erase()
        try:
            self.do_update_screen()
        finally:
            self.stdscr.refresh()
        return True

    def do_update_screen(self):
        #c = self.stdscr.getch()
        #if c==curses.KEY_RESIZE:
        height, width = self.stdscr.getmaxyx()
        #log.info("update_screen() %ix%i", height, width)
        title = get_title()
        x = max(0, width//2-len(title)//2)
        try:
            hpos = 0
            self.stdscr.addstr(hpos, x, title, curses.A_BOLD)
            hpos += 1
            if height<=hpos:
                return
            sd = self.dotxpra.socket_details()
            #group them by display instead of socket dir:
            displays = {}
            for sessions in sd.values():
                for state, display, path in sessions:
                    displays.setdefault(display, []).append((state, path))
            self.stdscr.addstr(hpos, 0, "found %i display%s" % (len(displays), engs(displays)))
            self.position = min(len(displays), self.position)
            self.selected_session = None
            hpos += 1
            if height<=hpos:
                return
            if self.message:
                ts, txt, attr = self.message
                if monotonic_time()-ts<10:
                    self.stdscr.addstr(hpos, 0, txt, attr)
                    hpos += 1
                    if height<=hpos:
                        return
                else:
                    self.message = None
            n = len(displays)
            for i, (display, state_paths) in enumerate(displays.items()):
                if height<=hpos:
                    return
                info = self.get_display_info(display, state_paths)
                l = len(info)
                if height<=hpos+l+2:
                    break
                self.box(1, hpos, width-2, l+2, open_top=i>0, open_bottom=i<n-1)
                hpos += 1
                if i==self.position:
                    self.selected_session = display
                    attr = curses.A_REVERSE
                else:
                    attr = 0
                for s in info:
                    if len(s)>=width-4:
                        s = s[:width-6]+".."
                    s = s.ljust(width-4)
                    self.stdscr.addstr(hpos, 2, s, attr)
                    hpos += 1
        except Exception as e:
            curses_err(self.stdscr, e)

    def get_display_info(self, display, state_paths):
        info = [display]
        valid_path = None
        for state, path in state_paths:
            sinfo = "%40s : %s" % (path, state)
            if POSIX:
                from pwd import getpwuid
                from grp import getgrgid
                try:
                    stat = os.stat(path)
                    #if stat.st_uid!=os.getuid():
                    sinfo += "  uid=%s" % getpwuid(stat.st_uid).pw_name
                    #if stat.st_gid!=os.getgid():
                    sinfo += "  gid=%s" % getgrgid(stat.st_gid).gr_name
                except Exception as e:
                    sinfo += "(stat error: %s)" % e
            info.append(sinfo)
            if state==DotXpra.LIVE:
                valid_path = path
        if valid_path:
            d = self.get_display_id_info(valid_path)
            name = d.get("session-name")
            uuid = d.get("uuid")
            stype = d.get("session-type")
            error = d.get("error")
            if error:
                info[0] = "%s  %s" % (display, error)
            else:
                info[0] = "%s  %s" % (display, name)
                info.insert(1, "uuid=%s, type=%s" % (uuid, stype))
            machine_id = d.get("machine-id")
            if machine_id is None or machine_id==get_machine_id():
                try:
                    pid = int(d.get("pid"))
                except (ValueError, TypeError):
                    pass
                else:
                    try:
                        process = self.psprocess.get(pid)
                        if not process:
                            import psutil
                            process = psutil.Process(pid)
                            self.psprocess[pid] = process
                        else:
                            cpu = process.cpu_percent()
                            info[0] += ", %3i%% CPU" % (cpu)
                    except Exception:
                        pass
        return info

    def get_display_id_info(self, path):
        d = {}
        try:
            cmd = get_nodock_command()+["id", "socket://%s" % path]
            proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
            out, err = proc.communicate()
            for line in bytestostr(out or err).splitlines():
                try:
                    k,v = line.split("=", 1)
                    d[k] = v
                except ValueError:
                    continue
            return d
        except Exception as e:
            d["error"] = str(e)
        return d


    def box(self, x, y, w, h, open_top=False, open_bottom=False):
        if open_top:
            ul = curses.ACS_LTEE        #@UndefinedVariable
            ur = curses.ACS_RTEE        #@UndefinedVariable
        else:
            ul = curses.ACS_ULCORNER    #@UndefinedVariable
            ur = curses.ACS_URCORNER    #@UndefinedVariable
        if open_bottom:
            ll = curses.ACS_LTEE        #@UndefinedVariable
            lr = curses.ACS_RTEE        #@UndefinedVariable
        else:
            ll = curses.ACS_LLCORNER    #@UndefinedVariable
            lr = curses.ACS_LRCORNER    #@UndefinedVariable
        box(self.stdscr, x, y, w, h, ul, ur, ll, lr)


class TopSessionClient(MonitorXpraClient):

    def __init__(self, conn, *args):
        self.stdscr = None
        self.log_file = None
        if CURSES_LOG:
            self.log_file = open(CURSES_LOG, "ab")
        self.info_request_pending = False
        self.server_last_info = typedict()
        self.server_last_info_time = 0
        self.info_timer = 0
        self.paused = False
        self.psprocess = {}
        self.modified = False
        self.setup()
        MonitorXpraClient.__init__(self, conn, *args)
        start_thread(self.input_thread, "input-thread", daemon=True)

    def client_type(self):
        #overriden in subclasses!
        return "top"

    def setup_connection(self, conn):
        MonitorXpraClient.setup_connection(self, conn)
        self.stdscr = curses_init()
        self.update_screen()

    def setup(self):
        self.stdscr = curses_init()
        try:
            curses.cbreak()
            curses.halfdelay(10)
        except Exception as e:
            self.log("failed to configure curses: %s" % e)

    def run(self):
        register_os_signals(self.signal_handler)
        self.log("run()")
        v = MonitorXpraClient.run(self)
        self.log("run()=%s" % v)
        self.cleanup()
        self.close_log()
        return v

    def signal_handler(self, signum, *args):
        self.log("exit_code=%s" % self.exit_code)
        self.log("signal_handler(%s, %s)" % (signum, args,))
        self.quit(128+signum)
        self.log("exit_code=%s" % self.exit_code)

    def cleanup(self):
        self.cancel_info_timer()
        MonitorXpraClient.cleanup(self)
        curses_clean(self.stdscr)

    def close_log(self):
        log_file = self.log_file
        if log_file:
            self.log("closing log")
            self.log_file = None
            log_file.close()

    def log(self, message):
        lf = self.log_file
        if lf:
            now = datetime.now()
            #we log from multiple threads,
            #so the file may have been closed
            #by the time we get here:
            noerr(lf.write, ("%s %s\n" % (now.strftime("%Y/%m/%d %H:%M:%S.%f"), message)).encode())
            noerr(lf.flush)

    def err(self, e):
        lf = self.log_file
        if lf:
            noerr(lf.write, b"%s\n" % e)
            noerr(lf.write(traceback.format_exc().encode()))
        else:
            curses_err(self.stdscr, e)

    def update_screen(self):
        self.modified = True


    def input_thread(self):
        self.log("input thread: signal handlers=%s" % signal.getsignal(signal.SIGINT))
        while self.exit_code is None:
            if not self.paused and self.modified:
                self.stdscr.erase()
                try:
                    self.do_update_screen()
                except Exception as e:
                    self.err(e)
                finally:
                    self.stdscr.refresh()
            try:
                curses.halfdelay(10)
                v = self.stdscr.getch()
            except Exception as e:
                self.log("getch() %s" % e)
                v = -1
            self.log("getch()=%s" % v)
            if v==-1:
                continue
            if v in EXIT_KEYS:
                self.log("exit on key '%s'" % v)
                self.quit(0)
                break
            if v in SIGNAL_KEYS:
                self.log("exit on signal key '%s'" % v)
                self.quit(128+SIGNAL_KEYS[v])
                break
            if v in PAUSE_KEYS:
                self.paused = not self.paused

    def do_update_screen(self):
        self.log("do_update_screen()")
        #c = self.stdscr.getch()
        #if c==curses.KEY_RESIZE:
        height, width = self.stdscr.getmaxyx()
        #log.info("update_screen() %ix%i", height, width)
        title = get_title()
        sli = self.server_last_info
        def _addstr(pad, y, x, s, *args):
            if len(s)+x>=width-pad:
                s = s[:max(0, width-x-2-pad)]+".."
            self.stdscr.addstr(y, x, s, *args)
        def addstr_main(y, x, s, *args):
            _addstr(0, y, x, s, *args)
        def addstr_box(y, x, s, *args):
            _addstr(2, y, x, s, *args)
        try:
            x = max(0, width//2-len(title)//2)
            addstr_main(0, x, title, curses.A_BOLD)
            if height<=1:
                return
            server_info = self.slidictget("server")
            build = self.slidictget("server", "build")
            vstr = caps_to_version(build)
            mode = server_info.strget("mode", "server")
            python_info = typedict(server_info.dictget("python", {}))
            bits = python_info.intget("bits", 32)
            server_str = "Xpra %s server version %s %i-bit" % (mode, vstr, bits)
            proxy_info = self.slidictget("proxy")
            if proxy_info:
                proxy_platform_info = typedict(proxy_info.dictget("platform", {}))
                proxy_platform = proxy_platform_info.strget("")
                proxy_release = proxy_platform_info.strget("release")
                proxy_build_info = typedict(proxy_info.dictget("build", {}))
                proxy_version = proxy_build_info.strget("version")
                proxy_distro = proxy_info.strget("linux_distribution")
                server_str += " via: %s proxy version %s" % (
                    platform_name(proxy_platform, proxy_distro or proxy_release),
                    std(proxy_version or "unknown")
                    )
            addstr_main(1, 0, server_str)
            if height<=2:
                return
            #load and uptime:
            now = datetime.now()
            uptime = ""
            elapsed_time = server_info.intget("elapsed_time")
            if elapsed_time:
                td = timedelta(seconds=elapsed_time)
                uptime = " up %s" % str(td).lstrip("0:")
            clients_info = self.slidictget("clients")
            nclients = clients_info.intget("")
            load_average = ""
            load = sli.inttupleget("load")
            if load and len(load)==3:
                float_load = tuple(v/1000.0 for v in load)
                load_average = ", load average: %1.2f, %1.2f, %1.2f" % float_load
            addstr_main(2, 0, "xpra top - %s%s, %2i users%s" % (
                               now.strftime("%H:%M:%S"), uptime, nclients, load_average))
            if height<=3:
                return
            thread_info = self.slidictget("threads")
            rinfo = "%i threads" % thread_info.intget("count")
            server_pid = server_info.intget("pid", 0)
            if server_pid:
                rinfo += ", pid %i" % server_pid
                machine_id = server_info.get("machine-id")
                if machine_id is None or machine_id==get_machine_id():
                    try:
                        process = self.psprocess.get(server_pid)
                        if not process:
                            import psutil
                            process = psutil.Process(server_pid)
                            self.psprocess[server_pid] = process
                        else:
                            cpu = process.cpu_percent()
                            rinfo += ", %3i%% CPU" % (cpu)
                    except Exception:
                        pass
            cpuinfo = self.slidictget("cpuinfo")
            if cpuinfo:
                rinfo += ", %s" % cpuinfo.strget("hz_actual")
            elapsed = monotonic_time()-self.server_last_info_time
            color = WHITE
            if self.server_last_info_time==0:
                rinfo += " - no server data"
            elif elapsed>2:
                rinfo += " - last updated %i seconds ago" % elapsed
                color = RED
            addstr_main(3, 0, rinfo, curses.color_pair(color))
            if height<=4:
                return
            #display:
            dinfo = []
            server = self.slidictget("server")
            rws = server.intpair("root_window_size", None)
            if rws:
                sinfo = "%ix%i display" % (rws[0], rws[1])
                mds = server.intpair("max_desktop_size")
                if mds:
                    sinfo += " (max %ix%i)" % (mds[0], mds[1])
                dinfo.append(sinfo)
            cursor_info = self.slidictget("cursor")
            if cursor_info:
                cx, cy = cursor_info.inttupleget("position", (0, 0))
                dinfo.append("cursor at %ix%i" % (cx, cy))
            display_info = self.slidictget("display")
            pid = display_info.intget("pid")
            if pid:
                dinfo.append("pid %i" % pid)
            addstr_main(4, 0, csv(dinfo))
            if height<=5:
                return
            hpos = 5
            gl_info = self.get_gl_info(display_info.dictget("opengl"))
            if gl_info:
                addstr_main(5, 0, gl_info)
                hpos += 1

            if hpos<height-3:
                hpos += 1
                if nclients==0:
                    addstr_main(hpos, 0, "no clients connected")
                else:
                    addstr_main(hpos, 0, "%i client%s connected:" % (nclients, engs(nclients)))
                hpos += 1
            client_info = self.slidictget("client")
            client_no = 0
            while True:
                ci = client_info.dictget(client_no)
                if not ci:
                    break
                client_no +=1
                ci = typedict(ci)
                session_id = ci.strget("session-id")
                if session_id:
                    #don't show ourselves:
                    if session_id==self.session_id:
                        continue
                elif not ci.boolget("windows", True):
                    #for older servers, hide any client that doesn't display windows:
                    continue
                ci = self.get_client_info(ci)
                l = len(ci)
                if hpos+2+l>height:
                    if hpos<height:
                        more = nclients-client_no
                        addstr_box(hpos, 0, "%i client%s not shown" % (more, engs(more)), curses.A_BOLD)
                    break
                self.box(1, hpos, width-2, 2+l)
                for i, info in enumerate(ci):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    addstr_box(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l

            windows = self.slidictget("windows")
            if hpos<height-3:
                hpos += 1
                addstr_main(hpos, 0, "%i window%s:" % (len(windows), engs(windows)))
                hpos += 1
            wins = tuple(windows.values())
            nwindows = len(wins)
            for win_no, win in enumerate(wins):
                wi = self.get_window_info(typedict(win))
                l = len(wi)
                if hpos+2+l>height:
                    if hpos<height:
                        more = nwindows-win_no
                        addstr_main(hpos, 0, "terminal window is too small: %i window%s not shown" % \
                                           (more, engs(more)), curses.A_BOLD)
                    break
                self.box(1, hpos, width-2, 2+l)
                for i, info in enumerate(wi):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    addstr_box(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l
        except Exception as e:
            self.err(e)

    def slidictget(self, *parts):
        return self.dictget(self.server_last_info, *parts)
    def dictget(self, dictinstance, *parts):
        d = dictinstance
        for part in parts:
            d = typedict(d.dictget(part, {}))
        return d

    def get_client_info(self, ci):
        #version info:
        ctype = ci.strget("type", "unknown")
        title = "%s client version " % ctype
        title += caps_to_version(ci)
        chost = ci.strget("hostname")
        conn_info = ""
        if chost:
            conn_info = "connected from %s " % chost
        cinfo = ci.dictget("connection")
        if cinfo:
            cinfo = typedict(cinfo)
            conn_info += "using %s %s" % (cinfo.strget("type"), cinfo.strget("protocol-type"))
            conn_info += ", with %s and %s" % (cinfo.strget("encoder"), cinfo.strget("compressor"))
        gl_info = self.get_gl_info(ci.dictget("opengl"))
        #audio
        audio_info = []
        for mode in ("speaker", "microphone"):
            audio_info.append(self._audio_info(ci, mode))
        audio_info.append(self._avsync_info(ci))
        #batch delay / latency:
        b_info = typedict(ci.dictget("batch", {}))
        bi_info = typedict(b_info.dictget("delay", {}))
        bcur = bi_info.intget("cur")
        bavg = bi_info.intget("avg")
        batch_info = "batch delay: %i (%i)" %(
            bcur,
            bavg,
            )
        #client latency:
        pl = self.dictget(ci, "connection", "client", "ping_latency")
        lcur = pl.intget("cur")
        lavg = pl.intget("avg")
        lmin = pl.intget("min")
        bl_color = GREEN
        if bcur>50 or (lcur>20 and lcur>2*lmin):
            bl_color = YELLOW
        elif bcur>100 or (lcur>20 and lcur>3*lmin):
            bl_color = RED
        batch_latency = batch_info.ljust(24)+"latency: %i (%i)" % (lcur, lavg)
        #speed / quality:
        edict = typedict(ci.dictget("encoding") or {})
        qs_info = ""
        qs_color = GREEN
        if edict:
            sinfo = typedict(edict.dictget("speed") or {})
            if sinfo:
                cur = sinfo.intget("cur")
                avg = sinfo.intget("avg")
                qs_info = "speed: %s%% (avg: %s%%)" % (cur, avg)
            qinfo = typedict(edict.dictget("quality") or {})
            if qinfo:
                qs_info = qs_info.ljust(24)
                cur = qinfo.intget("cur")
                avg = qinfo.intget("avg")
                qs_info += "quality: %s%% (avg: %s%%)" % (cur, avg)
                if avg<70:
                    qs_color = YELLOW
                if avg<50:
                    qs_color = RED
        return tuple((s, c) for s,c in (
            (title, WHITE),
            (conn_info, WHITE),
            (gl_info, WHITE),
            (csv(audio_info), WHITE),
            (batch_latency, bl_color),
            (qs_info, qs_color),
            ) if s)

    def _audio_info(self, ci, mode="speaker"):
        minfo = self.dictget(ci, "sound", mode)
        if not minfo:
            return "%s off" % mode
        minfo = typedict(minfo)
        audio_info = "%s: %s" % (mode, minfo.strget("codec_description") or \
                                 minfo.strget("codec") or \
                                 minfo.strget("state", "unknown"))
        bitrate = minfo.intget("bitrate")
        if bitrate:
            audio_info += " %sbps" % std_unit(bitrate)
        return audio_info

    def _avsync_info(self, ci):
        avsf = self.slidictget("features", "av-sync")
        if not avsf or not avsf.boolget("", False):
            return "av-sync: not supported by server"
        if not avsf.boolget("enabled", False):
            return "av-sync: disabled by server"
        #client specific attributes:
        avsi = self.dictget(ci, "av-sync")
        if not avsi.boolget("", False):
            return "av-sync: disabled by client"
        return "av-sync: enabled - video delay: %ims" % (avsi.intget("total", 0))

    def get_window_info(self, wi):
        #version info:
        geom = wi.inttupleget("geometry")
        g_str = "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])
        sc = wi.dictget("size-constraints")
        if sc:
            def sc_str(k, v):
                k = bytestostr(k)
                if k=="gravity":
                    v = GRAVITY_STR.get(v, v)
                return "%s=%s" % (k, str(v))
            g_str += " - %s" % csv(sc_str(k, v) for k,v in sc.items())
        line1 = ""
        pid = wi.intget("pid", 0)
        if pid:
            line1 = "pid %i: " % pid
        title = wi.bytesget("title", b"")
        if title:
            try:
                line1 += ' "%s"' % title.decode("utf8")
            except UnicodeDecodeError:
                line1 += ' "%s"' % bytestostr(title)
        attrs = [
            x for x in (
                "above", "below", "bypass-compositor",
                "focused", "fullscreen",
                "grabbed", "iconic", "maximized", "modal",
                "override-redirect", "shaded", "skip-pager",
                "skip-taskbar", "sticky", "tray",
                ) if wi.boolget(x)
            ]
        if not wi.boolget("shown"):
            attrs.insert(0, "hidden")
        wtype = wi.strtupleget("window-type", ("NORMAL",))
        tinfo = " - ".join(csv(x) for x in (wtype, attrs) if x)
        info = []
        if line1:
            info.append(line1)
        info += [g_str, tinfo]
        return tuple((x, WHITE) for x in info if x)

    def get_gl_info(self, gli):
        if not gli:
            return None
        gli = typedict(gli)
        def strget(key, sep="."):
            #fugly warning:
            #depending on where we get the gl info from,
            #the value might be a list of strings,
            #or a byte string...
            v = gli.rawget(key)
            if isinstance(v, (tuple, list)):
                return sep.join(bytestostr(x) for x in v)
            return bytestostr(v)
        if not gli.boolget("enabled", True):
            return "OpenGL disabled %s" % gli.strget("message", "")
        gl_info = "OpenGL %s enabled: %s" % (strget("opengl", "."), gli.strget("renderer") or gli.strget("vendor"))
        depth = gli.intget("depth")
        if depth not in (0, 24):
            gl_info += ", %ibits" % depth
        modes = gli.rawget("display_mode")
        if modes:
            gl_info += " - %s" % strget("display_mode", ", ")
        return gl_info

    def box(self, x, y, w, h):
        box(self.stdscr, x, y, w, h,
            ul=curses.ACS_ULCORNER, ur=curses.ACS_URCORNER,     #@UndefinedVariable
            ll=curses.ACS_LLCORNER, lr=curses.ACS_LRCORNER)     #@UndefinedVariable


    def do_command(self):
        self.send_info_request()
        self.timeout_add(REFRESH_RATE*1000, self.send_info_request)

    def send_info_request(self):
        self.log("send_info_request()")
        categories = ()
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = ()    #no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)
        if not self.info_timer:
            self.info_timer = self.timeout_add((REFRESH_RATE+2)*1000, self.info_timeout)
        return True

    def init_packet_handlers(self):
        MonitorXpraClient.init_packet_handlers(self)
        self.add_packet_handler("info-response", self._process_info_response, False)

    def _process_server_event(self, packet):
        self.log("server event: %s" % (packet,))
        self.last_server_event = packet[1:]
        self.update_screen()

    def _process_info_response(self, packet):
        self.log("info response: %s" % repr_ellipsized(packet))
        self.cancel_info_timer()
        self.info_request_pending = False
        self.server_last_info = typedict(packet[1])
        self.server_last_info_time = monotonic_time()
        #log.info("server_last_info=%s", self.server_last_info)
        self.update_screen()

    def cancel_info_timer(self):
        it = self.info_timer
        if it:
            self.info_timer = None
            self.source_remove(it)

    def info_timeout(self):
        self.log("info timeout")
        self.update_screen()
        return True
