# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from time import monotonic

from xpra.log import Logger
log = Logger("x11", "bindings", "randr")

from libc.stdio cimport printf
from xpra.x11.bindings.xlib cimport (
    Display, XID, Bool, Status, Time,
    XFree, XFlush, XSync,
    Success,
)
from xpra.x11.bindings.core cimport X11CoreBindingsInstance
from xpra.util.env import envint, envbool, first_time
from xpra.util.str_fn import csv, decode_str, strtobytes, bytestostr


from libc.stdint cimport uintptr_t  #pylint: disable=syntax-error

ctypedef unsigned long   XRecordClientSpec
ctypedef unsigned long   XRecordContext


cdef extern from "X11/Xproto.h":
    int X_GrabPointer
    int X_UngrabKey


cdef extern from "X11/Xlib.h":
    ctypedef char *XPointer


cdef extern from "X11/extensions/recordconst.h":
    int XRecordAllClients

###################################
# Record
###################################
cdef extern from "X11/extensions/record.h":

    ctypedef struct XRecordRange8:
        unsigned char       first
        unsigned char       last

    ctypedef struct XRecordRange16:
        unsigned short      first
        unsigned short      last

    ctypedef struct XRecordExtRange:
        XRecordRange8       ext_major
        XRecordRange16      ext_minor

    ctypedef struct XRecordRange:
        XRecordRange8     core_requests     # core X requests
        XRecordRange8     core_replies      # core X repliess
        XRecordExtRange   ext_requests      # extension requests
        XRecordExtRange   ext_replies       # extension replies
        XRecordRange8     delivered_events  # delivered core and ext events
        XRecordRange8     device_events     # all core and ext device events
        XRecordRange8     errors            # core X and ext errors
        Bool              client_started    # connection setup reply
        Bool              client_died       # notice of client disconnect

    ctypedef struct XRecordClientInfo:
        XRecordClientSpec   client
        unsigned long       nranges
        XRecordRange        **ranges

    ctypedef struct XRecordState:
        Bool                enabled
        int                 datum_flags
        unsigned long       nclients
        XRecordClientInfo   **client_info

    ctypedef struct XRecordInterceptData:
        XID         id_base
        Time                server_time
        unsigned long       client_seq
        int                 category
        Bool                client_swapped
        unsigned char       *data
        unsigned long       data_len            # in 4-byte units

    Status XRecordQueryVersion(Display * display, int * cmajor_return, int * cminor_return)

    XRecordContext XRecordCreateContext(Display *dpy,
                                        int datum_flags,
                                        XRecordClientSpec *clients, int nclients,
                                        XRecordRange **ranges, int nranges)

    XRecordRange *XRecordAllocRange()

    Status XRecordRegisterClients(Display *dpy, XRecordContext context,
                                  int datum_flags,
                                  XRecordClientSpec *clients, int nclients,
                                  XRecordRange **ranges, int nranges)

    Status XRecordUnregisterClients(Display *dpy, XRecordContext context,
                                    XRecordClientSpec *clients, int nclients)

    Status XRecordGetContext(Display *dpy, XRecordContext context, XRecordState **state_return)

    void XRecordFreeState(XRecordState *state)

    ctypedef void *XRecordInterceptProc(XPointer closure, XRecordInterceptData recorded_data) noexcept nogil

    Status XRecordEnableContext(Display *dpy, XRecordContext context,
                                void *callback, XPointer closure)

    Status XRecordEnableContextAsync(Display *dpy, XRecordContext context,
                                     void *callback, XPointer closure)

    void XRecordProcessReplies(Display *dpy)

    void XRecordFreeData(XRecordInterceptData *data)

    Status XRecordDisableContext(Display *dpy, XRecordContext context)

    Status XRecordFreeContext(Display *dpy, XRecordContext context)


cdef void event_callback(XPointer closure, XRecordInterceptData* recorded_data) noexcept nogil:
    printf("event\n")


cdef record(Display *display):
    cdef XRecordClientSpec rcs
    cdef XRecordContext rc
    cdef XRecordRange * rr = XRecordAllocRange()
    if not rr:
        raise RuntimeError("Could not alloc record range object")
    rr.core_requests.first = X_GrabPointer;
    rr.core_requests.last = X_UngrabKey
    rcs = XRecordAllClients

    rc = XRecordCreateContext(display, 0, &rcs, 1, &rr, 1)
    if not rc:
        raise RuntimeError("Could not create a record context")

    if not XRecordEnableContext(display, rc, &event_callback, NULL):
        raise RuntimeError("Cound not enable the record context")

    cdef int stop = 0
    while not stop:
        XRecordProcessReplies(display)

    XRecordDisableContext(display, rc)
    XRecordFreeContext(display, rc)
    XFree(rr)

    # XCloseDisplay(display)


cdef RecordBindingsInstance singleton = None
def RecordBindings():
    global singleton
    if singleton is None:
        singleton = RecordBindingsInstance()
    return singleton

cdef class RecordBindingsInstance(X11CoreBindingsInstance):

    cdef object version

    def __init__(self):
        self.version = self.query_version()

    def __repr__(self):
        return f"RecordBindings({self.display_name})"

    def get_version(self):
        return self.version

    def query_version(self):
        cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
        cdef int r = XRecordQueryVersion(self.display, &cmajor, &cminor)
        log(f"found XRecord extension version {cmajor}.{cminor}")
        return (cmajor, cminor)

    def get_info(self) -> dict:
        return {
            "version": self.get_version(),
        }

    def record(self):
        record(self.display)
