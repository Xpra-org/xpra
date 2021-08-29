# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.core_bindings cimport X11CoreBindingsInstance

from xpra.log import Logger
log = Logger("x11", "bindings")

ctypedef int pid_t
ctypedef unsigned long CARD32

cdef extern from "X11/X.h":
    unsigned long Success

######
# Xlib primitives and constants
######
cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    ctypedef CARD32 XID
    ctypedef unsigned long int Atom
    ctypedef int Bool
    ctypedef int Status
    ctypedef int Window


###################################
# XRes
###################################
cdef extern from "X11/extensions/XRes.h":
    ctypedef enum XResClientIdType:
        XRES_CLIENT_ID_XID
        XRES_CLIENT_ID_PID
        XRES_CLIENT_ID_NR

    ctypedef enum XResClientIdMask:
        XRES_CLIENT_ID_XID_MASK = 1 << XRES_CLIENT_ID_XID
        XRES_CLIENT_ID_PID_MASK = 1 << XRES_CLIENT_ID_PID

    ctypedef struct XResClientIdSpec:
        XID client
        unsigned int mask

    ctypedef struct XResResourceIdSpec:
        XID resource
        Atom type

    ctypedef struct XResClientIdValue:
        XResClientIdSpec spec
        long          length
        void         *value

    ctypedef struct XResClient:
        XID    resource_base
        XID    resource_mask

    ctypedef struct XResType:
        Atom    resource_type
        unsigned int    count

    Status XResQueryClientIds(Display *dpy, long num_specs, XResClientIdSpec *client_specs,
                              long *num_ids, XResClientIdValue **client_ids)
    void XResClientIdsDestroy(long num_ids, XResClientIdValue  *client_ids)
    XResClientIdType XResGetClientIdType(XResClientIdValue* value)
    pid_t XResGetClientPid(XResClientIdValue* value)

    Bool XResQueryExtension(Display *dpy, int *event_base_return, int *error_base_return)
    Status XResQueryVersion(Display *dpy, int *major_version_return, int *minor_version_return)



cdef ResBindingsInstance singleton = None
def ResBindings():
    global singleton
    if singleton is None:
        singleton = ResBindingsInstance()
    return singleton

cdef class ResBindingsInstance(X11CoreBindingsInstance):

    def __init__(self):
        pass

    def __repr__(self):
        return "XResBindings(%s)" % self.display_name

    def check_xres(self, min_version=(1, 2)):
        cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
        cdef Bool r = XResQueryExtension(self.display, &event_base, &ignored)
        log("XResQueryExtension()=%i", r)
        if not r:
            return False
        log("found XRes extension")
        if not XResQueryVersion(self.display, &cmajor, &cminor):
            return False
        log("found XRes extension version %i.%i", cmajor, cminor)
        return (cmajor, cminor) >= min_version

    def get_pid(self, Window xid):
        cdef XResClientIdSpec client_spec
        client_spec.client = xid
        client_spec.mask = XRES_CLIENT_ID_PID_MASK

        cdef long num_ids
        cdef XResClientIdValue *client_ids
        if XResQueryClientIds(self.display, 1, &client_spec, &num_ids, &client_ids):
            log.error("Error: failed to query pid for window %i", xid)
            return 0

        cdef int pid = 0
        for i in range(num_ids):
            if client_ids[i].spec.mask == XRES_CLIENT_ID_PID_MASK:
                pid = XResGetClientPid(&client_ids[i])
                if pid>=0:
                    break
        if num_ids:
            XResClientIdsDestroy(num_ids, client_ids)
        return pid
