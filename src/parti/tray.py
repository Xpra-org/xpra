# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import gtk

# FIXME: The current design here is lame... these should probably be models of
# some sort, or possibly hold many models, so that one can cycle through
# multiple layout implementations losslessly.  But just making them widgets is
# expedient for now.
class Tray(gtk.Widget):
    def __init__(self, trayset, tag):
        super(Tray, self).__init__()
        self.trayset = trayset
        self.tag = tag

    # Pure virtual methods, for children to implement:
    def add(self, window):
        raise NotImplementedError

    def windows(self):
        raise NotImplementedError

    def work_area(self):
        # Returns (x, y, width, height) of part of allocation that is using
        # for client windows (e.g. minus any STRUT reservations).
        raise NotImplementedError

    # A tray should also be clever about receiving focus (e.g., remembering
    # which client had it the last time the tray was focused, and putting it
    # back there).

# An arbitrarily ordered set, with key-based access.  (Currently just backed
# by an array.)  Think of this as an MVC Model.
class TraySet(gobject.GObject):
    __gsignals__ = {
        "removed": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE,
                 (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT,)),
        "moved": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE,
                 (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT,)),
        "added": (gobject.SIGNAL_RUN_LAST,
                  gobject.TYPE_NONE,
                  (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT,)),
        "renamed": (gobject.SIGNAL_RUN_LAST,
                   gobject.TYPE_NONE,
                   (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT,)),
        # Emitted by all of the above signals:
        "changed": (gobject.SIGNAL_RUN_LAST,
                    gobject.TYPE_NONE, ()),
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.trays = []

    def tags(self):
        return [tray.tag for tray in self.trays]

    def has_tag(self, tag):
        for tray in self.trays:
            if tray.tag == tag:
                return True
        return False
    __contains__ = has_tag

    def __getitem__(self, tag):
        tray = self.get(tag)
        if tray is None:
            raise KeyError(tag)
        return tag

    def get(self, tag):
        try:
            return self[tag]
        except KeyError:
            return None

    def remove(self, tag):
        for i in range(len(self.trays)):
            if self.trays[i] == tag:
                tray = self.trays[i]
                del self.trays[i]
                self.emit("removed", tag, tray)
                self.emit("changed")
                return

    def index(self, tag):
        for i in range(len(self.trays)):
            if self.trays[i] == tag:
                return i
        raise KeyError(tag)

    def __len__(self):
        return len(self.trays)

    def move(self, tag, newidx):
        assert newidx < len(self)
        oldidx = self.index(tag)
        tray = self.trays.pop(oldidx)
        self.trays.insert(newidx, tray)
        self.emit("moved", tag, newidx)
        self.emit("changed")

    def new(self, tag, type):
        assert tag not in self
        assert isinstance(tag, unicode)
        tray = type(self, tag)
        self.trays.append(tray)
        self.emit("added", tag, tray)
        self.emit("changed")
        return tray

    def rename(self, tag, newtag):
        self[tag].tag = newtag
        self.emit("renamed", tag, newtag)
        self.emit("changed")

gobject.type_register(TraySet)
