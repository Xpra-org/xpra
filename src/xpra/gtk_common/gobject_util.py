# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.gtk_common.gobject_compat import import_gobject
gobject = import_gobject()
gobject.threads_init()
try:
    SIGNAL_RUN_LAST = gobject.SIGNAL_RUN_LAST
except:
    SIGNAL_RUN_LAST = gobject.SignalFlags.RUN_LAST
def n_arg_signal(n):
    return (SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,) * n)
no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)


class AutoPropGObjectMixin(object):
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        super(AutoPropGObjectMixin, self).__init__()
        self._gproperties = {}

    def do_get_property(self, pspec):
        getter = "do_get_property_" + pspec.name.replace("-", "_")
        if hasattr(self, getter):
            return getattr(self, getter)(pspec.name)
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


# Collects the results from signal handlers for a given signal into a list,
# ignoring all handlers that return None.  (This filtering is useful because
# the intended use of this method is to "poll" all connected objects, so it's
# pretty useless to call a default do_* method... but even if such a method is
# not defined, a default implementation will still be called automatically,
# and that implementation simply returns None.)
def non_none_list_accumulator(ihint, return_accu, handler_return):
    if return_accu is None:
        return_accu = []
    if handler_return is not None:
        return_accu += [handler_return]
    return True, return_accu
