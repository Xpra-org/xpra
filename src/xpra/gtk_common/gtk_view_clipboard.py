#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>

import re
import sys
from collections import deque

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, is_gtk3, import_pango, import_gobject

gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()
gobject = import_gobject()

from xpra.gtk_common.gtk_util import TableBuilder, label, GetClipboard
from xpra.platform.paths import get_icon
from xpra.platform.features import CLIPBOARDS
from xpra.gtk_common.gobject_compat import get_xid


class ClipboardInstance(object):
    def __init__(self, selection, _log):
        self.clipboard = GetClipboard(selection)
        self.selection = selection
        self._log = _log
        self.owned_label = label()
        self.get_targets = gtk.combo_box_new_text()
        self.get_targets.set_sensitive(False)
        self.get_targets.connect("changed", self.get_target_changed)
        self.set_targets = gtk.combo_box_new_text()
        self.set_targets.append_text("STRING")
        self.set_targets.append_text("UTF8_STRING")
        self.set_targets.set_active(0)
        self.set_targets.connect("changed", self.set_target_changed)
        self.value_label = label()
        self.value_entry = gtk.Entry()
        self.value_entry.set_max_length(100)
        self.value_entry.set_width_chars(32)
        self.clear_label_btn = gtk.Button("X")
        self.clear_label_btn.connect("clicked", self.clear_label)
        self.clear_entry_btn = gtk.Button("X")
        self.clear_entry_btn.connect("clicked", self.clear_entry)
        self.get_get_targets_btn = gtk.Button("Get Targets")
        self.get_get_targets_btn.connect("clicked", self.do_get_targets)
        self.get_target_btn = gtk.Button("Get Target")
        self.get_target_btn.connect("clicked", self.do_get_target)
        self.get_target_btn.set_sensitive(False)
        self.set_target_btn = gtk.Button("Set Target")
        self.set_target_btn.connect("clicked", self.do_set_target)
        self.get_string_btn = gtk.Button("Get String")
        self.get_string_btn.connect("clicked", self.do_get_string)
        self.set_string_btn = gtk.Button("Set String")
        self.set_string_btn.connect("clicked", self.do_set_string)
        self.clipboard.connect("owner-change", self.owner_changed)
        self.log("ready")

    def __repr__(self):
        return "ClipboardInstance(%s)" % self.selection

    def log(self, msg):
        self._log(self.selection, msg)

    def clear_entry(self, *_args):
        self.value_entry.set_text("")

    def clear_label(self, *_args):
        self.value_label.set_text("")

    def get_targets_callback(self, c, targets, *_args):
        self.log("got targets: %s" % str(targets))
        if hasattr(targets, "name"):
            self.log("target is atom: %s" % targets.name())
            targets = []
        filtered = [x for x in (targets or []) if x not in ("MULTIPLE", "TARGETS")]
        ct = self.get_targets.get_active_text()
        if not ct:
            #choose a good default target:
            for x in ("STRING", "UTF8_STRING"):
                if x in filtered:
                    ct = x
                    break
        self.get_targets.get_model().clear()
        self.get_targets.set_sensitive(True)
        i = 0
        for t in filtered:
            self.get_targets.append_text(t)
            if t==ct:
                self.get_targets.set_active(i)
            i += 1
        self.get_targets.show_all()

    def do_get_targets(self, *_args):
        self.clipboard.request_targets(self.get_targets_callback, None)

    def get_target_changed(self, cb):
        target = self.get_targets.get_active_text()
        self.get_target_btn.set_sensitive(bool(target))

    def set_target_changed(self, cb):
        pass

    def ellipsis(self, val):
        if len(val)>24:
            return val[:24]+".."
        return val

    def selection_value_callback(self, cb, selection_data, *_args):
        #print("selection_value_callback(%s, %s, %s)" % (cb, selection_data, args))
        try:
            if selection_data.data is None:
                s = ""
            else:
                s = "type=%s, format=%s, data=%s" % (
                        selection_data.type,
                        selection_data.format,
                        self.ellipsis(re.escape(selection_data.data)))
        except TypeError:
            try:
                s = self.ellipsis("\\".join([str(x) for x in bytearray(selection_data.data)]))
            except:
                s = "!ERROR! binary data?"
        self.log("Got selection data: '%s'" % s)
        self.value_label.set_text(s)

    def do_get_target(self, *_args):
        self.clear_label()
        target = self.get_targets.get_active_text()
        self.log("Requesting %s" % target)
        self.clipboard.request_contents(target, self.selection_value_callback, None)

    def selection_clear_cb(self, clipboard, data):
        #print("selection_clear_cb(%s, %s)", clipboard, data)
        self.log("Selection has been cleared")

    def selection_get_callback(self, clipboard, selectiondata, info, *_args):
        #print("selection_get_callback(%s, %s, %s, %s) targets=%s" % (clipboard, selectiondata, info, args, selectiondata.get_targets()))
        value = self.value_entry.get_text()
        self.log("Answering selection request with value: '%s'" % self.ellipsis(value))
        selectiondata.set("STRING", 8, value)

    def do_set_target(self, *_args):
        target = self.set_targets.get_active_text()
        self.log("Target set to %s" % target)
        self.clipboard.set_with_data([(target, 0, 0)], self.selection_get_callback, self.selection_clear_cb)

    def string_value_callback(self, cb, value, *_args):
        if value is None:
            value = ""
        assert type(value)==str, "value is not a string!"
        self.log("Got string selection data: '%s'" % value)
        self.value_label.set_text(self.ellipsis(value))

    def do_get_string(self, *_args):
        #self.log("do_get_string%s on %s.%s" % (args, self, self.clipboard))
        self.clipboard.request_text(self.string_value_callback, None)

    def do_set_string(self, *_args):
        self.clipboard.set_text(self.ellipsis(self.value_entry.get_text()))

    def owner_changed(self, cb, event):
        r = {}
        if not is_gtk3():
            r = {gtk.gdk.OWNER_CHANGE_CLOSE : "close",
                 gtk.gdk.OWNER_CHANGE_DESTROY : "destroy",
                 gtk.gdk.OWNER_CHANGE_NEW_OWNER : "new owner"}
        owner = self.clipboard.get_owner()
        #print("xid=%s, owner=%s" % (self.value_entry.get_window().xid, event.owner))
        weownit = (owner is not None)
        if weownit:
            owner_info="(us)"
        else:
            owner_info = hex(event.owner)
        self.log("Owner changed, reason: %s, new owner=%s" % (
                        r.get(event.reason, event.reason), owner_info))



class ClipboardStateInfoWindow(object):

    def    __init__(self):
        self.window = gtk.Window()
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(640, 300)
        self.window.set_border_width(20)
        self.window.set_title("Clipboard Test Tool")

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(15)

        self.log = deque(maxlen=25)
        for x in range(25):
            self.log.append("")
        self.events = gtk.Label()
        fixed = pango.FontDescription('monospace 9')
        self.events.modify_font(fixed)

        #how many clipboards to show:
        self.clipboards = CLIPBOARDS

        tb = TableBuilder()
        table = tb.get_table()
        labels = [label("Selection")]
        labels += [label("Value"), label("Clear"), label("Targets"), label("Actions")]
        tb.add_row(*labels)
        for selection in self.clipboards:
            cs = ClipboardInstance(selection, self.add_event)
            get_actions = gtk.HBox()
            for x in (cs.get_get_targets_btn, cs.get_target_btn, cs.get_string_btn):
                get_actions.pack_start(x)
            tb.add_row(label(selection), cs.value_label, cs.clear_label_btn, cs.get_targets, get_actions)
            set_actions = gtk.HBox()
            for x in (cs.set_target_btn, cs.set_string_btn):
                set_actions.pack_start(x)
            tb.add_row(None, cs.value_entry, cs.clear_entry_btn, cs.set_targets, set_actions)
        vbox.pack_start(table)
        vbox.add(self.events)

        self.window.add(vbox)
        self.window.show_all()
        icon = get_icon("clipboard.png")
        if icon:
            self.window.set_icon(icon)
        try:
            self.add_event("ALL", "window=%s, xid=%#x" % (self.window, get_xid(self.window.get_window())))
        except:
            self.add_event("ALL", "window=%s" % self.window)

    def add_event(self, selection, message):
        msg = message
        if len(self.clipboards)>0:
            msg = "%s : %s" % (selection, message)
        self.log.append(msg)
        self.events.set_text("\n".join(self.log))

    def destroy(self, *_args):
        gtk.main_quit()


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Clipboard-Test", "Clipboard Test Tool"):
        enable_color()
        ClipboardStateInfoWindow()
        gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
