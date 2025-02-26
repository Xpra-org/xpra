#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal
from time import monotonic

from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue
from xpra.gtk.signals import register_os_signals
from xpra.util.objects import typedict, AdHocStruct
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import scaled_image, label
from xpra.gtk.pixbuf import get_icon_pixbuf, get_pixbuf_from_data
from xpra.log import Logger, enable_debug_for

log = Logger("util")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")

_instance = None


def getServerCommandsWindow(client):
    global _instance
    if _instance is None:
        _instance = ServerCommandsWindow(client)
    return _instance


class ServerCommandsWindow:

    def __init__(self, client):
        assert client
        self.client = client
        self.populate_timer = 0
        self.commands_info = {}
        self.contents = None
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 150)
        self.window.set_title("Server Commands")

        icon_pixbuf = get_icon_pixbuf("list.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(10)

        self.alignment = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1.0, yscale=1.0)
        vbox.pack_start(self.alignment, expand=True, fill=True)

        # Buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        vbox.pack_start(hbox)

        def btn(label, tooltip, callback, icon_name=None):
            b = self.btn(label, tooltip, callback, icon_name)
            hbox.pack_start(b)

        if self.client.server_start_new_commands:
            btn("Start New", "Run a command on the server", self.client.show_start_new_command, "forward.png")
        btn("Close", "", self.close, "quit.png")

        add_close_accel(self.window, self.close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def btn(self, label, tooltip, callback, icon_name=None):
        btn = Gtk.Button(label=label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        btn.set_tooltip_text(tooltip)
        btn.connect("clicked", callback)
        icon = get_icon_pixbuf(icon_name)
        if icon:
            btn.set_image(scaled_image(icon, 24))
        return btn

    def populate_table(self):
        commands_info = typedict(self.client.server_last_info).dictget("commands", {})
        if self.commands_info != commands_info and commands_info:
            log("populate_table() new commands_info=%s", commands_info)
            self.commands_info = commands_info
            if self.contents:
                self.alignment.remove(self.contents)
            grid = Gtk.Grid()

            def l(s=""):  # noqa: E743
                widget = label(s)
                widget.set_margin_start(5)
                widget.set_margin_end(5)
                return widget

            headers = ["", "PID", "Command", "Exit Code"]
            if self.client.server_commands_signals:
                headers.append("Send Signal")
            for i, text in enumerate(headers):
                grid.attach(l(text), i, 0, 1, 1)
            for row, procinfo in enumerate(self.commands_info.values()):
                if not isinstance(procinfo, dict):
                    continue
                # some records aren't procinfos:
                pi = typedict(procinfo)
                command = pi.strtupleget("command")
                pid = pi.intget("pid", 0)
                returncode: int | None = pi.intget("returncode") if "returncode" in pi else None
                if pid > 0 and command:
                    cmd_str = " ".join(command)
                    rstr = ""
                    if returncode is not None:
                        rstr = "%s" % returncode
                    # find the windows matching this pid
                    windows = ()
                    from xpra.client.base import features
                    if features.windows:
                        windows = tuple(w for w in self.client._id_to_window.values()
                                        if getattr(w, "_metadata", {}).get("pid") == pid)
                        log(f"windows matching pid={pid}: {windows}")
                    icon = label()
                    if windows:
                        try:
                            icons = tuple(getattr(w, "_current_icon", None) for w in windows)
                            icons = tuple(x for x in icons if x is not None)
                            log("icons: %s", icons)
                            if icons:
                                from PIL import Image  # @UnresolvedImport pylint: disable=import-outside-toplevel
                                try:
                                    LANCZOS = Image.Resampling.LANCZOS
                                except AttributeError:
                                    LANCZOS = Image.LANCZOS
                                img = icons[0].resize((24, 24), LANCZOS)
                                has_alpha = img.mode == "RGBA"
                                width, height = img.size
                                rowstride = width * (3 + int(has_alpha))
                                pixbuf = get_pixbuf_from_data(img.tobytes(), has_alpha, width, height, rowstride)
                                icon = Gtk.Image()
                                icon.set_from_pixbuf(pixbuf)
                        except Exception:
                            log("failed to get window icon", exc_info=True)
                    widgets = [icon, l(f"{pid}"), l(cmd_str), l(rstr)]
                    if self.client.server_commands_signals:
                        if returncode is None:
                            widgets.append(self.signal_button(pid))
                    for i, widget in enumerate(widgets):
                        grid.attach(widget, i, 1 + row, 1, 1)
            self.alignment.add(grid)
            grid.show_all()
            self.contents = grid
        self.client.send_info_request()
        return True

    def signal_button(self, pid):
        hbox = Gtk.HBox()
        combo = Gtk.ComboBoxText()
        for x in self.client.server_commands_signals:
            combo.append_text(x)

        def send(*_args):
            a = combo.get_active()
            if a >= 0:
                signame = self.client.server_commands_signals[a]
                self.client.send("command-signal", pid, signame)

        b = self.btn("Send", None, send, "forward.png")
        hbox.pack_start(combo)
        hbox.pack_start(b)
        return hbox

    def schedule_timer(self):
        if not self.populate_timer:
            self.populate_table()
            self.populate_timer = GLib.timeout_add(1000, self.populate_table)

    def cancel_timer(self):
        pt = self.populate_timer
        if pt:
            self.populate_timer = 0
            GLib.source_remove(pt)

    def show(self):
        log("show()")
        self.window.show_all()
        self.window.present()
        self.schedule_timer()

    def close(self, *args):
        log("close%s", args)
        if self.window:
            self.window.hide()
        self.cancel_timer()
        return True

    def destroy(self, *args):
        log("close%s", args)
        self.cancel_timer()
        if self.window:
            self.window.close()
            self.window = None

    def run(self) -> ExitValue:
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")
        return 0

    def quit(self, *args):
        log("quit%s", args)
        self.close()
        Gtk.main_quit()


def main():  # pragma: no cover
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready, init as gui_init
    gui_init()
    with program_context("Start-New-Command", "Start New Command"):
        if "-v" in sys.argv:
            enable_debug_for("util")

        client = AdHocStruct()
        client.server_last_info_time = monotonic()
        commands_info = {
            0: {
                'returncode': None, 'name': 'xterm', 'pid': 542, 'dead': False,
                'ignore': True, 'command': ('xterm',), 'forget': False,
            },
            'start-child': (),
            'start-new': True,
            'start-after-connect-done': True,
            'start': ('xterm',),
            'start-after-connect': (),
            'start-child-on-connect': (),
            'exit-with-children': False,
            'start-child-after-connect': (),
            'start-on-connect': (),
        }
        client.server_last_info = {"commands": commands_info}
        client.server_start_new_commands = True
        client.server_commands_signals = ("SIGINT", "SIGTERM", "SIGUSR1")

        def nosend(*_args):
            """
            this is for testing only - we are not connected to a server
            """

        client.send_info_request = nosend
        client.send = nosend
        window1 = AdHocStruct()
        window1._metadata = {"pid": 542}  # pylint: disable=protected-access
        client._id_to_window = {  # pylint: disable=protected-access
            1: window1
        }

        def show_start_new_command(*_args):
            from xpra.gtk.dialogs.start_new_command import getStartNewCommand
            getStartNewCommand(None).show()

        client.show_start_new_command = show_start_new_command

        app = ServerCommandsWindow(client)
        app.close = app.quit
        register_os_signals(app.quit)
        try:
            gui_ready()
            app.show()
            return app.run()
        except KeyboardInterrupt:
            return 128 + int(signal.SIGINT)


if __name__ == "__main__":  # pragma: no cover
    v = main()
    sys.exit(v)
