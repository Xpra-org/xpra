# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
from math import sqrt
from time import monotonic

from xpra import __version__
from xpra.util.env import envint, envbool, ignorewarnings
from xpra.os_util import OSX, WIN32, gi_import
from xpra.util.system import SIGNAMES
from xpra.util.thread import start_thread
from xpra.exit_codes import ExitCode, ExitValue
from xpra.common import SPLASH_EXIT_DELAY
from xpra.gtk.widget import label
from xpra.gtk.css_overrides import add_screen_css
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.util.glib import install_signal_handlers
from xpra.gtk.css_overrides import inject_css_overrides
from xpra.platform.gui import force_focus, set_window_progress
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

log = Logger("splash")

inject_css_overrides()

TIMEOUT = envint("XPRA_SPLASH_TIMEOUT", 60)
READ_SLEEP = envint("XPRA_SPLASH_READ_SLEEP", 0)
FOCUS_EXIT = envbool("XPRA_SPLASH_FOCUS_EXIT", True)
FADEOUT = envbool("XPRA_SPLASH_FADEOUT", True)
ICON = os.environ.get("XPRA_SPLASH_ICON", "xpra.png")
TITLE = os.environ.get("XPRA_SPLASH_TITLE", "Xpra %s" % __version__)
SIZE = os.environ.get("XPRA_SPLASH_SIZE", "normal")
THREADED_READ = envbool("XPRA_SPLASH_THREADED_READ", WIN32)

if SIZE == "small":
    W = 240
    FONT_SIZE = 12
    LINE_SIZE = 30
    MARGIN = 5
    LINES = 3
elif SIZE == "big":
    W = 600
    FONT_SIZE = 15
    LINE_SIZE = 50
    MARGIN = 25
    LINES = 7
else:
    W = 400
    FONT_SIZE = 13
    LINE_SIZE = 40
    MARGIN = 15
    LINES = 5
LINES = envint("XPRA_SPLASH_LINES", LINES)


CSS = b"""
#splash-frame {
    background-color: rgba(35, 35, 48, 0.90);
    border-radius: 20px;
}
title {
    color: #f0fff0;
}
label {
    color: #f0fff0;
}
#progress-bar > trough {
    border-radius: 8px;
    background-color: #e0e0e0;
}
#progress-bar > trough > progress {
    background-color: #4CA450;
    border-radius: 5px;
}
#progress-bar progress {
    background-image: linear-gradient(to right, #66bb6a, #43a047);
}
"""

IO_CONDITIONS: dict = {
    GLib.IOCondition.ERR: "ERR",
    GLib.IOCondition.HUP: "HUP",
    GLib.IOCondition.IN: "IN",
    GLib.IOCondition.NVAL: "NVAL",
    GLib.IOCondition.OUT: "OUT",
    GLib.IOCondition.PRI: "PRI",
}


def cond(mask: int) -> str:
    return "|".join(v for k, v in IO_CONDITIONS.items() if mask & k)


class SplashScreen(Gtk.Window):

    def __init__(self, title=TITLE, icon_name=ICON):
        self.exit_code = None
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.connect("delete_event", self.exit)
        self.add_events(Gdk.EventType.BUTTON_PRESS)
        self.connect("button-press-event", self.exit)
        self.connect("key-press-event", self.exit)
        self.set_title(title)
        self.set_size_request(W, 20 + MARGIN + LINE_SIZE * (1 + LINES))

        # enable transparency and compositing
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.init_css()

        # main container with rounded corners
        frame = Gtk.Frame()
        frame.set_name("splash-frame")
        frame.set_shadow_type(Gtk.ShadowType.NONE)

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
        vbox.set_margin_start(MARGIN + 5)
        vbox.set_margin_end(MARGIN + 5)
        vbox.set_margin_top(MARGIN)
        vbox.set_margin_bottom(MARGIN)
        hbox = Gtk.HBox(homogeneous=False)
        if icon_name:
            image = Gtk.Image()
            hbox.pack_start(image, False, False, 20)

            def set_icon(filename: str) -> None:
                icon = get_icon_pixbuf(filename)
                if icon:
                    image.set_from_pixbuf(icon)

            if icon_name.startswith("http"):
                def download() -> None:
                    from urllib.request import urlretrieve
                    from xpra.platform.paths import get_xpra_tmp_dir
                    ext = os.path.splitext(icon_name)[1]
                    icon_tmp = os.path.join(get_xpra_tmp_dir(), f"splash-icon.{ext}")
                    urlretrieve(icon_name, icon_tmp)
                    GLib = gi_import("GLib")
                    GLib.idle_add(set_icon, icon_tmp)
                from xpra.util.thread import start_thread
                start_thread(download, "download-icon", daemon=True)
            else:
                set_icon(icon_name)
        self.title_label = label(title, font=f"Adwaita sans {FONT_SIZE+5}")
        self.title_label.set_css_name("title")
        al = Gtk.Alignment(xalign=0.2, yalign=0.5, xscale=0, yscale=0)
        al.add(self.title_label)
        hbox.pack_start(al, True, True, 20)
        vbox.add(hbox)
        self.labels = []
        for i in range(LINES):
            lbl = label(" ", font=f"Adwaita sans {FONT_SIZE}")
            lbl.set_css_name("label")
            lbl.set_opacity(sqrt((i + 1) / LINES))
            self.labels.append(lbl)
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0, yscale=0)
            al.add(lbl)
            vbox.pack_start(al, True, True, 4)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_size_request(W - 40 - MARGIN * 2, LINE_SIZE - 10)
        self.progress_bar.set_show_text(False)
        self.progress_bar.set_fraction(0)
        self.progress_bar.set_name("progress-bar")
        self.progress_timer = 0
        self.fade_out_timer = 0
        self.exit_timer = 0
        vbox.add(self.progress_bar)
        self.timeout_timer = 0
        self.line_count = 0
        frame.add(vbox)
        self.add(frame)
        install_signal_handlers("Splash", self.handle_signal)
        sigpipe = getattr(signal, "SIGPIPE", None)
        if sigpipe:  # ie: POSIX
            signal.signal(sigpipe, self.handle_signal)
        self.opacity = 100
        self.pct = 0
        self.start_time = monotonic()
        self.had_top_level_focus = False
        self.connect("notify::has-toplevel-focus", self._focus_change)

    def init_css(self) -> None:
        add_screen_css(CSS)

    def run(self) -> ExitValue:
        start_thread(self.read_thread, "read-thread", True)
        self.show_all()
        force_focus()
        self.present()
        self.timeout_timer = GLib.timeout_add(TIMEOUT * 1000, self.timeout)
        scrash = envint("XPRA_SPLASH_CRASH", -1)
        if scrash >= 0:
            from xpra.os_util import crash
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

    def read_thread(self) -> None:
        while self.exit_code is None:
            try:
                line = sys.stdin.readline()
                log("read_stdin_line() line=%r", line)
                if not line:
                    # EOF
                    self.exit()
                    return
                self.line_count += 1
                if line.strip():
                    GLib.timeout_add(self.line_count * READ_SLEEP, self.handle_stdin_line, line)
            except OSError:
                self.exit_code = ExitCode.FAILURE
                self.exit()
                return

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
            else:
                if self.pct != pct:
                    for i in range(len(self.labels) - 1):
                        next_line = self.labels[i + 1].get_label()
                        self.labels[i].set_label(next_line)
                self.labels[-1].set_label(text)
        self.pct = pct

    def show_progress_value(self, pct: int) -> None:
        self.cancel_progress_timer()
        GLib.idle_add(self.progress_bar.set_fraction, pct / 100.0)
        if pct >= 100:
            self.exit_code = 0
            self.cancel_fade_out_timer()
            if FADEOUT:
                self.fade_out_timer = GLib.timeout_add(SPLASH_EXIT_DELAY * 1000 // 100, self.fade_out)
            self.cancel_exit_timer()

            def exit_splash() -> None:
                self.exit_timer = 0
                self.exit()

            self.exit_timer = GLib.timeout_add(SPLASH_EXIT_DELAY * 1000, exit_splash)
        else:
            self.progress_timer = GLib.timeout_add(40, self.increase_fraction, pct)
            self.opacity = min(100, max(50, 130 - pct))
            if FADEOUT:
                self.set_opacity(sqrt(sqrt(self.opacity / 100.0)))
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
            self.set_opacity(sqrt(self.opacity / 100.0))
        if actual <= 0:
            self.fade_out_timer = 0
        return actual > 0

    def exit(self, *args) -> None:
        log("exit%s calling %s", args, Gtk.main_quit)
        if self.exit_code is None:
            self.exit_code = 0
        self.cancel_progress_timer()
        self.cancel_timeout_timer()
        self.cancel_fade_out_timer()
        self.cancel_exit_timer()
        Gtk.main_quit()

    def handle_signal(self, signum, frame=None) -> None:
        log("handle_signal(%s, %s)", SIGNAMES.get(signum, signum), frame)
        self.exit_code = 128 - (signum or 0)
        GLib.idle_add(self.exit)


def main(args: list[str]) -> ExitValue:
    import os
    if os.environ.get("XPRA_HIDE_DOCK") is None:
        os.environ["XPRA_HIDE_DOCK"] = "1"
    icon = ICON
    title = TITLE
    for arg in args:
        if arg.startswith("--icon="):
            icon = arg[len("--icon="):]
        elif arg.startswith("--title="):
            title = arg[len("--title="):]
        elif arg.startswith("--session-name="):
            title = arg[len("--session-name="):]
    from xpra.platform import program_context
    with program_context("splash", "Splash"):
        Gtk.Window.set_auto_startup_notification(setting=False)
        w = SplashScreen(title, icon)
        from xpra.gtk.window import add_close_accel
        add_close_accel(w, Gtk.main_quit)
        return w.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
