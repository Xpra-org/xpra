# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import curses
from datetime import datetime, timedelta

from xpra import __version__
from xpra.util import typedict, std, envint, csv, engs
from xpra.os_util import platform_name, bytestostr
from xpra.client.gobject_client_base import MonitorXpraClient
from xpra.log import Logger

log = Logger("gobject", "client")

REFRESH_RATE = envint("XPRA_REFRESH_RATE", 1)

WHITE = 0
GREEN = 1
YELLOW = 2
RED = 3

class TopClient(MonitorXpraClient):

    def __init__(self, *args):
        MonitorXpraClient.__init__(self, *args)
        self.info_request_pending = False
        self.server_last_info = typedict()
        #curses init:
        self.stdscr = curses.initscr()
        self.stdscr.keypad(True)
        self.stdscr.nodelay(True)
        self.stdscr.clear()
        curses.noecho()
        curses.cbreak()
        curses.start_color()
        curses.use_default_colors()
        #for i in range(0, curses.COLORS):
        #    curses.init_pair(i+1, i, -1)
        curses.init_pair(WHITE, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(RED, curses.COLOR_RED, curses.COLOR_BLACK)
        self.update_screen()

    def cleanup(self):
        MonitorXpraClient.cleanup(self)
        self.stdscr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    def update_screen(self):
        self.stdscr.erase()
        try:
            self.do_update_screen()
        finally:
            self.stdscr.refresh()

    def do_update_screen(self):
        #c = self.stdscr.getch()
        #if c==curses.KEY_RESIZE:
        height, width = self.stdscr.getmaxyx()
        #log.info("update_screen() %ix%i", height, width)
        title = "Xpra top %s" % __version__
        try:
            from xpra.src_info import REVISION, LOCAL_MODIFICATIONS
            title += "-r%s" % REVISION
            if LOCAL_MODIFICATIONS:
                title += "M"
        except ImportError:
            pass
        x = max(0, width//2-len(title)//2)
        sli = self.server_last_info
        try:
            self.stdscr.addstr(0, x, title, curses.A_BOLD)
            if height<=1:
                return
            server_info = self.dictget("server")
            build = self.dictget("build")
            v = build.strget("version")
            revision = build.strget("revision")
            if v and revision:
                v = " version %s-r%s" % (v, revision)
            mode = server_info.strget("mode", "server")
            python_info = typedict(server_info.dictget("python", {}))
            bits = python_info.intget("bits", 32)
            server_str = "Xpra %s server%s %i-bit" % (mode, std(v), bits)
            proxy_info = self.dictget("proxy")
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
            self.stdscr.addstr(1, 0, server_str)
            if height<=2:
                return
            #load and uptime:
            now = datetime.now()
            uptime = ""
            elapsed_time = server_info.intget("elapsed_time")
            if elapsed_time:
                td = timedelta(seconds=elapsed_time)
                uptime = " up %s" % str(td).lstrip("0:")
            clients_info = self.dictget("clients")
            nclients = clients_info.intget("")
            load_average = ""
            load = sli.intlistget("load")
            if load and len(load)==3:
                float_load = tuple(v/1000.0 for v in load)
                load_average = ", load average: %1.2f, %1.2f, %1.2f" % float_load
            self.stdscr.addstr(2, 0, "xpra top - %s%s, %2i users%s" % (
                               now.strftime("%H:%M:%S"), uptime, nclients, load_average))
            if height<=3:
                return
            thread_info = self.dictget("threads")
            self.stdscr.addstr(3, 0, "%i threads" % thread_info.intget("count"))
            if height<=4:
                return
            #cursor:
            cursor_info = self.dictget("cursor")
            cx, cy = cursor_info.intlistget("position", (0, 0))
            self.stdscr.addstr(4, 0, "cursor at %ix%i" % (cx, cy))
            if height<=5:
                return

            hpos = 6
            client_info = self.dictget("client")
            client_no = 0
            while True:
                ci = client_info.dictget(client_no)
                if not ci:
                    break
                client_no +=1
                ci = typedict(ci)
                if not ci.boolget("windows", True):
                    continue
                ci = self.get_client_info(ci)
                l = len(ci)
                if hpos+2+l>height:
                    if hpos<height:
                        more = nclients-client_no
                        self.stdscr.addstr(hpos, 0, "%i client%s not shown" % (more, engs(more)), curses.A_BOLD)
                    break
                self.box(self.stdscr, 1, hpos, width-2, 2+l)
                for i, info in enumerate(ci):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    self.stdscr.addstr(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l

            windows = self.dictget("windows")
            if hpos<height-3:
                hpos += 1
                self.stdscr.addstr(hpos, 0, "%i windows" % len(windows))
                hpos += 1
            wins = tuple(windows.values())
            nwindows = len(wins)
            for win_no, win in enumerate(wins):
                wi = self.get_window_info(typedict(win))
                l = len(wi)
                if hpos+2+l>height:
                    if hpos<height:
                        more = nwindows-win_no
                        self.stdscr.addstr(hpos, 0, "terminal window is too small: %i window%s not shown" % (more, engs(more)), curses.A_BOLD)
                    break
                self.box(self.stdscr, 1, hpos, width-2, 2+l)
                for i, info in enumerate(wi):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    self.stdscr.addstr(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l
        except Exception as e:
            import traceback
            self.stdscr.addstr(0, 0, str(e))
            self.stdscr.addstr(0, 1, traceback.format_exc())

    def dictget(self, *parts):
        d = self.server_last_info
        while parts:
            d = typedict(d.dictget(parts[0], {}))
            parts = parts[1:]
        return d

    def get_client_info(self, ci):
        #version info:
        ctype = ci.strget("type", "unknown")
        title = "%s client version %s-r%s" % (ctype, ci.strget("version"), ci.strget("revision"))
        #batch delay:
        b_info = typedict(ci.dictget("batch", {}))
        bi_info = typedict(b_info.dictget("delay", {}))
        bcur = bi_info.intget("cur")
        bavg = bi_info.intget("avg")
        batch_info = "batch delay: %i (%i)" %(
            bcur,
            bavg,
            )
        bcolor = GREEN
        if bcur>50:
            bcolor = YELLOW
        elif bcur>100:
            bcolor = RED
        #client latency:
        pl = self.dictget("connection", "client", "ping_latency")
        lcur = pl.intget("cur")
        lavg = pl.intget("avg")
        lmin = pl.intget("min")
        latency_info = "latency: %i (%i)" % (lcur, lavg)
        lcolor = GREEN
        if lcur>20:
            if lcur>2*lmin:
                lcolor = YELLOW
            elif lcur>3*lmin:
                lcolor = RED
        return (
            (title, WHITE),
            (batch_info, bcolor),
            (latency_info, lcolor),
            )

    def get_window_info(self, wi):
        #version info:
        geom = tuple(wi.intlistget("geometry"))
        g_str = "%ix%i at %i,%i" % (geom[2], geom[3], geom[0], geom[1])
        sc = wi.dictget("size-constraints")
        if sc:
            g_str += " - %s" % csv("%s=%s" % (bytestostr(k), v) for k,v in sc.items())
        title = wi.strget("title", "")
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
        info = (title, g_str, csv(attrs), csv(wi.strlistget("window-type", ("NORMAL",))))
        return tuple((x, WHITE) for x in info if x)

    def box(self, window, x, y, w, h):
        window.hline(y, x, curses.ACS_HLINE, w-1)               #@UndefinedVariable
        window.hline(y + h - 1, x, curses.ACS_HLINE, w - 1)     #@UndefinedVariable
        window.vline(y, x, curses.ACS_VLINE, h)                 #@UndefinedVariable
        window.vline(y, x + w -1, curses.ACS_VLINE, h)          #@UndefinedVariable
        window.addch(y, x, curses.ACS_ULCORNER)                 #@UndefinedVariable
        window.addch(y, x + w - 1, curses.ACS_URCORNER)         #@UndefinedVariable
        window.addch(y + h - 1, x, curses.ACS_LLCORNER)         #@UndefinedVariable
        window.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER) #@UndefinedVariable


    def do_command(self):
        self.send_info_request()
        self.timeout_add(REFRESH_RATE*1000, self.send_info_request)

    def send_info_request(self):
        categories = ()
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = ()    #no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)
        return True

    def init_packet_handlers(self):
        MonitorXpraClient.init_packet_handlers(self)
        self.add_packet_handler("info-response", self._process_info_response, False)

    def _process_server_event(self, packet):
        self.last_server_event = packet[1:]
        self.update_screen()

    def _process_info_response(self, packet):
        self.info_request_pending = False
        self.server_last_info = typedict(packet[1])
        #log.info("server_last_info=%s", self.server_last_info)
        self.update_screen()
