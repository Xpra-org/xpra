# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal
from gi.repository import Gtk, Gdk, GLib, Pango

from xpra import __version__
from xpra.util import envint
from xpra.os_util import SIGNAMES, OSX
from xpra.exit_codes import EXIT_TIMEOUT, EXIT_CONNECTION_LOST
from xpra.common import SPLASH_EXIT_DELAY
from xpra.gtk_common.gtk_util import add_close_accel, get_icon_pixbuf
from xpra.gtk_common.gobject_compat import install_signal_handlers
from xpra.client.gtk_base.css_overrides import inject_css_overrides
from xpra.platform.gui import force_focus
from xpra.log import Logger

log = Logger("client", "util")

inject_css_overrides()

TIMEOUT = envint("XPRA_SPLASH_TIMEOUT", 60)
LINES = envint("XPRA_SPLASH_LINES", 4)

#PULSE_CHARS = "▁▂▃▄▅▆▇█▇▆▅▄▃▁"
PULSE_CHARS = "◐◓◑◒"
if OSX:
    DONE_CHAR = "-"
else:
    DONE_CHAR = "⬤"

W = 400


class SplashScreen(Gtk.Window):

    def __init__(self):
        self.exit_code = None
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.connect("delete_event", self.exit)
        title = "Xpra %s" % __version__
        self.set_title(title)
        self.set_size_request(W, 40+40*LINES)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)
        self.set_opacity(0.9)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_pager_hint(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        vbox = Gtk.VBox()
        hbox = Gtk.HBox(homogeneous=False)
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
            hbox.pack_start(Gtk.Image.new_from_pixbuf(icon), False, False, 20)
        self.title_label = Gtk.Label(label=title)
        self.title_label.modify_font(Pango.FontDescription("sans 18"))
        hbox.pack_start(self.title_label, True, True, 20)
        vbox.add(hbox)
        self.labels = []
        for i in range(LINES):
            l = Gtk.Label(label=" ")
            l.set_opacity((i+1)/LINES)
            #l.set_line_wrap(True)
            self.labels.append(l)
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0, yscale=0)
            al.add(l)
            vbox.pack_start(al, True, True, 4)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_size_request(320, 30)
        self.progress_bar.set_show_text(False)
        self.progress_bar.set_fraction(0)
        self.progress_timer = None
        self.fade_out_timer = None
        self.exit_timer = None
        vbox.add(self.progress_bar)
        self.timeout_timer = 0
        self.pulse_timer = 0
        self.pulse_counter = 0
        self.current_label_text = None
        self.add(vbox)
        install_signal_handlers(None, self.handle_signal)
        SIGPIPE = getattr(signal, "SIGPIPE", None)
        if SIGPIPE: #ie: POSIX
            signal.signal(SIGPIPE, self.handle_signal)
        self.opacity = 100
        self.pct = 0


    def run(self):
        from xpra.make_thread import start_thread
        start_thread(self.read_stdin, "read-stdin", True)
        self.show_all()
        force_focus()
        self.present()
        self.timeout_timer = GLib.timeout_add(TIMEOUT*1000, self.timeout)
        self.pulse_timer = GLib.timeout_add(100, self.pulse)
        Gtk.main()
        return self.exit_code or 0

    def timeout(self):
        log("timeout()")
        self.timeout_timer = None
        self.exit_code = EXIT_TIMEOUT
        self.show_progress_value(100)
        self.progress_bar.set_text("timeout")
        self.progress_bar.set_show_text(True)

    def cancel_timeout_timer(self):
        tt = self.timeout_timer
        if tt:
            self.timeout_timer = 0
            GLib.source_remove(tt)

    def pulse(self):
        if not self.current_label_text:
            return True
        if self.pct<100:
            pulse_char = PULSE_CHARS[self.pulse_counter % len(PULSE_CHARS)]
        else:
            pulse_char = DONE_CHAR
        label = "  %s %s" % (pulse_char, self.current_label_text)
        self.labels[-1].set_label(label)
        self.pulse_counter += 1
        return True

    def read_stdin(self):
        log("read_stdin()")
        while self.exit_code is None:
            line = sys.stdin.readline()
            if not line:
                self.exit_code = EXIT_CONNECTION_LOST
                self.exit()
            else:
                GLib.idle_add(self.handle_stdin_line, line)

    def handle_stdin_line(self, line):
        parts = line.rstrip("\n\r").split(":", 1)
        log("handle_stdin_line(%r)", line)
        pct = self.pct
        if parts[0]:
            try:
                pct = int(parts[0])
            except ValueError:
                pass
            else:
                if pct>0:
                    self.show_progress_value(pct)
        if len(parts)>=2:
            text = parts[1]
            if pct==0:
                self.set_title(text)
                self.title_label.set_text(text)
                self.current_label_text = ""
            else:
                self.current_label_text = text
                if self.pct!=pct:
                    for i in range(len(self.labels)-1):
                        next_line = self.labels[i+1].get_label()
                        for c in PULSE_CHARS:
                            next_line = next_line.replace(c, DONE_CHAR)
                        self.labels[i].set_label(next_line)
            self.pulse_counter = 0
        self.pct = pct
        if pct>0:
            self.pulse()

    def show_progress_value(self, pct):
        self.cancel_progress_timer()
        GLib.idle_add(self.progress_bar.set_fraction, pct/100.0)
        if pct>=100:
            self.cancel_pulse_timer()
            self.cancel_fade_out_timer()
            self.opacity = 100
            self.fade_out_timer = GLib.timeout_add(SPLASH_EXIT_DELAY*1000//100, self.fade_out)
            self.cancel_exit_timer()
            def exit_splash():
                self.exit_timer = None
                self.exit()
            self.exit_timer = GLib.timeout_add(SPLASH_EXIT_DELAY*1000, exit_splash)
        else:
            self.progress_timer = GLib.timeout_add(40, self.increase_fraction, pct)

    def cancel_exit_timer(self):
        et = self.exit_timer
        if et:
            self.exit_timer = None
            GLib.source_remove(et)

    def cancel_fade_out_timer(self):
        fot = self.fade_out_timer
        if fot:
            self.fade_out_timer = None
            GLib.source_remove(fot)

    def cancel_progress_timer(self):
        pt = self.progress_timer
        if pt:
            self.progress_timer = None
            GLib.source_remove(pt)

    def cancel_pulse_timer(self):
        pt = self.pulse_timer
        if pt:
            self.pulse_timer = None
            GLib.source_remove(pt)

    def increase_fraction(self, pct, inc=1, max_increase=10):
        log("increase_fraction%s", (pct, inc, max_increase))
        self.cancel_progress_timer()
        GLib.idle_add(self.progress_bar.set_fraction, (pct+inc)/100.0)
        if inc<max_increase:
            self.progress_timer = GLib.timeout_add(40+20*(2+inc)**2, self.increase_fraction, pct, inc+1, max_increase)
        return False


    def fade_out(self):
        self.opacity = max(0, self.opacity-1)
        actual = int(self.get_opacity()*100)
        if actual>self.opacity:
            self.set_opacity(self.opacity/100.0)
        if actual<=0:
            self.fade_out_timer = None
        return actual>0

    def exit(self, *args):
        log("exit%s calling %s", args, Gtk.main_quit)
        if self.exit_code is None:
            self.exit_code = 0
        self.cancel_progress_timer()
        self.cancel_timeout_timer()
        self.cancel_fade_out_timer()
        self.cancel_pulse_timer()
        self.cancel_exit_timer()
        Gtk.main_quit()


    def handle_signal(self, signum, frame=None):
        log("handle_signal(%s, %s)", SIGNAMES.get(signum, signum), frame)
        self.exit_code = 128-(signum or 0)
        GLib.idle_add(self.exit)


def main(_args):
    import os
    if os.environ.get("XPRA_HIDE_DOCK") is None:
        os.environ["XPRA_HIDE_DOCK"] = "1"
    from xpra.platform import program_context
    with program_context("splash", "Splash"):
        Gtk.Window.set_auto_startup_notification(False)
        w = SplashScreen()
        add_close_accel(w, Gtk.main_quit)
        return w.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
