#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Create a real GTK3 xpra ClientWindow using FakeClient."""

import os
import sys
from typing import Any

os.environ.setdefault("XPRA_USE_FAKE_BACKING", "1")

from xpra.client.gui.fake_client import FakeClient
from xpra.client.gui.window_border import WindowBorder
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.log import consume_verbose_argv
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("window")

MIXIN_NAMES: tuple[str, ...] = (
    "action", "headerbar", "dragndrop", "focus",
    "grab", "workspace", "keyboard", "pointer",
)


class TestClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.title = "@title@"

    def get_window_menu_helper(self):
        return None

    def get_frame_extents(self, *_args) -> dict[str, Any]:
        return {}

    def get_root_size(self) -> tuple[int, int]:
        screen = Gtk.Window().get_screen()
        return screen.get_width(), screen.get_height()

    def after_handshake(self, callback, *args) -> None:
        GLib.idle_add(callback, *args)

    def get_image(self, icon_name: str, size=None):
        try:
            from xpra.gtk.pixbuf import get_icon_pixbuf
            pixbuf = get_icon_pixbuf(icon_name)
            if pixbuf and size:
                pixbuf = pixbuf.scale_simple(size, size, 2)
            if pixbuf:
                return Gtk.Image.new_from_pixbuf(pixbuf)
        except Exception:
            pass
        return Gtk.Image()

    def window_close_event(self, wid: int, *_args) -> None:
        if window := self._id_to_window.get(wid):
            window.destroy()


def parse_geometry(value: str) -> tuple[int, int, int, int]:
    try:
        size, _, pos = value.partition("+")
        w, h = (int(x) for x in size.lower().split("x", 1))
        if pos:
            x, y = (int(x) for x in pos.split("+", 1))
        else:
            x, y = 100, 100
        return x, y, w, h
    except Exception as e:
        raise ValueError(f"invalid geometry {value!r}: {e}") from None


class Options:
    geometry = 100, 100, 511, 225
    headerbar = "force"
    title = "FakeClient xterm"
    min_width = 25
    min_height = 17
    base_width = 4
    base_height = 4
    width_inc = 8
    height_inc = 17
    max_width = 0
    max_height = 0
    mixins = ",".join(MIXIN_NAMES)
    no_platform_hooks = False
    no_backing = False
    no_update_metadata = False
    no_finalize = False
    no_class_instance = False
    no_window_type = False
    no_size_constraints = False


def make_metadata(args) -> typedict:
    constraints = {
        "minimum-size": (args.min_width, args.min_height),
    }
    if args.base_width or args.base_height:
        constraints["base-size"] = (args.base_width, args.base_height)
    if args.width_inc or args.height_inc:
        constraints["increment"] = (args.width_inc, args.height_inc)
    if args.max_width or args.max_height:
        constraints["maximum-size"] = (args.max_width or 32768, args.max_height or 32768)
    metadata = typedict({
        "title": args.title,
        "decorations": True,
        "has-alpha": False,
        "size-constraints": constraints,
    })
    if not args.no_class_instance:
        metadata["class-instance"] = ("xterm", "XTerm")
    if not args.no_window_type:
        metadata["window-type"] = ("NORMAL",)
    if args.no_size_constraints:
        metadata.pop("size-constraints", None)
    return metadata


def patch_window_base_classes(args) -> None:
    def add_mixin(bases: list[type], name: str) -> None:
        if name == "action":
            from xpra.client.gui.window.action import ActionWindow
            bases.append(ActionWindow)
        elif name == "headerbar":
            from xpra.client.gtk3.window.headerbar import HeaderBarWindow
            bases.append(HeaderBarWindow)
        elif name == "dragndrop":
            from xpra.client.gtk3.window.dragndrop import DragNDropWindow
            bases.append(DragNDropWindow)
        elif name == "focus":
            from xpra.client.gtk3.window.focus import FocusWindow
            bases.append(FocusWindow)
        elif name == "grab":
            from xpra.client.gtk3.window.grab import GrabWindow
            bases.append(GrabWindow)
        elif name == "workspace":
            from xpra.client.gtk3.window.workspace import WorkspaceWindow
            bases.append(WorkspaceWindow)
        elif name == "keyboard":
            from xpra.client.gtk3.window.keyboard import KeyboardWindow
            bases.append(KeyboardWindow)
        elif name == "pointer":
            from xpra.client.gtk3.window.pointer import PointerWindow
            bases.append(PointerWindow)
        else:
            raise ValueError(f"invalid mixin {name!r}")

    def get_window_base_classes() -> tuple[type, ...]:
        from xpra.client.gtk3.window.base import GTKClientWindowBase
        bases: list[type] = [GTKClientWindowBase]
        for name in args.mixins.split(","):
            name = name.strip().lower()
            if name:
                add_mixin(bases, name)
        log.info("fake client window bases from mixins=%r: %s",
                 args.mixins, [c.__name__ for c in bases])
        return tuple(bases)

    from xpra.client.gtk3.window import factory
    factory.get_window_base_classes = get_window_base_classes


def patch_window_methods(args) -> None:
    from xpra.common import noop
    if args.no_platform_hooks:
        from xpra.client.gtk3.window import base
        base.add_window_hooks = noop
        base.remove_window_hooks = noop
    if args.no_backing:
        from xpra.client.gui.window_base import ClientWindowBase
        ClientWindowBase.setup_window = lambda _self, _bw, _bh: None
    if args.no_update_metadata:
        from xpra.client.gui.window_base import ClientWindowBase
        ClientWindowBase.update_metadata = lambda _self, _metadata: None
    if args.no_finalize:
        from xpra.client.gui.window_base import ClientWindowBase
        ClientWindowBase.finalize_window = noop
        from xpra.client.gtk3.window.base import GTKClientWindowBase
        GTKClientWindowBase.finalize_window = noop


def make_xpra_window(args):
    patch_window_base_classes(args)
    # Import after XPRA_USE_FAKE_BACKING is set.
    from xpra.client.gtk3.window.window import ClientWindow
    patch_window_methods(args)
    log.info("fake client window MRO: %s", [c.__name__ for c in ClientWindow.__mro__])

    client = TestClient()
    wid = 1
    geom = args.geometry
    metadata = make_metadata(args)
    window = ClientWindow(
        client, None, wid,
        geom, geom[2:4],
        metadata, False, typedict(),
        WindowBorder(False),
        (32768, 32768), 24,
        headerbar=args.headerbar,
    )
    client._id_to_window[wid] = window
    client._window_to_id[window] = wid

    def close_window(_window, _event) -> bool:
        window.destroy()
        return True

    window.connect("delete-event", close_window)
    return window


def make_simple_window(args):
    from xpra.gtk.examples.window_geometry_hints import HintedWindows
    kwargs = {
        "title": "simple GTK",
        "headerbar": args.headerbar not in ("0", "no", "false", "off"),
        "width": args.geometry[2],
        "height": args.geometry[3],
        "min_width": args.min_width,
        "min_height": args.min_height,
    }
    if args.base_width or args.base_height:
        kwargs.update({
            "base_width": args.base_width,
            "base_height": args.base_height,
        })
    if args.width_inc or args.height_inc:
        kwargs.update({
            "width_inc": args.width_inc,
            "height_inc": args.height_inc,
        })
    if args.max_width or args.max_height:
        kwargs.update({
            "max_width": args.max_width or 32768,
            "max_height": args.max_height or 32768,
        })
    window = HintedWindows(**kwargs)
    window.move(args.geometry[0] + args.geometry[2] + 40, args.geometry[1])
    return window


class LauncherWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Fake Client Window")
        self.set_default_size(620, 420)
        self.connect("destroy", Gtk.main_quit)
        self.windows = []

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)
        self.add(grid)

        row = 0
        self.geometry = self.entry("511x225+100+100")
        self.attach_row(grid, row, "Geometry", self.geometry)
        row += 1

        self.title_entry = self.entry(Options.title)
        self.attach_row(grid, row, "Title", self.title_entry)
        row += 1

        self.headerbar = self.combo(("force", "yes", "no"), Options.headerbar)
        self.attach_row(grid, row, "Headerbar", self.headerbar)
        row += 1

        mixin_grid = Gtk.Grid()
        mixin_grid.set_column_spacing(16)
        mixin_grid.set_row_spacing(6)
        self.mixin_checks = {}
        enabled_mixins = set(Options.mixins.split(","))
        for i, name in enumerate(MIXIN_NAMES):
            check = self.check(name)
            check.set_active(name in enabled_mixins)
            self.mixin_checks[name] = check
            mixin_grid.attach(check, i % 2, i // 2, 1, 1)
        self.attach_row(grid, row, "Bases", mixin_grid)
        row += 1

        sizes = Gtk.Grid()
        sizes.set_column_spacing(8)
        sizes.set_row_spacing(8)
        self.min_width = self.spin(Options.min_width)
        self.min_height = self.spin(Options.min_height)
        self.base_width = self.spin(Options.base_width)
        self.base_height = self.spin(Options.base_height)
        self.width_inc = self.spin(Options.width_inc)
        self.height_inc = self.spin(Options.height_inc)
        self.max_width = self.spin(Options.max_width)
        self.max_height = self.spin(Options.max_height)
        for y, (label_text, w, h) in enumerate((
            ("Minimum", self.min_width, self.min_height),
            ("Base", self.base_width, self.base_height),
            ("Increment", self.width_inc, self.height_inc),
            ("Maximum", self.max_width, self.max_height),
        )):
            sizes.attach(Gtk.Label(label=label_text, xalign=0), 0, y, 1, 1)
            sizes.attach(w, 1, y, 1, 1)
            sizes.attach(h, 2, y, 1, 1)
        self.attach_row(grid, row, "Constraints", sizes)
        row += 1

        flags = Gtk.Grid()
        flags.set_column_spacing(16)
        flags.set_row_spacing(6)
        self.no_platform_hooks = self.check("No platform hooks")
        self.no_backing = self.check("No backing")
        self.no_update_metadata = self.check("No metadata")
        self.no_finalize = self.check("No finalize")
        self.no_class_instance = self.check("No class-instance")
        self.no_window_type = self.check("No window-type")
        self.no_size_constraints = self.check("No size constraints")
        for i, widget in enumerate((
            self.no_platform_hooks, self.no_backing, self.no_update_metadata,
            self.no_finalize, self.no_class_instance, self.no_window_type,
            self.no_size_constraints,
        )):
            flags.attach(widget, i % 2, i // 2, 1, 1)
        self.attach_row(grid, row, "Switches", flags)
        row += 1

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label_text, callback in (
            ("Create Xpra", self.create_xpra),
            ("Create Simple", self.create_simple),
            ("Create Both", self.create_both),
        ):
            button = Gtk.Button(label=label_text)
            button.connect("clicked", callback)
            buttons.pack_start(button, False, False, 0)
        grid.attach(buttons, 1, row, 1, 1)

    @staticmethod
    def entry(text: str) -> Gtk.Entry:
        widget = Gtk.Entry()
        widget.set_text(text)
        widget.set_hexpand(True)
        return widget

    @staticmethod
    def spin(value: int) -> Gtk.SpinButton:
        widget = Gtk.SpinButton.new_with_range(0, 32768, 1)
        widget.set_value(value)
        return widget

    @staticmethod
    def check(label: str) -> Gtk.CheckButton:
        return Gtk.CheckButton(label=label)

    @staticmethod
    def combo(values: tuple[str, ...], active: str) -> Gtk.ComboBoxText:
        widget = Gtk.ComboBoxText()
        for value in values:
            widget.append_text(value)
        widget.set_active(max(0, values.index(active) if active in values else 0))
        return widget

    @staticmethod
    def attach_row(grid: Gtk.Grid, row: int, label_text: str, widget) -> None:
        grid.attach(Gtk.Label(label=label_text, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    def get_options(self) -> Options | None:
        options = Options()
        try:
            options.geometry = parse_geometry(self.geometry.get_text())
        except ValueError as e:
            log.error("Error: %s", e)
            return None
        options.title = self.title_entry.get_text()
        options.headerbar = self.headerbar.get_active_text() or Options.headerbar
        options.mixins = ",".join(
            name for name, check in self.mixin_checks.items() if check.get_active()
        )
        for name in (
            "min_width", "min_height", "base_width", "base_height",
            "width_inc", "height_inc", "max_width", "max_height",
        ):
            setattr(options, name, getattr(self, name).get_value_as_int())
        for name in (
            "no_platform_hooks", "no_backing", "no_update_metadata",
            "no_finalize", "no_class_instance", "no_window_type",
            "no_size_constraints",
        ):
            setattr(options, name, getattr(self, name).get_active())
        return options

    def track_window(self, window) -> None:
        self.windows.append(window)

        def cleanup(_window) -> None:
            if _window in self.windows:
                self.windows.remove(_window)

        window.connect("destroy", cleanup)
        window.show_all()
        window.present()

    def create_xpra(self, *_args) -> None:
        if options := self.get_options():
            self.track_window(make_xpra_window(options))

    def create_simple(self, *_args) -> None:
        if options := self.get_options():
            self.track_window(make_simple_window(options))

    def create_both(self, *_args) -> None:
        if options := self.get_options():
            self.track_window(make_xpra_window(options))
            self.track_window(make_simple_window(options))


def main(argv: list[str]) -> int:
    consume_verbose_argv(argv, "all")

    from xpra.platform import program_context
    from xpra.gtk.util import quit_on_signals, gtk_main
    from xpra.util.system import is_X11

    with program_context("fake-client-window", "Fake Client Window"):
        if is_X11():
            from xpra.x11.gtk.display_source import init_gdk_display_source
            init_gdk_display_source()
        quit_on_signals("fake client window")
        launcher = LauncherWindow()

        def show_launcher() -> None:
            from xpra.platform.gui import force_focus
            force_focus()
            launcher.show_all()
            launcher.present()

        GLib.idle_add(show_launcher)
        gtk_main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
