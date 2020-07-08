# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import datetime
from collections import deque

from xpra.version_util import XPRA_VERSION
from xpra.os_util import bytestostr, strtobytes, get_linux_distribution, monotonic_time
from xpra.util import prettify_plug_name, typedict, csv, engs, iround
from xpra.gtk_common.graph import make_graph_imagesurface
from xpra.simple_stats import values_to_scaled_values, values_to_diff_scaled_values, to_std_unit, std_unit_dec, std_unit
from xpra.scripts.config import python_platform
from xpra.client import mixin_features
from xpra.gtk_common.gtk_util import (
    add_close_accel, label, title_box,
    TableBuilder, imagebutton, get_preferred_size, get_gtk_version_info,
    RELIEF_NONE, RELIEF_NORMAL, EXPAND, FILL, WIN_POS_CENTER,
    RESPONSE_CANCEL, RESPONSE_OK, RESPONSE_CLOSE, RESPONSE_DELETE_EVENT,
    FILE_CHOOSER_ACTION_SAVE,
    )
from xpra.net.net_util import get_network_caps
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_glib, is_gtk3
from xpra.log import Logger

log = Logger("info")

gtk = import_gtk()
gdk = import_gdk()
glib = import_glib()

N_SAMPLES = 20      #how many sample points to show on the graphs
SHOW_PIXEL_STATS = True
SHOW_SOUND_STATS = True
SHOW_RECV = True


def pixelstr(v):
    if v<0:
        return  "n/a"
    return std_unit_dec(v)
def fpsstr(v):
    if v<0:
        return  "n/a"
    return "%s" % (int(v*10)/10.0)

def average(seconds, pixel_counter):
    now = monotonic_time()
    total = 0
    total_n = 0
    mins = None
    maxs = 0
    avgs = 0
    mint = now-seconds      #ignore records older than N seconds
    startt = now            #when we actually start counting from
    for _, t, count in pixel_counter:
        if t>=mint:
            total += count
            total_n += 1
            startt = min(t, startt)
            if mins:
                mins = min(mins,count)
            else:
                mins = count
            maxs = max(maxs, count)
            avgs += count
    if total==0 or startt==now:
        return  None
    avgs = avgs/total_n
    elapsed = now-startt
    return int(total/elapsed), total_n/elapsed, mins, avgs, maxs

def dictlook(d, k, fallback=None):
    #deal with old-style non-namespaced dicts first:
    #"batch.delay.avg"
    if d is None:
        return fallback
    v = d.get(k)
    if v is not None:
        return v
    parts = (b"client."+strtobytes(k)).split(b".")
    v = newdictlook(d, parts, fallback)
    if v is None:
        parts = strtobytes(k).split(b".")
        v = newdictlook(d, parts, fallback)
    if v is None:
        return fallback
    return v

def newdictlook(d, parts, fallback=None):
    #ie: {}, ["batch", "delay", "avg"], 0
    v = d
    for p in parts:
        try:
            newv = v.get(p)
            if newv is None:
                newv = v.get(strtobytes(p))
                if newv is None:
                    return fallback
            v = newv
        except:
            return fallback
    return v

def slabel(text="", tooltip=None, font=None):
    l = label(text, tooltip, font)
    l.set_selectable(True)
    return l


class SessionInfo(gtk.Window):

    def __init__(self, client, session_name, window_icon_pixbuf, conn, get_pixbuf):
        gtk.Window.__init__(self)
        self.client = client
        self.session_name = session_name
        self.connection = conn
        self.last_populate_time = 0
        self.last_populate_statistics = 0
        self.is_closed = False
        self.get_pixbuf = get_pixbuf
        if not self.session_name or self.session_name=="Xpra":
            title = u"Session Info"
        else:
            title = u"%s: Session Info" % self.session_name
        self.set_title(title)
        self.set_destroy_with_parent(True)
        self.set_resizable(True)
        self.set_decorated(True)
        if window_icon_pixbuf:
            self.set_icon(window_icon_pixbuf)
        self.set_position(WIN_POS_CENTER)

        #tables on the left in a vbox with buttons at the top:
        self.tab_box = gtk.VBox(False, 0)
        self.tab_button_box = gtk.HBox(True, 0)
        self.tabs = []          #pairs of button, table
        self.populate_cb = None
        self.tab_box.pack_start(self.tab_button_box, expand=False, fill=True, padding=0)

        #Package Table:
        tb = self.table_tab("package.png", "Software", self.populate_package)[0]
        #title row:
        tb.attach(title_box(""), 0, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Client"), 1, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Server"), 2, xoptions=EXPAND|FILL, xpadding=0)
        tb.inc()

        def make_os_str(sys_platform, platform_release, platform_platform, platform_linux_distribution):
            from xpra.os_util import platform_name
            s = [platform_name(sys_platform, platform_release)]
            if platform_linux_distribution and len(platform_linux_distribution)==3 and len(platform_linux_distribution[0])>0:
                s.append(" ".join([str(x) for x in platform_linux_distribution]))
            elif platform_platform:
                s.append(platform_platform)
            return "\n".join(s)
        distro = get_linux_distribution()
        LOCAL_PLATFORM_NAME = make_os_str(sys.platform, python_platform.release(), python_platform.platform(), distro)
        SERVER_PLATFORM_NAME = make_os_str(self.client._remote_platform,
                                           self.client._remote_platform_release,
                                           self.client._remote_platform_platform,
                                           self.client._remote_platform_linux_distribution)
        tb.new_row("Operating System", slabel(LOCAL_PLATFORM_NAME), slabel(SERVER_PLATFORM_NAME))
        scaps = self.client.server_capabilities
        tb.new_row("Xpra", slabel(XPRA_VERSION), slabel(self.client._remote_version or "unknown"))
        cl_rev, cl_ch, cl_date = "unknown", "", ""
        try:
            from xpra.build_info import BUILD_DATE as cl_date, BUILD_TIME as cl_time
            from xpra.src_info import REVISION as cl_rev, LOCAL_MODIFICATIONS as cl_ch      #@UnresolvedImport
        except:
            pass
        def make_version_str(version):
            if version and isinstance(version, (tuple, list)):
                version = ".".join(bytestostr(x) for x in version)
            return bytestostr(version or "unknown")
        def server_info(*prop_names):
            for x in prop_names:
                k = strtobytes(x)
                v = dictlook(scaps, k)
                #log("server_info%s dictlook(%s)=%s", prop_names, k, v)
                if v is not None:
                    return v
                v = dictlook(self.client.server_last_info, k)
                if v is not None:
                    return v
            return None
        def server_version_info(prop_name):
            return make_version_str(server_info(prop_name))
        def make_revision_str(rev, changes):
            try:
                cint = int(changes)
            except (TypeError, ValueError):
                return rev
            else:
                return "%s (%s change%s)" % (rev, cint, engs(cint))
        def make_datetime(date, time):
            if not time:
                return bytestostr(date)
            return "%s %s" % (bytestostr(date), bytestostr(time))
        tb.new_row("Revision", slabel(make_revision_str(cl_rev, cl_ch)),
                               slabel(make_revision_str(self.client._remote_revision, server_version_info("build.local_modifications"))))
        tb.new_row("Build date", slabel(make_datetime(cl_date, cl_time)),
                                 slabel(make_datetime(server_info("build_date", "build.date"), server_info("build.time"))))
        gtk_version_info = get_gtk_version_info()
        def client_vinfo(prop, fallback="unknown"):
            s = make_version_str(newdictlook(gtk_version_info, (prop, "version"), fallback))
            return slabel(s)
        def server_vinfo(prop):
            k = "%s.version" % prop
            return slabel(server_version_info(k))
        tb.new_row("Glib",      client_vinfo("glib"),       server_vinfo("glib"))
        tb.new_row("PyGlib",    client_vinfo("pyglib"),     server_vinfo("pyglib"))
        tb.new_row("Gobject",   client_vinfo("gobject"),    server_vinfo("gobject"))
        tb.new_row("PyGTK",     client_vinfo("pygtk", ""),  server_vinfo("pygtk"))
        tb.new_row("GTK",       client_vinfo("gtk"),        server_vinfo("gtk"))
        tb.new_row("GDK",       client_vinfo("gdk"),        server_vinfo("gdk"))
        tb.new_row("Cairo",     client_vinfo("cairo"),      server_vinfo("cairo"))
        tb.new_row("Pango",     client_vinfo("pango"),      server_vinfo("pango"))
        tb.new_row("Python", slabel(python_platform.python_version()), slabel(server_version_info("server.python.version")))

        try:
            from xpra.sound.wrapper import query_sound
            props = query_sound()
        except Exception:
            log("cannot load sound information: %s", exc_info=True)
            props = typedict()
        gst_version = props.strlistget("gst.version")
        pygst_version = props.strlistget("pygst.version")
        tb.new_row("GStreamer", slabel(make_version_str(gst_version)), slabel(server_version_info("sound.gst.version")))
        tb.new_row("pygst", slabel(make_version_str(pygst_version)), slabel(server_version_info("sound.pygst.version")))
        def gllabel(prop="opengl", default_value="n/a"):
            return slabel(make_version_str(self.client.opengl_props.get(prop, default_value)))
        tb.new_row("OpenGL", gllabel("opengl", "n/a"), slabel(server_version_info("opengl.opengl")))
        tb.new_row("OpenGL Vendor", gllabel("vendor", ""), slabel(server_version_info("opengl.vendor")))
        tb.new_row("PyOpenGL", gllabel("pyopengl", "n/a"), slabel(server_version_info("opengl.pyopengl")))

        # Features Table:
        vbox = self.vbox_tab("features.png", "Features", self.populate_features)
        #add top table:
        tb = TableBuilder(rows=1, columns=2, row_spacings=15)
        table = tb.get_table()
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        vbox.pack_start(al, expand=True, fill=False, padding=10)
        #top table contents:
        randr_box = gtk.HBox(False, 20)
        self.server_randr_label = slabel()
        self.server_randr_icon = gtk.Image()
        randr_box.add(self.server_randr_icon)
        randr_box.add(self.server_randr_label)
        tb.new_row("RandR Support", randr_box)
        self.client_display = slabel()
        tb.new_row("Client Display", self.client_display)
        opengl_box = gtk.HBox(False, 20)
        self.client_opengl_label = slabel()
        self.client_opengl_label.set_line_wrap(True)
        self.client_opengl_icon = gtk.Image()
        opengl_box.add(self.client_opengl_icon)
        opengl_box.add(self.client_opengl_label)
        tb.new_row("Client OpenGL", opengl_box)
        self.opengl_buffering = slabel()
        tb.new_row("OpenGL Mode", self.opengl_buffering)
        self.window_rendering = slabel()
        tb.new_row("Window Rendering", self.window_rendering)
        self.server_mmap_icon = gtk.Image()
        tb.new_row("Memory Mapped Transfers", self.server_mmap_icon)
        self.server_clipboard_icon = gtk.Image()
        tb.new_row("Clipboard", self.server_clipboard_icon)
        self.server_notifications_icon = gtk.Image()
        tb.new_row("Notifications", self.server_notifications_icon)
        self.server_bell_icon = gtk.Image()
        tb.new_row("Bell", self.server_bell_icon)
        self.server_cursors_icon = gtk.Image()
        tb.new_row("Cursors", self.server_cursors_icon)

        # Codecs Table:
        vbox = self.vbox_tab("encoding.png", "Codecs", self.populate_codecs)
        tb = TableBuilder(rows=1, columns=2, col_spacings=0, row_spacings=10)
        table = tb.get_table()
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        vbox.pack_start(al, expand=True, fill=False, padding=10)
        #table headings:
        tb.attach(title_box(""), 0, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Client"), 1, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Server"), 2, xoptions=EXPAND|FILL, xpadding=0)
        tb.inc()
        #table contents:
        self.client_encodings_label = slabel()
        self.client_encodings_label.set_line_wrap(True)
        self.server_encodings_label = slabel()
        self.server_encodings_label.set_line_wrap(True)
        tb.new_row("Picture Encodings",
                   self.client_encodings_label, self.server_encodings_label,
                   xoptions=FILL|EXPAND, yoptions=FILL|EXPAND)
        self.client_speaker_codecs_label = slabel()
        self.client_speaker_codecs_label.set_line_wrap(True)
        self.server_speaker_codecs_label = slabel()
        self.server_speaker_codecs_label.set_line_wrap(True)
        tb.new_row("Speaker Codecs",
                   self.client_speaker_codecs_label, self.server_speaker_codecs_label,
                   xoptions=FILL|EXPAND, yoptions=FILL|EXPAND)
        self.client_microphone_codecs_label = slabel()
        self.client_microphone_codecs_label.set_line_wrap(True)
        self.server_microphone_codecs_label = slabel()
        self.server_microphone_codecs_label.set_line_wrap(True)
        tb.new_row("Microphone Codecs",
                   self.client_microphone_codecs_label, self.server_microphone_codecs_label,
                   xoptions=FILL|EXPAND, yoptions=FILL|EXPAND)
        self.client_packet_encoders_label = slabel()
        self.client_packet_encoders_label.set_line_wrap(True)
        self.server_packet_encoders_label = slabel()
        self.server_packet_encoders_label.set_line_wrap(True)
        tb.new_row("Packet Encoders",
                   self.client_packet_encoders_label, self.server_packet_encoders_label,
                   xoptions=FILL|EXPAND, yoptions=FILL|EXPAND)
        self.client_packet_compressors_label = slabel()
        self.server_packet_compressors_label = slabel()
        tb.new_row("Packet Compressors",
                   self.client_packet_compressors_label, self.server_packet_compressors_label,
                   xoptions=FILL|EXPAND, yoptions=FILL|EXPAND)

        # Connection Table:
        tb = self.table_tab("connect.png", "Connection", self.populate_connection)[0]
        if self.connection:
            tb.new_row("Server Endpoint", slabel(self.connection.target))
        if mixin_features.display and self.client.server_display:
            tb.new_row("Server Display", slabel(prettify_plug_name(self.client.server_display)))
        hostname = scaps.strget("hostname")
        if hostname:
            tb.new_row("Server Hostname", slabel(hostname))
        if self.client.server_platform:
            tb.new_row("Server Platform", slabel(self.client.server_platform))
        self.server_load_label = slabel()
        tb.new_row("Server Load", self.server_load_label, label_tooltip="Average over 1, 5 and 15 minutes")
        self.session_started_label = slabel()
        tb.new_row("Session Started", self.session_started_label)
        self.session_connected_label = slabel()
        tb.new_row("Session Connected", self.session_connected_label)
        self.input_packets_label = slabel()
        tb.new_row("Packets Received", self.input_packets_label)
        self.input_bytes_label = slabel()
        tb.new_row("Bytes Received", self.input_bytes_label)
        self.output_packets_label = slabel()
        tb.new_row("Packets Sent", self.output_packets_label)
        self.output_bytes_label = slabel()
        tb.new_row("Bytes Sent", self.output_bytes_label)
        self.compression_label = slabel()
        tb.new_row("Encoding + Compression", self.compression_label)
        self.connection_type_label = slabel()
        tb.new_row("Connection Type", self.connection_type_label)
        self.input_encryption_label = slabel()
        tb.new_row("Input Encryption", self.input_encryption_label)
        self.output_encryption_label = slabel()
        tb.new_row("Output Encryption", self.output_encryption_label)

        self.speaker_label = slabel()
        self.speaker_details = slabel(font="monospace 10")
        tb.new_row("Speaker", self.speaker_label, self.speaker_details)
        self.microphone_label = slabel()
        tb.new_row("Microphone", self.microphone_label)

        # Details:
        tb, stats_box = self.table_tab("browse.png", "Statistics", self.populate_statistics)
        tb.widget_xalign = 1.0
        tb.attach(title_box(""), 0, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Latest"), 1, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Minimum"), 2, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Average"), 3, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("90 percentile"), 4, xoptions=EXPAND|FILL, xpadding=0)
        tb.attach(title_box("Maximum"), 5, xoptions=EXPAND|FILL, xpadding=0)
        tb.inc()

        def maths_labels():
            return slabel(), slabel(), slabel(), slabel(), slabel()
        self.server_latency_labels = maths_labels()
        tb.add_row(slabel("Server Latency (ms)", "The time it takes for the server to respond to pings"),
                   *self.server_latency_labels)
        self.client_latency_labels = maths_labels()
        tb.add_row(slabel("Client Latency (ms)",
                          "The time it takes for the client to respond to pings, as measured by the server"),
                   *self.client_latency_labels)
        if mixin_features.windows and self.client.windows_enabled:
            self.batch_labels = maths_labels()
            tb.add_row(slabel("Batch Delay (MPixels / ms)",
                              "How long the server waits for new screen updates to accumulate before processing them"),
                       *self.batch_labels)
            self.damage_labels = maths_labels()
            tb.add_row(slabel("Damage Latency (ms)",
                              "The time it takes to compress a frame and pass it to the OS network layer"),
                       *self.damage_labels)
            self.quality_labels = maths_labels()
            tb.add_row(slabel("Encoding Quality (pct)",
                              "Automatic picture quality, average for all the windows"),
                              *self.quality_labels)
            self.speed_labels = maths_labels()
            tb.add_row(slabel("Encoding Speed (pct)",
                              "Automatic picture encoding speed (bandwidth vs CPU usage), average for all the windows"),
                              *self.speed_labels)

            self.decoding_labels = maths_labels()
            tb.add_row(slabel("Decoding Latency (ms)",
                              "How long it takes the client to decode a screen update"),
                              *self.decoding_labels)
            self.regions_per_second_labels = maths_labels()
            tb.add_row(slabel("Regions/s",
                              "The number of screen updates per second"
                              +" (includes both partial and full screen updates)"),
                              *self.regions_per_second_labels)
            self.regions_sizes_labels = maths_labels()
            tb.add_row(slabel("Pixels/region", "The number of pixels per screen update"), *self.regions_sizes_labels)
            self.pixels_per_second_labels = maths_labels()
            tb.add_row(slabel("Pixels/s", "The number of pixels processed per second"), *self.pixels_per_second_labels)

            #Window count stats:
            wtb = TableBuilder()
            stats_box.add(wtb.get_table())
            #title row:
            wtb.attach(title_box(""), 0, xoptions=EXPAND|FILL, xpadding=0)
            wtb.attach(title_box("Regular"), 1, xoptions=EXPAND|FILL, xpadding=0)
            wtb.attach(title_box("Transient"), 2, xoptions=EXPAND|FILL, xpadding=0)
            wtb.attach(title_box("Trays"), 3, xoptions=EXPAND|FILL, xpadding=0)
            if self.client.client_supports_opengl:
                wtb.attach(title_box("OpenGL"), 4, xoptions=EXPAND|FILL, xpadding=0)
            wtb.inc()

            wtb.attach(slabel("Windows:"), 0, xoptions=EXPAND|FILL, xpadding=0)
            self.windows_managed_label = slabel()
            wtb.attach(self.windows_managed_label, 1)
            self.transient_managed_label = slabel()
            wtb.attach(self.transient_managed_label, 2)
            self.trays_managed_label = slabel()
            wtb.attach(self.trays_managed_label, 3)
            if self.client.client_supports_opengl:
                self.opengl_label = slabel()
                wtb.attach(self.opengl_label, 4)

            #add encoder info:
            etb = TableBuilder()
            stats_box.add(etb.get_table())
            self.encoder_info_box = gtk.HBox(spacing=4)
            etb.new_row("Window Encoders", self.encoder_info_box)

        self.graph_box = gtk.VBox(False, 10)
        self.add_tab("statistics.png", "Graphs", self.populate_graphs, self.graph_box)
        bandwidth_label = "Bandwidth used"
        if SHOW_PIXEL_STATS:
            bandwidth_label += ",\nand number of pixels rendered"
        self.bandwidth_graph = self.add_graph_button(bandwidth_label, self.save_graph)
        self.latency_graph = self.add_graph_button(None, self.save_graph)
        if SHOW_SOUND_STATS:
            self.sound_queue_graph = self.add_graph_button(None, self.save_graph)
        else:
            self.sound_queue_graph = None
        self.connect("realize", self.populate_graphs)
        self.pixel_in_data = deque(maxlen=N_SAMPLES+4)
        self.net_in_bytecount = deque(maxlen=N_SAMPLES+4)
        self.net_out_bytecount = deque(maxlen=N_SAMPLES+4)
        self.sound_in_bitcount = deque(maxlen=N_SAMPLES+4)
        self.sound_out_bitcount = deque(maxlen=N_SAMPLES+4)
        self.sound_out_queue_min = deque(maxlen=N_SAMPLES*10+4)
        self.sound_out_queue_max = deque(maxlen=N_SAMPLES*10+4)
        self.sound_out_queue_cur  = deque(maxlen=N_SAMPLES*10+4)

        self.set_border_width(15)
        self.add(self.tab_box)
        if not is_gtk3():
            self.set_geometry_hints(self.tab_box)
        def window_deleted(*_args):
            self.is_closed = True
        self.connect('delete_event', window_deleted)
        self.show_tab(self.tabs[0][2])
        self.set_size_request(-1, -1)
        self.init_counters()
        self.populate()
        self.populate_all()
        glib.timeout_add(1000, self.populate)
        glib.timeout_add(100, self.populate_tab)
        if mixin_features.audio and SHOW_SOUND_STATS:
            glib.timeout_add(100, self.populate_sound_stats)
        add_close_accel(self, self.destroy)


    def table_tab(self, icon_filename, title, populate_cb):
        tb = TableBuilder()
        table = tb.get_table()
        vbox = self.vbox_tab(icon_filename, title, populate_cb)
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        vbox.pack_start(al, expand=True, fill=True, padding=20)
        return tb, vbox

    def vbox_tab(self, icon_filename, title, populate_cb):
        vbox = gtk.VBox(False, 0)
        self.add_tab(icon_filename, title, populate_cb, contents=vbox)
        return vbox


    def add_tab(self, icon_filename, title, populate_cb, contents):
        icon = self.get_pixbuf(icon_filename)
        def show_tab(*_args):
            self.show_tab(contents)
        button = imagebutton(title, icon, clicked_callback=show_tab)
        button.connect("clicked", show_tab)
        button.set_relief(RELIEF_NONE)
        self.tab_button_box.add(button)
        self.tabs.append((title, button, contents, populate_cb))

    def show_tab(self, table):
        button = None
        for _, b, t, p_cb in self.tabs:
            if t==table:
                button = b
                b.set_relief(RELIEF_NORMAL)
                b.grab_focus()
                self.populate_cb = p_cb
            else:
                b.set_relief(RELIEF_NONE)
        assert button
        for x in self.tab_box.get_children():
            if x!=self.tab_button_box:
                self.tab_box.remove(x)
        self.tab_box.pack_start(table, expand=True, fill=True, padding=0)
        table.show_all()
        #ensure we re-draw the whole window:
        window = self.get_window()
        if window:
            alloc = self.get_allocation()
            window.invalidate_rect(alloc, True)

    def set_args(self, *args):
        #this is a generic way for keyboard shortcuts or remote commands
        #to pass parameters to us
        log("set_args%s", args)
        if not args:
            return
        #at the moment, we only handle the tab name as argument:
        tab_name = args[0]
        if tab_name.lower()!="help":
            title = ""
            for title, _, table, _ in self.tabs:
                if title.lower()==tab_name.lower():
                    self.show_tab(table)
                    return
            log.warn("could not find session info tab named: %s", title)
        log.warn("The options for tab names are: %s)", [x[0] for x in self.tabs])

    def populate_all(self):
        for tab in self.tabs:
            p_cb = tab[3]
            if p_cb:
                p_cb()

    def add_graph_button(self, tooltip, click_cb):
        button = gtk.EventBox()
        def set_cursor(widget):
            if is_gtk3():
                cursor = gdk.Cursor.new(gdk.CursorType.BASED_ARROW_DOWN)
            else:
                cursor = gdk.Cursor(gdk.BASED_ARROW_DOWN)
            widget.get_window().set_cursor(cursor)
        button.connect("realize", set_cursor)
        graph = gtk.Image()
        graph.set_size_request(0, 0)
        button.connect("button_press_event", click_cb, graph)
        button.add(graph)
        if tooltip:
            graph.set_tooltip_text(tooltip)
        self.graph_box.add(button)
        return graph

    def bool_icon(self, image, on_off):
        if on_off:
            icon = self.get_pixbuf("ticked-small.png")
        else:
            icon = self.get_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)

    def populate_sound_stats(self, *_args):
        #runs every 100ms
        if self.is_closed:
            return False
        ss = self.client.sound_sink
        if SHOW_SOUND_STATS and ss:
            info = ss.get_info()
            if info:
                info = typedict(info)
                def qlookup(attr):
                    return int(newdictlook(info, ("queue", attr), 0))
                self.sound_out_queue_cur.append(qlookup("cur"))
                self.sound_out_queue_min.append(qlookup("min"))
                self.sound_out_queue_max.append(qlookup("max"))
        return not self.is_closed

    def populate(self, *_args):
        conn = self.connection
        if self.is_closed or not conn:
            return False
        self.client.send_ping()
        self.last_populate_time = monotonic_time()

        self.show_opengl_state()
        self.show_window_renderers()
        #record bytecount every second:
        self.net_in_bytecount.append(conn.input_bytecount)
        self.net_out_bytecount.append(conn.output_bytecount)
        if mixin_features.audio and SHOW_SOUND_STATS:
            if self.client.sound_in_bytecount>0:
                self.sound_in_bitcount.append(self.client.sound_in_bytecount * 8)
            if self.client.sound_out_bytecount>0:
                self.sound_out_bitcount.append(self.client.sound_out_bytecount * 8)

        if mixin_features.windows:
            #count pixels in the last second:
            since = monotonic_time()-1
            decoded = [0]+[pixels for _,t,pixels in self.client.pixel_counter if t>since]
            self.pixel_in_data.append(sum(decoded))
        #update latency values
        #there may be more than one record for each second
        #so we have to average them to prevent the graph from "jumping":
        def get_ping_latency_records(src, size=25):
            recs = {}
            src_list = list(src)
            now = int(monotonic_time())
            while src_list and len(recs)<size:
                when, value = src_list.pop()
                if when>=(now-1):           #ignore last second
                    continue
                iwhen = int(when)
                cv = recs.get(iwhen)
                v = 1000.0*value
                if cv:
                    v = (v+cv) / 2.0        #not very fair if more than 2 values... but this shouldn't happen anyway
                recs[iwhen] = v
            #ensure we always have a record for the last N seconds, even an empty one
            for x in range(size):
                i = now-2-x
                if i not in recs:
                    recs[i] = None
            return tuple(recs.get(x) for x in sorted(recs.keys()))
        self.server_latency = get_ping_latency_records(self.client.server_ping_latency)
        self.client_latency = get_ping_latency_records(self.client.client_ping_latency)
        if self.client.server_last_info:
            #populate running averages for graphs:
            def getavg(*names):
                return (
                    newdictlook(self.client.server_last_info, list(names)+["avg"]) or
                    newdictlook(self.client.server_last_info, ["client"]+list(names)+["avg"])
                    )
            def addavg(l, *names):
                v = getavg(*names)
                if v:
                    l.append(v)
            addavg(self.avg_batch_delay, "batch", "delay")
            addavg(self.avg_damage_out_latency, "damage", "out_latency")
            spl = tuple(1000.0*x[1] for x in tuple(self.client.server_ping_latency))
            cpl = tuple(1000.0*x[1] for x in tuple(self.client.client_ping_latency))
            if spl and cpl:
                self.avg_ping_latency.append(iround(sum(spl+cpl)/len(spl+cpl)))
            pc = tuple(self.client.pixel_counter)
            if mixin_features.windows and pc:
                tsize = 0
                ttime = 0
                for start_time, end_time, size in pc:
                    ttime += 1000.0 * (end_time-start_time) * size
                    tsize += size
                self.avg_decoding_latency.append(iround(ttime/tsize))
        #totals: ping latency is halved since we only care about sending, not sending+receiving
        els  = (
            (tuple(self.avg_batch_delay), 1),
            (tuple(self.avg_damage_out_latency), 1),
            (tuple(self.avg_ping_latency), 2),
            (tuple(self.avg_decoding_latency), 1),
            )
        if all(x[0] for x in els):
            totals = tuple(x[-1]/r for x, r in els)
            log("frame totals=%s", totals)
            self.avg_total.append(iround(sum(totals)))
        return not self.is_closed

    def init_counters(self):
        self.avg_batch_delay = deque(maxlen=N_SAMPLES+4)
        self.avg_damage_out_latency = deque(maxlen=N_SAMPLES+4)
        self.avg_ping_latency = deque(maxlen=N_SAMPLES+4)
        self.avg_decoding_latency = deque(maxlen=N_SAMPLES+4)
        self.avg_total = deque(maxlen=N_SAMPLES+4)

    def populate_tab(self, *_args):
        if self.is_closed:
            return False
        #now re-populate the tab we are seeing:
        if self.populate_cb:
            if not self.populate_cb():
                self.populate_cb = None
        return not self.is_closed

    def populate_package(self):
        return False


    def show_opengl_state(self):
        if self.client.opengl_enabled:
            glinfo = "%s / %s" % (
                self.client.opengl_props.get("vendor", ""),
                self.client.opengl_props.get("renderer", ""),
                )
            display_mode = self.client.opengl_props.get("display_mode", [])
            bit_depth = self.client.opengl_props.get("depth", 0)
            info = []
            if bit_depth:
                info.append("%i-bit" % bit_depth)
            if "DOUBLE" in display_mode:
                info.append("double buffering")
            elif "SINGLE" in display_mode:
                info.append("single buffering")
            else:
                info.append("unknown buffering")
            if "ALPHA" in display_mode:
                info.append("with transparency")
            else:
                info.append("without transparency")
        else:
            #info could be telling us that the gl bindings are missing:
            glinfo = self.client.opengl_props.get("info", "disabled")
            info = ["n/a"]
        self.client_opengl_label.set_text(glinfo)
        self.opengl_buffering.set_text(" ".join(info))

    def show_window_renderers(self):
        if not mixin_features.windows:
            return
        wr = []
        renderers = {}
        for wid, window in tuple(self.client._id_to_window.items()):
            renderers.setdefault(window.get_backing_class(), []).append(wid)
        for bclass, windows in renderers.items():
            wr.append("%s (%i)" % (bclass.__name__.replace("Backing", ""), len(windows)))
        self.window_rendering.set_text("GTK%s: %s" % (["2","3"][is_gtk3()], csv(wr)))

    def populate_features(self):
        size_info = ""
        if mixin_features.windows:
            if self.client.server_actual_desktop_size:
                w,h = self.client.server_actual_desktop_size
                size_info = "%sx%s" % (w,h)
                if self.client.server_randr and self.client.server_max_desktop_size:
                    size_info += " (max %s)" % ("x".join([str(x) for x in self.client.server_max_desktop_size]))
                self.bool_icon(self.server_randr_icon, self.client.server_randr)
        else:
            size_info = "unknown"
            unknown = self.get_pixbuf("unknown.png")
            if unknown:
                self.server_randr_icon.set_from_pixbuf(unknown)
        self.server_randr_label.set_text("%s" % size_info)
        root_w, root_h = self.client.get_root_size()
        if mixin_features.windows and (self.client.xscale!=1 or self.client.yscale!=1):
            sw, sh = self.client.cp(root_w, root_h)
            display_info = "%ix%i (scaled from %ix%i)" % (sw, sh, root_w, root_h)
        else:
            display_info = "%ix%i" % (root_w, root_h)
        self.client_display.set_text(display_info)
        self.bool_icon(self.client_opengl_icon, self.client.client_supports_opengl)

        scaps = self.client.server_capabilities
        self.show_window_renderers()
        self.bool_icon(self.server_mmap_icon, self.client.mmap_enabled)
        self.bool_icon(self.server_clipboard_icon,      scaps.boolget("clipboard", False))
        self.bool_icon(self.server_notifications_icon,  scaps.boolget("notifications", False))
        self.bool_icon(self.server_bell_icon,           scaps.boolget("bell", False))
        self.bool_icon(self.server_cursors_icon,        scaps.boolget("cursors", False))

    def populate_codecs(self):
        #clamp the large labels so they will overflow vertically:
        w = get_preferred_size(self.tab_box)[0]
        lw = max(200, int(w//2.5))
        self.client_encodings_label.set_size_request(lw, -1)
        self.server_encodings_label.set_size_request(lw, -1)
        self.client_speaker_codecs_label.set_size_request(lw, -1)
        self.server_speaker_codecs_label.set_size_request(lw, -1)
        self.client_microphone_codecs_label.set_size_request(lw, -1)
        self.server_microphone_codecs_label.set_size_request(lw, -1)
        self.client_packet_encoders_label.set_size_request(lw, -1)
        self.server_packet_encoders_label.set_size_request(lw, -1)
        #sound/video codec table:
        scaps = self.client.server_capabilities
        def codec_info(enabled, codecs):
            if not enabled:
                return "n/a"
            return ", ".join(codecs or [])
        if mixin_features.audio:
            self.server_speaker_codecs_label.set_text(codec_info(scaps.boolget("sound.send", False), scaps.strlistget("sound.encoders", [])))
            self.client_speaker_codecs_label.set_text(codec_info(self.client.speaker_allowed, self.client.speaker_codecs))
            self.server_microphone_codecs_label.set_text(codec_info(scaps.boolget("sound.receive", False), scaps.strlistget("sound.decoders", [])))
            self.client_microphone_codecs_label.set_text(codec_info(self.client.microphone_allowed, self.client.microphone_codecs))
        def encliststr(v):
            v = list(v)
            try:
                v.remove("rgb")
            except ValueError:
                pass
            return csv(sorted(v))
        se = scaps.strlistget("encodings.core", scaps.strlistget("encodings"))
        self.server_encodings_label.set_text(encliststr(se))
        if mixin_features.encoding:
            self.client_encodings_label.set_text(encliststr(self.client.get_core_encodings()))
        else:
            self.client_encodings_label.set_text("n/a")

        def get_encoder_list(caps):
            from xpra.net import packet_encoding
            return [x for x in packet_encoding.ALL_ENCODERS if typedict(caps).rawget(x)]
        self.client_packet_encoders_label.set_text(", ".join(get_encoder_list(get_network_caps())))
        self.server_packet_encoders_label.set_text(", ".join(get_encoder_list(self.client.server_capabilities)))

        def get_compressor_list(caps):
            from xpra.net import compression
            return [x for x in compression.ALL_COMPRESSORS if typedict(caps).rawget(x)]
        self.client_packet_compressors_label.set_text(", ".join(get_compressor_list(get_network_caps())))
        self.server_packet_compressors_label.set_text(", ".join(get_compressor_list(self.client.server_capabilities)))
        return False

    def populate_connection(self):
        def settimedeltastr(label, from_time):
            import time
            delta = datetime.timedelta(seconds=(int(time.time())-int(from_time)))
            label.set_text(str(delta))
        if self.client.server_load:
            self.server_load_label.set_text("  ".join("%.1f" % (x/1000.0) for x in self.client.server_load))
        if self.client.server_start_time>0:
            settimedeltastr(self.session_started_label, self.client.server_start_time)
        else:
            self.session_started_label.set_text("unknown")
        settimedeltastr(self.session_connected_label, self.client.start_time)

        p = self.client._protocol
        if p is None:
            #no longer connected!
            return False
        c = p._conn
        if c:
            self.input_packets_label.set_text(std_unit_dec(p.input_packetcount))
            self.input_bytes_label.set_text(std_unit_dec(c.input_bytecount))
            self.output_packets_label.set_text(std_unit_dec(p.output_packetcount))
            self.output_bytes_label.set_text(std_unit_dec(c.output_bytecount))
        else:
            for l in (
                self.input_packets_label,
                self.input_bytes_label,
                self.output_packets_label,
                self.output_bytes_label,
                ):
                l.set_text("n/a")

        if mixin_features.audio:
            def get_sound_info(supported, prop):
                if not supported:
                    return {"state" : "disabled"}
                if prop is None:
                    return {"state" : "inactive"}
                return prop.get_info()
            def set_sound_info(label, details, supported, prop):
                d = typedict(get_sound_info(supported, prop))
                state = d.strget("state", "")
                codec_descr = d.strget("codec") or d.strget("codec_description")
                container_descr = d.strget("container_description", "")
                if state=="active" and codec_descr:
                    if codec_descr.find(container_descr)>=0:
                        descr = codec_descr
                    else:
                        descr = csv(x for x in (codec_descr, container_descr) if x)
                    state = "%s: %s" % (state, descr)
                label.set_text(state)
                if details:
                    s = ""
                    bitrate = d.intget("bitrate", 0)
                    if bitrate>0:
                        s = "%sbit/s" % std_unit(bitrate)
                    details.set_text(s)
            set_sound_info(self.speaker_label, self.speaker_details, self.client.speaker_enabled, self.client.sound_sink)
            set_sound_info(self.microphone_label, None, self.client.microphone_enabled, self.client.sound_source)

        self.connection_type_label.set_text(c.socktype)
        protocol_info = p.get_info()
        encoder = protocol_info.get("encoder", "bug")
        compressor = protocol_info.get("compressor", "none")
        level = protocol_info.get("compression_level", 0)
        compression_str = encoder + " + "+compressor
        if level>0:
            compression_str += " (level %s)" % level
        self.compression_label.set_text(compression_str)

        def enclabel(label, cipher):
            if not cipher:
                info = "None"
            else:
                info = str(cipher)
            if c.socktype.lower()=="ssh":
                info += " (%s)" % c.socktype
            ncaps = get_network_caps()
            backend = ncaps.get("backend")
            if backend=="python-cryptography":
                info += " / python-cryptography"
            label.set_text(info)
        enclabel(self.input_encryption_label, p.cipher_in_name)
        enclabel(self.output_encryption_label, p.cipher_out_name)
        return True


    def getval(self, prefix, suffix, alt=""):
        if self.client.server_last_info is None:
            return ""
        altv = ""
        if alt:
            altv = dictlook(self.client.server_last_info, (alt+"."+suffix).encode(), "")
        return dictlook(self.client.server_last_info, (prefix+"."+suffix).encode(), altv)

    def values_from_info(self, prefix, alt=None):
        def getv(suffix):
            return self.getval(prefix, suffix, alt)
        return getv("cur"), getv("min"), getv("avg"), getv("90p"), getv("max")

    def all_values_from_info(self, *window_props):
        #newer (2.4 and later) servers can just give us the value directly:
        for window_prop in window_props:
            prop_path = "client.%s" % window_prop
            v = dictlook(self.client.server_last_info, prop_path)
            if v is not None:
                try:
                    v = typedict(v)
                except TypeError:
                    #backwards compatibility:
                    #older servers don't expose the correct value or type here
                    #so don't use this value
                    log("expected dictionary for %s", prop_path)
                    log(" got %s: %s", type(v), v)
                else:
                    iget = v.intget
                    return iget("cur"), iget("min"), iget("avg"), iget("90p"), iget("max")

        #legacy servers: sum up the values for all the windows found
        def avg(values):
            if not values:
                return ""
            return sum(values) // len(values)
        def getv(suffix, op):
            if self.client.server_last_info is None:
                return ""
            values = []
            for wid in self.client._window_to_id.values():
                for window_prop in window_props:
                    #Warning: this is ugly...
                    proppath = "window[%s].%s.%s" % (wid, window_prop, suffix)
                    v = self.client.server_last_info.get(proppath)
                    if v is None:
                        wprop = window_prop.split(".")              #ie: "encoding.speed" -> ["encoding", "speed"]
                        newpath = ["window", wid]+wprop+[suffix]    #ie: ["window", 1, "encoding", "speed", "cur"]
                        v = newdictlook(self.client.server_last_info, newpath)
                    if v is not None:
                        values.append(v)
                        break
            if not values:
                return ""
            try:
                return op(values)
            except (TypeError, ValueError):
                log("%s(%s)", op, values, exc_info=True)
                return ""
        return getv("cur", avg), getv("min", min), getv("avg", avg), getv("90p", avg), getv("max", max)

    def populate_statistics(self):
        log("populate_statistics()")
        if monotonic_time()-self.last_populate_statistics<1.0:
            #don't repopulate more than every second
            return True
        self.last_populate_statistics = monotonic_time()
        self.client.send_info_request()
        def setall(labels, values):
            assert len(labels)==len(values), "%s labels and %s values (%s vs %s)" % (
                len(labels), len(values), labels, values)
            for i, l in enumerate(labels):
                l.set_text(str(values[i]))
        def setlabels(labels, values, rounding=int):
            if not values:
                return
            avg = sum(values)/len(values)
            svalues = sorted(values)
            l = len(svalues)
            assert l>0
            if l<10:
                index = l-1
            else:
                index = int(l*90/100)
            index = max(0, min(l-1, index))
            pct = svalues[index]
            disp = values[-1], min(values), avg, pct, max(values)
            rounded_values = [rounding(v) for v in disp]
            setall(labels, rounded_values)

        if self.client.server_ping_latency:
            spl = tuple(int(1000*x[1]) for x in tuple(self.client.server_ping_latency))
            setlabels(self.server_latency_labels, spl)
        if self.client.client_ping_latency:
            cpl = tuple(int(1000*x[1]) for x in tuple(self.client.client_ping_latency))
            setlabels(self.client_latency_labels, cpl)
        if mixin_features.windows and self.client.windows_enabled:
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
                    decoding_latency.append(int(1000.0*(end_time-start_time)))
                    region_sizes.append(size)
                    if min_time is None or min_time>end_time:
                        min_time = end_time
                    if max_time is None or max_time<end_time:
                        max_time = end_time
                    time_in_seconds = int(end_time)
                    regions = regions_per_second.get(time_in_seconds, 0)
                    regions_per_second[time_in_seconds] = regions+1
                    pixels = pixels_per_second.get(time_in_seconds, 0)
                    pixels_per_second[time_in_seconds] = pixels + size
                if int(min_time)+1 < int(max_time):
                    for t in range(int(min_time)+1, int(max_time)):
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
                    transient +=1
                else:
                    windows += 1
                if w.is_GL():
                    gl += 1
            self.windows_managed_label.set_text(str(windows))
            self.transient_managed_label.set_text(str(transient))
            self.trays_managed_label.set_text(str(trays))
            if self.client.client_supports_opengl:
                self.opengl_label.set_text(str(gl))

            #remove all the current labels:
            for x in self.encoder_info_box.get_children():
                self.encoder_info_box.remove(x)
            if self.client.server_last_info:
                window_encoder_stats = self.get_window_encoder_stats()
                #log("window_encoder_stats=%s", window_encoder_stats)
                for wid, props in window_encoder_stats.items():
                    l = slabel("%s (%s)" % (wid, bytestostr(props.get(""))))
                    l.show()
                    info = ("%s=%s" % (k,v) for k,v in props.items() if k!="")
                    l.set_tooltip_text(" ".join(info))
                    self.encoder_info_box.add(l)
        return True

    def get_window_encoder_stats(self):
        window_encoder_stats = {}
        #new-style server with namespace (easier):
        window_dict = self.client.server_last_info.get("window")
        if window_dict and isinstance(window_dict, dict):
            for k,v in window_dict.items():
                try:
                    wid = int(k)
                    encoder_stats = v.get("encoder")
                    if encoder_stats:
                        window_encoder_stats[wid] = encoder_stats
                except Exception:
                    log.error("Error: cannot lookup window dict", exc_info=True)
        return window_encoder_stats


    def set_graph_surface(self, graph, surface):
        w = surface.get_width()
        h = surface.get_height()
        graph.set_size_request(w, h)
        graph.surface = surface
        if is_gtk3():
            graph.set_from_surface(surface)
        else:
            pixmap = gdk.Pixmap(None, w, h, 24)
            context = pixmap.cairo_create()
            context.set_source_surface(surface)
            context.paint()
            graph.set_from_pixmap(pixmap, None)

    def populate_graphs(self, *_args):
        #older servers have 'batch' at top level,
        #newer servers store it under client
        self.client.send_info_request("network", "damage", "state", "batch", "client")
        box = self.tab_box
        h = get_preferred_size(box)[1]
        bh = get_preferred_size(self.tab_button_box)[1]
        if h<=0:
            return True
        start_x_offset = min(1.0, (monotonic_time()-self.last_populate_time)*0.95)
        rect = box.get_allocation()
        maxw, maxh = self.client.get_root_size()
        ngraphs = 2+int(SHOW_SOUND_STATS)
        #the preferred size (which does not cause the window to grow too big):
        W = 360
        H = 160*3//ngraphs
        w = min(maxw, max(W, rect.width-20))
        #need some padding to be able to shrink the window again:
        pad = 50
        h = min(maxh-pad//ngraphs, max(H, (h-bh-pad)//ngraphs, (rect.height-bh-pad)//ngraphs))
        #bandwidth graph:
        labels, datasets = [], []
        if self.net_in_bytecount and self.net_out_bytecount:
            def unit(scale):
                if scale==1:
                    return ""
                unit, value = to_std_unit(scale)
                if value==1:
                    return str(unit)
                return "x%s%s" % (int(value), unit)
            net_in_scale, net_in_data = values_to_diff_scaled_values(tuple(self.net_in_bytecount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)
            net_out_scale, net_out_data = values_to_diff_scaled_values(tuple(self.net_out_bytecount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)
            if SHOW_RECV:
                labels += ["recv %sB/s" % unit(net_in_scale), "sent %sB/s" % unit(net_out_scale)]
                datasets += [net_in_data, net_out_data]
            else:
                labels += ["recv %sB/s" % unit(net_in_scale)]
                datasets += [net_in_data]
        if mixin_features.windows and SHOW_PIXEL_STATS and self.client.windows_enabled:
            pixel_scale, in_pixels = values_to_scaled_values(tuple(self.pixel_in_data)[3:N_SAMPLES+4], min_scaled_value=100)
            datasets.append(in_pixels)
            labels.append("%s pixels/s" % unit(pixel_scale))
        if mixin_features.audio and SHOW_SOUND_STATS and self.sound_in_bitcount:
            sound_in_scale, sound_in_data = values_to_diff_scaled_values(tuple(self.sound_in_bitcount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)
            datasets.append(sound_in_data)
            labels.append("Speaker %sb/s" % unit(sound_in_scale))
        if mixin_features.audio and SHOW_SOUND_STATS and self.sound_out_bitcount:
            sound_out_scale, sound_out_data = values_to_diff_scaled_values(tuple(self.sound_out_bitcount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)
            datasets.append(sound_out_data)
            labels.append("Mic %sb/s" % unit(sound_out_scale))

        if labels and datasets:
            surface = make_graph_imagesurface(datasets, labels=labels,
                                              width=w, height=h,
                                              title="Bandwidth", min_y_scale=10, rounding=10,
                                              start_x_offset=start_x_offset)
            self.set_graph_surface(self.bandwidth_graph, surface)

        def norm_lists(items, size=N_SAMPLES):
            #ensures we always have exactly 20 values,
            #(and skip if we don't have any)
            values, labels = [], []
            for l, name in items:
                if not l:
                    continue
                l = list(l)
                if len(l)<size:
                    for _ in range(size-len(l)):
                        l.insert(0, None)
                else:
                    l = l[:size]
                values.append(l)
                labels.append(name)
            return values, labels

        #latency graph:
        latency_values, latency_labels = norm_lists(
            (
                (self.avg_ping_latency,         "network"),
                (self.avg_batch_delay,          "batch delay"),
                (self.avg_damage_out_latency,   "encode&send"),
                (self.avg_decoding_latency,     "decoding"),
                (self.avg_total,                "frame total"),
            ))
        #debug:
        #for i, v in enumerate(latency_values):
        #    log.warn("%20s = %s", latency_labels[i], v)
        surface = make_graph_imagesurface(latency_values, labels=latency_labels,
                                          width=w, height=h,
                                          title="Latency (ms)", min_y_scale=10, rounding=25,
                                          start_x_offset=start_x_offset)
        self.set_graph_surface(self.latency_graph, surface)

        if mixin_features.audio and SHOW_SOUND_STATS and self.client.sound_sink:
            #sound queue graph:
            queue_values, queue_labels = norm_lists(
                (
                    (self.sound_out_queue_max, "Max"),
                    (self.sound_out_queue_cur, "Level"),
                    (self.sound_out_queue_min, "Min"),
                    ), N_SAMPLES*10)
            surface = make_graph_imagesurface(queue_values, labels=queue_labels,
                                              width=w, height=h,
                                              title="Sound Buffer (ms)", min_y_scale=10, rounding=25,
                                              start_x_offset=start_x_offset)
            self.set_graph_surface(self.sound_queue_graph, surface)
        return True

    def save_graph(self, _ebox, btn, graph):
        log("save_graph%s", (btn, graph))
        chooser = gtk.FileChooserDialog("Save graph as a PNG image",
                                    parent=self, action=FILE_CHOOSER_ACTION_SAVE,
                                    buttons=(gtk.STOCK_CANCEL, RESPONSE_CANCEL, gtk.STOCK_SAVE, RESPONSE_OK))
        chooser.set_select_multiple(False)
        chooser.set_default_response(RESPONSE_OK)
        file_filter = gtk.FileFilter()
        file_filter.set_name("PNG")
        file_filter.add_pattern("*.png")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filenames = chooser.get_filenames()
        chooser.hide()
        chooser.destroy()
        if response == RESPONSE_OK:
            if len(filenames)==1:
                filename = filenames[0]
                surface = graph.surface
                log("saving surface %s to %s", surface, filename)
                with open(filename, "wb") as f:
                    surface.write_to_png(f)
        elif response in (RESPONSE_CANCEL, RESPONSE_CLOSE, RESPONSE_DELETE_EVENT):
            log("closed/cancelled")
        else:
            log.warn("unknown chooser response: %d" % response)

    def destroy(self, *args):
        log("SessionInfo.destroy(%s) is_closed=%s", args, self.is_closed)
        self.is_closed = True
        gtk.Window.destroy(self)
        log("SessionInfo.destroy(%s) done", args)
