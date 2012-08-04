import gtk
import gobject
from wimpiggy.util import n_arg_signal
from wimpiggy.lowlevel import add_event_receiver    #@UnresolvedImport
from wimpiggy.prop import prop_get

from wimpiggy.log import Logger
log = Logger()

class XRootPropWatcher(gobject.GObject):
    __gsignals__ = {
        "root-prop-changed": n_arg_signal(2),
        "wimpiggy-property-notify-event": n_arg_signal(1),
        }

    def __init__(self, props):
        gobject.GObject.__init__(self)
        self._props = props
        self._root = gtk.gdk.get_default_root_window()
        add_event_receiver(self._root, self)

    def do_wimpiggy_property_notify_event(self, event):
        if event.atom in self._props:
            self._notify(event.atom)

    def _notify(self, prop):
        v = prop_get(gtk.gdk.get_default_root_window(),
                     prop, "latin1", ignore_errors=True)
        self.emit("root-prop-changed", prop, v)

    def notify_all(self):
        for prop in self._props:
            self._notify(prop)

gobject.type_register(XRootPropWatcher)
