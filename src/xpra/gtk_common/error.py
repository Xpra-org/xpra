# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Goal: make it as easy and efficient as possible to manage the X errors that
# a WM is inevitably susceptible to.  (E.g., if a window goes away while we
# are working on it.)  On the one hand, we want to parcel operations into as
# broad chunks as possible that at treated as succeeding or failing as a whole
# (e.g., "setting up a new window", we don't really care how much was
# accomplished before the failure occurred).  On the other, we do want to
# check for X errors often, for use in debugging (esp., this makes it more
# useful to run with -sync).
#
# The solution is to keep a stack of how deep we are in "transaction-like"
# operations -- a transaction is a series of operations where we don't care if
# we don't find about the failures until the end.  We only sync when exiting a
# top-level transaction.
#
# The _synced and _unsynced variants differ in whether they assume the X
# connection was left in a synchronized state by the code they called (e.g.,
# if the last operation was an XGetProperty, then there is no need for us to
# do another XSync).
#
# (In this modern world, with WM's either on the same machine or over
# super-fast connections to the X server, everything running on fast
# computers... does being this careful to avoid sync's actually matter?)

__all__ = ["XError", "trap"]


from xpra.util import envbool
#run xpra in synchronized mode to debug X11 errors:
XPRA_SYNCHRONIZE = envbool("XPRA_SYNCHRONIZE", True)

from xpra.log import Logger
log = Logger("x11", "util")
elog = Logger("x11", "util", "error")

from xpra.gtk_common.gobject_compat import import_gdk
gdk = import_gdk()

class XError(Exception):
    def __init__(self, message):
        Exception.__init__(self)
        self.msg = message

    def __str__(self):
        return "XError: %s" % str(self.msg)


xerror_to_name = None
def get_X_error(xerror):
    global xerror_to_name
    if type(xerror)!=int:
        return xerror
    try:
        from xpra.x11.bindings.window_bindings import constants     #@UnresolvedImport
        if xerror_to_name is None:
            xerror_to_name = {}
            for name,code in constants.items():
                if name=="Success" or name.startswith("Bad"):
                    xerror_to_name[code] = name
            log("get_X_error(..) initialized error names: %s", xerror_to_name)
        if xerror in xerror_to_name:
            return xerror_to_name.get(xerror)
        from xpra.x11.bindings.core_bindings import X11CoreBindings     #@UnresolvedImport
        return X11CoreBindings().get_error_text(xerror)
    except Exception as e:
        log.error("get_X_error(%s) %s", xerror, e, exc_info=True)
    return xerror

class XErrorInfo(object):
    def __init__(self, xerror):
        self.xerror = xerror
    def __repr__(self):
        return str(get_X_error(self.xerror))


# gdk has its own depth tracking stuff, but we have to duplicate it here to
# minimize calls to XSync.
class _ErrorManager(object):
    def __init__(self):
        self.depth = 0

    def _enter(self):
        assert self.depth >= 0
        gdk.error_trap_push()
        self.depth += 1

    def _exit(self, need_sync):
        assert self.depth >= 0
        self.depth -= 1
        if self.depth == 0 and need_sync:
            gdk.flush()
        # This is a Xlib error constant (Success == 0)
        error = gdk.error_trap_pop()
        if error:
            raise XError(get_X_error(error))

    def _call(self, need_sync, fun, args, kwargs):
        # Goal: call the function.  In all conditions, call _exit exactly once
        # on the way out.  However, if we are exiting because of an exception,
        # then probably that exception is more informative than any XError
        # that might also be raised, so suppress the XError in that case.
        value = None
        try:
            self._enter()
            value = fun(*args, **kwargs)
        except Exception as e:
            elog("_call(%s,%s,%s,%s) %s", need_sync, fun, args, kwargs, e, exc_info=True)
            log("_call(%s,%s,%s,%s) %s", need_sync, fun, args, kwargs, e)
            try:
                self._exit(need_sync)
            except XError as ee:
                log("XError %s detected while already in unwind; discarding", XErrorInfo(ee))
            raise
        self._exit(need_sync)
        return value

    def call_unsynced(self, fun, *args, **kwargs):
        return self._call(False, fun, args, kwargs)

    def call_synced(self, fun, *args, **kwargs):
        return self._call(True, fun, args, kwargs)

    if XPRA_SYNCHRONIZE:
        call = call_synced
    else:
        call = call_unsynced

    def swallow_unsynced(self, fun, *args, **kwargs):
        try:
            self.call_unsynced(fun, *args, **kwargs)
            return True
        except XError as e:
            log("Ignoring X error: %s on %s", XErrorInfo(e.msg), fun)
            return False

    def swallow_synced(self, fun, *args, **kwargs):
        try:
            self.call_synced(fun, *args, **kwargs)
            return True
        except XError as e:
            log("Ignoring X error: %s on %s", XErrorInfo(e.msg), fun)
            return False

    if XPRA_SYNCHRONIZE:
        swallow = swallow_synced
    else:
        swallow = swallow_unsynced

    def assert_out(self):
        assert self.depth == 0

trap = _ErrorManager()


class XSyncContext(object):

    def __enter__(self):
        trap._enter()

    def __exit__(self, e_typ, _e_val, _trcbak):
        #log("xsync.exit%s", (e_typ, e_val, trcbak))
        try:
            trap._exit(True)
        except XError as ee:
            if e_typ is None:
                #we are not handling an exception yet, so raise this one:
                raise
            log("XError %s detected while already in unwind; discarding", XErrorInfo(ee))
        #raise the original exception:
        return False

xsync = XSyncContext()


class XSwallowContext(object):

    def __enter__(self):
        trap._enter()

    def __exit__(self, *_args):
        #log("xswallow.exit%s", (e_typ, e_val, trcbak))
        try:
            trap._exit(True)
        except XError as ee:
            log("XError %s detected while already in unwind; discarding", XErrorInfo(ee))
        #don't raise exceptions:
        return True

xswallow = XSwallowContext()
