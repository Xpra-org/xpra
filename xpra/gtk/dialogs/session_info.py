# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import datetime
import platform
from typing import Any
from time import monotonic
from collections import deque
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.version import XPRA_VERSION, revision_str, make_revision_str, caps_to_revision
from xpra.util.system import get_linux_distribution, platform_name
from xpra.util.objects import typedict, AtomicInteger
from xpra.util.screen import prettify_plug_name
from xpra.util.str_fn import csv, strtobytes, bytestostr, Ellipsizer
from xpra.util.env import envint
from xpra.common import noop
from xpra.util.stats import values_to_scaled_values, values_to_diff_scaled_values, to_std_unit, std_unit_dec, std_unit
from xpra.client.base import features
from xpra.client.base.command import InfoTimerClient
from xpra.gtk.window import add_close_accel
from xpra.gtk.graph import make_graph_imagesurface
from xpra.gtk.widget import imagebutton, title_box, slabel, FILE_CHOOSER_NATIVE
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import Logger

log = Logger("info")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

N_SAMPLES = 20  # how many sample points to show on the graphs
SHOW_PIXEL_STATS = True
SHOW_SOUND_STATS = True
SHOW_RECV = True


def make_version_str(version) -> str:
    if version and isinstance(version, (tuple, list)):
        version = ".".join(bytestostr(x) for x in version)
    return bytestostr(version or "unknown")


def make_datetime(date, time) -> str:
    if not time:
        return bytestostr(date or "")
    return "%s %s" % (bytestostr(date), bytestostr(time))


def bool_icon(image, on_off: bool):
    if on_off:
        icon = get_icon_pixbuf("ticked-small.png")
    else:
        icon = get_icon_pixbuf("unticked-small.png")
    image.set_from_pixbuf(icon)


def setall(labels: Sequence[Gtk.Label], values: Sequence) -> None:
    assert len(labels) == len(values), "%s labels and %s values (%s vs %s)" % (
        len(labels), len(values), labels, values)
    for i, l in enumerate(labels):
        l.set_text(str(values[i]))


def setlabels(labels: Sequence[Gtk.Label], values: Sequence, rounding: Callable = int):
    if not values:
        return
    avg = sum(values) / len(values)
    svalues = sorted(values)
    l = len(svalues)
    assert l > 0
    if l < 10:
        index = l - 1
    else:
        index = int(l * 90 / 100)
    index = max(0, min(l - 1, index))
    pct = svalues[index]
    disp = values[-1], min(values), avg, pct, max(values)
    rounded_values = [rounding(v) for v in disp]
    setall(labels, rounded_values)


def pixelstr(v) -> str:
    if v < 0:
        return "n/a"
    return std_unit_dec(v)


def fpsstr(v) -> str:
    if v < 0:
        return "n/a"
    return "%s" % (int(v * 10) / 10.0)


def average(seconds, pixel_counter):
    now = monotonic()
    total = 0
    total_n = 0
    mins = None
    maxs = 0
    avgs = 0
    mint = now - seconds  # ignore records older than N seconds
    startt = now  # when we actually start counting from
    for _, t, count in pixel_counter:
        if t >= mint:
            total += count
            total_n += 1
            startt = min(t, startt)
            if mins:
                mins = min(mins, count)
            else:
                mins = count
            maxs = max(maxs, count)
            avgs += count
    if total == 0 or startt == now:
        return None
    avgs = avgs / total_n
    elapsed = now - startt
    return int(total / elapsed), total_n / elapsed, mins, avgs, maxs


def dictlook(d, k, fallback=None):
    # deal with old-style non-namespaced dicts first:
    # "batch.delay.avg"
    if d is None:
        return fallback
    v = d.get(k)
    if v is not None:
        return v
    parts = (b"client." + strtobytes(k)).split(b".")
    v = newdictlook(d, parts, fallback)
    if v is None:
        parts = strtobytes(k).split(b".")
        v = newdictlook(d, parts, fallback)
    if v is None:
        return fallback
    return v


def newdictlook(d, parts, fallback=None):
    # ie: {}, ["batch", "delay", "avg"], 0
    v = d
    for p in parts:
        try:
            newv = v.get(p)
            if newv is None:
                newv = v.get(strtobytes(p))
                if newv is None:
                    return fallback
            v = newv
        except (ValueError, TypeError, AttributeError):
            return fallback
    return v


def image_label_hbox() -> tuple:
    hbox = Gtk.HBox(homogeneous=False, spacing=10)
    image_widget = Gtk.Image()
    image_widget.set_size_request(48, 48)
    al_i = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
    al_i.add(image_widget)
    label_widget = slabel()
    al_l = Gtk.Alignment(xalign=0, yalign=0.5, xscale=1.0, yscale=0.0)
    al_l.add(label_widget)
    hbox.add(al_i)
    hbox.add(al_l)
    return image_widget, label_widget, hbox


def settimedeltastr(label_widget, from_time) -> None:
    import time
    delta = datetime.timedelta(seconds=(int(time.time()) - int(from_time)))
    label_widget.set_text(str(delta))


def make_os_str(sys_platform, platform_release, platform_platform, platform_linux_distribution) -> str:
    s = [platform_name(sys_platform, platform_release)]
    pld = platform_linux_distribution

    def remstr(values: Sequence) -> Sequence[str]:
        return tuple(str(v) for v in values if v not in (None, "", "n/a"))
    if pld and len(pld) == 3 and pld[0]:
        s.append(" ".join(remstr(pld)))
    elif platform_platform:
        s.append(platform_platform)
    return "\n".join(remstr(s))


def get_server_platform_name(client) -> str:
    server_info: dict = getattr(client, "server_last_info") or {}
    pinfo = server_info.get("server", {}).get("platform", {})

    def plat(key=""):
        # we can get the platform information from the server info mixin,
        # or from the server last info:
        return pinfo.get(key) or getattr(client, f"_remote_platform{key}", "")

    return make_os_str(
        plat(""),
        plat("release"),
        plat("platform"),
        plat("linux_distribution"),
    )


def get_local_platform_name() -> str:
    return make_os_str(sys.platform, platform.release(), platform.platform(), get_linux_distribution())


def get_server_builddate(client) -> str:
    build_info = getattr(client, "server_last_info", {}).get("server", {}).get("build", {})

    def cattr(name):
        return build_info.get(name, "") or getattr(client, f"_remote_build_{name}", "")

    return make_datetime(cattr("date"), cattr("time"))


def get_local_builddate() -> str:
    try:
        from xpra.build_info import build
        date = build["date"]
        time = build["time"]
        return make_datetime(date, time)
    except (ImportError, KeyError):
        return ""


def get_server_version(client) -> str:
    v = getattr(client, "_remote_version")
    return make_version_str(v or "unknown")


def get_server_revision_str(client) -> str:
    def cattr(name):
        return getattr(client, name, "")

    build_info = getattr(client, "server_last_info", {}).get("server", {}).get("build", {})
    if build_info:
        return caps_to_revision(typedict(build_info))

    return make_revision_str(
        cattr("_remote_revision"),
        cattr("_remote_modifications"),
        cattr("_remote_branch"),
        cattr("_remote_commit"),
    )


def get_glbuffering_info(opengl_props: dict) -> str:
    info = []
    tprops = typedict(opengl_props)
    display_mode = tprops.strtupleget("display_mode")
    bit_depth = tprops.intget("depth", 0)
    if bit_depth:
        info.append("%i-bit" % bit_depth)
    buffering = "unknown"
    if "double-buffered" in tprops:
        buffering = "double" if tprops.boolget("double-buffered") else "single"
    elif "DOUBLE" in display_mode:
        buffering = "double"
    elif "SINGLE" in display_mode:
        buffering = "single"
    info.append(f"{buffering} buffering")
    if tprops.intget("alpha-size", 0) > 0 or "ALPHA" in display_mode:
        info.append("with transparency")
    else:
        info.append("without transparency")
    return " ".join(info)


def set_graph_surface(graph, surface) -> None:
    w = surface.get_width()
    h = surface.get_height()
    graph.set_size_request(w, h)
    graph.surface = surface
    graph.set_from_surface(surface)


def save_graph(_ebox, btn, graph) -> None:
    log("save_graph%s", (btn, graph))
    title = "Save graph as a PNG image"
    if FILE_CHOOSER_NATIVE:
        chooser = Gtk.FileChooserNative(title=title, action=Gtk.FileChooserAction.SAVE)
        chooser.set_accept_label("Save")
    else:
        chooser = Gtk.FileChooserDialog(title=title, action=Gtk.FileChooserAction.SAVE)
        buttons = (
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        chooser.add_buttons(*buttons)
        chooser.set_default_response(Gtk.ResponseType.OK)
    file_filter = Gtk.FileFilter()
    file_filter.set_name("PNG")
    file_filter.add_pattern("*.png")
    chooser.add_filter(file_filter)
    response = chooser.run()
    filenames = chooser.get_filenames()
    chooser.hide()
    if hasattr(chooser, "close"):
        chooser.close()
    if response == Gtk.ResponseType.OK:
        if len(filenames) == 1:
            filename = filenames[0]
            if not filename.lower().endswith(".png"):
                filename += ".png"
            surface = graph.surface
            log("saving surface %s to %s", surface, filename)
            from io import BytesIO
            b = BytesIO()
            surface.write_to_png(b)

            def save_file() -> None:
                with open(filename, "wb") as f:
                    f.write(b.getvalue())

            from xpra.util.thread import start_thread
            start_thread(save_file, "save-graph")
    elif response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
        log("closed/cancelled")
    else:
        log.warn(f"Warning: unknown chooser response: {response}")


class SessionInfo(Gtk.Window):

    def __init__(self, client, session_name, conn, show_client=True, show_server=True):
        assert show_client or show_server
        self.client = client
        self.session_name = session_name
        self.connection = conn
        self.show_client = show_client
        self.show_server = show_server
        super().__init__()
        self.last_populate_time = 0.0
        self.last_populate_statistics = 0
        self.is_closed = False
        self.set_title(self.get_window_title())
        self.set_destroy_with_parent(True)
        self.set_resizable(True)
        self.set_decorated(True)
        window_icon_pixbuf = get_icon_pixbuf("statistics.png") or get_icon_pixbuf("xpra.png")
        if window_icon_pixbuf:
            self.set_icon(window_icon_pixbuf)
        self.set_position(Gtk.WindowPosition.CENTER)

        # tab box to contain everything:
        self.tab_box = Gtk.VBox(homogeneous=False, spacing=0)
        self.add(self.tab_box)
        self.tab_button_box = Gtk.HBox(homogeneous=True, spacing=0)
        self.tabs: list[tuple[str, Any, Any, Callable]] = []
        self.row = AtomicInteger()
        self.grid = None

        self.populate_cb = None
        self.tab_box.pack_start(self.tab_button_box, expand=False, fill=True, padding=0)

        self.add_software_tab()
        self.add_features_tab()
        self.add_codecs_tab()
        self.add_connection_tab()
        self.add_statistics_tab()
        if show_client:
            self.add_graphs_tab()

        self.set_border_width(15)

        def window_deleted(*_args) -> None:
            self.is_closed = True

        self.connect('delete_event', window_deleted)
        self.show_tab(self.tabs[0][2])
        self.set_size_request(-1, -1)
        self.init_counters()
        self.populate()
        self.populate_all()
        GLib.timeout_add(1000, self.populate)
        GLib.timeout_add(100, self.populate_tab)
        if features.audio and SHOW_SOUND_STATS and show_client:
            GLib.timeout_add(100, self.populate_audio_stats)
        add_close_accel(self, self.close)

    def get_window_title(self) -> str:
        t = ["Session Info"]
        c = self.client
        if c:
            if c.session_name or c.server_session_name:
                t.append(c.session_name or c.server_session_name)
            p = c._protocol
            if p:
                conn = getattr(p, "_conn", None)
                if conn:
                    cinfo = conn.get_info()
                    t.append(cinfo.get("endpoint", bytestostr(conn.target)))
        v = " - ".join(str(x) for x in t)
        return v

    def add_row(self, *widgets) -> None:
        r = int(self.row)
        for i, widget in enumerate(widgets):
            self.grid.attach(widget, i, r, 1, 1)
        self.row.increase()

    def new_row(self, text: str, *widgets) -> None:
        self.add_row(slabel(text), *widgets)

    def label_row(self, text: str, value="") -> Gtk.Label:
        lbl = slabel(value)
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
        al.add(lbl)
        self.add_row(title_box(text), al)
        return lbl

    def clrow(self, label_str: str, client_label, server_label) -> None:
        labels = []
        if self.show_client:
            labels.append(client_label)
        if self.show_server:
            labels.append(server_label)
        self.add_row(title_box(label_str), *labels)

    def csrow(self, label_str, client_str, server_str) -> None:
        self.clrow(
            label_str,
            slabel(client_str) if self.show_client else None,
            slabel(server_str) if self.show_server else None,
        )

    def grid_tab(self, icon_filename: str, title: str, populate_cb: Callable) -> Gtk.VBox:
        self.grid = Gtk.Grid()
        self.row.set(0)
        vbox = self.vbox_tab(icon_filename, title, populate_cb)
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(self.grid)
        vbox.pack_start(al, expand=True, fill=True, padding=20)
        return vbox

    def vbox_tab(self, icon_filename: str, title: str, populate_cb: Callable) -> Gtk.VBox:
        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        self.add_tab(icon_filename, title, populate_cb, contents=vbox)
        return vbox

    def add_tab(self, icon_filename: str, title: str, populate_cb: Callable, contents) -> None:
        icon = get_icon_pixbuf(icon_filename)

        def show_tab(*_args):
            self.show_tab(contents)

        button = imagebutton(title, icon, clicked_callback=show_tab)
        button.connect("clicked", show_tab)
        button.set_relief(Gtk.ReliefStyle.NONE)
        self.tab_button_box.add(button)
        self.tabs.append((title, button, contents, populate_cb))

    def show_tab(self, grid) -> None:
        button = None
        for _, b, t, p_cb in self.tabs:
            if t == grid:
                button = b
                b.set_relief(Gtk.ReliefStyle.NORMAL)
                b.grab_focus()
                self.populate_cb = p_cb
            else:
                b.set_relief(Gtk.ReliefStyle.NONE)
        assert button
        for x in self.tab_box.get_children():
            if x != self.tab_button_box:
                self.tab_box.remove(x)
        self.tab_box.pack_start(grid, expand=True, fill=True, padding=0)
        grid.show_all()
        # ensure we re-draw the whole window:
        window = self.get_window()
        if window:
            alloc = self.get_allocation()
            window.invalidate_rect(alloc, True)

    def set_args(self, *args) -> None:
        # this is a generic way for keyboard shortcuts or remote commands
        # to pass parameters to us
        log("set_args%s", args)
        if not args:
            return
        # at the moment, we only handle the tab name as argument:
        tab_name = args[0]
        if tab_name.lower() != "help":
            title = ""
            for title, _, table, _ in self.tabs:
                if title.lower() == tab_name.lower():
                    self.show_tab(table)
                    return
            log.warn("could not find session info tab named: %s", title)
        log.warn("The options for tab names are: %s)", [x[0] for x in self.tabs])

    def populate_all(self) -> None:
        for tab in self.tabs:
            p_cb = tab[3]
            if p_cb:
                p_cb()

    def add_graph_button(self, tooltip: str = "", click_cb: Callable = noop) -> Gtk.Image:
        button = Gtk.EventBox()
        try:
            display = Gdk.Display.get_default()
            arrow_down = Gdk.Cursor.new_for_display(display, Gdk.CursorType.BASED_ARROW_DOWN)
        except TypeError:
            arrow_down = None

        def set_cursor(widget) -> None:
            widget.get_window().set_cursor(arrow_down)

        if arrow_down:
            button.connect("realize", set_cursor)
        graph = Gtk.Image()
        graph.set_size_request(0, 0)
        button.connect("button_press_event", click_cb, graph)
        button.add(graph)
        if tooltip:
            graph.set_tooltip_text(tooltip)
        self.graph_box.add(button)
        return graph

    def populate_audio_stats(self, *_args) -> bool:
        # runs every 100ms
        if self.is_closed:
            return False
        ss = self.client.audio_sink
        if SHOW_SOUND_STATS and ss:
            info = ss.get_info()
            if info:
                info = typedict(info)

                def qlookup(attr) -> int:
                    return int(newdictlook(info, ("queue", attr), 0))

                self.audio_out_queue_cur.append(qlookup("cur"))
                self.audio_out_queue_min.append(qlookup("min"))
                self.audio_out_queue_max.append(qlookup("max"))
        return not self.is_closed

    def last_info(self) -> dict:
        return dict(getattr(self.client, "server_last_info", {}))

    def populate(self, *_args) -> bool:
        conn = self.connection
        if self.is_closed or not conn:
            return False
        self.client.send_ping()
        self.last_populate_time = monotonic()

        if self.show_client:
            self.show_opengl_state()
            self.show_window_renderers()
            # record bytecount every second:
            self.net_in_bitcount.append(conn.input_bytecount * 8)
            self.net_out_bitcount.append(conn.output_bytecount * 8)
            if features.audio and SHOW_SOUND_STATS:
                if self.client.audio_in_bytecount > 0:
                    self.audio_in_bitcount.append(self.client.audio_in_bytecount * 8)
                if self.client.audio_out_bytecount > 0:
                    self.audio_out_bitcount.append(self.client.audio_out_bytecount * 8)

        if self.show_client and features.window:
            # count pixels in the last second:
            since = monotonic() - 1
            decoded = [0] + [pixels for _, t, pixels in self.client.pixel_counter if t > since]
            self.pixel_in_data.append(sum(decoded))

        # update latency values
        # there may be more than one record for each second,
        # so we have to average them to prevent the graph from "jumping":

        def get_ping_latency_records(src, size=25) -> tuple:
            recs = {}
            src_list = list(src)
            now = int(monotonic())
            while src_list and len(recs) < size:
                when, value = src_list.pop()
                if when >= (now - 1):  # ignore last second
                    continue
                iwhen = int(when)
                cv = recs.get(iwhen)
                v = 1000.0 * value
                if cv:
                    v = (v + cv) / 2.0  # not very fair if more than 2 values... but this shouldn't happen anyway
                recs[iwhen] = v
            # ensure we always have a record for the last N seconds, even an empty one
            for x in range(size):
                i = now - 2 - x
                if i not in recs:
                    recs[i] = None
            return tuple(recs.get(x) for x in sorted(recs.keys()))

        self.server_latency = get_ping_latency_records(self.client.server_ping_latency)
        self.client_latency = get_ping_latency_records(self.client.client_ping_latency)
        server_last_info = self.last_info()
        if server_last_info:
            # populate running averages for graphs:

            def getavg(*names):
                return newdictlook(server_last_info, list(names) + ["avg"]) or \
                    newdictlook(server_last_info, ["client"] + list(names) + ["avg"])

            def addavg(l, *names) -> None:
                v = getavg(*names)
                if v:
                    l.append(v)

            addavg(self.avg_batch_delay, "batch", "delay")
            addavg(self.avg_damage_out_latency, "damage", "out_latency")
            spl = tuple(1000.0 * x[1] for x in tuple(self.client.server_ping_latency))
            cpl = tuple(1000.0 * x[1] for x in tuple(self.client.client_ping_latency))
            if spl and cpl:
                self.avg_ping_latency.append(round(sum(spl + cpl) / len(spl + cpl)))
            if features.window and self.show_client:
                pc = tuple(self.client.pixel_counter)
                if pc:
                    tsize = 0
                    ttime = 0
                    for start_time, end_time, size in pc:
                        ttime += 1000.0 * (end_time - start_time) * size
                        tsize += size
                    self.avg_decoding_latency.append(round(ttime / tsize))
        # totals: ping latency is halved since we only care about sending, not sending+receiving
        els = (
            (tuple(self.avg_batch_delay), 1),
            (tuple(self.avg_damage_out_latency), 1),
            (tuple(self.avg_ping_latency), 2),
            (tuple(self.avg_decoding_latency), 1),
        )
        if all(x[0] for x in els):
            totals = tuple(x[-1] / r for x, r in els)
            log("frame totals=%s", totals)
            self.avg_total.append(round(sum(totals)))
        return not self.is_closed

    def add_software_tab(self) -> None:
        # Package Table:
        self.grid_tab("package.png", "Software", noop)
        if self.show_client and self.show_server:
            self.add_row(title_box(""), title_box("Client"), title_box("Server"))
        self.csrow("Operating System", get_local_platform_name(), get_server_platform_name(self.client))
        self.csrow("Xpra", XPRA_VERSION, get_server_version(self.client))
        self.csrow("Revision", revision_str(), get_server_revision_str(self.client))
        self.csrow("Build date", get_local_builddate(), get_server_builddate(self.client))

        def server_vinfo(lib) -> str:
            rlv = getattr(self.client, "_remote_lib_versions", {})
            return make_version_str(rlv.get(lib, ""))

        try:
            from xpra.audio.wrapper import query_audio
            props = query_audio()
        except ImportError:
            log("cannot load audio information: %s", exc_info=True)
            props = typedict()
        gst_version = props.strtupleget("gst.version")
        self.csrow("GStreamer", make_version_str(gst_version), server_vinfo("sound.gst") or server_vinfo("gst") or "unknown")

        def clientgl(prop="opengl", default_value="n/a") -> str:
            if not self.show_client:
                return ""
            return make_version_str(self.client.opengl_props.get(prop, default_value))

        def servergl(prop="opengl", default_value="n/a") -> str:
            if not self.show_server:
                return ""
            return make_version_str(typedict(self.client.server_opengl or {}).get(prop, default_value))

        for prop in ("OpenGL", "Vendor", "PyOpenGL"):
            key = prop.lower()
            self.csrow(prop, clientgl(key), servergl(key))

    def init_counters(self) -> None:
        self.avg_batch_delay = deque(maxlen=N_SAMPLES + 4)
        self.avg_damage_out_latency = deque(maxlen=N_SAMPLES + 4)
        self.avg_ping_latency = deque(maxlen=N_SAMPLES + 4)
        self.avg_decoding_latency = deque(maxlen=N_SAMPLES + 4)
        self.avg_total = deque(maxlen=N_SAMPLES + 4)

    def populate_tab(self, *_args) -> bool:
        if self.is_closed:
            return False
        # now re-populate the tab we are seeing:
        if self.populate_cb and not self.populate_cb():
            self.populate_cb = None
        return not self.is_closed

    def show_opengl_state(self) -> None:
        if self.client.opengl_enabled:
            glinfo = "%s / %s" % (
                self.client.opengl_props.get("vendor", ""),
                self.client.opengl_props.get("renderer", ""),
            )
            info = get_glbuffering_info(self.client.opengl_props)
        else:
            # info could be telling us that the gl bindings are missing:
            glinfo = self.client.opengl_props.get("info", "disabled")
            info = "n/a"
        self.client_opengl_label.set_text(glinfo)
        self.opengl_buffering.set_text(info)

    def show_window_renderers(self) -> None:
        if not features.window:
            return
        wr = []
        renderers = {}
        for wid, window in tuple(self.client._id_to_window.items()):
            renderers.setdefault(window.get_backing_class(), []).append(wid)
        for bclass, windows in renderers.items():
            wr.append("%s (%i)" % (bclass.__name__.replace("Backing", ""), len(windows)))
        self.window_rendering.set_text("GTK3: %s" % csv(wr))

    def add_features_tab(self) -> None:
        # Features Table:
        self.grid_tab("features.png", "Features", self.populate_features)

        def image_row(text: str) -> Gtk.Image:
            img = Gtk.Image()
            img.set_margin_start(5)
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
            al.add(img)
            self.add_row(title_box(text), al)
            return img

        self.server_randr_icon, self.server_randr_label, randr_box = image_label_hbox()
        self.add_row(title_box("RandR Support"), randr_box)
        if self.show_client:
            self.client_display = self.label_row("Client Display")
            self.client_opengl_icon, self.client_opengl_label, opengl_box = image_label_hbox()
            self.add_row(title_box("Client OpenGL"), opengl_box)
            self.opengl_buffering = self.label_row("OpenGL Mode")
            self.window_rendering = self.label_row("Window Rendering")
        if features.mmap:
            self.server_mmap_icon = image_row("Memory Mapped Transfers")
        if features.clipboard:
            self.server_clipboard_icon = image_row("Clipboard")
        if features.notification:
            self.server_notifications_icon = image_row("Notifications")
        if features.window:
            self.server_bell_icon = image_row("Bell")
            self.server_cursors_icon = image_row("Cursors")

    def populate_features(self) -> bool:
        size_info = ""
        if features.window:
            if self.client.server_actual_desktop_size:
                w, h = self.client.server_actual_desktop_size
                size_info = f"{w}x{h}"
                if self.client.server_randr and self.client.server_max_desktop_size:
                    size_info += " (max %s)" % ("x".join([str(x) for x in self.client.server_max_desktop_size]))
                bool_icon(self.server_randr_icon, self.client.server_randr)
        else:
            size_info = "unknown"
            unknown = get_icon_pixbuf("unknown.png")
            if unknown:
                self.server_randr_icon.set_from_pixbuf(unknown)
        self.server_randr_label.set_text("%s" % size_info)
        if self.show_client:
            root_w, root_h = self.client.get_root_size()
            if features.window and (self.client.xscale != 1 or self.client.yscale != 1):
                sw, sh = self.client.cp(root_w, root_h)
                display_info = "%ix%i (scaled from %ix%i)" % (sw, sh, root_w, root_h)
            else:
                display_info = "%ix%i" % (root_w, root_h)
            self.client_display.set_text(display_info)
            bool_icon(self.client_opengl_icon, self.client.client_supports_opengl)
            self.show_window_renderers()

        if features.mmap:
            bool_icon(self.server_mmap_icon, bool(self.client.mmap_read_area))
        if features.clipboard:
            bool_icon(self.server_clipboard_icon, self.client.server_clipboard)
        if features.notification:
            bool_icon(self.server_notifications_icon, self.client.server_notifications)
        if features.window:
            bool_icon(self.server_bell_icon, self.client.server_bell)
        if features.cursor:
            bool_icon(self.server_cursors_icon, self.client.server_cursors)
        return True

    def add_codecs_tab(self) -> None:
        # Codecs Table:
        self.grid_tab("encoding.png", "Codecs", self.populate_codecs)
        if self.show_client and self.show_server:
            # table headings:
            for i, text in enumerate(("", "Client", "Server")):
                self.grid.attach(title_box(text), i, 0, 1, 1)
            self.row.increase()
        # grid contents:
        self.client_encodings_label = slabel()
        self.server_encodings_label = slabel()
        self.clrow("Picture Encodings", self.client_encodings_label, self.server_encodings_label)
        self.client_speaker_codecs_label = slabel()
        self.server_speaker_codecs_label = slabel()
        self.clrow("Speaker Codecs", self.client_speaker_codecs_label, self.server_speaker_codecs_label)
        self.client_microphone_codecs_label = slabel()
        self.server_microphone_codecs_label = slabel()
        self.clrow("Microphone Codecs", self.client_microphone_codecs_label, self.server_microphone_codecs_label)
        self.client_packet_encoders_label = slabel()
        self.server_packet_encoders_label = slabel()
        self.clrow("Packet Encoders", self.client_packet_encoders_label, self.server_packet_encoders_label)
        self.client_packet_compressors_label = slabel()
        self.server_packet_compressors_label = slabel()
        self.clrow("Packet Compressors", self.client_packet_compressors_label, self.server_packet_compressors_label)

    def populate_codecs(self) -> bool:
        # clamp the large labels so they will overflow vertically:
        w = self.tab_box.get_preferred_width()[0]
        lw = max(200, int(w // 2.5))
        if self.show_client:
            self.client_encodings_label.set_size_request(lw, -1)
            self.client_speaker_codecs_label.set_size_request(lw, -1)
            self.client_microphone_codecs_label.set_size_request(lw, -1)
        if self.show_server:
            self.server_encodings_label.set_size_request(lw, -1)
            self.server_speaker_codecs_label.set_size_request(lw, -1)
            self.server_microphone_codecs_label.set_size_request(lw, -1)

        # audio/video codec table:

        def codec_info(enabled, codecs) -> str:
            if not enabled:
                return "n/a"
            return ", ".join(codecs or ())

        if features.audio:
            c = self.client
            if self.show_server:
                self.server_speaker_codecs_label.set_text(
                    codec_info(c.server_audio_send, c.server_audio_encoders))
            if self.show_client:
                self.client_speaker_codecs_label.set_text(
                    codec_info(c.speaker_allowed, c.speaker_codecs))
            if self.show_server:
                self.server_microphone_codecs_label.set_text(
                    codec_info(c.server_audio_receive, c.server_audio_decoders))
            if self.show_client:
                self.client_microphone_codecs_label.set_text(
                    codec_info(c.microphone_allowed, c.microphone_codecs))

        def encliststr(v) -> str:
            v = list(v)
            try:
                v.remove("rgb")
            except ValueError:
                pass
            return csv(sorted(v))

        se = ()
        if features.encoding:
            se = self.client.server_core_encodings
        self.server_encodings_label.set_text(encliststr(se))
        if self.show_client and features.encoding:
            self.client_encodings_label.set_text(encliststr(self.client.get_core_encodings()))
        else:
            self.client_encodings_label.set_text("n/a")

        from xpra.net.packet_encoding import get_enabled_encoders
        if self.show_client:
            self.client_packet_encoders_label.set_text(csv(get_enabled_encoders()))
        if self.show_server:
            self.server_packet_encoders_label.set_text(csv(self.client.server_packet_encoders))

        from xpra.net.compression import get_enabled_compressors
        if self.show_client:
            self.client_packet_compressors_label.set_text(csv(get_enabled_compressors()))
        if self.show_server:
            self.server_packet_compressors_label.set_text(csv(self.client.server_compressors))
        return False

    def add_connection_tab(self) -> None:
        self.grid_tab("connect.png", "Connection", self.populate_connection)

        def cattr(name) -> str:
            return getattr(self.client, name, "")

        if self.connection:
            self.connection.target = self.label_row("Server Endpoint")
        if features.display and self.client.server_display:
            self.label_row("Server Display", prettify_plug_name(self.client.server_display))
        self.label_row("Server Hostname", cattr("_remote_hostname"))
        if cattr("_remote_platform"):
            self.label_row("Server Platform", cattr("_remote_platform"))
        self.server_load_label = self.label_row("Server Load")
        self.server_load_label.set_tooltip_text("Average over 1, 5 and 15 minutes")
        self.session_started_label = self.label_row("Session Started")
        if not self.show_client:
            return
        self.session_connected_label = self.label_row("Session Connected")
        self.input_packets_label = self.label_row("Packets Received")
        self.input_bytes_label = self.label_row("Bytes Received")
        self.output_packets_label = self.label_row("Packets Sent")
        self.output_bytes_label = self.label_row("Bytes Sent")
        self.compression_label = self.label_row("Encoding + Compression")
        self.connection_type_label = self.label_row("Connection Type")
        self.input_encryption_label = self.label_row("Input Encryption")
        self.output_encryption_label = self.label_row("Output Encryption")

        def add_audio_row(text) -> tuple[Gtk.Label, Gtk.Label]:
            lbl = slabel()
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
            al.add(lbl)
            details = slabel(font="monospace 10")
            self.add_row(title_box(text), al, details)
            return lbl, details

        self.speaker_label, self.speaker_details = add_audio_row("Speaker")
        self.microphone_label, self.microphone_details = add_audio_row("Microphone")

    def populate_connection(self) -> bool:
        if self.client.server_load:
            self.server_load_label.set_text("  ".join("%.1f" % (x / 1000.0) for x in self.client.server_load))
        if self.client.server_start_time > 0:
            settimedeltastr(self.session_started_label, self.client.server_start_time)
        else:
            self.session_started_label.set_text("unknown")
        settimedeltastr(self.session_connected_label, self.client.start_time)

        p = self.client._protocol
        if not self.show_client:
            return True
        if p is None:
            # no longer connected!
            return False
        c = p._conn
        if c:
            self.input_packets_label.set_text(std_unit_dec(p.input_packetcount))
            self.input_bytes_label.set_text(std_unit_dec(c.input_bytecount))
            self.output_packets_label.set_text(std_unit_dec(p.output_packetcount))
            self.output_bytes_label.set_text(std_unit_dec(c.output_bytecount))
        else:
            for lbl in (
                    self.input_packets_label,
                    self.input_bytes_label,
                    self.output_packets_label,
                    self.output_bytes_label,
            ):
                lbl.set_text("n/a")

        if features.audio:

            def get_audio_info(supported, prop) -> dict:
                if not supported:
                    return {"state": "disabled"}
                if prop is None:
                    return {"state": "inactive"}
                return prop.get_info()

            def set_audio_info(label, details, supported, prop) -> None:
                d = typedict(get_audio_info(supported, prop))
                state = d.strget("state")
                codec_descr = d.strget("codec") or d.strget("codec_description")
                container_descr = d.strget("container_description")
                if state == "active" and codec_descr:
                    if codec_descr.find(container_descr) >= 0:
                        descr = codec_descr
                    else:
                        descr = csv(x for x in (codec_descr, container_descr) if x)
                    state = f"{state}: {descr}"
                label.set_text(state)
                if details:
                    s = ""
                    bitrate = d.intget("bitrate", 0)
                    if bitrate > 0:
                        s = "%sbit/s" % std_unit(bitrate)
                    details.set_text(s)

            set_audio_info(self.speaker_label, self.speaker_details,
                           self.client.speaker_enabled, self.client.audio_sink)
            set_audio_info(self.microphone_label, None,
                           self.client.microphone_enabled, self.client.audio_source)

        self.connection_type_label.set_text(c.socktype)
        protocol_info = p.get_info()
        encoder = protocol_info.get("encoder", "bug")
        compressor = protocol_info.get("compressor", "none")
        level = protocol_info.get("compression_level", 0)
        compression_str = encoder + " + " + compressor
        if level > 0:
            compression_str += " (level %s)" % level
        self.compression_label.set_text(compression_str)

        from xpra.net.crypto import get_crypto_caps
        ccaps = get_crypto_caps()

        def enclabel(label_widget, cipher) -> None:
            if not cipher:
                info = "None"
            else:
                info = str(cipher)
            if c.socktype.lower() == "ssh":
                info += " (%s)" % c.socktype
            backend = ccaps.get("backend")
            if backend == "python-cryptography":
                info += " / python-cryptography"
            label_widget.set_text(info)

        enclabel(self.input_encryption_label, p.cipher_in_name)
        enclabel(self.output_encryption_label, p.cipher_out_name)
        return True

    def getval(self, prefix, suffix, alt=""):
        server_last_info = self.last_info()
        if not server_last_info:
            return ""
        altv = ""
        if alt:
            altv = dictlook(server_last_info, (alt + "." + suffix).encode(), "")
        return dictlook(server_last_info, (prefix + "." + suffix).encode(), altv)

    def values_from_info(self, prefix, alt=None) -> tuple:
        def getv(suffix):
            return self.getval(prefix, suffix, alt)

        return getv("cur"), getv("min"), getv("avg"), getv("90p"), getv("max")

    def all_values_from_info(self, *window_props) -> tuple[int, int, int, int, int]:
        server_last_info = self.last_info()
        for window_prop in window_props:
            prop_path = "client.%s" % window_prop
            v = dictlook(server_last_info, prop_path)
            if v is not None:
                v = typedict(v)
                iget = v.intget
                return iget("cur"), iget("min"), iget("avg"), iget("90p"), iget("max")
        return 0, 0, 0, 0, 0

    def add_statistics_tab(self) -> None:
        # Details:
        vbox = self.grid_tab("browse.png", "Statistics", self.populate_statistics)
        self.add_row(*(title_box(x) for x in ("", "Latest", "Minimum", "Average", "90 percentile", "Maximum")))

        def maths_labels(metric="", tooltip=""):
            labels = [title_box(metric, tooltip), slabel(), slabel(), slabel(), slabel(), slabel()]
            self.add_row(*labels)
            return labels[1:]

        self.server_latency_labels = maths_labels(
            "Server Latency (ms)",
            "The time it takes for the server to respond to pings",
        )
        self.client_latency_labels = maths_labels(
            "Client Latency (ms)",
            "The time it takes for the client to respond to pings, as measured by the server",
        )
        if not features.window or not self.client.windows_enabled:
            return
        self.batch_labels = maths_labels(
            "Batch Delay (MPixels / ms)",
            "How long the server waits for new screen updates to accumulate before processing them",
        )
        self.damage_labels = maths_labels(
            "Damage Latency (ms)",
            "The time it takes to compress a frame and pass it to the OS network layer",
        )
        self.quality_labels = maths_labels(
            "Encoding Quality (pct)",
            "Automatic picture quality, average for all the windows"
        )
        self.speed_labels = maths_labels(
            "Encoding Speed (pct)",
            "Automatic picture encoding speed (bandwidth vs CPU usage), average for all the windows",
        )
        self.decoding_labels = maths_labels(
            "Decoding Latency (ms)",
            "How long it takes the client to decode a screen update",
        )
        self.regions_per_second_labels = maths_labels(
            "Regions/s",
            "The number of screen updates per second (includes both partial and full screen updates)",
        )
        self.regions_sizes_labels = maths_labels(
            "Pixels/region",
            "The number of pixels per screen update",
        )
        self.pixels_per_second_labels = maths_labels(
            "Pixels/s",
            "The number of pixels processed per second",
        )

        # grid 2:
        self.grid = Gtk.Grid()
        self.row.set(0)
        vbox.add(self.grid)
        self.add_row(*(title_box(x) for x in ("", "Regular", "Transient", "Trays", "OpenGL")))
        self.windows_managed_label = slabel()
        self.transient_managed_label = slabel()
        self.trays_managed_label = slabel()
        self.opengl_label = slabel()
        self.add_row(title_box("Windows"),
                     self.windows_managed_label, self.transient_managed_label,
                     self.trays_managed_label, self.opengl_label)

        self.encoder_info_box = Gtk.HBox(spacing=4)
        self.encoder_info_box.add(title_box("Window Encoders"))
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1.0, yscale=0.0)
        al.set_margin_start(10)
        al.set_margin_end(10)
        al.add(self.encoder_info_box)
        vbox.add(al)

    def populate_statistics(self) -> bool:
        log("populate_statistics()")
        if monotonic() - self.last_populate_statistics < 1.0:
            # don't repopulate more than every second
            return True
        self.last_populate_statistics = monotonic()
        self.client.send_info_request()

        if self.client.server_ping_latency:
            spl = tuple(int(1000 * x[1]) for x in tuple(self.client.server_ping_latency))
            setlabels(self.server_latency_labels, spl)
        if self.client.client_ping_latency:
            cpl = tuple(int(1000 * x[1]) for x in tuple(self.client.client_ping_latency))
            setlabels(self.client_latency_labels, cpl)
        if features.window and self.client.windows_enabled:
            setall(self.batch_labels, self.values_from_info("batch_delay", "batch.delay"))
            setall(self.damage_labels, self.values_from_info("damage_out_latency", "damage.out_latency"))
            setall(self.quality_labels, self.all_values_from_info("quality", "encoding.quality"))
            setall(self.speed_labels, self.all_values_from_info("speed", "encoding.speed"))

            region_sizes = []
            rps = []
            pps = []
            decoding_latency = []
            if self.client.pixel_counter:
                min_time = None
                max_time = None
                regions_per_second = {}
                pixels_per_second = {}
                for start_time, end_time, size in self.client.pixel_counter:
                    decoding_latency.append(int(1000.0 * (end_time - start_time)))
                    region_sizes.append(size)
                    if min_time is None or min_time > end_time:
                        min_time = end_time
                    if max_time is None or max_time < end_time:
                        max_time = end_time
                    time_in_seconds = int(end_time)
                    regions = regions_per_second.get(time_in_seconds, 0)
                    regions_per_second[time_in_seconds] = regions + 1
                    pixels = pixels_per_second.get(time_in_seconds, 0)
                    pixels_per_second[time_in_seconds] = pixels + size
                if int(min_time) + 1 < int(max_time):
                    for t in range(int(min_time) + 1, int(max_time)):
                        rps.append(regions_per_second.get(t, 0))
                        pps.append(pixels_per_second.get(t, 0))
            setlabels(self.decoding_labels, decoding_latency)
            setlabels(self.regions_per_second_labels, rps)
            setlabels(self.regions_sizes_labels, region_sizes, rounding=std_unit_dec)
            setlabels(self.pixels_per_second_labels, pps, rounding=std_unit_dec)

            windows, gl, transient, trays = 0, 0, 0, 0
            for w in self.client._window_to_id.keys():
                if w.is_tray():
                    trays += 1
                elif w.is_OR():
                    transient += 1
                else:
                    windows += 1
                if w.is_GL():
                    gl += 1
            self.windows_managed_label.set_text(str(windows))
            self.transient_managed_label.set_text(str(transient))
            self.trays_managed_label.set_text(str(trays))
            if self.client.client_supports_opengl:
                self.opengl_label.set_text(str(gl))

            # remove all the current labels:
            for x in self.encoder_info_box.get_children():
                self.encoder_info_box.remove(x)
            server_last_info = self.last_info()
            if server_last_info:
                window_encoder_stats = self.get_window_encoder_stats()
                # log("window_encoder_stats=%s", window_encoder_stats)
                for wid, props in window_encoder_stats.items():
                    lbl = slabel("%s (%s)" % (wid, bytestostr(props.get(""))))
                    lbl.show()
                    info = ("%s=%s" % (k, v) for k, v in props.items() if k != "")
                    lbl.set_tooltip_text(" ".join(info))
                    self.encoder_info_box.add(lbl)
        return True

    def get_window_encoder_stats(self) -> dict:
        window_encoder_stats = {}
        # new-style server with namespace (easier):
        server_last_info = self.last_info()
        window_dict = server_last_info.get("window")
        if window_dict and isinstance(window_dict, dict):
            for k, v in window_dict.items():
                with log.trap_error("Error: cannot lookup window dict"):
                    wid = int(k)
                    encoder_stats = v.get("encoder")
                    if encoder_stats:
                        window_encoder_stats[wid] = encoder_stats
        return window_encoder_stats

    def add_graphs_tab(self) -> None:
        self.graph_box = Gtk.VBox(homogeneous=False, spacing=10)
        self.add_tab("statistics.png", "Graphs", self.populate_graphs, self.graph_box)
        bandwidth_label = "Bandwidth used"
        if SHOW_PIXEL_STATS:
            bandwidth_label += ",\nand number of pixels rendered"
        self.bandwidth_graph = self.add_graph_button(bandwidth_label, save_graph)
        self.latency_graph = self.add_graph_button("", save_graph)
        if SHOW_SOUND_STATS:
            self.audio_queue_graph = self.add_graph_button("", save_graph)
        else:
            self.audio_queue_graph = None
        self.connect("realize", self.populate_graphs)
        self.pixel_in_data = deque(maxlen=N_SAMPLES + 4)
        self.net_in_bitcount = deque(maxlen=N_SAMPLES + 4)
        self.net_out_bitcount = deque(maxlen=N_SAMPLES + 4)
        self.audio_in_bitcount = deque(maxlen=N_SAMPLES + 4)
        self.audio_out_bitcount = deque(maxlen=N_SAMPLES + 4)
        self.audio_out_queue_min = deque(maxlen=N_SAMPLES * 10 + 4)
        self.audio_out_queue_max = deque(maxlen=N_SAMPLES * 10 + 4)
        self.audio_out_queue_cur = deque(maxlen=N_SAMPLES * 10 + 4)

    def populate_graphs(self, *_args) -> bool:
        # older servers have 'batch' at top level,
        # newer servers store it under client
        self.client.send_info_request("network", "damage", "state", "batch", "client")
        box = self.tab_box
        h = box.get_preferred_height()[0]
        bh = self.tab_button_box.get_preferred_height()[0]
        if h <= 0:
            return True
        start_x_offset = min(1.0, (monotonic() - self.last_populate_time) * 0.95)
        rect = box.get_allocation()
        maxw, maxh = self.client.get_root_size()
        ngraphs = 2 + int(SHOW_SOUND_STATS)
        # the preferred size (which does not cause the window to grow too big):
        W = 360
        H = 160 * 3 // ngraphs
        w = min(maxw, max(W, rect.width - 20))
        # need some padding to be able to shrink the window again:
        pad = 50
        h = min(maxh - pad // ngraphs, max(H, (h - bh - pad) // ngraphs, (rect.height - bh - pad) // ngraphs))
        # bandwidth graph:
        labels, datasets = [], []

        def unit(scale) -> str:
            if scale == 1:
                return ""
            unit, value = to_std_unit(scale)
            if value == 1:
                return str(unit)
            return f"x{int(value)}{unit}"

        if self.net_in_bitcount and self.net_out_bitcount:
            net_in_scale, net_in_data = values_to_diff_scaled_values(tuple(
                self.net_in_bitcount)[1:N_SAMPLES + 3], scale_unit=1000, min_scaled_value=50)
            net_out_scale, net_out_data = values_to_diff_scaled_values(tuple(
                self.net_out_bitcount)[1:N_SAMPLES + 3], scale_unit=1000, min_scaled_value=50)
            if SHOW_RECV:
                labels += ["recv %sb/s" % unit(net_in_scale), "sent %sb/s" % unit(net_out_scale)]
                datasets += [net_in_data, net_out_data]
            else:
                labels += ["recv %sb/s" % unit(net_in_scale)]
                datasets += [net_in_data]
        if features.window and SHOW_PIXEL_STATS and self.client.windows_enabled:
            pixel_scale, in_pixels = values_to_scaled_values(tuple(
                self.pixel_in_data)[3:N_SAMPLES + 4], min_scaled_value=100)
            datasets.append(in_pixels)
            labels.append("%s pixels/s" % unit(pixel_scale))
        if features.audio and SHOW_SOUND_STATS and self.audio_in_bitcount:
            audio_in_scale, audio_in_data = values_to_diff_scaled_values(tuple(
                self.audio_in_bitcount)[1:N_SAMPLES + 3], scale_unit=1000, min_scaled_value=50)
            datasets.append(audio_in_data)
            labels.append("Speaker %sb/s" % unit(audio_in_scale))
        if features.audio and SHOW_SOUND_STATS and self.audio_out_bitcount:
            audio_out_scale, audio_out_data = values_to_diff_scaled_values(tuple(
                self.audio_out_bitcount)[1:N_SAMPLES + 3], scale_unit=1000, min_scaled_value=50)
            datasets.append(audio_out_data)
            labels.append("Mic %sb/s" % unit(audio_out_scale))

        if labels and datasets:
            surface = make_graph_imagesurface(datasets, labels=labels,
                                              width=w, height=h,
                                              title="Bandwidth", min_y_scale=10, rounding=10,
                                              start_x_offset=start_x_offset)
            set_graph_surface(self.bandwidth_graph, surface)

        def norm_lists(items, size=N_SAMPLES) -> tuple:
            # ensures we always have exactly 20 values,
            # (and skip if we don't have any)
            values, labels = [], []
            for l, name in items:
                if not l:
                    continue
                l = list(l)
                if len(l) < size:
                    for _ in range(size - len(l)):
                        l.insert(0, None)
                else:
                    l = l[:size]
                values.append(l)
                labels.append(name)
            return values, labels

        # latency graph:
        latency_values, latency_labels = norm_lists(
            (
                (self.avg_ping_latency, "network"),
                (self.avg_batch_delay, "batch delay"),
                (self.avg_damage_out_latency, "encode&send"),
                (self.avg_decoding_latency, "decoding"),
                (self.avg_total, "frame total"),
            )
        )
        # debug:
        # for i, v in enumerate(latency_values):
        #    log.warn("%20s = %s", latency_labels[i], v)
        surface = make_graph_imagesurface(latency_values, labels=latency_labels,
                                          width=w, height=h,
                                          title="Latency (ms)", min_y_scale=10, rounding=25,
                                          start_x_offset=start_x_offset)
        set_graph_surface(self.latency_graph, surface)

        if features.audio and SHOW_SOUND_STATS and self.client.audio_sink:
            # audio queue graph:
            queue_values, queue_labels = norm_lists(
                (
                    (self.audio_out_queue_max, "Max"),
                    (self.audio_out_queue_cur, "Level"),
                    (self.audio_out_queue_min, "Min"),
                ),
                N_SAMPLES * 10
            )
            surface = make_graph_imagesurface(queue_values, labels=queue_labels,
                                              width=w, height=h,
                                              title="Audio Buffer (ms)", min_y_scale=10, rounding=25,
                                              start_x_offset=start_x_offset)
            set_graph_surface(self.audio_queue_graph, surface)
        return True

    def close(self, *args) -> None:
        log("SessionInfo.close(%s) is_closed=%s", args, self.is_closed)
        self.is_closed = True
        super().close()
        log("SessionInfo.close(%s) done", args)


class SessionInfoClient(InfoTimerClient):
    REFRESH_RATE = envint("XPRA_INFO_REFRESH_RATE", 2)

    def __init__(self, *args):
        super().__init__(*args)
        self.client_type = "session-info"

    def setup_connection(self, conn) -> None:
        self.session_name = self.server_session_name = "session-info"
        self.windows_enabled = False
        self.send_ping = noop
        self.server_audio_send = self.server_audio_receive = True
        self.server_audio_encoders = self.server_audio_decoders = []
        self.server_ping_latency = self.client_ping_latency = []
        self.server_start_time = 0
        super().setup_connection(conn)
        self.window = None

    def run_loop(self) -> None:
        Gtk.main()

    def exit_loop(self) -> None:
        Gtk.main_quit()

    def update_screen(self) -> None:
        # this is called every time we get the server info back
        server_last_info = self.last_info()
        log("update_screen() server_last_info=%s", Ellipsizer(server_last_info))
        if not server_last_info:
            return
        td = typedict(server_last_info)

        def rtdict(*keys):
            d = td
            for prop in keys:
                v = d.dictget(prop)
                d = typedict(v or {})
            return d

        from xpra.client.base.serverinfo import get_remote_lib_versions
        features = rtdict("features")
        self.server_clipboard = features.boolget("clipboard")
        self.server_notifications = features.boolget("notification")
        display = rtdict("display")
        self.server_opengl = rtdict("display", "opengl")
        self.server_bell = display.boolget("bell")
        self.server_cursors = display.boolget("cursors")
        self.server_randr = display.boolget("randr")
        server = rtdict("server")
        self.server_actual_desktop_size = server.inttupleget("root_window_size")
        self.server_max_desktop_size = server.inttupleget("max_desktop_size")
        self._remote_lib_versions = get_remote_lib_versions(rtdict("server"))
        encodings = rtdict("encodings")
        self.server_core_encodings = encodings.strtupleget("core")
        network = rtdict("network")
        self.server_packet_encoders = network.strtupleget("encoders")
        self.server_compressors = network.strtupleget("compressors")
        self.server_load = server.inttupleget("load")
        self._remote_hostname = server.strget("hostname")
        build = rtdict("server", "build")
        self._remote_version = build.strget("version")
        self._remote_build_date = build.strget("date")
        self._remote_build_time = build.strget("time")
        self._remote_revision = build.intget("revision")
        self._remote_modifications = build.intget("local_modifications")
        self._remote_branch = build.strget("branch")
        self._remote_commit = build.strget("commit")
        platform_info = rtdict("server", "platform")
        self._remote_platform = platform_info.strget("")
        self._remote_platform_release = platform_info.strget("release")
        self._remote_platform_platform = platform_info.strget("platform")
        self._remote_platform_linux_distribution = platform_info.strget("linux_distribution")
        self.server_display = server.strget("display")
        GLib.idle_add(self.do_update_screen)

    def do_update_screen(self) -> bool:
        if not self.window:
            self.window = SessionInfo(self, "session-info", self._protocol._conn, show_client=False)
            self.window.show_all()

            def destroy(*_args):
                self.exit_loop()

            self.window.connect("destroy", destroy)
        self.window.populate()
        return False
