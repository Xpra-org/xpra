# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import shlex
from textwrap import wrap
from subprocess import Popen, PIPE

from xpra.util.types import AtomicInteger
from xpra.os_util import gi_import, OSX, WIN32
from xpra.util.system import is_gnome, is_X11
from xpra.gtk.configure.common import DISCLAIMER, sync
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label, slabel, title_box
from xpra.platform.paths import get_image
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("gstreamer", "util")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.warning_shown = False
        self.warning_pixbuf = get_image("warning.png")
        size = (800, 554)
        if self.warning_pixbuf:
            size = self.warning_pixbuf.get_width()+20, self.warning_pixbuf.get_height()+20
        super().__init__(
            "Configure Xpra's GStreamer Codecs",
            "gstreamer.png",
            wm_class=("xpra-configure-gstreamer-gui", "Xpra Configure GStreamer GUI"),
            default_size=size,
            header_bar=(True, False),
            parent=parent,
        )
        self.set_resizable(False)

    def populate(self):
        self.clear_vbox()
        if not self.warning_shown:
            self.populate_with_warning()
        else:
            self.populate_with_grid()
        self.vbox.show_all()

    def populate_with_grid(self):
        self.add_widget(label("Configure Xpra GStreamer Codecs", font="sans 20"))
        grid = Gtk.Grid()
        grid.set_row_homogeneous(False)
        grid.set_column_homogeneous(True)
        hbox = Gtk.HBox()
        hbox.add(slabel("Please select the viewing element"))
        videosink = "ximagesink"
        self.add_widget(hbox)
        self.add_widget(grid)
        grid.attach(title_box("Mode"), 0, 0, 1, 1)
        grid.attach(title_box("GStreamer Elements"), 1, 0, 1, 1)
        grid.attach(title_box("Test"), 2, 0, 1, 1)
        grid.attach(title_box("Result"), 3, 0, 1, 1)
        row = AtomicInteger(1)

        WIDTH = 640
        HEIGHT = 480
        FRAMERATE = 10

        def lal(text:str, element:str, test="") -> None:
            r = int(row)
            grid.attach(title_box(text), 0, r, 1, 1)
            lbl = slabel(element)
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
            al.add(lbl)
            grid.attach(al, 1, r, 1, 1)
            if test:
                btn = Gtk.Button(label="Run")
                grid.attach(btn, 2, r, 1, 1)
                lbl = slabel()
                al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
                al.add(lbl)
                grid.attach(al, 3, r, 1, 1)

                def run_test(btn, lbl):
                    log(f"run_test({btn}, {lbl})")
                    lbl.set_label(f"Testing {element}")
                    from xpra.util.thread import start_thread
                    start_thread(self.test_element, f"test {element}", True, (lbl, element, test))
                btn.connect("clicked", run_test, lbl)
            row.increase()
        if is_X11():
            lal("X11 Capture", "ximagesrc",
                f"ximagesrc use-damage=0 ! video/x-raw,framerate={FRAMERATE}/1 !"
                f" videoscale method=0 ! video/x-raw,width={WIDTH},height={HEIGHT}  ! {videosink}")
        if is_gnome():
            lal("pipewire ScreenCast", "pipewiresrc")
            lal("pipewire RemoteDesktop", "pipewiresrc")

        def testencoder(element, fmt) -> str:
            return "videotestsrc num-buffers=50 !"\
                   f" 'video/x-raw,format=(string)NV12,width={WIDTH},height={HEIGHT},"\
                   f"framerate=(fraction){FRAMERATE}/1' !"\
                   " videoconvert ! {element} ! avdec_{fmt} ! videoconvert ! {videosink}"

        def encoder_option(text:str, element:str, fmt:str):
            lal(text, element, testencoder(element, fmt))

        for sw in ("x264", "vp8", "vp9", "av1"):
            fmt = {"x264" : "h264"}.get(sw, sw)
            encoder_option(f"software {sw} encoder", f"{sw}enc", fmt)
        for fmt in ("h264", "h265", "jpeg", "vp8", "vp9"):
            encoder_option(f"vaapi {fmt} encoder", f"vaapi{fmt}enc", fmt)
            encoder_option(f"libva {fmt} encoder", f"va{fmt}enc", fmt)
        if WIN32:
            for fmt in ("h264", "h265"):
                encoder_option(f"NVidia D3D11 {fmt}", f"nvd3d11{fmt}enc", fmt)
        for fmt in ("h264", "h265"):
            encoder_option(f"NVENC {fmt}", f"nv{fmt}enc", fmt)
        if not (OSX or WIN32):
            for fmt in ("h264", "h265"):
                lal(f"AMD AMF {fmt}", f"amf{fmt}enc", fmt)

    def test_element(self, lbl, element, test):

        def set_label(message="OK"):
            GLib.timeout_add(1000, lbl.set_label, message)

        def run_test_cmd(cmd):
            try:
                log.info(f"running {cmd!r}")
                proc = Popen(cmd, text=True, stdout=PIPE, stderr=PIPE)
                out, err = proc.communicate(None)
                if proc.returncode==0:
                    return True
                log(f"{proc}.communicate(None)={out!r},{err!r}")
                log.error(f"Error: {cmd!r} returned {proc.returncode}")
                set_label(f"Error: test pipeline returned {proc.returncode}")
            except OSError as e:
                log.error(f"Error running {cmd!r}: {e}")
                set_label(f"Error: {e}")
            return False
        sync()
        # first make sure that the element exists:
        if not run_test_cmd(["gst-inspect-1.0", element]):
            return
        set_label("Element found")
        if not run_test_cmd(["gst-launch-1.0"]+shlex.split(test)):
            return
        set_label("Test pipeline worked")

    def populate_with_warning(self):
        layout = Gtk.Layout()
        layout.set_margin_top(0)
        layout.set_margin_bottom(0)
        layout.set_margin_start(0)
        layout.set_margin_end(0)
        self.vbox.add(layout)
        if self.warning_pixbuf:
            image = Gtk.Image.new_from_pixbuf(self.warning_pixbuf)
            layout.put(image, 0, 0)
        for i, text in enumerate((
            "This tool can cause your system to crash,",
            "it may even damage hardware in rare cases.",
            "            Use with caution.",
        )):
            lbl = label(text, font="Sans 22")
            layout.put(lbl, 86, 70+i*40)
        for i, line in enumerate(wrap(DISCLAIMER, width=70)):
            lbl = label(line, font="Sans 12")
            layout.put(lbl, 72, 220+i*24)
        button = Gtk.Button.new_with_label("Understood")
        button.connect("clicked", self.understood)
        layout.put(button, 200, 450)
        button = Gtk.Button.new_with_label("Get me out of here")
        button.connect("clicked", self.dismiss)
        layout.put(button, 400, 450)
        self.warning_shown = True

    def understood(self, *args):
        self.warning_shown = True
        self.populate()


def main(_args) -> int:
    from xpra.gtk.configure.main import run_gui
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
