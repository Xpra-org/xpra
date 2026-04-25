# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen, PIPE, DEVNULL
from datetime import datetime, timedelta
from time import monotonic

from xpra.os_util import gi_import, get_machine_id
from xpra.util.version import caps_to_version, full_version_str
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, bytestostr, std
from xpra.util.env import envint
from xpra.util.thread import start_thread
from xpra.util.stats import std_unit
from xpra.util.system import platform_name
from xpra.common import gravity_str
from xpra.net.constants import SocketState
from xpra.platform.dotxpra import DotXpra
from xpra.platform.paths import get_nodock_command, get_socket_dirs
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.client.base.command import InfoTimerClient
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("gtk", "client")

REFRESH_RATE = envint("XPRA_REFRESH_RATE", 1)

WHITE = "black"
GREEN = "#00aa00"
YELLOW = "#aaaa00"
RED = "#cc0000"


def get_title() -> str:
    return f"Xpra top {full_version_str()}"


def colored_label(text: str, color: str = WHITE) -> Gtk.Label:
    lbl = Gtk.Label()
    lbl.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(text)}</span>')
    lbl.set_xalign(0)
    lbl.set_selectable(True)
    return lbl


def section_frame(title: str) -> tuple[Gtk.Frame, Gtk.VBox]:
    frame = Gtk.Frame()
    frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
    lbl = Gtk.Label()
    lbl.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    frame.set_label_widget(lbl)
    vbox = Gtk.VBox(homogeneous=False, spacing=2)
    vbox.set_margin_start(6)
    vbox.set_margin_end(6)
    vbox.set_margin_top(2)
    vbox.set_margin_bottom(4)
    frame.add(vbox)
    return frame, vbox


class TopGUI(BaseGUIWindow):
    """
    GTK dialog showing local xpra sessions — equivalent to the curses TopClient.
    Displays discovered sessions with state, uuid and type, and lets the user
    attach, detach or stop a selected session.
    """

    def __init__(self, opts=None):
        self.opts = opts
        socket_dirs = getattr(opts, "socket_dirs", None) or get_socket_dirs()
        socket_dir = getattr(opts, "socket_dir", None) or ""
        self.dotxpra = DotXpra(socket_dir, socket_dirs)
        self.selected_display: str | None = None
        self.psprocess: dict[int, object] = {}
        self._refresh_timer = 0
        self._last_display_items: frozenset = frozenset()
        self._screenshots: dict[str, bytes] = {}       # session_key -> png bytes
        self._screenshot_pending: set[str] = set()     # session_keys being captured
        self._screenshot_times: dict[str, float] = {}  # session_key -> capture time
        self._screenshot_widgets: dict[str, Gtk.Image] = {}  # session_key -> live Gtk.Image
        self._session_paths: dict[str, str] = {}       # session_key -> socket path
        super().__init__(
            title=get_title(),
            icon_name="xpra.png",
            wm_class=("xpra-top", "Xpra-Top"),
            default_size=(700, 400),
            header_bar=(True, False, False),
        )

    def populate(self) -> None:
        self.vbox.set_spacing(4)

        # session list in a scrolled window
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        sw.add(self.listbox)
        self.vbox.pack_start(sw, True, True, 0)

        # action buttons
        self._action_buttons: list[Gtk.Button] = []
        hbox = Gtk.HBox(homogeneous=True, spacing=6)
        for label, cb in (
            ("Attach", self._attach),
            ("Detach", self._detach),
            ("Stop", self._stop),
        ):
            btn = Gtk.Button.new_with_label(label)
            btn.connect("clicked", cb)
            btn.set_sensitive(False)
            hbox.pack_start(btn, True, True, 0)
            self._action_buttons.append(btn)
        self.vbox.pack_start(hbox, False, False, 0)

        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
        self._refresh_timer = GLib.timeout_add(REFRESH_RATE * 1000, self._refresh)

    def _refresh(self) -> bool:
        sd = self.dotxpra.socket_details()
        displays: dict[str, list] = {}
        for sessions in sd.values():
            for state, display, path in sessions:
                displays.setdefault(display, []).append((state, path))
        display_items = frozenset(
            (display, state, path)
            for display, state_paths in displays.items()
            for state, path in state_paths
        )
        if display_items != self._last_display_items:
            self._rebuild_list(displays)
        else:
            self._refresh_screenshots()
        self._refresh_timer = GLib.timeout_add(REFRESH_RATE * 1000, self._refresh)
        return False

    def _refresh_screenshots(self) -> None:
        now = monotonic()
        for session_key, img in list(self._screenshot_widgets.items()):
            last = self._screenshot_times.get(session_key, 0)
            if now - last >= 10 and session_key not in self._screenshot_pending:
                path = self._session_paths.get(session_key)
                if path:
                    self._request_screenshot(session_key, path, img)

    def _rebuild_list(self, displays: dict[str, list]) -> None:
        self._last_display_items = frozenset(
            (display, state, path)
            for display, state_paths in displays.items()
            for state, path in state_paths
        )
        self._screenshot_widgets.clear()

        # preserve selection
        selected = self.selected_display

        for row in self.listbox.get_children():
            self.listbox.remove(row)

        if not displays:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label="No sessions found"))
            self.listbox.add(row)
            self.listbox.show_all()
            return

        for display, state_paths in displays.items():
            row = Gtk.ListBoxRow()
            row.display = display
            frame, vbox = section_frame(display)

            uuid = ""
            live_path = ""
            for state, path in state_paths:
                if state != SocketState.LIVE:
                    vbox.add(colored_label(f"{path}  :  {state}"))
                    continue
                d = self._get_display_id_info(path)
                if not uuid:
                    # first live socket: extract session identity
                    uuid = d.get("uuid", "")
                    live_path = path
                    if err := d.get("error"):
                        frame.set_label(f"{display}  {err}")
                    else:
                        name = d.get("session-name", "")
                        stype = d.get("session-type", "")
                        frame.set_label(f"{display}  {name}")
                        vbox.add(colored_label(f"uuid={uuid}, type={stype}"))
                # additional live sockets for the same session: skip (same uuid)

            if live_path:
                session_key = uuid or live_path
                img = Gtk.Image()
                self._screenshot_widgets[session_key] = img
                self._session_paths[session_key] = live_path
                if session_key in self._screenshots:
                    self._load_screenshot_into(session_key, img)
                elif session_key not in self._screenshot_pending:
                    self._request_screenshot(session_key, live_path, img)
                vbox.add(img)

            row.add(frame)
            self.listbox.add(row)

            if display == selected:
                self.listbox.select_row(row)

        self.listbox.show_all()

    def _get_display_id_info(self, path: str) -> dict:
        d = {}
        try:
            cmd = get_nodock_command() + ["id", f"socket://{path}"]
            proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
            out, err = proc.communicate(timeout=3)
            for line in (out or err).splitlines():
                try:
                    k, v = line.split("=", 1)
                    d[k] = v
                except ValueError:
                    continue
        except Exception as e:
            d["error"] = str(e)
        return d

    def _request_screenshot(self, session_key: str, path: str, img: Gtk.Image) -> None:
        self._screenshot_pending.add(session_key)

        def _take() -> None:
            # `xpra screenshot - <socket>` writes PNG data to stdout
            cmd = get_nodock_command() + ["screenshot", "-", f"socket://{path}"]
            data = b""
            try:
                proc = Popen(cmd, stdout=PIPE, stderr=DEVNULL)
                out, _ = proc.communicate(timeout=10)
                if proc.returncode == 0:
                    data = out or b""
            except Exception as e:
                log("screenshot failed for %s: %s", path, e)
            GLib.idle_add(_done, data)

        def _done(data: bytes) -> None:
            self._screenshot_pending.discard(session_key)
            self._screenshot_times[session_key] = monotonic()
            if data:
                self._screenshots[session_key] = data
                self._load_screenshot_into(session_key, img)

        start_thread(_take, f"screenshot-{session_key}", daemon=True)

    def _load_screenshot_into(self, session_key: str, img: Gtk.Image) -> None:
        data = self._screenshots.get(session_key)
        if not data:
            return
        try:
            GdkPixbuf = gi_import("GdkPixbuf")
            Gio = gi_import("Gio")
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
            pb = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
            w, h = pb.get_width(), pb.get_height()
            max_w, max_h = 320, 180
            scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
            if scale < 1.0:
                pb = pb.scale_simple(int(w * scale), int(h * scale), GdkPixbuf.InterpType.BILINEAR)
            img.set_from_pixbuf(pb)
        except Exception as e:
            log("failed to load screenshot for %s: %s", session_key, e)

    def _cpu_str(self, pid: int) -> str:
        try:
            process = self.psprocess.get(pid)
            if not process:
                import psutil
                process = psutil.Process(pid)
                self.psprocess[pid] = process
                return ""
            cpu = process.cpu_percent()
            return f", {cpu:3.0f}% CPU"
        except Exception:
            return ""

    def _on_row_selected(self, _listbox, row) -> None:
        self.selected_display = getattr(row, "display", None) if row else None
        sensitive = bool(self.selected_display)
        for btn in self._action_buttons:
            btn.set_sensitive(sensitive)

    def _run_subcommand(self, subcommand: str) -> None:
        if not self.selected_display:
            return
        cmd = get_nodock_command() + [subcommand, self.selected_display]
        try:
            proc = Popen(cmd, stdout=DEVNULL, stderr=DEVNULL)
        except Exception as e:
            log.error("Error running %s: %s", subcommand, e)
            return
        from xpra.util.child_reaper import get_child_reaper
        get_child_reaper().add_process(proc, f"{subcommand}-{self.selected_display}", cmd, True, True)

    def _attach(self, *_args) -> None:
        self._run_subcommand("attach")

    def _detach(self, *_args) -> None:
        self._run_subcommand("detach")

    def _stop(self, *_args) -> None:
        self._run_subcommand("stop")

    def quit(self, *args) -> None:
        if self._refresh_timer:
            GLib.source_remove(self._refresh_timer)
            self._refresh_timer = 0
        self._screenshots.clear()
        super().quit(*args)


class TopSessionGUI(Gtk.Window):
    """
    GTK window showing live info about a connected xpra session —
    equivalent to the curses TopSessionClient.  Attach an InfoTimerClient
    as `client` and call update() whenever server_last_info is refreshed.
    """

    def __init__(self, client):
        super().__init__()
        self.client = client
        self.psprocess: dict[int, object] = {}

        self.set_title(get_title())
        self.set_default_size(740, 600)
        self.set_position(Gtk.WindowPosition.CENTER)
        from xpra.gtk.pixbuf import get_icon_pixbuf
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
        self.connect("delete-event", self._on_close)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._content = Gtk.VBox(homogeneous=False, spacing=4)
        self._content.set_margin_start(8)
        self._content.set_margin_end(8)
        self._content.set_margin_top(6)
        self._content.set_margin_bottom(6)
        sw.add(self._content)
        self.add(sw)

    def _on_close(self, *_args) -> bool:
        self.client.quit(0)
        return False

    def update(self) -> None:
        GLib.idle_add(self._rebuild)

    def _rebuild(self) -> None:
        for child in self._content.get_children():
            self._content.remove(child)

        c = self.client
        info = c.server_last_info

        def sldict(*parts) -> typedict:
            d = info
            for part in parts:
                d = typedict(d.dictget(part) or {})
            return d

        def td(d) -> typedict:
            return typedict(d) if d else typedict()

        # --- title row ---
        title_lbl = Gtk.Label()
        title_lbl.set_markup(f"<b><big>{GLib.markup_escape_text(get_title())}</big></b>")
        self._content.pack_start(title_lbl, False, False, 2)

        # --- server version ---
        server_info = sldict("server")
        build = sldict("server", "build")
        vstr = caps_to_version(build)
        mode = server_info.strget("mode", "server")
        python_info = td(server_info.dictget("python") or {})
        bits = python_info.intget("bits", 0)
        bitsstr = f" {bits}-bit" if bits else ""
        proxy_str = self._proxy_str(sldict("proxy"))
        server_str = f"Xpra {mode} server version {vstr}{bitsstr}{proxy_str}"
        self._content.pack_start(colored_label(server_str), False, False, 0)

        # --- summary line ---
        now = datetime.now()
        elapsed_time = server_info.intget("elapsed_time")
        uptime = ""
        if elapsed_time:
            uptime = " up " + str(timedelta(seconds=elapsed_time)).lstrip("0:")
        clients_info = sldict("clients")
        nclients = clients_info.intget("")
        load_average = ""
        load = info.inttupleget("load")
        if load and len(load) == 3:
            fl = tuple(v / 1000.0 for v in load)
            load_average = ", load average: %1.2f, %1.2f, %1.2f" % fl
        summary = "xpra top - %s%s, %2i users%s" % (now.strftime("%H:%M:%S"), uptime, nclients, load_average)
        self._content.pack_start(colored_label(summary), False, False, 0)

        # --- machine/threads line ---
        thread_info = sldict("threads")
        thread_count = thread_info.intget("count")
        rinfo = f"{thread_count} threads"
        server_pid = server_info.intget("pid", 0)
        if server_pid:
            rinfo += f", pid {server_pid}"
            machine_id = server_info.get("machine-id")
            if machine_id is None or machine_id == get_machine_id():
                cpu_str = self._cpu_str(server_pid)
                if cpu_str:
                    rinfo += cpu_str
        if cpuinfo := sldict("cpuinfo"):
            rinfo += ", " + cpuinfo.strget("hz_actual")
        elapsed = monotonic() - c.server_last_info_time
        color = WHITE
        if c.server_last_info_time == 0:
            rinfo += " - no server data"
            color = RED
        elif elapsed > 2:
            rinfo += f" - last updated {elapsed:.0f}s ago"
            color = RED
        self._content.pack_start(colored_label(rinfo, color), False, False, 0)

        # --- display line ---
        server = sldict("server")
        display_info = sldict("display")
        dparts = []
        rws = server.intpair("root_window_size", None)
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
            dparts.append(sinfo)
        if cursor_info := sldict("cursor"):
            cx, cy = cursor_info.inttupleget("position", (0, 0))
            dparts.append(f"cursor at {cx}x{cy}")
        if dpid := display_info.intget("pid"):
            dparts.append(f"pid {dpid}")
        if dparts:
            self._content.pack_start(colored_label(csv(dparts)), False, False, 0)

        # --- OpenGL ---
        if gl_str := self._gl_info(display_info.dictget("opengl")):
            self._content.pack_start(colored_label(gl_str), False, False, 0)

        # --- clients ---
        client_info = sldict("client")
        nclients_total = 0
        gui_clients = []
        while True:
            if nclients_total not in client_info:
                break
            ci = td(client_info.dictget(nclients_total))
            if ci.strget("session-id") != c.session_id and ci.boolget("windows", True) and ci.strget("type") != "top":
                gui_clients.append(nclients_total)
            nclients_total += 1

        ngui = len(gui_clients)
        clients_hdr = "".join((
            f"{nclients_total} clients connected, ",
            f"{ngui} gui clients:" if ngui else "no gui clients",
        ))
        self._content.pack_start(colored_label(clients_hdr), False, False, 4)

        for client_no in gui_clients:
            ci = td(client_info.dictget(client_no))
            lines = self._client_info_lines(ci, td)
            if not lines:
                continue
            ctype = ci.strget("type", "client")
            frame, fvbox = section_frame(ctype)
            for text, color in lines:
                fvbox.add(colored_label(text, color))
            self._content.pack_start(frame, False, False, 2)

        # --- windows ---
        windows = sldict("windows")
        wins = list(windows.values())
        self._content.pack_start(colored_label(f"{len(wins)} windows:"), False, False, 4)
        for win in wins:
            wi = self._window_info(td(win))
            if not wi:
                continue
            title_parts = [s for s, _ in wi]
            frame_title = title_parts[0] if title_parts else "window"
            frame, fvbox = section_frame(frame_title)
            for text, color in wi[1:]:
                fvbox.add(colored_label(text, color))
            self._content.pack_start(frame, False, False, 2)

        self._content.show_all()

    def _proxy_str(self, proxy_info: typedict) -> str:
        if not proxy_info:
            return ""
        proxy_platform_info = typedict(proxy_info.dictget("platform") or {})
        proxy_platform = proxy_platform_info.strget("")
        proxy_release = proxy_platform_info.strget("release")
        proxy_build_info = typedict(proxy_info.dictget("build") or {})
        proxy_version = proxy_build_info.strget("version")
        proxy_distro = proxy_info.strget("linux_distribution")
        return " via: %s proxy version %s" % (
            platform_name(proxy_platform, proxy_distro or proxy_release),
            std(proxy_version or "unknown"),
        )

    def _cpu_str(self, pid: int) -> str:
        try:
            process = self.psprocess.get(pid)
            if not process:
                import psutil
                process = psutil.Process(pid)
                self.psprocess[pid] = process
                return ""
            return f", {process.cpu_percent():3.0f}% CPU"
        except Exception:
            return ""

    def _gl_info(self, gli: dict | None) -> str:
        if not gli:
            return ""
        gli = typedict(gli)
        if not gli.boolget("enabled", True):
            return "OpenGL disabled " + gli.strget("message")

        def strget(key: str, sep=".") -> str:
            v = gli.get(key)
            if isinstance(v, (tuple, list)):
                return sep.join(str(x) for x in v)
            return bytestostr(v)

        gl_info = "OpenGL %s enabled: %s" % (strget("opengl", "."), gli.strget("renderer") or gli.strget("vendor"))
        depth = gli.intget("depth")
        if depth not in (0, 24):
            gl_info += f", {depth}bits"
        modes = gli.get("display_mode")
        if modes:
            gl_info += " - " + strget("display_mode", ", ")
        return gl_info

    def _client_info_lines(self, ci: typedict, td) -> list[tuple[str, str]]:
        ctype = ci.strget("type", "unknown")
        title = f"{ctype} client version {caps_to_version(ci)}"
        chost = ci.strget("hostname")
        conn_info = f"connected from {chost} " if chost else ""
        cinfo = ci.dictget("connection")
        if cinfo:
            cinfo = td(cinfo)
            conn_info += "using %s %s" % (cinfo.strget("type"), cinfo.strget("protocol-type"))
            conn_info += ", with %s and %s" % (cinfo.strget("encoder"), cinfo.strget("compressor"))
        gl_info = self._gl_info(ci.dictget("opengl"))
        audio_parts = [self._audio_info(ci, mode, td) for mode in ("speaker", "microphone")]
        audio_parts.append(self._avsync_info(ci, td))
        b_info = td(ci.dictget("batch") or {})
        bi_info = td(b_info.dictget("delay") or {})
        bcur = bi_info.intget("cur")
        bavg = bi_info.intget("avg")
        pl = td(td(td(ci.dictget("connection") or {}).dictget("client") or {}).dictget("ping_latency") or {})
        lcur = pl.intget("cur")
        lavg = pl.intget("avg")
        lmin = pl.intget("min")
        bl_color = GREEN
        if bcur > 100 or (lcur > 20 and lcur > 3 * lmin):
            bl_color = RED
        elif bcur > 50 or (lcur > 20 and lcur > 2 * lmin):
            bl_color = YELLOW
        batch_latency = f"batch delay: {bcur} ({bavg})".ljust(24) + f"latency: {lcur} ({lavg})"
        edict = td(ci.dictget("encoding") or {})
        qs_info = ""
        qs_color = GREEN
        if edict:
            if sinfo := td(edict.dictget("speed") or {}):
                cur = sinfo.intget("cur")
                avg = sinfo.intget("avg")
                qs_info = f"speed: {cur}% (avg: {avg}%)"
            if qinfo := td(edict.dictget("quality") or {}):
                cur = qinfo.intget("cur")
                avg = qinfo.intget("avg")
                qs_info = qs_info.ljust(24) + f"quality: {cur}% (avg: {avg}%)"
                if avg < 50:
                    qs_color = RED
                elif avg < 70:
                    qs_color = YELLOW
        rows = [
            (title, WHITE),
            (conn_info, WHITE),
            (gl_info, WHITE),
            (csv(audio_parts), WHITE),
            (batch_latency, bl_color),
            (qs_info, qs_color),
        ]
        return [(s, c) for s, c in rows if s]

    def _audio_info(self, ci: typedict, mode: str, td) -> str:
        minfo = td(ci.dictget(f"audio.{mode}") or ci.dictget(f"sound.{mode}") or {})
        if not minfo:
            return f"{mode} off"
        descr = minfo.strget("codec_description") or minfo.strget("codec") or minfo.strget("state", "unknown")
        ainfo = f"{mode}: {descr}"
        if bitrate := minfo.intget("bitrate"):
            ainfo += f" {std_unit(bitrate)}bps"
        return ainfo

    def _avsync_info(self, ci: typedict, td) -> str:
        avsf = td(self.client.server_last_info.dictget("features") or {}).dictget("av-sync") or {}
        avsf = typedict(avsf)
        if not avsf or not avsf.boolget("", False):
            return "av-sync: not supported by server"
        if not avsf.boolget("enabled", False):
            return "av-sync: disabled by server"
        avsi = td(ci.dictget("av-sync") or {})
        if not avsi.boolget("", False):
            return "av-sync: disabled by client"
        return "av-sync: enabled - video delay: %ims" % avsi.intget("total", 0)

    def _window_info(self, wi: typedict) -> list[tuple[str, str]]:
        geom = wi.inttupleget("geometry")
        if not geom or len(geom) < 4:
            return []
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
            line1 += f'"{title}"'
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
        rows = [line1 or g_str, g_str if line1 else "", tinfo]
        return [(s, WHITE) for s in rows if s]


class TopSessionClient(InfoTimerClient):
    """
    GTK replacement for the curses TopSessionClient.
    Delegates all rendering to TopSessionGUI.
    """

    def server_connection_established(self, caps: typedict) -> bool:
        self._gui = TopSessionGUI(self)
        self._gui.show_all()
        return super().server_connection_established(caps)

    def print_desktop_size(self, c: typedict) -> None:
        pass

    def print_server_info(self, c: typedict) -> None:
        pass

    def update_screen(self) -> None:
        if gui := getattr(self, "_gui", None):
            gui.update()


def main(opts=None) -> None:
    from xpra.gtk.util import init_display_source
    from xpra.gtk.util import quit_on_signals, gtk_main
    init_display_source()
    quit_on_signals("top gui")
    w = TopGUI(opts)
    w.show_all()
    gtk_main()


if __name__ == "__main__":
    main()
