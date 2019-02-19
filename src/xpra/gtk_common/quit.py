# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import traceback


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
        # that on every user of this function.
        from xpra.gtk_common.gobject_compat import import_gtk
        gtk = import_gtk()
        # So long as there are more nested main loops, re-register ourselves
        # to be called again:
        if gtk.main_level() > 0:
            gtk.main_quit()
            return True
        # But when we've just quit the outermost main loop, then
        # unregister ourselves so that it's possible to start the
        # main-loop again if desired:
        return False
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()
    glib.timeout_add(0, gtk_main_quit_forever)

# If a user hits control-C, and we are currently executing Python code below
# the main loop, then the exception will get swallowed up. (If we're just
# idling in the main loop, then it will pass the exception along, but it won't
# propagate it from Python code. Sigh.) But sys.excepthook will still get
# called with such exceptions.
_oldhook = None
def gtk_main_quit_on_fatal_exceptions_enable():
    global _oldhook
    if _oldhook:
        return
    _oldhook = sys.excepthook
    def gtk_main_quit_on_fatal_exception(etype, val, tb):
        if issubclass(etype, (KeyboardInterrupt, SystemExit)):
            print("Shutting down main-loop")
            gtk_main_quit_really()
            return None
        if issubclass(etype, RuntimeError) and val.args and "recursion" in val.args[0]:
            # We weren't getting tracebacks from this -- maybe calling oldhook
            # was hitting the limit again or something? -- so try this
            # instead. (I don't know why print_exception wouldn't trigger the
            # same problem as calling oldhook, though.)
            print(traceback.print_exception(etype, val, tb))
            print("Maximum recursion depth exceeded")
            return None
        return _oldhook(etype, val, tb)
    sys.excepthook = gtk_main_quit_on_fatal_exception

def gtk_main_quit_on_fatal_exceptions_disable():
    global _oldhook
    oh = _oldhook
    if oh:
        _oldhook = None
        sys.excepthook = oh
