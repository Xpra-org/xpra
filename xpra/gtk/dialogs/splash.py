# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal
from time import sleep, monotonic

from xpra import __version__
from xpra.util.env import envint, envbool, ignorewarnings
from xpra.os_util import OSX, WIN32, gi_import
from xpra.util.system import SIGNAMES
from xpra.exit_codes import ExitCode, ExitValue
from xpra.common import SPLASH_EXIT_DELAY
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.signals import install_signal_handlers
from xpra.gtk.css_overrides import inject_css_overrides
from xpra.platform.gui import force_focus, set_window_progress
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

log = Logger("client", "util")

inject_css_overrides()

TIMEOUT = envint("XPRA_SPLASH_TIMEOUT", 60)
LINES = envint("XPRA_SPLASH_LINES", 4)
READ_SLEEP = envint("XPRA_SPLASH_READ_SLEEP", 0)
FOCUS_EXIT = envbool("XPRA_SPLASH_FOCUS_EXIT", True)

# alternative: "▁▂▃▄▅▆▇█▇▆▅▄▃▁"
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
        self.add_events(Gdk.EventType.BUTTON_PRESS)
        self.connect("button-press-event", self.exit)
        self.connect("key-press-event", self.exit)
        title = "Xpra %s" % __version__
        self.set_title(title)
        self.set_size_request(W, 40 + 40 * LINES)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        self.set_opacity(0.9)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_pager_hint(True)
        self.set_skip_taskbar_hint(True)
        if not OSX:
            self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        vbox = Gtk.VBox()
        hbox = Gtk.HBox(homogeneous=False)
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
            hbox.pack_start(Gtk.Image.new_from_pixbuf(icon), False, False, 20)
        self.title_label = label(title, font="sans 18")
        hbox.pack_start(self.title_label, True, True, 20)
        vbox.add(hbox)
        self.labels = []
        for i in range(LINES):
            lbl = label(" ")
            lbl.set_opacity((i + 1) / LINES)
            self.labels.append(lbl)
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0, yscale=0)
            al.add(lbl)
            vbox.pack_start(al, True, True, 4)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_size_request(320, 30)
        self.progress_bar.set_show_text(False)
        self.progress_bar.set_fraction(0)
        self.progress_timer = 0
        self.fade_out_timer = 0
        self.exit_timer = 0
        vbox.add(self.progress_bar)
        self.timeout_timer = 0
        self.pulse_timer = 0
        self.pulse_counter = 0
        self.current_label_text = None
        self.add(vbox)
        install_signal_handlers("", self.handle_signal)
        sigpipe = getattr(signal, "SIGPIPE", None)
        if sigpipe:  # ie: POSIX
            signal.signal(sigpipe, self.handle_signal)
        self.opacity = 100
        self.pct = 0
        self.start_time = monotonic()
        self.had_top_level_focus = False
        self.fd_watch = 0
        self.connect("notify::has-toplevel-focus", self._focus_change)

    def cancel_io_watch(self) -> None:
        fd = self.fd_watch
        if fd:
            self.fd_watch = 0
            GLib.source_remove(fd)

    def run(self) -> ExitValue:
        events = GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR
        self.fd_watch = GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_LOW, events, self.read_stdin)
        self.show_all()
        force_focus()
        self.present()
        self.timeout_timer = GLib.timeout_add(TIMEOUT * 1000, self.timeout)
        self.pulse_timer = GLib.timeout_add(100, self.pulse)
        scrash = envint("XPRA_SPLASH_CRASH", -1)
        if scrash >= 0:
            def crash():
                import ctypes  # pylint: disable=import-outside-toplevel
                ctypes.string_at(0)

            GLib.timeout_add(scrash, crash)
        self.start_time = monotonic()
        Gtk.main()
        return self.exit_code or 0

    def _focus_change(self, *args) -> None:
        if WIN32 and monotonic() - self.start_time < 1:
            # ignore initial focus events on win32
            return
        has = self.has_toplevel_focus()
        had = self.had_top_level_focus
        log(f"_focus_change{args} {had=}, {has=}")
        if had and not has:
            if FOCUS_EXIT:
                self.exit()
        elif has:
            self.had_top_level_focus = True

    def timeout(self) -> None:
        log("timeout()")
        self.timeout_timer = 0
        self.exit_code = ExitCode.TIMEOUT
        self.show_progress_value(100)
        self.progress_bar.set_text("timeout")
        self.progress_bar.set_show_text(True)
        self.exit()

    def cancel_timeout_timer(self) -> None:
        tt = self.timeout_timer
        if tt:
            self.timeout_timer = 0
            GLib.source_remove(tt)

    def pulse(self) -> bool:
        if not self.current_label_text:
            return True
        if self.pct < 100:
            pulse_char = PULSE_CHARS[self.pulse_counter % len(PULSE_CHARS)]
        else:
            pulse_char = DONE_CHAR
        self.labels[-1].set_label(f"  {pulse_char} {self.current_label_text}")
        self.pulse_counter += 1
        return True

    def read_stdin(self, fd, cb_condition) -> bool:
        log(f"read_stdin({fd}, {cb_condition})")
        if cb_condition in (GLib.IO_HUP, GLib.IO_ERR):
            self.fd_watch = 0
            self.exit_code = ExitCode.CONNECTION_LOST
            self.exit()
            return False
        if cb_condition == GLib.IO_IN:
            try:
                line = sys.stdin.readline()
                GLib.idle_add(self.handle_stdin_line, line)
                sleep(READ_SLEEP)
                return True
            except OSError:
                self.fd_watch = 0
                self.exit_code = ExitCode.FAILURE
                self.exit()
                return False
        # unexpected condition - continue
        return True

    def handle_stdin_line(self, line: str) -> None:
        parts = line.rstrip("\n\r").split(":", 1)
        log("handle_stdin_line(%r)", line)
        pct = self.pct
        if parts[0]:
            try:
                pct = int(parts[0])
            except ValueError:
                pass
            else:
                if pct > 0:
                    self.show_progress_value(pct)
        if len(parts) >= 2:
            text = parts[1]
            if pct == 0:
                self.set_title(text)
                self.title_label.set_text(text)
                self.current_label_text = ""
            else:
                self.current_label_text = text
                if self.pct != pct:
                    for i in range(len(self.labels) - 1):
                        next_line = self.labels[i + 1].get_label()
                        for c in PULSE_CHARS:
                            next_line = next_line.replace(c, DONE_CHAR)
                        self.labels[i].set_label(next_line)
            self.pulse_counter = 0
        self.pct = pct
        if pct > 0:
            self.pulse()

    def show_progress_value(self, pct: int) -> None:
        self.cancel_progress_timer()
        GLib.idle_add(self.progress_bar.set_fraction, pct / 100.0)
        if pct >= 100:
            self.cancel_pulse_timer()
            self.cancel_fade_out_timer()
            self.fade_out_timer = GLib.timeout_add(SPLASH_EXIT_DELAY * 1000 // 100, self.fade_out)
            self.cancel_exit_timer()

            def exit_splash():
                self.exit_timer = 0
                self.exit()

            self.exit_timer = GLib.timeout_add(SPLASH_EXIT_DELAY * 1000, exit_splash)
        else:
            self.progress_timer = GLib.timeout_add(40, self.increase_fraction, pct)
            self.opacity = min(100, max(50, 130 - pct))
            self.set_opacity(self.opacity / 100.0)
        set_window_progress(self, pct)

    def cancel_exit_timer(self) -> None:
        et = self.exit_timer
        if et:
            self.exit_timer = 0
            GLib.source_remove(et)

    def cancel_fade_out_timer(self) -> None:
        fot = self.fade_out_timer
        if fot:
            self.fade_out_timer = 0
            GLib.source_remove(fot)

    def cancel_progress_timer(self) -> None:
        pt = self.progress_timer
        if pt:
            self.progress_timer = 0
            GLib.source_remove(pt)

    def cancel_pulse_timer(self) -> None:
        pt = self.pulse_timer
        if pt:
            self.pulse_timer = 0
            GLib.source_remove(pt)

    def increase_fraction(self, pct: int, inc=1, max_increase=10) -> bool:
        log("increase_fraction%s", (pct, inc, max_increase))
        self.cancel_progress_timer()
        GLib.idle_add(self.progress_bar.set_fraction, (pct + inc) / 100.0)
        if inc < max_increase:
            self.progress_timer = GLib.timeout_add(40 + 20 * (2 + inc) ** 2, self.increase_fraction, pct, inc + 1,
                                                   max_increase)
        return False

    def fade_out(self) -> bool:
        self.opacity = max(0, self.opacity - 1)
        actual = int(ignorewarnings(self.get_opacity) * 100)
        if actual > self.opacity:
            self.set_opacity(self.opacity / 100.0)
        if actual <= 0:
            self.fade_out_timer = 0
        return actual > 0

    def exit(self, *args) -> None:
        log("exit%s calling %s", args, Gtk.main_quit)
        if self.exit_code is None:
            self.exit_code = 0
        self.cancel_io_watch()
        self.cancel_progress_timer()
        self.cancel_timeout_timer()
        self.cancel_fade_out_timer()
        self.cancel_pulse_timer()
        self.cancel_exit_timer()
        Gtk.main_quit()

    def handle_signal(self, signum, frame=None) -> None:
        log("handle_signal(%s, %s)", SIGNAMES.get(signum, signum), frame)
        self.exit_code = 128 - (signum or 0)
        GLib.idle_add(self.exit)


def main(_args) -> ExitValue:
    import os
    if os.environ.get("XPRA_HIDE_DOCK") is None:
        os.environ["XPRA_HIDE_DOCK"] = "1"
    from xpra.platform import program_context
    with program_context("splash", "Splash"):
        Gtk.Window.set_auto_startup_notification(setting=False)
        w = SplashScreen()
        from xpra.gtk.window import add_close_accel
        add_close_accel(w, Gtk.main_quit)
        return w.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
