# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import traceback
import sys
from wimpiggy.gobject_compat import import_gobject
gobject = import_gobject()

class AutoPropGObjectMixin(object):
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""
    def __init__(self):
        super(AutoPropGObjectMixin, self).__init__()
        self._gproperties = {}

    def _munge_property_name(self, name):
        return name.replace("-", "_")

    def do_get_property(self, pspec):
        getter = "do_get_property_" + self._munge_property_name(pspec.name)
        if hasattr(self, getter):
            return getattr(self, getter)(pspec.name)
        return self._gproperties.get(pspec.name)

    def do_set_property(self, pspec, value):
        self._internal_set_property(pspec.name, value)

    # Exposed for subclasses that wish to set readonly properties --
    # .set_property (the public api) will fail, but the property can still be
    # modified via this method.
    def _internal_set_property(self, name, value):
        setter = "do_set_property_" + self._munge_property_name(name)
        if hasattr(self, setter):
            getattr(self, setter)(name, value)
        else:
            self._gproperties[name] = value
        self.notify(name)


def dump_exc():
    """Call this from a except: clause to print a nice traceback."""
    print("".join(traceback.format_exception(*sys.exc_info())))


# A simple little class whose instances we can stick random bags of attributes
# on.
class AdHocStruct(object):
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))

def n_arg_signal(n):
    return (gobject.SIGNAL_RUN_LAST,
            gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,) * n)
no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)


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


# *Fully* exits the gtk main loop, even in the presence of recursive calls to
# gtk.main().  Useful when you really just want to quit, and don't want to
# care if you're inside a recursive mainloop.
def gtk_main_quit_really():
    # We used to call gtk.main_quit() repeatedly, but this doesn't actually
    # work -- gtk.main_quit() always marks the *current* level of main loop
    # for destruction, so it's actually idempotent. We have to call
    # gtk.main_quit once, and then return to the main loop, and then call it
    # again, and then return to the main loop, etc. So we use a trick: We
    # register a function that gtk should call 'forever' (i.e., as long as the
    # main loop is running!)
    def gtk_main_quit_forever():
        # We import gtk inside here, rather than at the top of the file,
        # because importing gtk has the side-effect of trying to connect to
        # the X server (and this process may block, may cause us to later be
        # killed if the X server goes away, etc.), and we don't want to impose
        # that on every user of wimpiggy.util.
        from wimpiggy.gobject_compat import import_gtk
        gtk = import_gtk()
        gtk.main_quit()
        # So long as there are more nested main loops, re-register ourselves
        # to be called again:
        if gtk.main_level() > 1:
            return True
        else:
            # But when we've just quit the outermost main loop, then
            # unregister ourselves so that it's possible to start the
            # main-loop again if desired:
            return False
    gobject.timeout_add(0, gtk_main_quit_forever)

# If a user hits control-C, and we are currently executing Python code below
# the main loop, then the exception will get swallowed up. (If we're just
# idling in the main loop, then it will pass the exception along, but it won't
# propagate it from Python code. Sigh.) But sys.excepthook will still get
# called with such exceptions.
def gtk_main_quit_on_fatal_exceptions_enable():
    oldhook = sys.excepthook
    def gtk_main_quit_on_fatal_exception(etype, val, tb):
        if issubclass(etype, (KeyboardInterrupt, SystemExit)):
            print("Shutting down main-loop")
            gtk_main_quit_really()
        if issubclass(etype, RuntimeError) and "recursion" in val.message:
            # We weren't getting tracebacks from this -- maybe calling oldhook
            # was hitting the limit again or something? -- so try this
            # instead. (I don't know why print_exception wouldn't trigger the
            # same problem as calling oldhook, though.)
            print(traceback.print_exception(etype, val, tb))
            print("Maximum recursion depth exceeded")
        else:
            return oldhook(etype, val, tb)
    sys.excepthook = gtk_main_quit_on_fatal_exception
