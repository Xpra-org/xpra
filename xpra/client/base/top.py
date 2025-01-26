# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import curses
import signal
import traceback
from time import monotonic, sleep
from collections.abc import Sequence
from subprocess import Popen, PIPE, DEVNULL
from datetime import datetime, timedelta

from xpra.util.version import caps_to_version, full_version_str
from xpra.util.objects import typedict
from xpra.util.str_fn import std, csv, bytestostr
from xpra.util.env import envint
from xpra.os_util import get_machine_id, POSIX
from xpra.util.system import platform_name, SIGNAMES
from xpra.exit_codes import ExitCode, ExitValue
from xpra.util.thread import start_thread
from xpra.client.base.command import InfoTimerClient
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_nodock_command
from xpra.util.stats import std_unit
from xpra.common import gravity_str, SocketState, noerr
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
    3: signal.SIGINT,
}
if hasattr(signal, "SIGSTOP"):
    SIGNAL_KEYS[26] = signal.SIGSTOP


def get_title() -> str:
    return f"Xpra top {full_version_str()}"


def curses_init():
    stdscr = curses.initscr()
    stdscr.keypad(True)
    stdscr.nodelay(True)
    stdscr.clear()
    curses.noecho()
    curses.raw()
    curses.start_color()
    if curses.can_change_color():
        try:
            curses.use_default_colors()
            curses.init_pair(WHITE, curses.COLOR_WHITE, curses.COLOR_BLACK)
            curses.init_pair(GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)
            curses.init_pair(YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
            curses.init_pair(RED, curses.COLOR_RED, curses.COLOR_BLACK)
        except Exception:
            # this can fail on some terminals, ie: mingw
            pass
    # for i in range(0, curses.COLORS):
    #    curses.init_pair(i+1, i, -1)
    return stdscr


def curses_clean(stdscr):
    if not stdscr:
        return
    stdscr.keypad(False)
    curses.nocbreak()
    curses.echo()
    curses.endwin()


def curses_err(stdscr, e) -> None:
    if CURSES_LOG:
        with open(CURSES_LOG, "ab") as f:
            f.write(b"%s\n" % e)
            f.write(traceback.format_exc().encode())
        return
    stdscr.addstr(0, 0, str(e))
    for i, l in enumerate(traceback.format_exc().split("\n")):
        try:
            stdscr.addstr(i + 1, 0, l)
        except Exception:
            pass


def box(stdscr, x: int, y: int, w: int, h: int, ul, ur, ll, lr) -> None:
    stdscr.hline(y, x, curses.ACS_HLINE, w - 1)  # @UndefinedVariable
    stdscr.hline(y + h - 1, x, curses.ACS_HLINE, w - 1)  # @UndefinedVariable
    stdscr.vline(y, x, curses.ACS_VLINE, h)  # @UndefinedVariable
    stdscr.vline(y, x + w - 1, curses.ACS_VLINE, h)  # @UndefinedVariable
    stdscr.addch(y, x, ul)
    stdscr.addch(y, x + w - 1, ur)
    stdscr.addch(y + h - 1, x, ll)
    stdscr.addch(y + h - 1, x + w - 1, lr)


def get_display_id_info(path: str) -> dict[str, str]:
    d = {}
    try:
        cmd = get_nodock_command() + ["id", f"socket://{path}"]
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
        out, err = proc.communicate()
        for line in (out or err).splitlines():
            try:
                k, v = line.split("=", 1)
                d[k] = v
            except ValueError:
                continue
        return d
    except Exception as e:
        d["error"] = str(e)
    return d


def get_window_info(wi: typedict) -> Sequence[tuple[str, int]]:
    # version info:
    geom = wi.inttupleget("geometry")
    g_str = "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])
    sc = wi.dictget("size-constraints")
    if sc:
        def sc_str(k, v):
            if k == "gravity":
                v = gravity_str(v)
            return f"{k}={v}"

        g_str += " - %s" % csv(sc_str(k, v) for k, v in sc.items())
    line1 = ""
    pid = wi.intget("pid", 0)
    if pid:
        line1 = f"pid {pid}: "
    title = wi.strget("title")
    if title:
        line1 += f' "{title}"'
    attrs = [
        x for x in (
            "above", "below", "bypass-compositor",
            "focused", "fullscreen",
            "grabbed", "iconic", "maximized", "modal",
            "override-redirect", "shaded", "skip-pager",
            "skip-taskbar", "sticky", "tray",
        )
        if wi.boolget(x)
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


class TopClient:

    def __init__(self, opts):
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

    def run(self) -> ExitValue:
        self.setup()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self.signal_handler)
        self.update_loop()
        self.cleanup()
        return self.exit_code or 0

    def signal_handler(self, signum: int, *_args) -> None:
        self.exit_code = 128 + signum

    def setup(self) -> None:
        self.stdscr = curses_init()
        curses.cbreak()

    def cleanup(self) -> None:
        scr = self.stdscr
        if scr:
            curses.nocbreak()
            scr.erase()
            curses_clean(scr)
            self.stdscr = None

    def update_loop(self) -> None:
        while self.exit_code is None:
            self.update_screen()
            # elapsed is in milliseconds:
            elapsed = int(1000 * monotonic() - self.last_getch)
            # delay is in tenths of a second (1 to 10 here):
            delay = max(1, min(1000, 1000 - elapsed) // 100)
            curses.halfdelay(delay)
            try:
                v = self.stdscr.getch()
            except Exception:
                v = -1
            self.last_getch = int(1000 * monotonic())
            print(f"getch()={v}")
            if v in EXIT_KEYS:
                self.exit_code = 0
            if v in SIGNAL_KEYS:
                self.exit_code = 128 + SIGNAL_KEYS[v]
            if v == 258:  # down arrow
                self.position += 1
            elif v == 259:  # up arrow
                self.position = max(self.position - 1, 0)
            elif v == 10 and self.selected_session:
                self.show_selected_session()
            elif v in (ord("s"), ord("S")):
                self.run_subcommand("stop")
            elif v in (ord("a"), ord("A")):
                self.run_subcommand("attach")
            elif v in (ord("d"), ord("D")):
                self.run_subcommand("detach")

    def show_selected_session(self) -> None:
        # show this session:
        try:
            self.cleanup()
            env = os.environ.copy()
            # we only deal with local sessions, should be fast:
            env["XPRA_CONNECT_TIMEOUT"] = "3"
            proc = self.do_run_subcommand("top", env=env)
            if not proc:
                self.message = monotonic(), "failed to execute subprocess", curses.color_pair(RED)
                return
            exit_code = proc.wait()
            txt = "top subprocess terminated"
            attr = 0
            if exit_code != 0:
                attr = curses.color_pair(RED)
                txt += f" with error code {exit_code}"
                try:
                    estr = ExitCode(exit_code).name
                    txt += f" ({estr})"
                except ValueError:
                    if (exit_code - 128) in SIGNAMES:  # pylint: disable=superfluous-parens
                        txt += f" ({SIGNAMES[exit_code - 128]})"
            self.message = monotonic(), txt, attr
        finally:
            self.setup()

    def run_subcommand(self, subcommand: str) -> Popen | None:
        return self.do_run_subcommand(subcommand, stdout=DEVNULL, stderr=DEVNULL)

    def do_run_subcommand(self, subcommand: str, **kwargs) -> Popen | None:
        cmd = get_nodock_command() + [subcommand, self.selected_session]
        try:
            return Popen(cmd, **kwargs)
        except Exception:
            return None

    def update_screen(self) -> bool:
        self.stdscr.erase()
        try:
            self.do_update_screen()
        finally:
            self.stdscr.refresh()
        return True

    def do_update_screen(self) -> None:
        # c = self.stdscr.getch()
        # if c==curses.KEY_RESIZE:
        height, width = self.stdscr.getmaxyx()
        # log.info("update_screen() %ix%i", height, width)
        title = get_title()
        x = max(0, width // 2 - len(title) // 2)
        try:
            hpos = 0
            self.stdscr.addstr(hpos, x, title, curses.A_BOLD)
            hpos += 1
            if height <= hpos:
                return
            sd = self.dotxpra.socket_details()
            # group them by display instead of socket dir:
            displays = {}
            for sessions in sd.values():
                for state, display, path in sessions:
                    displays.setdefault(display, []).append((state, path))
            self.stdscr.addstr(hpos, 0, f"found {len(displays)} displays:")
            self.position = min(len(displays), self.position)
            self.selected_session = None
            hpos += 1
            if height <= hpos:
                return
            if self.message:
                ts, txt, attr = self.message
                if monotonic() - ts < 10:
                    self.stdscr.addstr(hpos, 0, txt, attr)
                    hpos += 1
                    if height <= hpos:
                        return
                else:
                    self.message = None
            n = len(displays)
            for i, (display, state_paths) in enumerate(displays.items()):
                if height <= hpos:
                    return
                info = self.get_display_info(display, state_paths)
                nlines = len(info)
                if height <= hpos + nlines + 2:
                    break
                self.box(1, hpos, width - 2, nlines + 2, open_top=i > 0, open_bottom=i < n - 1)
                hpos += 1
                if i == self.position:
                    self.selected_session = display
                    attr = curses.A_REVERSE
                else:
                    attr = 0
                for s in info:
                    if len(s) >= width - 4:
                        s = s[:width - 6] + ".."
                    s = s.ljust(width - 4)
                    self.stdscr.addstr(hpos, 2, s, attr)
                    hpos += 1
        except Exception as e:
            curses_err(self.stdscr, e)

    def get_display_info(self, display, state_paths) -> list[str]:
        info = [display]
        valid_path = None
        for state, path in state_paths:
            sinfo = f"{path:50} : {state}"
            if POSIX:
                # pylint: disable=import-outside-toplevel
                from pwd import getpwuid
                from grp import getgrgid
                try:
                    stat = os.stat(path)
                    # if stat.st_uid!=os.getuid():
                    sinfo += "  uid=" + getpwuid(stat.st_uid).pw_name
                    # if stat.st_gid!=os.getgid():
                    sinfo += "  gid=" + getgrgid(stat.st_gid).gr_name
                except Exception as e:
                    sinfo += f"(stat error: {e})"
            info.append(sinfo)
            if state == SocketState.LIVE:
                valid_path = path
        if valid_path:
            d = get_display_id_info(valid_path)
            name = d.get("session-name")
            uuid = d.get("uuid")
            stype = d.get("session-type")
            error = d.get("error")
            if error:
                info[0] = f"{display}  {error}"
            else:
                info[0] = f"{display}  {name}"
                info.insert(1, f"uuid={uuid}, type={stype}")
            machine_id = d.get("machine-id")
            if machine_id is None or machine_id == get_machine_id():
                try:
                    pid = int(d.get("pid"))
                except (ValueError, TypeError):
                    pass
                else:
                    try:
                        process = self.psprocess.get(pid)
                        if not process:
                            import psutil  # pylint: disable=import-outside-toplevel
                            process = psutil.Process(pid)
                            self.psprocess[pid] = process
                        else:
                            cpu = process.cpu_percent()
                            info[0] += f", {cpu:3}% CPU"
                    except Exception:
                        pass
        return info

    def box(self, x: int, y: int, w: int, h: int, open_top=False, open_bottom=False) -> None:
        if open_top:
            ul = curses.ACS_LTEE
            ur = curses.ACS_RTEE
        else:
            ul = curses.ACS_ULCORNER
            ur = curses.ACS_URCORNER
        if open_bottom:
            ll = curses.ACS_LTEE
            lr = curses.ACS_RTEE
        else:
            ll = curses.ACS_LLCORNER
            lr = curses.ACS_LRCORNER
        box(self.stdscr, x, y, w, h, ul, ur, ll, lr)


class TopSessionClient(InfoTimerClient):

    def __init__(self, *args):
        super().__init__(*args)
        self.log_file = None
        if CURSES_LOG:
            self.log_file = open(CURSES_LOG, "ab")  # pylint: disable=consider-using-with
        self.paused = False
        self.stdscr = None
        self.modified = False
        self.psprocess = {}
        start_thread(self.input_thread, "input-thread", daemon=True)

    def client_type(self) -> str:
        return "top"

    def server_connection_established(self, caps) -> bool:
        self.log(f"server_connection_established({caps!r})")
        self.log("traceback: " + str(traceback.extract_stack()))
        self.setup()
        self.update_screen()
        return super().server_connection_established(caps)

    def setup(self) -> None:
        if self.stdscr is None:
            self.stdscr = curses_init()
        try:
            curses.cbreak()
            curses.halfdelay(10)
        except Exception as e:
            self.log(f"failed to configure curses: {e}")

    def cleanup(self) -> None:
        super().cleanup()
        curses_clean(self.stdscr)
        self.stdscr = None
        self.close_log()

    def close_log(self) -> None:
        log_file = self.log_file
        if log_file:
            self.log("closing log")
            self.log_file = None
            log_file.close()

    def log(self, message) -> None:
        lf = self.log_file
        if lf:
            now = datetime.now()
            # we log from multiple threads,
            # so the file may have been closed
            # by the time we get here:
            noerr(lf.write, (now.strftime("%Y/%m/%d %H:%M:%S.%f") + " " + message + "\n").encode())
            noerr(lf.flush)

    def err(self, e) -> None:
        lf = self.log_file
        if lf:
            noerr(lf.write, b"%s\n" % e)
            noerr(lf.write, traceback.format_exc().encode())
        else:
            curses_err(self.stdscr, e)

    def dictwarn(self, msg: str, *args) -> None:
        try:
            self.log(msg % (args,))
        except Exception as e:
            self.log(f"error logging message: {e}")

    def td(self, d) -> typedict:
        d = typedict(d)
        # override warning method so that we don't corrupt the curses output
        d.warn = self.dictwarn
        return d

    def update_screen(self) -> None:
        self.modified = True

    def input_thread(self) -> None:
        self.log(f"input thread: signal handlers={signal.getsignal(signal.SIGINT)}")
        while self.exit_code is None:
            if not self.stdscr:
                sleep(0.1)
                continue
            if not self.paused and self.modified:
                self.stdscr.erase()
                try:
                    self.do_update_screen()
                except Exception as e:
                    self.err(e)
                finally:
                    self.stdscr.refresh()
                    self.modified = False
            try:
                curses.halfdelay(10)
                v = self.stdscr.getch()
            except Exception as e:
                self.log(f"getch() {e}")
                v = -1
            self.log(f"getch()={v}")
            if v == -1:
                continue
            if v in EXIT_KEYS:
                self.log(f"exit on key {v!r}")
                self.quit(0)
                break
            if v in SIGNAL_KEYS:
                self.log(f"exit on signal key {v!r}")
                self.quit(128 + SIGNAL_KEYS[v])
                break
            if v in PAUSE_KEYS:
                self.paused = not self.paused

    def do_update_screen(self) -> None:
        self.log("do_update_screen()")
        # c = self.stdscr.getch()
        # if c==curses.KEY_RESIZE:
        height, width = self.stdscr.getmaxyx()
        title = get_title()
        sli = self.server_last_info

        def _addstr(pad: int, py: int, px: int, s: str, *args) -> None:
            if len(s) + px >= width - pad:
                s = s[:max(0, width - px - 2 - pad)] + ".."
            self.stdscr.addstr(py, px, s, *args)

        def addstr_main(py: int, px: int, s: str, *args) -> None:
            _addstr(0, py, px, s, *args)

        def addstr_box(y: int, x: int, s: str, *args) -> None:
            _addstr(2, y, x, s, *args)

        try:
            x = max(0, width // 2 - len(title) // 2)
            addstr_main(0, x, title, curses.A_BOLD)
            if height <= 1:
                return
            server_info = self.slidictget("server")
            build = self.slidictget("server", "build")
            vstr = caps_to_version(build)
            mode = server_info.strget("mode", "server")
            python_info = self.td(server_info.dictget("python", {}))
            bits = python_info.intget("bits", 0)
            bitsstr = "" if bits == 0 else f" {bits}-bit"
            server_str = f"Xpra {mode} server version {vstr}{bitsstr}"
            proxy_info = self.slidictget("proxy")
            if proxy_info:
                proxy_platform_info = self.td(proxy_info.dictget("platform", {}))
                proxy_platform = proxy_platform_info.strget("")
                proxy_release = proxy_platform_info.strget("release")
                proxy_build_info = self.td(proxy_info.dictget("build", {}))
                proxy_version = proxy_build_info.strget("version")
                proxy_distro = proxy_info.strget("linux_distribution")
                server_str += " via: %s proxy version %s" % (
                    platform_name(proxy_platform, proxy_distro or proxy_release),
                    std(proxy_version or "unknown")
                )
            addstr_main(1, 0, server_str)
            if height <= 2:
                return
            # load and uptime:
            now = datetime.now()
            uptime = ""
            elapsed_time = server_info.intget("elapsed_time")
            if elapsed_time:
                td = timedelta(seconds=elapsed_time)
                uptime = " up " + str(td).lstrip("0:")
            clients_info = self.slidictget("clients")
            nclients = clients_info.intget("")
            load_average = ""
            load = sli.inttupleget("load")
            if load and len(load) == 3:
                float_load = tuple(v / 1000.0 for v in load)
                load_average = ", load average: %1.2f, %1.2f, %1.2f" % float_load
            addstr_main(2, 0, "xpra top - %s%s, %2i users%s" % (
                now.strftime("%H:%M:%S"), uptime, nclients, load_average))
            if height <= 3:
                return
            thread_info = self.slidictget("threads")
            thread_count = thread_info.intget("count")
            rinfo = f"{thread_count} threads"
            server_pid = server_info.intget("pid", 0)
            if server_pid:
                rinfo += f", pid {server_pid}"
                machine_id = server_info.get("machine-id")
                if machine_id is None or machine_id == get_machine_id():
                    try:
                        process = self.psprocess.get(server_pid)
                        if not process:
                            import psutil
                            process = psutil.Process(server_pid)
                            self.psprocess[server_pid] = process
                        else:
                            cpu = process.cpu_percent()
                            rinfo += f", {cpu:3}% CPU"
                    except Exception:
                        pass
            cpuinfo = self.slidictget("cpuinfo")
            if cpuinfo:
                rinfo += ", " + cpuinfo.strget("hz_actual")
            elapsed = monotonic() - self.server_last_info_time
            color = WHITE
            if self.server_last_info_time == 0:
                rinfo += " - no server data"
            elif elapsed > 2:
                rinfo += f" - last updated {elapsed} seconds ago"
                color = RED
            addstr_main(3, 0, rinfo, curses.color_pair(color))
            if height <= 4:
                return
            # display:
            dinfo = []
            server = self.slidictget("server")
            rws = server.intpair("root_window_size", None)
            display_info = self.slidictget("display")
            if rws:
                rww, rwh = rws
                sinfo = f"{rww}x{rwh}"
                depth = display_info.intget("depth")
                if depth > 0:
                    sinfo += f" {depth}-bit"
                sinfo += " display"
                mds = server.intpair("max_desktop_size")
                if mds:
                    mdw, mdh = mds
                    sinfo += f" (max {mdw}x{mdh})"
                dinfo.append(sinfo)
            cursor_info = self.slidictget("cursor")
            if cursor_info:
                cx, cy = cursor_info.inttupleget("position", (0, 0))
                dinfo.append(f"cursor at {cx}x{cy}")
            pid = display_info.intget("pid")
            if pid:
                dinfo.append(f"pid {pid}")
            addstr_main(4, 0, csv(dinfo))
            if height <= 5:
                return
            hpos = 5
            gl_info = self.get_gl_info(display_info.dictget("opengl"))
            if gl_info:
                addstr_main(5, 0, gl_info)
                hpos += 1

            # filter clients, only show GUI clients:
            client_info = self.slidictget("client")
            gui_clients = []
            nclients = 0
            while True:
                if nclients not in client_info:
                    break
                ci = self.td(client_info.dictget(nclients))
                session_id = ci.strget("session-id")
                if session_id != self.session_id and ci.boolget("windows", True) and ci.strget("type") != "top":
                    gui_clients.append(nclients)
                nclients += 1

            ngui = 0
            if hpos < height - 3:
                hpos += 1
                if nclients == 0:
                    clients_str = "no clients connected"
                else:
                    ngui = len(gui_clients)
                    clients_str = f"{nclients} clients connected, "
                    if ngui == 0:
                        clients_str += "no gui clients"
                    else:
                        clients_str += f"{ngui} gui clients:"
                addstr_main(hpos, 0, clients_str)
                hpos += 1
            for client_index, client_no in enumerate(gui_clients):
                ci = client_info.dictget(client_no)
                assert ci
                ci = self.get_client_info(self.td(ci))
                nlines = len(ci)
                if hpos + 2 + nlines > height:
                    if hpos < height:
                        more = ngui - client_index
                        addstr_box(hpos, 0, f"{more} clients not shown", curses.A_BOLD)
                    break
                self.box(1, hpos, width - 2, 2 + nlines)
                for i, info in enumerate(ci):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    addstr_box(hpos + i + 1, 2, info_text, cpair)
                hpos += 2 + nlines

            windows = self.slidictget("windows")
            if hpos < height - 3:
                hpos += 1
                addstr_main(hpos, 0, f"{len(windows)} windows:")
                hpos += 1
            wins = tuple(windows.values())
            nwindows = len(wins)
            for win_no, win in enumerate(wins):
                wi = get_window_info(self.td(win))
                nlines = len(wi)
                if hpos + 2 + nlines > height:
                    if hpos < height:
                        more = nwindows - win_no
                        addstr_main(hpos, 0,
                                    f"terminal window is too small: {more} windows not shown",
                                    curses.A_BOLD)
                    break
                self.box(1, hpos, width - 2, 2 + nlines)
                for i, info in enumerate(wi):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    addstr_box(hpos + i + 1, 2, info_text, cpair)
                hpos += 2 + nlines
        except Exception as e:
            self.err(e)

    def slidictget(self, *parts) -> typedict:
        return self.dictget(self.server_last_info, *parts)

    def dictget(self, dictinstance, *parts) -> typedict:
        d = dictinstance
        for part in parts:
            d = self.td(d.dictget(part, {}))
        return d

    def get_client_info(self, ci: typedict) -> tuple:
        # version info:
        ctype = ci.strget("type", "unknown")
        title = f"{ctype} client version "
        title += caps_to_version(ci)
        chost = ci.strget("hostname")
        conn_info = ""
        if chost:
            conn_info = f"connected from {chost} "
        cinfo = ci.dictget("connection")
        if cinfo:
            cinfo = self.td(cinfo)
            conn_info += "using %s %s" % (cinfo.strget("type"), cinfo.strget("protocol-type"))
            conn_info += ", with %s and %s" % (cinfo.strget("encoder"), cinfo.strget("compressor"))
        gl_info = self.get_gl_info(ci.dictget("opengl"))
        # audio
        audio_info = []
        for mode in ("speaker", "microphone"):
            audio_info.append(self._audio_info(ci, mode))
        audio_info.append(self._avsync_info(ci))
        # batch delay / latency:
        b_info = self.td(ci.dictget("batch", {}))
        bi_info = self.td(b_info.dictget("delay", {}))
        bcur = bi_info.intget("cur")
        bavg = bi_info.intget("avg")
        batch_info = f"batch delay: {bcur} ({bavg})"
        # client latency:
        pl = self.dictget(ci, "connection", "client", "ping_latency")
        lcur = pl.intget("cur")
        lavg = pl.intget("avg")
        lmin = pl.intget("min")
        bl_color = GREEN
        if bcur > 50 or (lcur > 20 and lcur > 2 * lmin):
            bl_color = YELLOW
        elif bcur > 100 or (lcur > 20 and lcur > 3 * lmin):
            bl_color = RED
        batch_latency = batch_info.ljust(24) + f"latency: {lcur} ({lavg})"
        # speed / quality:
        edict = self.td(ci.dictget("encoding") or {})
        qs_info = ""
        qs_color = GREEN
        if edict:
            sinfo = self.td(edict.dictget("speed") or {})
            if sinfo:
                cur = sinfo.intget("cur")
                avg = sinfo.intget("avg")
                qs_info = f"speed: {cur}% (avg: f{avg}%)"
            qinfo = self.td(edict.dictget("quality") or {})
            if qinfo:
                qs_info = qs_info.ljust(24)
                cur = qinfo.intget("cur")
                avg = qinfo.intget("avg")
                qs_info += f"quality: {cur}% (avg: {avg}%)"
                if avg < 70:
                    qs_color = YELLOW
                if avg < 50:
                    qs_color = RED
        str_color = [
            (title, WHITE),
            (conn_info, WHITE),
            (gl_info, WHITE),
            (csv(audio_info), WHITE),
            (batch_latency, bl_color),
            (qs_info, qs_color),
        ]
        return tuple((s, c) for s, c in str_color if s)

    def _audio_info(self, ci, mode="speaker") -> str:
        minfo = self.dictget(ci, "audio", mode) or self.dictget(ci, "sound", mode)
        if not minfo:
            return f"{mode} off"
        minfo = self.td(minfo)
        descr = minfo.strget("codec_description") or minfo.strget("codec") or minfo.strget("state", "unknown")
        audio_info = f"{mode}: {descr}"
        bitrate = minfo.intget("bitrate")
        if bitrate:
            audio_info += f" {std_unit(bitrate)}bps"
        return audio_info

    def _avsync_info(self, ci) -> str:
        avsf = self.slidictget("features", "av-sync")
        if not avsf or not avsf.boolget("", False):
            return "av-sync: not supported by server"
        if not avsf.boolget("enabled", False):
            return "av-sync: disabled by server"
        # client specific attributes:
        avsi = self.dictget(ci, "av-sync")
        if not avsi.boolget("", False):
            return "av-sync: disabled by client"
        return "av-sync: enabled - video delay: %ims" % (avsi.intget("total", 0))

    def get_gl_info(self, gli) -> str:
        if not gli:
            return ""
        gli = self.td(gli)

        def strget(key: str, sep=".") -> str:
            # fugly warning:
            # depending on where we get the gl info from,
            # the value might be a list of strings,
            # or a byte string...
            v = gli.get(key)
            if isinstance(v, (tuple, list)):
                return sep.join(str(x) for x in v)
            return bytestostr(v)

        if not gli.boolget("enabled", True):
            return "OpenGL disabled " + gli.strget("message")
        gl_info = "OpenGL %s enabled: %s" % (strget("opengl", "."), gli.strget("renderer") or gli.strget("vendor"))
        depth = gli.intget("depth")
        if depth not in (0, 24):
            gl_info += f", {depth}bits"
        modes = gli.get("display_mode")
        if modes:
            gl_info += " - " + strget("display_mode", ", ")
        return gl_info

    def box(self, x, y, w, h) -> None:
        box(self.stdscr, x, y, w, h,
            ul=curses.ACS_ULCORNER, ur=curses.ACS_URCORNER,  # @UndefinedVariable
            ll=curses.ACS_LLCORNER, lr=curses.ACS_LRCORNER)  # @UndefinedVariable
