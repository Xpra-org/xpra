#!/usr/bin/env python3

import sys
import json
from io import BytesIO
import os.path
from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue

from PIL import Image
import cairo

Gtk = gi_import("Gtk")
Pango = gi_import("Pango")


winfo = "window.info"


def read_json(filename: str):
    with open(filename, "rb") as f:
        serialized = f.read()
    return json.loads(serialized)


def load_window_dir(dirpath: str) -> tuple[dict, list[dict]]:
    data = {}
    windowinfo_file = os.path.join(dirpath, winfo)
    if not os.path.exists(windowinfo_file):
        raise ValueError(f"directory {dirpath!r} does not look like a replay directory, {winfo!r} not found")
    windowinfo = read_json(windowinfo_file)

    for dirname in os.listdir(dirpath):
        if dirname == winfo:
            continue
        subdirpath = os.path.join(dirpath, dirname)
        if not os.path.isdir(subdirpath):
            print(f"warning: {subdirpath!r} is not a directory!")
            continue
        try:
            ts = int(dirname)
        except ValueError:
            raise ValueError(f"directory {dirname!r} is not a timestamp!") from None
        data[ts] = load_update_dir(subdirpath)
    updates = []
    for ts in sorted(data.keys()):
        updates.append(data[ts])
    return windowinfo, updates


def load_update_dir(dirpath: str) -> dict:
    data = {}
    for entry in os.listdir(dirpath):
        if not entry.endswith(".info"):
            continue
        flush = int(entry.split(".", 1)[0])
        filename = os.path.join(dirpath, entry)
        update_data = read_json(filename)
        update_data["directory"] = dirpath
        data[flush] = update_data
    return dict(reversed(sorted(data.items())))


class ReplayApp:

    def __init__(self, window_info: dict, replay_data: list[dict]):
        self.replay_data = replay_data
        self.frame = 0
        self.update = 0
        self.frame_data = {}
        self.backing = None
        self.window_info = window_info
        self.window_size = window_info.get("dimensions", (200, 200))
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect("draw", self.draw_cb)
        self.replay_window = self.init_replay_window()
        self.control_window = self.init_control_window()
        self.draw_frame()

    def init_replay_window(self) -> Gtk.Window:
        replay_window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        replay_window.set_size_request(*self.window_size)
        replay_window.add(self.drawing_area)
        replay_window.connect("delete_event", Gtk.main_quit)
        replay_window.show_all()
        return replay_window

    def init_control_window(self) -> Gtk.Window:
        control_window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        control_window.set_transient_for(self.replay_window)
        control_window.set_size_request(1920, 720)
        control_window.connect("delete_event", Gtk.main_quit)
        vbox = Gtk.VBox(homogeneous=False, spacing=0)

        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        vbox.pack_start(hbox, False, False, 10)

        restart = Gtk.Button(label="Restart")
        restart.connect("clicked", self.restart)
        hbox.add(restart)
        nf = Gtk.Button(label="Next Frame")
        nf.connect("clicked", self.next_frame)
        hbox.add(nf)

        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        vbox.pack_start(hbox, False, False, 10)

        pu = Gtk.Button(label="Previous Update")
        pu.connect("clicked", self.previous_update)
        hbox.add(pu)
        nu = Gtk.Button(label="Next Update")
        nu.connect("clicked", self.next_update)
        hbox.add(nu)

        self.label = Gtk.Label()
        fontdesc = Pango.FontDescription("monospace 9")
        self.label.modify_font(fontdesc)
        self.label.set_margin_start(10)
        self.label.set_xalign(0)
        self.label.set_line_wrap(True)
        vbox.pack_start(self.label, True, True, 0)

        control_window.add(vbox)
        control_window.show_all()
        return control_window

    def update_label(self) -> None:
        frame_info = [
            f"frame {self.frame} / {len(self.replay_data)}",
            f"update {self.update} / {len(self.frame_data)}",
            "",
        ]

        for flush, data in self.frame_data.items():
            prefix = "****" if flush == self.update else "    "
            frame_info.append(f"{prefix}{flush} = {data}")
        self.label.set_label("\n".join(frame_info))

    def previous_update(self, *_args):
        if self.update > 0:
            self.update = self.update - 1
            self.draw_update()

    def next_update(self, *_args):
        self.update = self.update + 1
        if self.update >= len(self.frame_data):
            self.next_frame()
        else:
            self.draw_update()

    def draw_cb(self, _widget, cr):
        cr.set_source_surface(self.backing, 0, 0)
        cr.paint()
        return False

    def draw_update(self):
        self.update_label()
        update = self.frame_data[self.update]
        x = update["x"]
        y = update["y"]
        w = update["w"]
        h = update["h"]
        stride = update["stride"]
        options = update.get("options", {})
        if not options.get("paint", True):
            return

        ww, wh = self.window_size
        if self.backing is None:
            self.backing = cairo.ImageSurface(cairo.Format.ARGB32, ww, wh)

        encoding = update.get("encoding")
        filename = update.get("file", f"{self.update}.{encoding}")
        dirpath = update.get("directory")
        file_path = os.path.join(dirpath, filename)
        if encoding == "scroll":
            with open(file_path, "rb") as f:
                scrolls = json.loads(f.read())
            # ie: scrolls=[[0, 664, 1278, 103, 0, -264], [0, 1113, 1278, 116, 0, -264], ..]
            old_backing = self.backing
            self.backing = cairo.ImageSurface(cairo.Format.ARGB32, ww, wh)
            gc = cairo.Context(self.backing)
            gc.set_operator(cairo.Operator.SOURCE)
            gc.set_source_surface(old_backing, 0, 0)
            gc.rectangle(0, 0, ww, wh)
            gc.fill()
            for sx, sy, sw, sh, xdelta, ydelta in scrolls:
                gc.set_source_surface(old_backing, xdelta, ydelta)
                x = sx + xdelta
                y = sy + ydelta
                gc.rectangle(x, y, sw, sh)
                gc.fill()
            self.backing.flush()
        else:
            with open(file_path, "rb") as f:
                file_data = f.read()
            if encoding in ("rgb32", "rgb24"):
                rgb_data = file_data
                if options.get("lz4"):
                    from xpra.net.lz4.lz4 import decompress
                    rgb_data = decompress(file_data)
                rgb_format = options.get("rgb_format", "BGRX")
                if len(rgb_format) == 3:
                    from xpra.codecs.argb.argb import rgb_to_bgrx
                    rgb_data = rgb_to_bgrx(rgb_data)
            else:
                buf = BytesIO(file_data)
                img = Image.open(buf)
                img = img.convert("RGBA")
                rgb_data = img.tobytes("raw", img.mode)
            ba = bytearray(rgb_data)
            cfmt = cairo.FORMAT_ARGB32 if encoding != "rgb24" else cairo.FORMAT_RGB24
            surface = cairo.ImageSurface.create_for_data(ba, cfmt, w, h, stride or w*4)
            # paint in on the backing:
            ctx = cairo.Context(self.backing)
            ctx.set_source_surface(surface, x, y)
            ctx.paint()
        self.drawing_area.queue_draw()

    def restart(self, *_args) -> None:
        # we need to undo the updates!
        # (or just use the screenshot next?)
        self.frame = 0
        self.update = 0
        self.draw_frame()

    def next_frame(self, *_args) -> None:
        # make sure we apply all the updates before moving to the next frame:
        while self.update < len(self.frame_data) - 1:
            self.update = self.update + 1
            self.draw_update()
        self.frame = (self.frame + 1) % len(self.replay_data)
        self.update = 0
        self.draw_frame()

    def draw_frame(self, *_args) -> None:
        self.frame_data = self.replay_data[self.frame]
        self.draw_update()

    def run(self) -> ExitValue:
        Gtk.main()
        return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        print("usage: %s directory" % (argv[0]))
        return 1
    dirpath = argv[1]
    app = ReplayApp(*load_window_dir(dirpath))
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
