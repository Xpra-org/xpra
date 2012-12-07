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

from xpra.platform.graph import make_graph_pixmap
from xpra.deque import maxdeque
from xpra.maths import values_to_scaled_values, values_to_diff_scaled_values, to_std_unit, std_unit_dec
from wimpiggy.log import Logger
from xpra.platform.client_extras_base import set_tooltip_text, get_build_info
log = Logger()

N_SAMPLES = 20      #how many sample points to show on the graphs
SHOW_PIXEL_STATS = True


def label(text="", tooltip=None):
    l = gtk.Label(text)
    if tooltip:
        set_tooltip_text(l, tooltip)
    return l


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

class SessionInfo(gtk.Window):

    def __init__(self, client, session_name, window_icon_pixbuf, conn):
        gtk.Window.__init__(self)
        self.client = client
        self.session_name = session_name
        self.connection = conn
        self.is_closed = False
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

        # Contents box
        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(2)
        self.table = gtk.Table(1, columns=2)
        self.table.set_col_spacings(3)
        self.table.set_row_spacings(3)
        #hbox: data table on left, graph box on right:
        self.hbox = gtk.HBox(False, 10)
        vbox.add(self.hbox)
        self.hbox.add(self.table)
        #graph box:
        self.graph_box = gtk.VBox(False, 10)
        self.hbox.add(self.graph_box)
        self.bandwidth_graph = self.add_graph_button("Number of bytes measured by the networks sockets,\nand pixels rendered", self.save_graphs)
        self.latency_graph = self.add_graph_button("The time it takes to send an echo packet and get the reply", self.save_graphs)
        self.pixel_in_data = maxdeque(N_SAMPLES+3)
        self.net_in_data = maxdeque(N_SAMPLES+3)
        self.net_out_data = maxdeque(N_SAMPLES+2)

        # now add some rows with info:
        self.row = 0
        from xpra.__init__ import __version__
        self.new_row("Xpra version", label(__version__))
        self.new_row("Xpra build", label("\n".join(get_build_info())))
        self.server_version_label = label()
        self.new_row("Server Version", self.server_version_label)
        if is_gtk3():
            self.new_row("PyGobject version", label(gobject._version))
            self.new_row("GTK version", label(gtk._version))
            self.new_row("GDK version", label(gdk._version))
        else:
            def make_version_str(version):
                return  ".".join([str(x) for x in version])
            def make_version_info(prop_name):
                info = "unknown"
                if hasattr(gtk, prop_name):
                    info = make_version_str(getattr(gtk, prop_name))
                server_version = self.client.server_capabilities.get(prop_name)
                if server_version:
                    info += " (server: %s)" % make_version_str(server_version)
                return info
            self.new_row("PyGTK version", label(make_version_info("pygtk_version")))
            self.new_row("GTK version", label(make_version_info("gtk_version")))

        self.new_row("Server Endpoint", label(self.connection.target))
        if self.client.server_display:
            self.new_row("Server Display", label(self.client.server_display))
        if self.client.server_platform:
            self.new_row("Server Platform", label(self.client.server_platform))
        self.server_randr_label = label()
        self.new_row("Server RandR Support", self.server_randr_label)
        self.server_load_label = label()
        self.new_row("Server Load", self.server_load_label, "Average over 1, 5 and 15 minutes")
        self.server_latency_label = label()
        self.new_row("Server Latency", self.server_latency_label, "last value and average")
        self.client_latency_label = label()
        self.new_row("Client Latency", self.client_latency_label, "last value and average")
        self.session_started_label = label()
        self.new_row("Session Started", self.session_started_label)
        self.session_connected_label = label()
        self.new_row("Session Connected", self.session_connected_label)
        if self.client.windows_enabled:
            self.windows_managed_label = label()
            self.new_row("Windows Managed", self.windows_managed_label,
                          "The number of windows forwarded, some may just be temporary widgets (usually transient ones)")
            self.regions_sizes_label = label()
            self.new_row("Pixels/region", self.regions_sizes_label,
                          "The number of pixels updated at a time: min/avg/max")
            self.regions_per_second_label = label()
            self.new_row("Regions/s", self.regions_per_second_label,
                          "The number of screen updates per second")
            self.pixels_per_second_label = label()
            self.new_row("Pixels/s", self.pixels_per_second_label,
                          "The number of pixels updated per second")

        self.set_border_width(15)
        self.add(vbox)
        if not is_gtk3():
            self.set_geometry_hints(vbox)
        def window_deleted(*args):
            self.is_closed = True
        self.connect('delete_event', window_deleted)


    def add_row(self, row, label, widget):
        l_al = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
        l_al.add(label)
        self.table.attach(l_al, 0, 1, row, row + 1, xpadding=10)
        w_al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
        w_al.add(widget)
        self.table.attach(w_al, 1, 2, row, row + 1, xpadding=10)

    def new_row(self, row_label_text, value_label, tooltip_text=None):
        row_label = label(row_label_text, tooltip_text)
        if tooltip_text:
            set_tooltip_text(value_label, tooltip_text)
        self.add_row(self.row, row_label, value_label)
        self.row += 1

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

    def populate_info(self, *args):
        if self.is_closed:
            return False
        self.client.send_ping()
        def settimedeltastr(label, from_time):
            delta = datetime.timedelta(seconds=(int(time.time())-int(from_time)))
            label.set_text(str(delta))
        v = self.client._remote_version or "unknown"
        if self.client._remote_revision:
            v += " (revision %s)" % self.client._remote_revision
        if self.client.mmap_enabled:
            self.server_version_label.set_text("%s (mmap in use)" % v)
        else:
            self.server_version_label.set_text(v)
        size_info = ""
        if self.client.server_actual_desktop_size:
            w,h = self.client.server_actual_desktop_size
            size_info = " - %s*%s" % (w,h)
            if self.client.server_randr and self.client.server_max_desktop_size:
                size_info += " (max %s)" % ("x".join([str(x) for x in self.client.server_max_desktop_size]))
        if self.client.server_randr:
            self.server_randr_label.set_text("Yes%s" % size_info)
        else:
            self.server_randr_label.set_text("No%s" % size_info)
        if self.client.server_load:
            self.server_load_label.set_text("  ".join([str(x/1000.0) for x in self.client.server_load]))
        if len(self.client.server_ping_latency)>0:
            spl = [x for _,x in list(self.client.server_ping_latency)]
            avg = sum(spl)/len(spl)
            self.server_latency_label.set_text("%sms  (%sms)" % (int(1000.0*spl[-1]), int(1000.0*avg)))
        if len(self.client.client_ping_latency)>0:
            cpl = [x for _,x in list(self.client.client_ping_latency)]
            avg = sum(cpl)/len(cpl)
            self.client_latency_label.set_text("%sms  (%sms)" % (int(1000*cpl[-1]), int(1000.0*avg)))
        if self.client.server_start_time>0:
            settimedeltastr(self.session_started_label, self.client.server_start_time)
        else:
            self.session_started_label.set_text("unknown")
        settimedeltastr(self.session_connected_label, self.client.start_time)

        if self.client.windows_enabled:
            real, redirect, trays = 0, 0, 0
            for w in self.client._window_to_id.keys():
                if w.is_tray():
                    trays += 1
                elif w.is_OR():
                    redirect +=1
                else:
                    real += 1
            self.windows_managed_label.set_text("%s  (%s transient - %s trays)" % (real, redirect, trays))
            regions_sizes = "n/a"
            regions = "n/a"
            pixels = "n/a"
            if len(self.client.pixel_counter)>0:
                p20 = average(20, self.client.pixel_counter)
                if p20:
                    avg20,fps20,mins,avgs,maxs = p20
                    p1 = average(1, self.client.pixel_counter)
                    if p1:
                        avg1,fps1 = p1[:2]
                    else:
                        avg1,fps1 = -1, -1
                    pixels = "%s  (%s)" % (pixelstr(avg1), pixelstr(avg20))
                    regions = "%s  (%s)" % (fpsstr(fps1), fpsstr(fps20))
                    regions_sizes = "%s  %s  %s" % (pixelstr(mins), pixelstr(avgs), pixelstr(maxs))

            self.regions_sizes_label.set_text(regions_sizes)
            self.regions_per_second_label.set_text(regions)
            self.pixels_per_second_label.set_text(pixels)
            #count pixels in the last second:
            since = time.time()-1
            decoded = [0]+[pixels for t,pixels in self.client.pixel_counter if t>since]
            self.pixel_in_data.append(sum(decoded))
        #record bytecount every second:
        self.net_in_data.append(self.connection.input_bytecount)
        self.net_out_data.append(self.connection.output_bytecount)
        w, h = self.hbox.size_request()
        if h>0:
            rect = self.hbox.get_allocation()
            h = max(100, h-20, rect.height-20)
            w = max(360, rect.width/2-40)
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

    def destroy(self):
        self.is_closed = True
        gtk.Window.destroy(self)
