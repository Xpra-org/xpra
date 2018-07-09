#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys
import signal

from xpra.platform.gui import init as gui_init
gui_init()

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_glib, import_pango

gtk = import_gtk()
gdk = import_gdk()
glib = import_glib()
pango = import_pango()


from xpra.os_util import monotonic_time
from xpra.util import AdHocStruct, typedict
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file, \
                                    get_pixbuf_from_data, window_defaults, TableBuilder, WIN_POS_CENTER
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger, enable_debug_for
log = Logger("util")


_instance = None
def getServerCommandsWindow(client):
    global _instance
    if _instance is None:
        _instance = ServerCommandsWindow(client)
    return _instance


class ServerCommandsWindow(object):

    def __init__(self, client):
        assert client
        self.client = client
        self.populate_timer = None
        self.commands_info = {}
        self.table = None
        self.window = gtk.Window()
        window_defaults(self.window)
        self.window.connect("destroy", self.close)
        self.window.set_default_size(400, 150)
        self.window.set_title("Server Commands")

        icon_pixbuf = self.get_icon("list.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(10)

        self.alignment = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1.0, yscale=1.0)
        vbox.pack_start(self.alignment, expand=True, fill=True)

        # Buttons:
        hbox = gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        def btn(label, tooltip, callback, icon_name=None):
            b = self.btn(label, tooltip, callback, icon_name)
            hbox.pack_start(b)
        if self.client.server_start_new_commands:
            btn("Start New", "Run a command on the server", self.client.show_start_new_command, "forward.png")
        btn("Close", "", self.close, "quit.png")

        def accel_close(*_args):
            self.close()
        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def btn(self, label, tooltip, callback, icon_name=None):
        btn = gtk.Button(label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        btn.set_tooltip_text(tooltip)
        btn.connect("clicked", callback)
        if icon_name:
            icon = self.get_icon(icon_name)
            if icon:
                btn.set_image(scaled_image(icon, 24))
        return btn

    def populate_table(self):
        commands_info = typedict(self.client.server_last_info).dictget("commands")
        if self.commands_info!=commands_info and commands_info:
            log("populate_table() new commands_info=%s", commands_info)
            self.commands_info = commands_info
            if self.table:
                self.alignment.remove(self.table)
            tb = TableBuilder(rows=1, columns=2, row_spacings=15)
            self.table = tb.get_table()
            headers = [gtk.Label(""), gtk.Label("PID"), gtk.Label("Command"), gtk.Label("Exit Code")]
            if self.client.server_commands_signals:
                headers.append(gtk.Label("Send Signal"))
            tb.add_row(*headers)
            for procinfo in self.commands_info.values():
                if not isinstance(procinfo, dict):
                    continue
                #some records aren't procinfos:
                pi = typedict(procinfo)
                command = pi.strlistget("command")
                pid = pi.intget("pid", 0)
                returncode = pi.intget("returncode", None)
                if pid>0 and command:
                    cmd_str = " ".join(command)
                    rstr = ""
                    if returncode is not None:
                        rstr = "%s" % returncode
                    #find the windows matching this pid
                    windows = ()
                    from xpra.client import mixin_features
                    if mixin_features.windows:
                        windows = tuple(w for w in self.client._id_to_window.values() if getattr(w, "_metadata", {}).get("pid")==pid)
                        log("windows matching pid=%i: %s", pid, windows)
                    icon = gtk.Label()
                    if windows:
                        try:
                            icons = tuple(getattr(w, "_current_icon", None) for w in windows)
                            icons = tuple(x for x in icons if x is not None)
                            log("icons: %s", icons)
                            if icons:
                                from PIL import Image
                                img = icons[0].resize((24, 24), Image.ANTIALIAS)
                                has_alpha = img.mode=="RGBA"
                                width, height = img.size
                                rowstride = width * (3+int(has_alpha))
                                pixbuf = get_pixbuf_from_data(img.tobytes(), has_alpha, width, height, rowstride)
                                icon = gtk.Image()
                                icon.set_from_pixbuf(pixbuf)
                        except Exception:
                            log("failed to get window icon", exc_info=True)
                    items = [icon, gtk.Label("%s" % pid), gtk.Label(cmd_str), gtk.Label(rstr)]
                    if self.client.server_commands_signals:
                        if returncode is None:
                            items.append(self.signal_button(pid))
                        else:
                            items.append(gtk.Label(""))
                    tb.add_row(*items)
            self.alignment.add(self.table)
            self.table.show_all()
        self.client.send_info_request()
        return True

    def signal_button(self, pid):
        hbox = gtk.HBox()
        combo = gtk.combo_box_new_text()
        for x in self.client.server_commands_signals:
            combo.append_text(x)
        def send(*_args):
            a = combo.get_active()
            if a>=0:
                signame = self.client.server_commands_signals[a]
                self.client.send("command-signal", pid, signame)
        b = self.btn("Send", None, send, "forward.png")
        hbox.pack_start(combo)
        hbox.pack_start(b)
        return hbox

    def schedule_timer(self):
        if not self.populate_timer:
            self.populate_table()
            self.populate_timer = glib.timeout_add(1000, self.populate_table)

    def cancel_timer(self):
        if self.populate_timer:
            glib.source_remove(self.populate_timer)
            self.populate_timer = None


    def show(self):
        log("show()")
        self.window.show_all()
        self.window.present()
        self.schedule_timer()

    def hide(self):
        log("hide()")
        self.window.hide()
        self.cancel_timer()

    def close(self, *args):
        log("close%s", args)
        self.hide()

    def destroy(self, *args):
        log("destroy%s", args)
        self.cancel_timer()
        if self.window:
            self.window.destroy()
            self.window = None


    def run(self):
        log("run()")
        gtk_main()
        log("run() gtk_main done")

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        gtk.main_quit()


    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready
    with program_context("Start-New-Command", "Start New Command"):
        #logging init:
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.os_util import SIGNAMES
        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        client = AdHocStruct()
        client.server_last_info_time = monotonic_time()
        commands_info = {
            0: {'returncode': None, 'name': 'xterm', 'pid': 542, 'dead': False, 'ignore': True, 'command': ('xterm',), 'forget': False},
            'start-child'              : (),
            'start-new'                : True,
            'start-after-connect-done' : True,
            'start'                    : ('xterm',),
            'start-after-connect'      : (),
            'start-child-on-connect'   : (),
            'exit-with-children'       : False,
            'start-child-after-connect': (),
            'start-on-connect'         : (),
            }
        client.server_last_info = {"commands" : commands_info}
        client.server_start_new_commands = True
        client.server_commands_signals = ("SIGINT", "SIGTERM", "SIGUSR1")
        def noop(*_args):
            pass
        client.send_info_request = noop
        client.send = noop
        window1 = AdHocStruct()
        window1._metadata = {"pid" : 542}
        client._id_to_window = {
            1 : window1
            }
        def show_start_new_command(*_args):
            from xpra.client.gtk_base.start_new_command import getStartNewCommand
            getStartNewCommand(None).show()
        client.show_start_new_command = show_start_new_command

        app = ServerCommandsWindow(client)
        app.hide = app.quit
        def app_signal(signum, _frame):
            print("")
            log.info("got signal %s", SIGNAMES.get(signum, signum))
            app.quit()
        signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)
        try:
            gui_ready()
            app.show()
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
