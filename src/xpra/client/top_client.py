# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import curses
from datetime import datetime, timedelta

from xpra import __version__
from xpra.util import typedict, std, envint, csv, engs
from xpra.os_util import platform_name, bytestostr, monotonic_time
from xpra.client.gobject_client_base import MonitorXpraClient
from xpra.simple_stats import std_unit
from xpra.common import GRAVITY_STR
from xpra.log import Logger

log = Logger("gobject", "client")

REFRESH_RATE = envint("XPRA_REFRESH_RATE", 1)

WHITE = 0
GREEN = 1
YELLOW = 2
RED = 3

def get_title():
    title = "Xpra top %s" % __version__
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS
        title += "-r%s" % REVISION
        if LOCAL_MODIFICATIONS:
            title += "M"
    except ImportError:
        pass
    return title

def curses_init():
    stdscr = curses.initscr()
    stdscr.keypad(True)
    stdscr.nodelay(True)
    stdscr.clear()
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
    return stdscr

def curses_clean(stdscr):
    stdscr.keypad(False)
    curses.nocbreak()
    curses.echo()
    curses.endwin()

def curses_err(stdscr, e):
    import traceback
    stdscr.addstr(0, 0, str(e))
    for i, l in enumerate(traceback.format_exc().split("\n")):
        try:
            stdscr.addstr(0, i+1, l)
        except Exception:
            pass


class TopClient(MonitorXpraClient):

    def __init__(self, *args):
        super().__init__(*args)
        self.info_request_pending = False
        self.server_last_info = typedict()
        self.server_last_info_time = 0
        self.info_timer = 0
        self.stdscr = curses_init()
        self.update_screen()

    def cleanup(self):
        self.cancel_info_timer()
        MonitorXpraClient.cleanup(self)
        curses_clean(self.stdscr)

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
        title = get_title()
        x = max(0, width//2-len(title)//2)
        sli = self.server_last_info
        try:
            self.stdscr.addstr(0, x, title, curses.A_BOLD)
            if height<=1:
                return
            server_info = self.slidictget("server")
            build = self.slidictget("build")
            v = build.strget("version")
            revision = build.strget("revision")
            if v and revision:
                v = " version %s-r%s" % (v, revision)
            mode = server_info.strget("mode", "server")
            python_info = typedict(server_info.dictget("python", {}))
            bits = python_info.intget("bits", 32)
            server_str = "Xpra %s server%s %i-bit" % (mode, std(v), bits)
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
            clients_info = self.slidictget("clients")
            nclients = clients_info.intget("")
            load_average = ""
            load = sli.inttupleget("load")
            if load and len(load)==3:
                float_load = tuple(v/1000.0 for v in load)
                load_average = ", load average: %1.2f, %1.2f, %1.2f" % float_load
            self.stdscr.addstr(2, 0, "xpra top - %s%s, %2i users%s" % (
                               now.strftime("%H:%M:%S"), uptime, nclients, load_average))
            if height<=3:
                return
            thread_info = self.slidictget("threads")
            rinfo = "%i threads" % thread_info.intget("count")
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
            self.stdscr.addstr(3, 0, rinfo, curses.color_pair(color))
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
            self.stdscr.addstr(4, 0, csv(dinfo))
            if height<=5:
                return
            hpos = 5
            gl_info = self.get_gl_info(self.slidictget("opengl"))
            if gl_info:
                self.stdscr.addstr(5, 0, gl_info)
                hpos += 1

            if hpos<height-3:
                hpos += 1
                if nclients==0:
                    self.stdscr.addstr(hpos, 0, "no clients connected")
                else:
                    self.stdscr.addstr(hpos, 0, "%i client%s connected:" % (nclients, engs(nclients)))
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
                        self.stdscr.addstr(hpos, 0, "%i client%s not shown" % (more, engs(more)), curses.A_BOLD)
                    break
                self.box(self.stdscr, 1, hpos, width-2, 2+l)
                for i, info in enumerate(ci):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    self.stdscr.addstr(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l

            windows = self.slidictget("windows")
            if hpos<height-3:
                hpos += 1
                self.stdscr.addstr(hpos, 0, "%i window%s:" % (len(windows), engs(windows)))
                hpos += 1
            wins = tuple(windows.values())
            nwindows = len(wins)
            for win_no, win in enumerate(wins):
                wi = self.get_window_info(typedict(win))
                l = len(wi)
                if hpos+2+l>height:
                    if hpos<height:
                        more = nwindows-win_no
                        self.stdscr.addstr(hpos, 0, "terminal window is too small: %i window%s not shown" % \
                                           (more, engs(more)), curses.A_BOLD)
                    break
                self.box(self.stdscr, 1, hpos, width-2, 2+l)
                for i, info in enumerate(wi):
                    info_text, color = info
                    cpair = curses.color_pair(color)
                    self.stdscr.addstr(hpos+i+1, 2, info_text, cpair)
                hpos += 2+l
        except Exception as e:
            curses_err(self.stdscr, e)

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
        title = "%s client version %s-r%s" % (ctype, ci.strget("version"), ci.strget("revision"))
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
        pl = self.slidictget("connection", "client", "ping_latency")
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
        audio_info = []
        for mode in ("speaker", "microphone"):
            audio_info.append(self._audio_info(ci, mode))
        audio_info.append(self._avsync_info(ci))
        return tuple((s, c) for s,c in (
            (title, WHITE),
            (conn_info, WHITE),
            (gl_info, WHITE),
            (csv(audio_info), WHITE),
            (batch_info, bcolor),
            (latency_info, lcolor),
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
        wtype = wi.strtupleget("window-type", ("NORMAL",))
        tinfo = " - ".join(csv(x) for x in (wtype, attrs) if x)
        info = (title, g_str, tinfo)
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
            return "OpenGL disabled %s" % gli.strget("message")
        gl_info = "OpenGL %s enabled: %s" % (strget("opengl"), gli.strget("renderer") or gli.strget("vendor"))
        depth = gli.intget("depth")
        if depth not in (0, 24):
            gl_info += ", %ibits" % depth
        modes = gli.rawget("display_mode")
        if modes:
            gl_info += " - %s" % strget("display_mode", ", ")
        return gl_info

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
        if not self.info_timer:
            self.info_timer = self.timeout_add(REFRESH_RATE+2, self.info_timeout)
        return True

    def init_packet_handlers(self):
        MonitorXpraClient.init_packet_handlers(self)
        self.add_packet_handler("info-response", self._process_info_response, False)

    def _process_server_event(self, packet):
        self.last_server_event = packet[1:]
        self.update_screen()

    def _process_info_response(self, packet):
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
        self.update_screen()
        return True
