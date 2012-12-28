# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
import time
import datetime
import platform

from xpra.platform.graph import make_graph_pixmap
from xpra.deque import maxdeque
from xpra.maths import values_to_scaled_values, values_to_diff_scaled_values, to_std_unit, std_unit_dec
from wimpiggy.log import Logger
from xpra.platform.client_extras_base import set_tooltip_text
log = Logger()

N_SAMPLES = 20      #how many sample points to show on the graphs
SHOW_PIXEL_STATS = True


def add_close_accel(window, callback):
    if is_gtk3():
        return      #TODO: implement accel for gtk3
    # key accelerators
    accel_group = gtk.AccelGroup()
    accel_group.connect_group(ord('w'), gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
    window.add_accel_group(accel_group)
    accel_group = gtk.AccelGroup()
    escape_key, modifier = gtk.accelerator_parse('Escape')
    accel_group.connect_group(escape_key, modifier, gtk.ACCEL_LOCKED |  gtk.ACCEL_VISIBLE, callback)
    window.add_accel_group(accel_group)

def label(text="", tooltip=None):
    l = gtk.Label(text)
    if tooltip:
        set_tooltip_text(l, tooltip)
    return l

def title_box(label_str):
    eb = gtk.EventBox()
    l = label(label_str)
    l.modify_fg(gtk.STATE_NORMAL, gtk.gdk.Color('#300000'))
    al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
    al.set_padding(0, 0, 10, 10)
    al.add(l)
    eb.add(al)
    eb.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color('#dbe2f2'))
    return eb

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
    for t, count in pixel_counter:
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


class TableBuilder(object):

    def __init__(self, rows=1, columns=2, homogeneous=False):
        self.table = gtk.Table(rows, columns, homogeneous)
        self.table.set_col_spacings(0)
        self.table.set_row_spacings(0)
        self.row = 0
        self.widget_xalign = 0.0

    def get_table(self):
        return self.table

    def add_row(self, label, *widgets):
        if label:
            l_al = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
            l_al.add(label)
            self.attach(l_al, 0)
        if widgets:
            i = 1
            for w in widgets:
                if w:
                    w_al = gtk.Alignment(xalign=self.widget_xalign, yalign=0.5, xscale=0.0, yscale=0.0)
                    w_al.add(w)
                    self.attach(w_al, i)
                i += 1
        self.inc()

    def attach(self, widget, i, count=1, xoptions=gtk.FILL, xpadding=10):
        self.table.attach(widget, i, i+count, self.row, self.row+1, xoptions=xoptions, xpadding=xpadding)

    def inc(self):
        self.row += 1

    def new_row(self, row_label_str, value1, value2=None, label_text=None):
        row_label = label(row_label_str, label_text)
        self.add_row(row_label, value1, value2)


class SessionInfo(gtk.Window):

    def __init__(self, client, session_name, window_icon_pixbuf, conn, get_pixbuf):
        gtk.Window.__init__(self)
        self.client = client
        self.session_name = session_name
        self.connection = conn
        self.is_closed = False
        self.get_pixbuf = get_pixbuf
        self.set_title(self.session_name or "Session Info")
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
        tb = self.table_tab("package.png", "Software", self.populate_package)
        #title row:
        tb.attach(title_box(""), 0, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Client"), 1, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.attach(title_box("Server"), 2, xoptions=gtk.EXPAND|gtk.FILL, xpadding=0)
        tb.inc()

        scaps = self.client.server_capabilities
        from xpra.__init__ import __version__
        tb.new_row("Xpra", label(__version__), label(self.client._remote_version or "unknown"))
        cl_rev, cl_ch, cl_date = "unknown", "", ""
        try:
            from xpra.build_info import BUILD_DATE as cl_date, REVISION as cl_rev, LOCAL_MODIFICATIONS as cl_ch
        except:
            pass
        tb.new_row("Revision", label(cl_rev), label(self.client._remote_revision or "unknown"))
        tb.new_row("Local Changes", label(cl_ch), label(scaps.get("local_modifications", "unknown")))
        tb.new_row("Build date", label(cl_date), label(scaps.get("build_date", "unknown")))
        def make_version_str(version):
            if version and type(version) in (tuple, list):
                version = ".".join([str(x) for x in version])
            return version or "unknown"
        def server_version_info(prop_name):
            return make_version_str(scaps.get(prop_name))
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
            tb.new_row("PyGTK", label(client_version_info("pygtk_version")), label(server_version_info("pygtk_version")))
            tb.new_row("GTK", label(client_version_info("gtk_version")), label(server_version_info("gtk_version")))
        tb.new_row("Python", label(platform.python_version()), label(server_version_info("python_version")))
        cl_gst_v, cl_pygst_v = "", ""
        try:
            from xpra.sound.gstreamer_util import gst_version as cl_gst_v, pygst_version as cl_pygst_v
            pass
        except:
            pass
        tb.new_row("GStreamer", label(make_version_str(cl_gst_v)), label(server_version_info("gst_version")))
        tb.new_row("pygst", label(make_version_str(cl_pygst_v)), label(server_version_info("pygst_version")))
        tb.new_row("OpenGL", label(make_version_str(self.client.opengl_props.get("opengl", "n/a"))), label("n/a"))
        tb.new_row("OpenGL Vendor", label(make_version_str(self.client.opengl_props.get("vendor", ""))), label("n/a"))
        tb.new_row("PyOpenGL", label(make_version_str(self.client.opengl_props.get("pyopengl", "n/a"))), label("n/a"))

        # Features Table:
        tb = self.table_tab("features.png", "Server\nFeatures", self.populate_features)
        randr_box = gtk.HBox(False, 20)
        self.server_randr_label = label()
        self.server_randr_icon = gtk.Image()
        randr_box.add(self.server_randr_icon)
        randr_box.add(self.server_randr_label)
        tb.new_row("RandR Support", randr_box)
        self.server_encodings_label = label()
        tb.new_row("Server Encodings", self.server_encodings_label)
        self.client_encodings_label = label()
        tb.new_row("Client Encodings", self.client_encodings_label)
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
        self.server_speaker_codecs_label = label()
        tb.new_row("Server Codecs", self.server_speaker_codecs_label)
        self.client_speaker_codecs_label = label()
        tb.new_row("Client Codecs", self.client_speaker_codecs_label)
        microphone_box = gtk.HBox(False, 20)
        self.server_microphone_icon = gtk.Image()
        microphone_box.add(self.server_microphone_icon)
        self.microphone_codec_label = label()
        microphone_box.add(self.microphone_codec_label)
        tb.new_row("Microphone Forwarding", microphone_box)
        self.server_microphone_codecs_label = label()
        tb.new_row("Speaker Codecs", self.server_microphone_codecs_label)
        self.client_microphone_codecs_label = label()
        tb.new_row("Client Codecs", self.client_microphone_codecs_label)

        # Connection Table:
        tb = self.table_tab("connect.png", "Connection", self.populate_connection)
        tb.new_row("Server Endpoint", label(self.connection.target))
        if self.client.server_display:
            tb.new_row("Server Display", label(self.client.server_display))
        if "hostname" in scaps:
            tb.new_row("Server Hostname", label(scaps.get("hostname")))
        if self.client.server_platform:
            tb.new_row("Server Platform", label(self.client.server_platform))
        self.server_load_label = label()
        tb.new_row("Server Load", self.server_load_label, label_text="Average over 1, 5 and 15 minutes")
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
        tb.new_row("Compression Level", self.compression_label)
        self.connection_type_label = label()
        tb.new_row("Connection Type", self.connection_type_label)
        self.input_encryption_label = label()
        tb.new_row("Input Encryption", self.input_encryption_label)
        self.output_encryption_label = label()
        tb.new_row("Output Encryption", self.output_encryption_label)

        # Details:
        tb = self.table_tab("browse.png", "Statistics", self.populate_statistics)
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
        tb.add_row(label("Server Latency (ms)"), *self.server_latency_labels)
        self.client_latency_labels = maths_labels()
        tb.add_row(label("Client Latency (ms)"), *self.client_latency_labels)
        if self.client.windows_enabled:
            if self.client.server_info_request:
                self.batch_labels = maths_labels()
                tb.add_row(label("Batch Delay (ms)"), *self.batch_labels)
                self.damage_labels = maths_labels()
                tb.add_row(label("Damage Latency (ms)"), *self.damage_labels)

            self.regions_per_second_labels = maths_labels()
            tb.add_row(label("Regions/s"), *self.regions_per_second_labels)
            self.regions_sizes_labels = maths_labels()
            tb.add_row(label("Pixels/region"), *self.regions_sizes_labels)
            self.pixels_per_second_labels = maths_labels()
            tb.add_row(label("Pixels/s"), *self.pixels_per_second_labels)

            self.windows_managed_label = label()
            tb.new_row("Regular Windows", self.windows_managed_label),
            self.transient_managed_label = label()
            tb.new_row("Transient Windows", self.transient_managed_label),
            self.trays_managed_label = label()
            tb.new_row("Trays Managed", self.trays_managed_label),
            if self.client.opengl_enabled:
                self.opengl_label = label()
                tb.new_row("OpenGL Windows", self.opengl_label),

        self.graph_box = gtk.VBox(False, 10)
        self.add_tab("statistics.png", "Graphs", self.populate_graphs, self.graph_box)
        bandwidth_label = "Number of bytes measured by the networks sockets"
        if SHOW_PIXEL_STATS:
            bandwidth_label += ",\nand number of pixels rendered"
        self.bandwidth_graph = self.add_graph_button(bandwidth_label, self.save_graphs)
        self.latency_graph = self.add_graph_button("The time it takes to send an echo packet and get the reply", self.save_graphs)
        self.pixel_in_data = maxdeque(N_SAMPLES+3)
        self.net_in_data = maxdeque(N_SAMPLES+3)
        self.net_out_data = maxdeque(N_SAMPLES+2)

        self.set_border_width(15)
        self.add(self.tab_box)
        if not is_gtk3():
            self.set_geometry_hints(self.tab_box)
        def window_deleted(*args):
            self.is_closed = True
        self.connect('delete_event', window_deleted)
        self.show_tab(self.tabs[0][1])
        self.set_size_request(-1, 480)
        self.populate()
        self.populate_all()
        gobject.timeout_add(1000, self.populate)
        self.connect("realize", self.populate_graphs)
        add_close_accel(self, self.destroy)


    def table_tab(self, icon_filename, title, populate_cb):
        tb = TableBuilder()
        table = tb.get_table()
        box = gtk.VBox(False, 0)
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        box.pack_start(al, expand=True, fill=True, padding=20)
        self.add_tab(icon_filename, title, populate_cb, contents=box)
        return tb

    def add_tab(self, icon_filename, title, populate_cb, contents):
        icon = self.get_pixbuf(icon_filename)
        def show_tab(*args):
            self.show_tab(contents)
        button = self.imagebutton(title, icon, clicked_callback=show_tab)
        button.connect("clicked", show_tab)
        button.set_relief(gtk.RELIEF_NONE)
        self.tab_button_box.add(button)
        self.tabs.append((button, contents, populate_cb))

    def show_tab(self, table):
        button = None
        for b, t, p_cb in self.tabs:
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

    def populate_all(self):
        for _, _, p_cb in self.tabs:
            if p_cb:
                p_cb()

    def scaled_image(self, pixbuf, icon_size=None):
        if not icon_size:
            icon_size = self.get_icon_size()
        return gtk.image_new_from_pixbuf(pixbuf.scale_simple(icon_size,icon_size,gtk.gdk.INTERP_BILINEAR))

    def imagebutton(self, title, icon, tooltip=None, clicked_callback=None, icon_size=32, default=False, min_size=None):
        button = gtk.Button(title)
        settings = button.get_settings()
        settings.set_property('gtk-button-images', True)
        if icon:
            button.set_image(self.scaled_image(icon, icon_size))
        if tooltip:
            set_tooltip_text(button, tooltip)
        if min_size:
            button.set_size_request(min_size, min_size)
        if clicked_callback:
            button.connect("clicked", clicked_callback)
        if default:
            button.set_flags(gtk.CAN_DEFAULT)
        return button

    def add_graph_button(self, tooltip, click_cb):
        button = gtk.EventBox()
        def set_cursor(widget):
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.BASED_ARROW_DOWN))
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
        #record bytecount every second:
        self.net_in_data.append(self.connection.input_bytecount)
        self.net_out_data.append(self.connection.output_bytecount)
        #count pixels in the last second:
        since = time.time()-1
        decoded = [0]+[pixels for t,pixels in self.client.pixel_counter if t>since]
        self.pixel_in_data.append(sum(decoded))
        #now re-populate the tab we are seeing:
        if self.populate_cb:
            if not self.populate_cb():
                self.populate_cb = None
        return True

    def populate_package(self):
        pass

    def populate_features(self):
        from xpra.scripts.main import ENCODINGS
        size_info = ""
        if self.client.server_actual_desktop_size:
            w,h = self.client.server_actual_desktop_size
            size_info = "%s*%s" % (w,h)
            if self.client.server_randr and self.client.server_max_desktop_size:
                size_info += " (max %s)" % ("x".join([str(x) for x in self.client.server_max_desktop_size]))
        self.bool_icon(self.server_randr_icon, self.client.server_randr)
        self.server_randr_label.set_text("%s" % size_info)
        scaps = self.client.server_capabilities
        self.server_encodings_label.set_text(", ".join(scaps.get("encodings", [])))
        self.client_encodings_label.set_text(", ".join(ENCODINGS))
        self.bool_icon(self.server_mmap_icon, self.client.mmap_enabled)
        self.bool_icon(self.server_clipboard_icon, scaps.get("clipboard", False))
        self.bool_icon(self.server_notifications_icon, scaps.get("notifications", False))
        self.bool_icon(self.server_bell_icon, scaps.get("bell", False))
        self.bool_icon(self.server_cursors_icon, scaps.get("cursors", False))
        self.bool_icon(self.server_speaker_icon, scaps.get("sound.send", False))
        if self.client.sound_sink and self.client.sound_sink.codec:
            self.speaker_codec_label.set_text(self.client.sound_sink.codec)
        else:
            self.speaker_codec_label.set_text("")
        if scaps.get("sound.send", False):
            self.server_speaker_codecs_label.set_text(", ".join(scaps.get("sound.encoders", [])))
        else:
            self.server_speaker_codecs_label.set_text("n/a")
        self.client_speaker_codecs_label.set_text(", ".join(self.client.microphone_codecs or []))
        self.bool_icon(self.server_microphone_icon, scaps.get("sound.receive", False))
        if self.client.sound_source and self.client.sound_source.codec:
            self.microphone_codec_label.set_text(self.client.sound_source.codec)
        else:
            self.microphone_codec_label.set_text("")
        if scaps.get("sound.receive", False):
            self.server_microphone_codecs_label.set_text(", ".join(scaps.get("sound.decoders", [])))
        else:
            self.server_microphone_codecs_label.set_text("n/a")
        self.client_microphone_codecs_label.set_text(", ".join(self.client.speaker_codecs or []))
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
        c = p._conn
        self.input_packets_label.set_text(std_unit_dec(p.input_packetcount))
        self.input_bytes_label.set_text(std_unit_dec(c.input_bytecount))
        self.output_packets_label.set_text(std_unit_dec(p.output_packetcount))
        self.output_bytes_label.set_text(std_unit_dec(c.output_bytecount))

        self.connection_type_label.set_text(c.info)
        self.compression_label.set_text(str(p._compression_level))
        suffix = ""
        if c.info.lower()=="ssh":
            suffix = " (%s)" % c.info
        self.input_encryption_label.set_text((p.cipher_in_name or "None")+suffix)
        self.output_encryption_label.set_text((p.cipher_out_name or "None")+suffix)
        return True

    def populate_statistics(self):
        log("populate_statistics()")
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
                def values_from_info(prefix):
                    def getv(name):
                        if self.client.server_last_info is None:
                            return ""
                        return self.client.server_last_info.get(name, "")
                    return getv(prefix+".cur"), getv(prefix+".min"), getv(prefix+".avg"), getv(prefix+".90p"), getv(prefix+".max")
                setall(self.batch_labels, values_from_info("batch_delay"))
                setall(self.damage_labels, values_from_info("damage_out_latency"))
            region_sizes = []
            rps = []
            pps = []
            if len(self.client.pixel_counter)>0:
                min_time = None
                max_time = None
                regions_per_second = {}
                pixels_per_second = {}
                for event_time, size in self.client.pixel_counter:
                    region_sizes.append(size)
                    if min_time is None or min_time>event_time:
                        min_time = event_time
                    if max_time is None or max_time<event_time:
                        max_time = event_time
                    time_in_seconds = int(event_time)
                    regions = regions_per_second.get(time_in_seconds, 0)
                    regions_per_second[time_in_seconds] = regions+1
                    pixels = pixels_per_second.get(time_in_seconds, 0)
                    pixels_per_second[time_in_seconds] = pixels + size
                for t in xrange(int(min_time), int(max_time+1)):
                    rps.append(regions_per_second.get(t, 0))
                    pps.append(pixels_per_second.get(t, 0))
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
            if self.client.opengl_enabled:
                self.opengl_label.set_text(str(gl))
        return True

    def populate_graphs(self, *args):
        box = self.tab_box
        _, h = box.size_request()
        _, bh = self.tab_button_box.size_request()
        if h<=0:
            return True
        rect = box.get_allocation()
        h = max(200, h-bh-20, rect.height-bh-20)
        w = max(360, rect.width-20)
        #bandwidth graph:
        #Note: we skip the first record because the timing isn't right so the values aren't either..:
        in_scale, in_data = values_to_diff_scaled_values(list(self.net_in_data)[1:N_SAMPLES+2], scale_unit=1000, min_scaled_value=50)
        out_scale, out_data = values_to_diff_scaled_values(list(self.net_out_data)[1:N_SAMPLES+2], scale_unit=1000, min_scaled_value=50)
        if in_data and out_data:
            def unit(scale):
                if scale==1:
                    return ""
                else:
                    unit, value = to_std_unit(scale)
                    if value==1:
                        return str(unit)
                    return "x%s%s" % (int(value), unit)
            labels = ["recv %sB/s" % unit(in_scale), "sent %sB/s" % unit(out_scale)]
            datasets = [in_data, out_data]
            if SHOW_PIXEL_STATS and self.client.windows_enabled:
                pixel_scale, in_pixels = values_to_scaled_values(list(self.pixel_in_data)[:N_SAMPLES], min_scaled_value=100)
                datasets.append(in_pixels)
                labels.append("%s pixels/s" % unit(pixel_scale))
            pixmap = make_graph_pixmap(datasets, labels=labels, width=w, height=h/2, title="Bandwidth", min_y_scale=10, rounding=10)
            self.bandwidth_graph.set_size_request(*pixmap.get_size())
            self.bandwidth_graph.set_from_pixmap(pixmap, None)
        #latency graph:
        server_latency = [1000.0*x for _,x in list(self.client.server_ping_latency)[-20:]]
        client_latency = [1000.0*x for _,x in list(self.client.client_ping_latency)[-20:]]
        for l in (server_latency, client_latency):
            if len(l)<20:
                for _ in range(20-len(l)):
                    l.insert(0, None)
        pixmap = make_graph_pixmap([server_latency, client_latency], labels=["server", "client"],
                                    width=w, height=h/2,
                                    min_y_scale=10, rounding=50,
                                    title="Latency (ms)")
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
                pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, w, h)
                pixbuf.fill(0x00000000)
                x, y = 0, 0
                for pixmap in pixmaps:
                    if pixmap:
                        pw, ph = pixmap.get_size()
                        pixbuf = gtk.gdk.Pixbuf.get_from_drawable(pixbuf, pixmap, pixmap.get_colormap(), 0, 0, x, y, pw, ph)
                        y += ph
                pixbuf.save(filename, "png")
        elif response in (gtk.RESPONSE_CANCEL, gtk.RESPONSE_CLOSE, gtk.RESPONSE_DELETE_EVENT):
            log("closed/cancelled")
        else:
            log.warn("unknown chooser response: %d" % response)

    def destroy(self, *args):
        self.is_closed = True
        gtk.Window.destroy(self)
