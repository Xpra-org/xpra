# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from gi.repository import GObject
SIGNAL_RUN_LAST = GObject.SignalFlags.RUN_LAST
def n_arg_signal(n):
    return (SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_PYOBJECT,) * n)
no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)
two_arg_signal = n_arg_signal(2)


class AutoPropGObjectMixin:
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        self._gproperties = {}

    def do_get_property(self, pspec):
        return self._gproperties.get(pspec.name)

    def do_set_property(self, pspec, value):
        self._internal_set_property(pspec.name, value)

    # Exposed for subclasses that wish to set readonly properties --
    # .set_property (the public api) will fail, but the property can still be
    # modified via this method.
    def _internal_set_property(self, name, value):
        setter = "do_set_property_" + name.replace("-", "_")
        if hasattr(self, setter):
            getattr(self, setter)(name, value)
        else:
            self._gproperties[name] = value
        self.notify(name)
