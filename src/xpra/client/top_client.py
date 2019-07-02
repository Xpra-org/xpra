# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import curses
from datetime import datetime, timedelta

from xpra import __version__
from xpra.util import typedict, std
from xpra.os_util import platform_name
from xpra.client.gobject_client_base import MonitorXpraClient
from xpra.log import Logger

log = Logger("gobject", "client")

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
        #c = self.stdscr.getch()
        #if c==curses.KEY_RESIZE:
        self.stdscr.clear()
        _, width = self.stdscr.getmaxyx()
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
            #server info:
            #self.stdscr.addstr(3, 0, str(sli.get("build")))
            v = sli.strget("server.build.version")
            revision = sli.strget("server.build.revision")
            if v and revision:
                v = " version %s-r%s" % (v, revision)
            mode = sli.strget("server.mode", "server")
            bits = sli.intget("server.python.bits", 32)
            server_str = "Xpra %s server%s %i-bit" % (mode, std(v), bits)
            if sli.boolget("proxy"):
                proxy_platform = sli.strget("proxy.platform")
                proxy_release = sli.strget("proxy.platform.release")
                proxy_version = sli.strget("proxy.version")
                proxy_version = sli.strget("proxy.build.version", proxy_version)
                proxy_distro = sli.strget("proxy.linux_distribution")
                server_str += " via: %s proxy version %s" % (
                    platform_name(proxy_platform, proxy_distro or proxy_release),
                    std(proxy_version or "unknown")
                    )
            self.stdscr.addstr(1, 0, server_str)
            #load and uptime:
            now = datetime.now()
            uptime = ""
            elapsed_time = sli.intget("server.elapsed_time")
            if elapsed_time:
                td = timedelta(seconds=elapsed_time)
                uptime = " up %s" % str(td).lstrip("0:")
            nclients = sli.intget("clients")
            load_average = ""
            load = sli.intlistget("load")
            if load and len(load)==3:
                float_load = tuple(v/1000.0 for v in load)
                load_average = ", load average: %1.2f, %1.2f, %1.2f" % float_load
            self.stdscr.addstr(2, 0, "xpra top - %s%s, %2i users%s" % (
                               now.strftime("%H:%M:%S"), uptime, nclients, load_average))
            self.stdscr.addstr(3, 0, "%i threads" % sli.intget("threads.count"))
            #cursor:
            cx, cy = sli.intlistget("cursor.position", (0, 0))
            self.stdscr.addstr(4, 0, "cursor at %ix%i" % (cx, cy))
            #todo: show clipboard state

            hpos = 6
            for client_no in range(nclients):
                if nclients>1:
                    prefix = ".%s" % client_no
                else:
                    prefix = ""
                ci = self.get_client_info(prefix)
                l = len(ci)
                self.box(self.stdscr, 1, hpos, width-2, 2+l)
                for i, info in enumerate(ci):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    self.stdscr.addstr(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l
        except Exception:
            log.error("update_screen()", exc_info=True)
        self.stdscr.refresh()

    def get_client_info(self, prefix):
        cp = "client%s." % prefix
        sli = self.server_last_info
        #version info:
        ctype = sli.strget(cp+"type", "unknown")
        title = "%s client version %s-r%s" % (ctype, sli.strget(cp+"version"), sli.intget(cp+"revision"))
        #batch delay:
        bprefix = cp+"batch.delay."
        bcur = sli.intget(bprefix+"cur")
        bavg = sli.intget(bprefix+"avg")
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
        lprefix = cp+"connection.client.ping_latency."
        lcur = sli.intget(lprefix+"cur")
        lavg = sli.intget(lprefix+"avg")
        lmin = sli.intget(lprefix+"min")
        latency_info = "latency: %i (%i)" % (lcur, lavg)
        lcolor = GREEN
        if lcur>20:
            if lcur>2*lmin:
                lcolor = YELLOW
            elif lcur>3*lmin:
                lcolor = RED
        return [
            (title, WHITE),
            (batch_info, bcolor),
            (latency_info, lcolor),
            ]

    def box(self, window, x, y, w, h):
        window.hline(y, x, curses.ACS_HLINE, w-1)
        window.hline(y + h - 1, x, curses.ACS_HLINE, w - 1)
        window.vline(y, x, curses.ACS_VLINE, h)
        window.vline(y, x + w -1, curses.ACS_VLINE, h)
        window.addch(y, x, curses.ACS_ULCORNER)
        window.addch(y, x + w - 1, curses.ACS_URCORNER)
        window.addch(y + h - 1, x, curses.ACS_LLCORNER)
        window.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)


    def do_command(self):
        self.send_info_request()
        self.timeout_add(1000, self.send_info_request)

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
