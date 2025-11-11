#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import re
import sys
from collections import deque
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.util.str_fn import csv
from xpra.gtk.widget import label
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.platform.features import CLIPBOARDS

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


class ClipboardInstance:
    def __init__(self, selection, _log):
        atom = Gdk.Atom.intern(selection, False)
        self.clipboard = Gtk.Clipboard.get(atom)
        self.selection = selection
        self._log = _log
        self.owned_label = label()
        self.get_targets = Gtk.ComboBoxText()
        self.get_targets.set_sensitive(False)
        self.get_targets.connect("changed", self.get_target_changed)
        self.set_targets = Gtk.ComboBoxText()
        self.set_targets.append_text("STRING")
        self.set_targets.append_text("UTF8_STRING")
        self.set_targets.set_active(0)
        self.set_targets.connect("changed", self.set_target_changed)
        self.value_label = label()
        self.value_entry = Gtk.Entry()
        self.value_entry.set_max_length(100)
        self.value_entry.set_width_chars(32)

        def b(text: str, callback: Callable):
            btn = Gtk.Button(label=text)
            btn.connect("clicked", callback)
            return btn

        self.clear_label_btn = b("X", self.clear_label)
        self.clear_entry_btn = b("X", self.clear_entry)
        self.get_get_targets_btn = b("Get Targets", self.do_get_targets)
        self.get_target_btn = b("Get Target", self.do_get_target)
        self.get_target_btn.set_sensitive(False)
        self.set_target_btn = b("Set Target", self.do_set_target)
        self.get_string_btn = b("Get String", self.do_get_string)
        self.set_string_btn = b("Set String", self.do_set_string)
        self.clipboard.connect("owner-change", self.owner_changed)
        self.log("ready")

    def __repr__(self):
        return "ClipboardInstance(%s)" % self.selection

    def log(self, msg) -> None:
        self._log(self.selection, msg)

    def clear_entry(self, *_args) -> None:
        self.value_entry.set_text("")

    def clear_label(self, *_args) -> None:
        self.value_label.set_text("")

    def get_targets_callback(self, _c, targets, *_args) -> None:
        self.log("got targets: %s" % csv(str(x) for x in targets))
        if hasattr(targets, "name"):
            self.log("target is atom: %s" % targets.name())
            targets = []
        filtered = [x for x in (targets or []) if x not in ("MULTIPLE", "TARGETS")]
        ct = self.get_targets.get_active_text()
        if not ct:
            # choose a good default target:
            for x in ("STRING", "UTF8_STRING"):
                if x in filtered:
                    ct = x
                    break
        self.get_targets.get_model().clear()
        self.get_targets.set_sensitive(True)
        i = 0
        for t in filtered:
            self.get_targets.append_text(str(t))
            if t == ct:
                self.get_targets.set_active(i)
            i += 1
        self.get_targets.show_all()

    def do_get_targets(self, *_args) -> None:
        self.clipboard.request_targets(self.get_targets_callback, None)

    def get_target_changed(self, _cb) -> None:
        target = self.get_targets.get_active_text()
        self.get_target_btn.set_sensitive(bool(target))

    def set_target_changed(self, cb) -> None:
        self.log("set_target_changed(%s) target=%s" % (cb, self.set_targets.get_active_text()))

    def ellipsis(self, val: str) -> str:
        if len(val) > 24:
            return val[:24] + ".."
        return val

    def selection_value_callback(self, _cb, selection_data, *_args) -> None:
        data = b""
        try:
            data = selection_data.get_data()
            if data is None:
                s = ""
            else:
                s = "type=%s, format=%s, data=%s" % (
                    selection_data.get_data_type(),
                    selection_data.get_format(),
                    self.ellipsis(re.escape(data)))
        except TypeError:
            try:
                s = self.ellipsis("\\".join([str(x) for x in bytearray(data)]))
            except Exception as e:
                s = f"!ERROR: {e}! binary data?"
        self.log("Got selection data: '%s'" % s)
        self.value_label.set_text(s)

    def do_get_target(self, *_args) -> None:
        self.clear_label()
        target = self.get_targets.get_active_text()
        self.log("Requesting %s" % target)
        atom = Gdk.Atom.intern(target, False)
        self.clipboard.request_contents(atom, self.selection_value_callback, None)

    def selection_clear_cb(self, _clipboard, _data) -> None:
        self.log("Selection has been cleared")

    def selection_get_callback(self, _clipboard, selectiondata, _info, *_args) -> None:
        # log("selection_get_callback(%s, %s, %s, %s) targets=%s",
        #    clipboard, selectiondata, info, args, selectiondata.get_targets())
        value = self.value_entry.get_text()
        self.log("Answering selection request with value: '%s'" % self.ellipsis(value))
        selectiondata.set("STRING", 8, value)

    def do_set_target(self, *_args) -> None:
        target = self.set_targets.get_active_text()
        self.log("Target set to %s" % target)
        self.clipboard.set_with_data([(target, 0, 0)], self.selection_get_callback, self.selection_clear_cb)

    def string_value_callback(self, _cb, value, *_args) -> None:
        if value is None:
            value = ""
        assert isinstance(value, str), "value is not a string!"
        self.log("Got string selection data: '%s'" % value)
        self.value_label.set_text(self.ellipsis(value))

    def do_get_string(self, *_args) -> None:
        # self.log("do_get_string%s on %s.%s" % (args, self, self.clipboard))
        self.clipboard.request_text(self.string_value_callback, None)

    def do_set_string(self, *_args) -> None:
        text = self.ellipsis(self.value_entry.get_text())
        self.clipboard.set_text(text, len(text))

    def owner_changed(self, _cb, event) -> None:
        owner = self.clipboard.get_owner()
        weownit = (owner is not None)
        if weownit:
            owner_info = "(us)"
        else:
            owner_info = str(event.owner or 0)
        self.log("Owner changed, reason: %s, new owner=%s" % (event.reason, owner_info))


class ClipboardStateInfoWindow:

    def __init__(self):
        self.window = Gtk.Window()
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(640, 300)
        self.window.set_border_width(20)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_title("Clipboard Test Tool")

        add_close_accel(self.window, self.destroy)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)

        self.log: deque[str] = deque(maxlen=25)
        for _ in range(25):
            self.log.append("")
        self.events = label("", font="monospace 9")

        # how many clipboards to show:
        self.clipboards = CLIPBOARDS

        grid = Gtk.Grid()
        for i, text in enumerate(("Selection", "Value", "Clear", "Targets", "Actions")):
            grid.attach(label(text), i, 1, 1, 1)

        for row, selection in enumerate(self.clipboards):
            grid.attach(label(selection), 0, 2 + row * 2, 1, 2)
            cs = ClipboardInstance(selection, self.add_event)
            get_actions = Gtk.HBox()
            for x in (cs.get_get_targets_btn, cs.get_target_btn, cs.get_string_btn):
                get_actions.pack_start(x)
            for i, widget in enumerate((cs.value_label, cs.clear_label_btn, cs.get_targets, get_actions)):
                grid.attach(widget, 1 + i, 2 + row * 2, 1, 1)
            set_actions = Gtk.HBox()
            for x in (cs.set_target_btn, cs.set_string_btn):
                set_actions.pack_start(x)
            widgets = (cs.value_entry, cs.clear_entry_btn, cs.set_targets, set_actions)
            for i, widget in enumerate(widgets):
                grid.attach(widget, 1 + i, 3 + row * 2, 1, 1)
        vbox.pack_start(grid)
        vbox.add(self.events)

        self.window.add(vbox)
        self.window.show_all()
        icon = get_icon_pixbuf("clipboard.png")
        if icon:
            self.window.set_icon(icon)
        try:
            self.add_event("ALL", "window=%s, xid=%#x" % (self.window, self.window.get_window().get_xid()))
        except Exception:
            self.add_event("ALL", "window=%s" % self.window)

    def add_event(self, selection, message) -> None:
        msg = message
        if self.clipboards:
            msg = f"{selection} : {message}"
        self.log.append(msg)
        self.events.set_text("\n".join(self.log))

    def destroy(self, *_args) -> None:
        Gtk.main_quit()

    def show_with_focus(self) -> None:
        force_focus()
        self.window.show_all()
        self.window.present()


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.log import enable_color
    from xpra.platform.gui import init, set_default_icon
    with program_context("Clipboard-Test", "Clipboard Test Tool"):
        enable_color()

        set_default_icon("clipboard.png")
        init()

        from xpra.gtk.util import quit_on_signals
        quit_on_signals("clipboard test window")

        w = ClipboardStateInfoWindow()
        GLib.idle_add(w.show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
