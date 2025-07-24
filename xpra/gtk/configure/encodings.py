# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.configure.common import run_gui
from xpra.gtk.info import get_average_monitor_refresh_rate
from xpra.util.config import update_config_attribute, with_config
from xpra.gtk.widget import label
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def adj1_100(value: int) -> Gtk.Adjustment:
    return Gtk.Adjustment(value=value, lower=1, upper=100, step_increment=5, page_increment=0, page_size=0)


def make_scale(adjust, marks: dict) -> Gtk.Scale:
    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjust)
    for value, text in marks.items():
        scale.add_mark(value=value, position=Gtk.PositionType.TOP, markup=text)
    scale.set_digits(0)
    scale.set_draw_value(True)
    scale.set_has_origin(True)
    return scale


FRAMERATES: dict[str, str] = {
    "automatic": "auto",
    "1 fps": "1",
    "10 fps": "10",
    "15 fps": "15",
    "30 fps": "30",
    "50 fps": "50",
    "60 fps": "60",
    "75 fps": "75",
    "100 fps": "100",
    "50%": "50%",
    "20%": "20%",
}


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        super().__init__(
            "Configure Xpra's Picture Compression",
            "encoding.png",
            wm_class=("xpra-configure-encodings-gui", "Xpra Configure Encodings GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        with_config(self.do_populate)

    def do_populate(self, config) -> bool:
        self.clear_vbox()
        self.add_widget(label("Configure Xpra's Picture Compression", font="sans 20"))
        url = "https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Encodings.md#tuning"
        self.add_text_lines((
            f"Please read <a href='{url}'>the documentation</a>.",
        ))
        self.add_widget(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        rate = get_average_monitor_refresh_rate()
        text = "Framerate (Hz)"
        if rate > 0:
            text += f" (default: {rate})"
        self.add_widget(label(text, font="Sans 14"))
        self.add_widget(label("Lowering the framerate saves bandwidth and CPU time"))
        framerate_combo = Gtk.ComboBoxText()
        index = 0
        for rate, setting in FRAMERATES.items():
            framerate_combo.append_text(rate)
            if setting == config.refresh_rate:
                framerate_combo.set_active(index)
            index += 1
        framerate_combo.connect("changed", self.framerate_changed)
        self.add_widget(framerate_combo)
        self.add_widget(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.add_widget(label("Minimum Speed (percentage)", font="Sans 14"))
        self.add_widget(label("Increasing the speed costs bandwidth and CPU time"))
        scale = make_scale(adj1_100(config.min_speed), {
            1: "Lowest",
            50: "Average",
            100: "Highest",
        })
        scale.connect("value-changed", self.speed_changed)
        self.add_widget(scale)
        self.add_widget(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.add_widget(label("Minimum Quality (percentage)", font="Sans 14"))
        self.add_widget(label("Increasing the quality costs bandwidth, CPU time and may also increase the latency"))
        scale = make_scale(adj1_100(config.min_quality), {
            1: "Lowest",
            50: "Average",
            100: "Highest",
        })
        scale.connect("value-changed", self.quality_changed)
        self.add_widget(scale)
        self.add_widget(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.add_widget(label("Auto Refresh Delay (milliseconds)", font="Sans 14"))
        self.add_widget(label("Longer delays may become noticeable but save bandwidth"))
        adjust = Gtk.Adjustment(value=round(config.auto_refresh_delay * 1000), lower=0, upper=1000,
                                step_increment=50, page_increment=0, page_size=0)
        scale = make_scale(adjust, {
            0: "Disabled",
            50: "Fast",
            500: "Average",
            1000: "Slow",
        })
        scale.connect("value-changed", self.ar_changed)
        self.add_widget(scale)
        self.add_widget(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        grid = Gtk.Grid()
        grid.set_margin_start(40)
        grid.set_margin_end(40)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)
        switch = Gtk.Switch()
        switch.set_state(config.encoding == "grayscale")
        switch.connect("state-set", self.toggle_grayscale)
        lbl = label("Grayscale Mode", font="Sans 14")
        lbl.set_hexpand(True)
        grid.attach(lbl, 0, 0, 1, 1)
        grid.attach(switch, 1, 0, 1, 1)
        self.add_widget(label("Grayscale mode may save a little bandwidth and CPU time"))
        self.show_all()
        return False

    @staticmethod
    def framerate_changed(combo) -> None:
        value = FRAMERATES.get(combo.get_active_text(), "")
        update_config_attribute("refresh-rate", value)

    @staticmethod
    def speed_changed(widget) -> None:
        update_config_attribute("min-speed", int(widget.get_value()))

    @staticmethod
    def quality_changed(widget) -> None:
        update_config_attribute("min-quality", int(widget.get_value()))

    @staticmethod
    def ar_changed(widget) -> None:
        update_config_attribute("auto-refresh-delay", int(widget.get_value())/1000)

    @staticmethod
    def toggle_grayscale(_widget, state) -> None:
        update_config_attribute("encoding", "grayscale" if state else "auto")


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
