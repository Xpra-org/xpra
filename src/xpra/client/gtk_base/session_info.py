# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
import sys
import time
import datetime

from xpra.os_util import os_info
from xpra.gtk_common.graph import make_graph_pixmap
from xpra.deque import maxdeque
from xpra.simple_stats import values_to_scaled_values, values_to_diff_scaled_values, to_std_unit, std_unit_dec
from xpra.scripts.config import python_platform
from xpra.log import Logger
from xpra.gtk_common.gtk_util import add_close_accel, label, title_box, set_tooltip_text, TableBuilder, imagebutton
from xpra.net.protocol import get_network_caps
log = Logger()

N_SAMPLES = 20      #how many sample points to show on the graphs
SHOW_PIXEL_STATS = True


def pixelstr(v):
    if v<0:
        return  "n/a"
    return std_unit_dec(v)
def fpsstr(v):
    if v<0:
        return  "n/a"
    return "%s" % (int(v*10)/10.0)

def average(seconds, pixel_counter):
    now = time.time()
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
            title = "Session Info"
        else:
            title = "%s: Session Info" % self.session_name
        self.set_title(title)
        self.set_destroy_with_parent(True)
        self.set_resizable(True)
        self.set_decorated(True)
        if window_icon_pixbuf:
            self.set_icon(window_icon_pixbuf)
        if is_gtk3():
            self.set_position(gtk.WindowPosition.CENTER)
        else:
            self.set_position(gtk.WIN_POS_CENTER)

        #tables on the left in a vbox with buttons at the top:
        self.tab_box = gtk.VBox(False, 0)
        self.tab_button_box = gtk.HBox(True, 0)
        self.tabs = []          #pairs of button, table
        self.populate_cb = None
        self.tab_box.pack_start(self.tab_button_box, expand=False, fill=True, padding=0)

        #Package Table:
        tb, _ = self.table_tab("package.png", "Software", self.populate_package)
        #title row:
        tb.attach(title_box(""), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Client"), 1, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Server"), 2, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.inc()

        def make_os_str(*args):
            s = os_info(*args)
            return "\n".join(s)
        LOCAL_PLATFORM_NAME = make_os_str(sys.platform, python_platform.release(), python_platform.platform(), python_platform.linux_distribution())
        SERVER_PLATFORM_NAME = make_os_str(self.client._remote_platform, self.client._remote_platform_release, self.client._remote_platform_platform, self.client._remote_platform_linux_distribution)
        tb.new_row("Operating System", label(LOCAL_PLATFORM_NAME), label(SERVER_PLATFORM_NAME))
        scaps = self.client.server_capabilities
        from xpra.__init__ import __version__
        tb.new_row("Xpra", label(__version__), label(self.client._remote_version or "unknown"))
        cl_rev, cl_ch, cl_date = "unknown", "", ""
        try:
            from xpra.build_info import BUILD_DATE as cl_date
            from xpra.src_info import REVISION as cl_rev, LOCAL_MODIFICATIONS as cl_ch      #@UnresolvedImport
        except:
            pass
        def make_version_str(version):
            if version and type(version) in (tuple, list):
                version = ".".join([str(x) for x in version])
            return version or "unknown"
        def server_info(*prop_names):
            for x in prop_names:
                v = scaps.get(x)
                if v is not None:
                    return v
                if self.client.server_last_info:
                    v = self.client.server_last_info.get(x)
                if v is not None:
                    return v
            return None
        def server_version_info(*prop_names):
            return make_version_str(server_info(*prop_names))
        tb.new_row("Revision", label(cl_rev), label(make_version_str(self.client._remote_revision)))
        tb.new_row("Local Changes", label(cl_ch), label(server_version_info("build.local_modifications", "local_modifications")))
        tb.new_row("Build date", label(cl_date), label(server_info("build_date", "build.date")))
        def client_version_info(prop_name):
            info = "unknown"
            if hasattr(gtk, prop_name):
                info = make_version_str(getattr(gtk, prop_name))
            return info
        if is_gtk3():
            tb.new_row("PyGobject", label(gobject._version))
            tb.new_row("Client GDK", label(gdk._version))
            tb.new_row("GTK", label(gtk._version), label(server_version_info("gtk_version")))
        else:
            tb.new_row("PyGTK", label(client_version_info("pygtk_version")), label(server_version_info("pygtk.version", "pygtk_version")))
            tb.new_row("GTK", label(client_version_info("gtk_version")), label(server_version_info("gtk.version", "gtk_version")))
        tb.new_row("Python", label(python_platform.python_version()), label(server_version_info("server.python.version", "python_version", "python.version")))

        cl_gst_v, cl_pygst_v = "", ""
        try:
            from xpra.sound.gstreamer_util import gst_version as cl_gst_v, pygst_version as cl_pygst_v
        except Exception, e:
            log("cannot load gstreamer: %s", e)
        tb.new_row("GStreamer", label(make_version_str(cl_gst_v)), label(server_version_info("sound.gst.version", "gst_version")))
        tb.new_row("pygst", label(make_version_str(cl_pygst_v)), label(server_version_info("sound.pygst.version", "pygst_version")))
        tb.new_row("OpenGL", label(make_version_str(self.client.opengl_props.get("opengl", "n/a"))), label("n/a"))
        tb.new_row("OpenGL Vendor", label(make_version_str(self.client.opengl_props.get("vendor", ""))), label("n/a"))
        tb.new_row("PyOpenGL", label(make_version_str(self.client.opengl_props.get("pyopengl", "n/a"))), label("n/a"))

        # Features Table:
        vbox = self.vbox_tab("features.png", "Features", self.populate_features)
        #add top table:
        tb = TableBuilder(rows=1, columns=2)
        table = tb.get_table()
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        vbox.pack_start(al, expand=True, fill=False, padding=10)
        #top table contents:
        randr_box = gtk.HBox(False, 20)
        self.server_randr_label = label()
        self.server_randr_icon = gtk.Image()
        randr_box.add(self.server_randr_icon)
        randr_box.add(self.server_randr_label)
        tb.new_row("RandR Support", randr_box)
        opengl_box = gtk.HBox(False, 20)
        self.client_opengl_label = label()
        self.client_opengl_label.set_line_wrap(True)
        self.client_opengl_icon = gtk.Image()
        opengl_box.add(self.client_opengl_icon)
        opengl_box.add(self.client_opengl_label)
        tb.new_row("Client OpenGL", opengl_box)
        self.opengl_buffering = label()
        tb.new_row("OpenGL Buffering", self.opengl_buffering)
        self.server_mmap_icon = gtk.Image()
        tb.new_row("Memory Mapped Transfers", self.server_mmap_icon)
        self.server_clipboard_icon = gtk.Image()
        tb.new_row("Clipboard", self.server_clipboard_icon)
        self.server_notifications_icon = gtk.Image()
        tb.new_row("Notification Forwarding", self.server_notifications_icon)
        self.server_bell_icon = gtk.Image()
        tb.new_row("Bell Forwarding", self.server_bell_icon)
        self.server_cursors_icon = gtk.Image()
        tb.new_row("Cursor Forwarding", self.server_cursors_icon)
        speaker_box = gtk.HBox(False, 20)
        self.server_speaker_icon = gtk.Image()
        speaker_box.add(self.server_speaker_icon)
        self.speaker_codec_label = label()
        speaker_box.add(self.speaker_codec_label)
        tb.new_row("Speaker Forwarding", speaker_box)
        microphone_box = gtk.HBox(False, 20)
        self.server_microphone_icon = gtk.Image()
        microphone_box.add(self.server_microphone_icon)
        self.microphone_codec_label = label()
        microphone_box.add(self.microphone_codec_label)
        tb.new_row("Microphone Forwarding", microphone_box)
        #add bottom table:
        tb = TableBuilder(rows=1, columns=3)
        table = tb.get_table()
        vbox.pack_start(table, expand=True, fill=True, padding=20)
        #bottom table headings:
        tb.attach(title_box(""), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Client"), 1, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Server"), 2, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.inc()
        #bottom table contents:
        self.client_encodings_label = label()
        self.client_encodings_label.set_line_wrap(True)
        self.client_encodings_label.set_size_request(250, -1)
        self.server_encodings_label = label()
        self.server_encodings_label.set_line_wrap(True)
        self.server_encodings_label.set_size_request(250, -1)
        tb.new_row("Encodings", self.client_encodings_label, self.server_encodings_label)
        self.client_speaker_codecs_label = label()
        self.server_speaker_codecs_label = label()
        tb.new_row("Speaker Codecs", self.client_speaker_codecs_label, self.server_speaker_codecs_label)
        self.client_microphone_codecs_label = label()
        self.server_microphone_codecs_label = label()
        tb.new_row("Microphone Codecs", self.client_microphone_codecs_label, self.server_microphone_codecs_label)
        self.client_packet_encoders_label = label()
        self.server_packet_encoders_label = label()
        tb.new_row("Packet Encoders", self.client_packet_encoders_label, self.server_packet_encoders_label)
        self.client_packet_compressors_label = label()
        self.server_packet_compressors_label = label()
        tb.new_row("Packet Compressors", self.client_packet_compressors_label, self.server_packet_compressors_label)

        # Connection Table:
        tb, _ = self.table_tab("connect.png", "Connection", self.populate_connection)
        tb.new_row("Server Endpoint", label(self.connection.target))
        if self.client.server_display:
            tb.new_row("Server Display", label(self.client.server_display))
        if "hostname" in scaps:
            tb.new_row("Server Hostname", label(scaps.get("hostname")))
        if self.client.server_platform:
            tb.new_row("Server Platform", label(self.client.server_platform))
        self.server_load_label = label()
        tb.new_row("Server Load", self.server_load_label, label_tooltip="Average over 1, 5 and 15 minutes")
        self.session_started_label = label()
        tb.new_row("Session Started", self.session_started_label)
        self.session_connected_label = label()
        tb.new_row("Session Connected", self.session_connected_label)
        self.input_packets_label = label()
        tb.new_row("Packets Received", self.input_packets_label)
        self.input_bytes_label = label()
        tb.new_row("Bytes Received", self.input_bytes_label)
        self.output_packets_label = label()
        tb.new_row("Packets Sent", self.output_packets_label)
        self.output_bytes_label = label()
        tb.new_row("Bytes Sent", self.output_bytes_label)
        self.compression_label = label()
        tb.new_row("Compression + Encoding", self.compression_label)
        self.connection_type_label = label()
        tb.new_row("Connection Type", self.connection_type_label)
        self.input_encryption_label = label()
        tb.new_row("Input Encryption", self.input_encryption_label)
        self.output_encryption_label = label()
        tb.new_row("Output Encryption", self.output_encryption_label)

        self.speaker_label = label()
        self.speaker_details = label(font="monospace 10")
        tb.new_row("Speaker", self.speaker_label, self.speaker_details)
        self.microphone_label = label()
        tb.new_row("Microphone", self.microphone_label)

        # Details:
        tb, stats_box = self.table_tab("browse.png", "Statistics", self.populate_statistics)
        tb.widget_xalign = 1.0
        tb.attach(title_box(""), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Latest"), 1, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Minimum"), 2, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Average"), 3, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("90 percentile"), 4, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Maximum"), 5, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.inc()

        def maths_labels():
            return label(), label(), label(), label(), label()
        self.server_latency_labels = maths_labels()
        tb.add_row(label("Server Latency (ms)", "The time it takes for the server to respond to pings"),
                   *self.server_latency_labels)
        self.client_latency_labels = maths_labels()
        tb.add_row(label("Client Latency (ms)", "The time it takes for the client to respond to pings, as measured by the server"),
                   *self.client_latency_labels)
        if self.client.windows_enabled:
            if self.client.server_info_request:
                self.batch_labels = maths_labels()
                tb.add_row(label("Batch Delay (ms)", "How long the server waits for new screen updates to accumulate before processing them"),
                           *self.batch_labels)
                self.damage_labels = maths_labels()
                tb.add_row(label("Damage Latency (ms)", "The time it takes to compress a frame and pass it to the OS network layer"),
                           *self.damage_labels)
                self.quality_labels = maths_labels()
                tb.add_row(label("Encoding Quality (pct)"), *self.quality_labels)
                self.speed_labels = maths_labels()
                tb.add_row(label("Encoding Speed (pct)"), *self.speed_labels)

            self.decoding_labels = maths_labels()
            tb.add_row(label("Decoding Latency (ms)", "How long it takes the client to decode a screen update"), *self.decoding_labels)
            self.regions_per_second_labels = maths_labels()
            tb.add_row(label("Regions/s", "The number of screen updates per second (includes both partial and full screen updates)"), *self.regions_per_second_labels)
            self.regions_sizes_labels = maths_labels()
            tb.add_row(label("Pixels/region", "The number of pixels per screen update"), *self.regions_sizes_labels)
            self.pixels_per_second_labels = maths_labels()
            tb.add_row(label("Pixels/s", "The number of pixels processed per second"), *self.pixels_per_second_labels)

            #Window count stats:
            wtb = TableBuilder()
            stats_box.add(wtb.get_table())
            #title row:
            wtb.attach(title_box(""), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            wtb.attach(title_box("Regular"), 1, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            wtb.attach(title_box("Transient"), 2, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            wtb.attach(title_box("Trays"), 3, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            if self.client.client_supports_opengl:
                wtb.attach(title_box("OpenGL"), 4, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            wtb.inc()

            wtb.attach(label("Windows:"), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
            self.windows_managed_label = label()
            wtb.attach(self.windows_managed_label, 1)
            self.transient_managed_label = label()
            wtb.attach(self.transient_managed_label, 2)
            self.trays_managed_label = label()
            wtb.attach(self.trays_managed_label, 3)
            if self.client.client_supports_opengl:
                self.opengl_label = label()
                wtb.attach(self.opengl_label, 4)

            #add encoder info:
            etb = TableBuilder()
            stats_box.add(etb.get_table())
            self.encoder_info_box = gtk.HBox(spacing=4)
            etb.new_row("Window Encoders", self.encoder_info_box)

        self.graph_box = gtk.VBox(False, 10)
        self.add_tab("statistics.png", "Graphs", self.populate_graphs, self.graph_box)
        bandwidth_label = "Number of bytes measured by the networks sockets"
        if SHOW_PIXEL_STATS:
            bandwidth_label += ",\nand number of pixels rendered"
        self.bandwidth_graph = self.add_graph_button(bandwidth_label, self.save_graphs)
        self.latency_graph = self.add_graph_button("The time it takes to send an echo packet and get the reply", self.save_graphs)
        self.pixel_in_data = maxdeque(N_SAMPLES+4)
        self.net_in_bytecount = maxdeque(N_SAMPLES+4)
        self.net_out_bytecount = maxdeque(N_SAMPLES+4)

        self.set_border_width(15)
        self.add(self.tab_box)
        if not is_gtk3():
            self.set_geometry_hints(self.tab_box)
        def window_deleted(*args):
            self.is_closed = True
        self.connect('delete_event', window_deleted)
        self.show_tab(self.tabs[0][2])
        self.set_size_request(-1, 480)
        self.init_counters()
        self.populate()
        self.populate_all()
        gobject.timeout_add(1000, self.populate)
        gobject.timeout_add(100, self.populate_tab)
        self.connect("realize", self.populate_graphs)
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
        def show_tab(*args):
            self.show_tab(contents)
        button = imagebutton(title, icon, clicked_callback=show_tab)
        button.connect("clicked", show_tab)
        button.set_relief(gtk.RELIEF_NONE)
        self.tab_button_box.add(button)
        self.tabs.append((title, button, contents, populate_cb))

    def show_tab(self, table):
        button = None
        for _, b, t, p_cb in self.tabs:
            if t==table:
                button = b
                b.set_relief(gtk.RELIEF_NORMAL)
                b.grab_focus()
                self.populate_cb = p_cb
            else:
                b.set_relief(gtk.RELIEF_NONE)
        assert button
        for x in self.tab_box.get_children():
            if x!=self.tab_button_box:
                self.tab_box.remove(x)
        self.tab_box.pack_start(table, expand=True, fill=True, padding=0)
        table.show_all()


    def set_args(self, *args):
        #this is a generic way for keyboard shortcuts or remote commands
        #to pass parameters to us
        log("set_args%s", args)
        if len(args)==0:
            return
        #at the moment, we only handle the tab name as argument:
        tab_name = args[0]
        if tab_name.lower()!="help":
            for title, _, table, _ in self.tabs:
                if title.lower()==tab_name.lower():
                    self.show_tab(table)
                    return
            log.warn("could not find session info tab named: %s", title)
        log.warn("The options for tab names are: %s)", [x[0] for x in self.tabs])

    def populate_all(self):
        for _, _, _, p_cb in self.tabs:
            if p_cb:
                p_cb()

    def scaled_image(self, pixbuf, icon_size=None):
        if not icon_size:
            icon_size = self.get_icon_size()
        return gtk.image_new_from_pixbuf(pixbuf.scale_simple(icon_size,icon_size, gdk.INTERP_BILINEAR))

    def add_graph_button(self, tooltip, click_cb):
        button = gtk.EventBox()
        def set_cursor(widget):
            widget.window.set_cursor(gdk.Cursor(gdk.BASED_ARROW_DOWN))
        button.connect("realize", set_cursor)
        graph = gtk.Image()
        graph.set_size_request(0, 0)
        button.connect("button_press_event", click_cb)
        button.add(graph)
        set_tooltip_text(graph, tooltip)
        self.graph_box.add(button)
        return graph

    def bool_icon(self, image, on_off):
        if on_off:
            icon = self.get_pixbuf("ticked-small.png")
        else:
            icon = self.get_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)

    def populate(self, *args):
        if self.is_closed:
            return False
        self.client.send_ping()
        self.last_populate_time = time.time()
        #record bytecount every second:
        self.net_in_bytecount.append(self.connection.input_bytecount)
        self.net_out_bytecount.append(self.connection.output_bytecount)
        #pre-compute for graph:
        self.net_in_scale, self.net_in_data = values_to_diff_scaled_values(list(self.net_in_bytecount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)
        self.net_out_scale, self.net_out_data = values_to_diff_scaled_values(list(self.net_out_bytecount)[1:N_SAMPLES+3], scale_unit=1000, min_scaled_value=50)

        #count pixels in the last second:
        since = time.time()-1
        decoded = [0]+[pixels for _,t,pixels in self.client.pixel_counter if t>since]
        self.pixel_in_data.append(sum(decoded))
        #update latency values
        #there may be more than one record for each second
        #so we have to average them to prevent the graph from "jumping":
        def get_ping_latency_records(src, size=25):
            recs = {}
            src_list = list(src)
            now = int(time.time())
            while len(src_list)>0 and len(recs)<size:
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
            return [recs.get(x) for x in sorted(recs.keys())]
        self.server_latency = get_ping_latency_records(self.client.server_ping_latency)
        self.client_latency = get_ping_latency_records(self.client.client_ping_latency)
        if self.client.server_last_info:
            #populate running averages for graphs:
            def getavg(name):
                return self.client.server_last_info.get("%s.avg" % name)
            def addavg(l, name):
                v = getavg(name)
                if v:
                    l.append(v)
            addavg(self.avg_batch_delay, "batch.delay")
            addavg(self.avg_damage_out_latency, "damage.out_latency")
            if len(self.client.server_ping_latency)>0 and len(self.client.client_ping_latency)>0:
                spl = [1000.0*x for _,x in list(self.client.server_ping_latency)]
                cpl = [1000.0*x for _,x in list(self.client.client_ping_latency)]
                self.avg_ping_latency.append(sum(spl+cpl)/len(spl+cpl))
            if len(self.client.pixel_counter)>0:
                tsize = 0
                ttime = 0
                for start_time, end_time, size in self.client.pixel_counter:
                    ttime += 1000.0 * (end_time-start_time) * size
                    tsize += size
                self.avg_decoding_latency.append(int(ttime/tsize))
        #totals: ping latency is halved since we only care about sending, not sending+receiving
        els  = [(self.avg_batch_delay, 1), (self.avg_damage_out_latency, 1),
                (self.avg_ping_latency, 2), (self.avg_decoding_latency, 1)]
        if len([x for x, _ in els if len(x)>0])==len(els):
            totals = [x[-1]/r for x, r in els]
            log("frame totals=%s", totals)
            self.avg_total.append(sum(totals))
        return not self.is_closed

    def init_counters(self):
        self.avg_batch_delay = maxdeque(N_SAMPLES+4)
        self.avg_damage_out_latency = maxdeque(N_SAMPLES+4)
        self.avg_ping_latency = maxdeque(N_SAMPLES+4)
        self.avg_decoding_latency = maxdeque(N_SAMPLES+4)
        self.avg_total = maxdeque(N_SAMPLES+4)

    def populate_tab(self, *args):
        if self.is_closed:
            return False
        #now re-populate the tab we are seeing:
        if self.populate_cb:
            if not self.populate_cb():
                self.populate_cb = None
        return not self.is_closed

    def populate_package(self):
        return False

    def populate_features(self):
        size_info = ""
        if self.client.server_actual_desktop_size:
            w,h = self.client.server_actual_desktop_size
            size_info = "%s*%s" % (w,h)
            if self.client.server_randr and self.client.server_max_desktop_size:
                size_info += " (max %s)" % ("x".join([str(x) for x in self.client.server_max_desktop_size]))
        self.bool_icon(self.server_randr_icon, self.client.server_randr)
        self.server_randr_label.set_text("%s" % size_info)
        self.bool_icon(self.client_opengl_icon, self.client.client_supports_opengl)
        buffering = "n/a"
        if self.client.opengl_enabled:
            glinfo = "%s / %s" % (self.client.opengl_props.get("vendor", ""), self.client.opengl_props.get("renderer", ""))
            display_mode = self.client.opengl_props.get("display_mode", [])
            if "DOUBLE" in display_mode:
                buffering = "double buffering"
            elif "SINGLE" in display_mode:
                buffering = "single buffering"
            else:
                buffering = "unknown"
        else:
            glinfo = self.client.opengl_props.get("info", "")
        self.client_opengl_label.set_text(glinfo)
        self.opengl_buffering.set_text(buffering)

        scaps = self.client.server_capabilities
        self.bool_icon(self.server_mmap_icon, self.client.mmap_enabled)
        self.bool_icon(self.server_clipboard_icon, scaps.get("clipboard", False))
        self.bool_icon(self.server_notifications_icon, scaps.get("notifications", False))
        self.bool_icon(self.server_bell_icon, scaps.get("bell", False))
        self.bool_icon(self.server_cursors_icon, scaps.get("cursors", False))
        def pipeline_info(can_use, sound_pipeline):
            if not can_use:
                return ""   #the icon shows this is not available, status is irrelevant so leave it empty
            if sound_pipeline is None or sound_pipeline.codec is None:
                return "inactive"
            state = sound_pipeline.get_state()
            if state!="active":
                return state
            s = "%s: %s" % (state, sound_pipeline.codec_description)
            #if sound_pipeline.bitrate>0:
            #    s += " / %sbit/s" % std_unit(sound_pipeline.bitrate)
            return s
        def codec_info(enabled, codecs):
            if not enabled:
                return "n/a"
            return ", ".join(codecs or [])
        def populate_speaker_info(*args):
            can = scaps.get("sound.send", False) and self.client.speaker_allowed
            self.bool_icon(self.server_speaker_icon, can)
            self.speaker_codec_label.set_text(pipeline_info(can, self.client.sound_sink))
        populate_speaker_info()
        self.client.connect("speaker-changed", populate_speaker_info)
        def populate_microphone_info(*args):
            can = scaps.get("sound.receive", False) and self.client.microphone_allowed
            self.bool_icon(self.server_microphone_icon, can)
            self.microphone_codec_label.set_text(pipeline_info(can, self.client.sound_source))
        populate_microphone_info()
        self.client.connect("microphone-changed", populate_microphone_info)

        #sound/video codec table:
        self.server_speaker_codecs_label.set_text(codec_info(scaps.get("sound.send", False), scaps.get("sound.encoders", [])))
        self.client_speaker_codecs_label.set_text(codec_info(self.client.speaker_allowed, self.client.speaker_codecs))
        self.server_microphone_codecs_label.set_text(codec_info(scaps.get("sound.receive", False), scaps.get("sound.decoders", [])))
        self.client_microphone_codecs_label.set_text(codec_info(self.client.microphone_allowed, self.client.microphone_codecs))
        se = scaps.get("encodings.core", scaps.get("encodings", scaps.get("encodings.core", [])))
        self.server_encodings_label.set_text(", ".join(sorted(se)))
        self.client_encodings_label.set_text(", ".join(sorted(self.client.get_core_encodings())))

        def get_encoder_list(caps):
            l = []
            if caps.get("bencode", True):
                l.append("bencode")
            if caps.get("rencode", False):
                l.append("rencode")
            return l
        self.client_packet_encoders_label.set_text(", ".join(get_encoder_list(get_network_caps())))
        self.server_packet_encoders_label.set_text(", ".join(get_encoder_list(self.client.server_capabilities)))

        def get_compressor_list(caps):
            l = []
            if caps.get("zlib", False):
                l.append("zlib")
            if caps.get("lz4", False):
                l.append("lz4")
            return l
        self.client_packet_compressors_label.set_text(", ".join(get_compressor_list(get_network_caps())))
        self.server_packet_compressors_label.set_text(", ".join(get_compressor_list(self.client.server_capabilities)))
        return False

    def populate_connection(self):
        def settimedeltastr(label, from_time):
            delta = datetime.timedelta(seconds=(int(time.time())-int(from_time)))
            label.set_text(str(delta))
        if self.client.server_load:
            self.server_load_label.set_text("  ".join([str(x/1000.0) for x in self.client.server_load]))
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
        self.input_packets_label.set_text(std_unit_dec(p.input_packetcount))
        self.input_bytes_label.set_text(std_unit_dec(c.input_bytecount))
        self.output_packets_label.set_text(std_unit_dec(p.output_packetcount))
        self.output_bytes_label.set_text(std_unit_dec(c.output_bytecount))

        def get_sound_info(supported, prop):
            if not supported:
                return {"state" : "disabled"}
            if prop is None:
                return {"state" : "inactive"}
            return prop.get_info()
        def set_sound_info(label, details, supported, prop):
            p = get_sound_info(supported, prop)
            label.set_text(p.get("state", ""))
            if details:
                d = p.get("queue.used_pct", -1)
                if d>=0:
                    details.set_text(" (buffer: %s%%)" % str(d).rjust(3))
                else:
                    details.set_text("")
        set_sound_info(self.speaker_label, self.speaker_details, self.client.speaker_enabled, self.client.sound_sink)
        set_sound_info(self.microphone_label, None, self.client.microphone_enabled, self.client.sound_source)

        self.connection_type_label.set_text(c.info)
        protocol_state = p.save_state()
        level = protocol_state.get("compression_level")
        if level==0:
            compression_str = "None"
        else:
            compression_str = " + ".join([x for x in ("zlib", "lz4", "bencode", "rencode") if protocol_state.get(x, False)==True])
            compression_str += ", level %s" % level
        self.compression_label.set_text(compression_str)

        def enclabel(label, cipher):
            if not cipher:
                info = "None"
            else:
                info = str(cipher)
            if c.info.lower()=="ssh":
                info += " (%s)" % c.info
            if get_network_caps().get("pycrypto.fastmath", False):
                info += " (fastmath available)"
            label.set_text(info)
        enclabel(self.input_encryption_label, p.cipher_in_name)
        enclabel(self.output_encryption_label, p.cipher_out_name)
        return True


    def getval(self, prefix, suffix, alt=""):
        if self.client.server_last_info is None:
            return ""
        altv = ""
        if alt:
            altv = self.client.server_last_info.get(alt+"."+suffix, "")
        return self.client.server_last_info.get(prefix+"."+suffix, altv)

    def values_from_info(self, prefix, alt=None):
        def getv(suffix):
            return self.getval(prefix, suffix, alt)
        return getv("cur"), getv("min"), getv("avg"), getv("90p"), getv("max")

    def all_values_from_info(self, *window_props):
        def avg(values):
            if not values:
                return ""
            return sum(values) / len(values)
        def getv(suffix, op):
            if self.client.server_last_info is None:
                return ""
            values = []
            for wid in self.client._window_to_id.values():
                for window_prop in window_props:
                    v = self.client.server_last_info.get("window[%s].%s.%s" % (wid, window_prop, suffix))
                    if v is not None:
                        values.append(v)
                        break
            try:
                return op(values)
            except:
                #no values?
                return ""
        return getv("cur", avg), getv("min", min), getv("avg", avg), getv("90p", avg), getv("max", max)

    def populate_statistics(self):
        log("populate_statistics()")
        if time.time()-self.last_populate_statistics<1.0:
            #don't repopulate more than every second
            return True
        self.last_populate_statistics = time.time()
        if self.client.server_info_request:
            self.client.send_info_request()
        def setall(labels, values):
            assert len(labels)==len(values), "%s labels and %s values (%s vs %s)" % (len(labels), len(values), labels, values)
            for i in range(len(labels)):
                l = labels[i]
                v = values[i]
                l.set_text(str(v))
        def setlabels(labels, values, rounding=int):
            if len(values)==0:
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

        if len(self.client.server_ping_latency)>0:
            spl = [1000.0*x for _,x in list(self.client.server_ping_latency)]
            setlabels(self.server_latency_labels, spl)
        if len(self.client.client_ping_latency)>0:
            cpl = [1000.0*x for _,x in list(self.client.client_ping_latency)]
            setlabels(self.client_latency_labels, cpl)
        if self.client.windows_enabled:
            if self.client.server_info_request:
                setall(self.batch_labels, self.values_from_info("batch_delay", "batch.delay"))
                setall(self.damage_labels, self.values_from_info("damage_out_latency", "damage.out_latency"))
                setall(self.quality_labels, self.all_values_from_info("quality", "encoding.quality"))
                setall(self.speed_labels, self.all_values_from_info("speed", "encoding.speed"))

            region_sizes = []
            rps = []
            pps = []
            decoding_latency = []
            if len(self.client.pixel_counter)>0:
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
                    for t in xrange(int(min_time)+1, int(max_time)):
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
            window_encoder_stats = {}
            if self.client.server_last_info:
                #We are interested in data like:
                #window[1].encoder=x264
                #window[1].encoder.frames=1
                for k,v in self.client.server_last_info.items():
                    pos = k.find("].encoder")
                    if k.startswith("window[") and pos>0:
                        wid_str = k[len("window["):pos]     #ie: "1"
                        ekey = k[(pos+len("].encoder")):]   #ie: "" or ".frames"
                        if ekey.startswith("."):
                            ekey = ekey[1:]
                        try:
                            wid = int(wid_str)
                            props = window_encoder_stats.setdefault(wid, {})
                            props[ekey] = v
                        except:
                            #wid_str may be invalid, ie:
                            #window[1].pipeline_option[1].encoder=codec_spec(xpra.codecs.enc_x264.encoder.Encoder)
                            # -> wid_str= "1].pipeline_option[1"
                            pass
                #print("window_encoder_stats=%s" % window_encoder_stats)
                for wid, props in window_encoder_stats.items():
                    l = label("%s (%s)" % (wid, props.get("")))
                    l.show()
                    info = ["%s=%s" % (k,v) for k,v in props.items() if k!=""]
                    set_tooltip_text(l, " ".join(info))
                    self.encoder_info_box.add(l)
        return True

    def populate_graphs(self, *args):
        if self.client.server_info_request:
            self.client.send_info_request()
        box = self.tab_box
        _, h = box.size_request()
        _, bh = self.tab_button_box.size_request()
        if h<=0:
            return True
        start_x_offset = min(1.0, (time.time()-self.last_populate_time)*0.95)
        rect = box.get_allocation()
        h = max(200, h-bh-20, rect.height-bh-20)
        w = max(360, rect.width-20)
        #bandwidth graph:
        if self.net_in_data and self.net_out_data:
            def unit(scale):
                if scale==1:
                    return ""
                else:
                    unit, value = to_std_unit(scale)
                    if value==1:
                        return str(unit)
                    return "x%s%s" % (int(value), unit)
            labels = ["recv %sB/s" % unit(self.net_in_scale), "sent %sB/s" % unit(self.net_out_scale)]
            datasets = [self.net_in_data, self.net_out_data]
            if SHOW_PIXEL_STATS and self.client.windows_enabled:
                pixel_scale, in_pixels = values_to_scaled_values(list(self.pixel_in_data)[3:N_SAMPLES+4], min_scaled_value=100)
                datasets.append(in_pixels)
                labels.append("%s pixels/s" % unit(pixel_scale))
            pixmap = make_graph_pixmap(datasets, labels=labels,
                                       width=w, height=h/2,
                                       title="Bandwidth", min_y_scale=10, rounding=10,
                                       start_x_offset=start_x_offset)
            self.bandwidth_graph.set_size_request(*pixmap.get_size())
            self.bandwidth_graph.set_from_pixmap(pixmap, None)
        if self.client.server_info_request:
            pass
        #latency graph:
        latency_graph_items = (
                                (self.avg_ping_latency, "network"),
                                (self.avg_batch_delay, "batch delay"),
                                (self.avg_damage_out_latency, "encode&send"),
                                (self.avg_decoding_latency, "decoding"),
                                (self.avg_total, "frame total"),
                                )
        latency_graph_values = []
        labels = []
        for l, name in latency_graph_items:
            if len(l)==0:
                continue
            l = list(l)
            if len(l)<20:
                for _ in range(20-len(l)):
                    l.insert(0, None)
            latency_graph_values.append(l)
            labels.append(name)
        pixmap = make_graph_pixmap(latency_graph_values, labels=labels,
                                    width=w, height=h/2,
                                    title="Latency (ms)", min_y_scale=10, rounding=25,
                                    start_x_offset=start_x_offset)
        self.latency_graph.set_size_request(*pixmap.get_size())
        self.latency_graph.set_from_pixmap(pixmap, None)
        return True

    def save_graphs(self, *args):
        log("save_graph(%s)", args)
        chooser = gtk.FileChooserDialog("Save graphs as a PNG image",
                                    parent=self, action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                    buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE, gtk.RESPONSE_OK))
        chooser.set_select_multiple(False)
        chooser.set_default_response(gtk.RESPONSE_OK)
        file_filter = gtk.FileFilter()
        file_filter.set_name("PNG")
        file_filter.add_pattern("*.png")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filenames = chooser.get_filenames()
        chooser.hide()
        chooser.destroy()
        if response == gtk.RESPONSE_OK:
            if len(filenames)==1:
                filename = filenames[0]
                pixmaps = [image.get_pixmap()[0] for image in [self.bandwidth_graph, self.latency_graph]]
                log("saving pixmaps %s and %s to %s", pixmaps, filename)
                w, h = 0, 0
                for pixmap in pixmaps:
                    if pixmap:
                        pw, ph = pixmap.get_size()
                        w = max(w, pw)
                        h += ph
                pixbuf = gdk.Pixbuf(gdk.COLORSPACE_RGB, False, 8, w, h)
                pixbuf.fill(0x00000000)
                x, y = 0, 0
                for pixmap in pixmaps:
                    if pixmap:
                        pw, ph = pixmap.get_size()
                        pixbuf = gdk.Pixbuf.get_from_drawable(pixbuf, pixmap, pixmap.get_colormap(), 0, 0, x, y, pw, ph)
                        y += ph
                pixbuf.save(filename, "png")
        elif response in (gtk.RESPONSE_CANCEL, gtk.RESPONSE_CLOSE, gtk.RESPONSE_DELETE_EVENT):
            log("closed/cancelled")
        else:
            log.warn("unknown chooser response: %d" % response)

    def destroy(self, *args):
        log("SessionInfo.destroy(%s) is_closed=%s", args, self.is_closed)
        self.is_closed = True
        gtk.Window.destroy(self)
        log("SessionInfo.destroy(%s) done", args)
