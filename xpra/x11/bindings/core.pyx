# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cython
from collections.abc import Callable, Sequence

from xpra.x11.bindings.xlib cimport (
    Time, Status, Atom, Window,
    XInternAtom, XInternAtoms,
    XGetAtomName,
    XFree,
    XGetErrorText,
    XQueryPointer,
    XUngrabKeyboard, XUngrabPointer,
    XSynchronize, XSync, XFlush,
    CurrentTime,
    XDefaultRootWindow,
    XConnectionNumber,
    XProtocolVersion, XProtocolRevision,
    XServerVendor, XVendorRelease,
    XDisplayString,
)
from libc.stdlib cimport malloc, free        # pylint: disable=syntax-error
from libc.stdint cimport uintptr_t

from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes
from xpra.util.system import is_X11
from xpra.log import Logger
log = Logger("x11", "bindings", "core")

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.display_source import get_display_name


cdef void import_check(modname):
    upname = str(modname).upper()
    envname = f"XPRA_X11_{upname}"
    if not envbool(envname, True):
        raise ImportError(f"import of {modname!r} bindings is prevented by {envname!r}")


import_check("core")


DEF XNone = 0


cdef extern from "X11/Xlib.h":
    int CWX
    int CWY
    int CWWidth
    int CWHeight
    int InputOnly
    int InputOutput
    int RevertToParent
    int ClientMessage
    int ButtonPress
    int Button1
    int Button2
    int Button3
    int SelectionNotify
    int ConfigureNotify

    int CopyFromParent

    int CWOverrideRedirect
    int CWEventMask
    int CWColormap
    int CWBorderWidth
    int CWSibling
    int CWStackMode

    int NoEventMask
    int KeyPressMask
    int KeyReleaseMask
    int ButtonPressMask
    int ButtonReleaseMask
    int EnterWindowMask
    int LeaveWindowMask
    int PointerMotionMask
    int PointerMotionHintMask
    int Button1MotionMask
    int Button2MotionMask
    int Button3MotionMask
    int Button4MotionMask
    int Button5MotionMask
    int ButtonMotionMask
    int KeymapStateMask
    int ExposureMask
    int VisibilityChangeMask
    int StructureNotifyMask
    int ResizeRedirectMask
    int SubstructureNotifyMask
    int SubstructureRedirectMask
    int FocusChangeMask
    int PropertyChangeMask
    int ColormapChangeMask
    int OwnerGrabButtonMask

    int AnyPropertyType
    int Success
    int PropModeReplace
    int USPosition
    int PPosition
    int USSize
    int PSize
    int PMinSize
    int IsUnmapped
    int PMaxSize
    int PBaseSize
    int PResizeInc
    int PAspect
    int PWinGravity
    int InputHint
    int StateHint
    int IconPixmapHint
    int IconWindowHint
    int IconPositionHint
    int IconMaskHint
    int WindowGroupHint
    int XUrgencyHint
    int WithdrawnState
    int IconicState
    int NormalState
    int NotifyNormal
    int NotifyGrab
    int NotifyUngrab
    int NotifyWhileGrabbed
    int NotifyNonlinearVirtual
    int NotifyAncestor
    int NotifyVirtual
    int NotifyInferior
    int NotifyNonlinear
    int NotifyPointer
    int NotifyPointerRoot
    int NotifyDetailNone

    int BadRequest
    int BadValue
    int BadWindow
    int BadPixmap
    int BadAtom
    int BadCursor
    int BadFont
    int BadMatch
    int BadDrawable
    int BadAccess
    int BadAlloc
    int BadColor
    int BadGC
    int BadIDChoice
    int BadName
    int BadLength
    int BadImplementation


constants: Dict[str, int] = {
    "CWX"               : CWX,
    "CWY"               : CWY,
    "CWWidth"           : CWWidth,
    "CWHeight"          : CWHeight,
    "CurrentTime"       : CurrentTime,
    "IsUnmapped"        : IsUnmapped,
    "InputOnly"         : InputOnly,
    "RevertToParent"    : RevertToParent,
    "ClientMessage"     : ClientMessage,
    "ButtonPress"       : ButtonPress,
    "Button1"           : Button1,
    "Button2"           : Button2,
    "Button3"           : Button3,
    "SelectionNotify"   : SelectionNotify,
    "ConfigureNotify"   : ConfigureNotify,
    "CWBorderWidth"     : CWBorderWidth,
    "CWSibling"         : CWSibling,
    "CWStackMode"       : CWStackMode,
    "AnyPropertyType"   : AnyPropertyType,
    "Success"           : Success,
    "PropModeReplace"   : PropModeReplace,
    "USPosition"        : USPosition,
    "PPosition"         : PPosition,
    "USSize"            : USSize,
    "PSize"             : PSize,
    "PMinSize"          : PMinSize,
    "XNone"             : XNone,
    "PMaxSize"          : PMaxSize,
    "PBaseSize"         : PBaseSize,
    "PResizeInc"        : PResizeInc,
    "PAspect"           : PAspect,
    "PWinGravity"       : PWinGravity,
    "InputHint"         : InputHint,
    "StateHint"         : StateHint,
    "IconPixmapHint"    : IconPixmapHint,
    "IconWindowHint"    : IconWindowHint,
    "IconPositionHint"  : IconPositionHint,
    "IconMaskHint"      : IconMaskHint,
    "WindowGroupHint"   : WindowGroupHint,
    "XUrgencyHint"      : XUrgencyHint,
    "WithdrawnState"    : WithdrawnState,
    "IconicState"       : IconicState,
    "NormalState"       : NormalState,
    "NotifyNormal"      : NotifyNormal,
    "NotifyGrab"        : NotifyGrab,
    "NotifyUngrab"      : NotifyUngrab,
    "NotifyWhileGrabbed" : NotifyWhileGrabbed,
    "NotifyNonlinear"   : NotifyNonlinear,
    "NotifyNonlinearVirtual" : NotifyNonlinearVirtual,
    "NotifyAncestor"    : NotifyAncestor,
    "NotifyVirtual"     : NotifyVirtual,
    "NotifyInferior"    : NotifyInferior,
    "NotifyNonlinearVirtual" : NotifyNonlinearVirtual,
    "NotifyPointer"     : NotifyPointer,
    "NotifyPointerRoot" : NotifyPointerRoot,
    "NotifyDetailNone"  : NotifyDetailNone,

    "NoEventMask"       : NoEventMask,
    "StructureNotifyMask" : StructureNotifyMask,
    "SubstructureNotifyMask"   : SubstructureNotifyMask,
    "SubstructureRedirectMask" : SubstructureRedirectMask,
    "FocusChangeMask"   : FocusChangeMask,
    "KeyPressMask"      : KeyPressMask,
    "KeyReleaseMask"    : KeyReleaseMask,
    "ButtonPress"       : ButtonPressMask,
    "ButtonReleaseMask" : ButtonReleaseMask,
    "EnterWindowMask"   : EnterWindowMask,
    "LeaveWindowMask"   : LeaveWindowMask,
    "PointerMotionMask" : PointerMotionMask,
    "PointerMotionHintMask": PointerMotionHintMask,
    "Button1MotionMask" : Button1MotionMask,
    "Button2MotionMask" : Button2MotionMask,
    "Button3MotionMask" : Button3MotionMask,
    "Button4MotionMask" : Button4MotionMask,
    "Button5MotionMask" : Button5MotionMask,
    "ButtonMotionMask"  : ButtonMotionMask,
    "KeymapStateMask"   : KeymapStateMask,
    "ExposureMask"      : ExposureMask,
    "VisibilityChangeMask": VisibilityChangeMask,
    "StructureNotifyMask": StructureNotifyMask,
    "ResizeRedirectMask": ResizeRedirectMask,
    "SubstructureNotifyMask": SubstructureNotifyMask,
    "SubstructureRedirectMask": SubstructureRedirectMask,
    "FocusChangeMask"   : FocusChangeMask,
    "PropertyChangeMask": PropertyChangeMask,
    "ColormapChangeMask": ColormapChangeMask,
    "OwnerGrabButtonMask": OwnerGrabButtonMask,
}


errors = {
    BadRequest: "BadRequest",
    BadValue: "BadValue",
    BadWindow: "BadWindow",
    BadPixmap: "BadPixmap",
    BadAtom: "BadAtom",
    BadCursor: "BadCursor",
    BadFont: "BadFont",
    BadMatch: "BadMatch",
    BadDrawable: "BadDrawable",
    BadAccess: "BadAccess",
    BadAlloc: "BadAlloc",
    BadColor: "BadColor",
    BadGC: "BadGC",
    BadIDChoice: "BadIDChoice",
    BadName: "BadName",
    BadLength: "BadLength",
    BadImplementation: "BadImplementation",
}


def noop(*args) -> None:
    pass


cdef object context_check = noop


def set_context_check(fn: Callable) -> None:
    global context_check
    context_check = fn


def call_context_check(*args) -> None:
    context_check(*args)


cdef class X11CoreBindingsInstance:

    def __cinit__(self):
        if not is_X11():
            raise RuntimeError("cannot load X11 bindings on non-X11 platform")
        self.display = get_display()
        #log.warn("X11Core initialized")
        #import traceback
        #traceback.print_stack()
        if self.display == NULL:
            raise RuntimeError("X11 display is not set")
        self.display_name = get_display_name()
        self.XSynchronize(envbool("XPRA_X_SYNC", False))

    def XSynchronize(self, enable: bool) -> None:
        XSynchronize(self.display, enable)

    def XSync(self, discard=False) -> None:
        XSync(self.display, discard)

    def XFlush(self) -> None:
        XFlush(self.display)

    def context_check(self, *args) -> None:
        global context_check
        context_check(*args)

    def __repr__(self):
        return "X11CoreBindings(%s)" % self.display_name

    def get_connection_number(self) -> int:
        return XConnectionNumber(self.display)

    def get_root_xid(self) -> cython.ulong:
        assert self.display
        return XDefaultRootWindow(self.display)

    cdef Atom str_to_atom(self, atomstr):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        self.context_check("str_to_atom")
        bstr = strtobytes(atomstr)
        cdef char* string = bstr
        assert self.display!=NULL, "display is closed"
        return XInternAtom(self.display, string, False)

    cdef Atom xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        if isinstance(str_or_int, int):
            return <Atom> str_or_int
        return self.str_to_atom(str_or_int)

    def intern_atoms(self, atom_names: Sequence[str]) -> None:
        cdef int count = len(atom_names)
        cdef char** names = <char **> malloc(sizeof(uintptr_t)*(count+1))
        assert names!=NULL
        cdef Atom* atoms_return = <Atom*> malloc(sizeof(Atom)*(count+1))
        assert atoms_return!=NULL
        from ctypes import create_string_buffer, addressof
        str_names = [create_string_buffer(x.encode("latin1")) for x in atom_names]
        cdef uintptr_t ptr
        for i, x in enumerate(str_names):
            ptr = addressof(x)
            names[i] = <char*> ptr
        cdef Status s = XInternAtoms(self.display, names, count, 0, atoms_return)
        free(names)
        free(atoms_return)
        assert s!=0, "failed to intern some atoms"

    def get_xatom(self, str_or_int) -> Atom:
        return self.xatom(str_or_int)

    def XGetAtomName(self, Atom atom) -> bytes:
        self.context_check("XGetAtomName")
        cdef char *v = XGetAtomName(self.display, atom)
        if v == NULL:
            return b""
        r = v[:]
        XFree(v)
        return r

    def get_atom_name(self, Atom atom) -> str:
        self.context_check("XGetAtomName")
        bin_name = self.XGetAtomName(atom)
        return bin_name.decode("latin1")

    def get_error_text(self, code) -> str:
        if self.display == NULL:
            raise RuntimeError("display is closed")
        if not isinstance(code, int):
            return str(code)
        cdef char[128] buffer
        XGetErrorText(self.display, code, buffer, 128)
        return (bytes(buffer[:128]).split(b"\0", 1)[0]).decode("latin1")

    def UngrabKeyboard(self, Time time=CurrentTime) -> cython.ulong:
        self.context_check("UngrabKeyboard")
        if self.display == NULL:
            raise RuntimeError("display is closed")
        return XUngrabKeyboard(self.display, time)

    def UngrabPointer(self, Time time=CurrentTime) -> cython.ulong:
        self.context_check("UngrabPointer")
        if self.display == NULL:
            raise RuntimeError("display is closed")
        return XUngrabPointer(self.display, time)

    def query_pointer(self) -> Tuple[int, int]:
        self.context_check("query_pointer")
        cdef Window root_window = XDefaultRootWindow(self.display)
        cdef Window root, child
        cdef int root_x, root_y
        cdef int win_x, win_y
        cdef unsigned int mask
        XQueryPointer(self.display, root_window, &root, &child,
                      &root_x, &root_y, &win_x, &win_y, &mask)
        return root_x, root_y

    def query_mask(self) -> int:
        self.context_check("query_mask")
        cdef Window root_window = XDefaultRootWindow(self.display)
        cdef Window root, child
        cdef int root_x, root_y
        cdef int win_x, win_y
        cdef unsigned int mask
        XQueryPointer(self.display, root_window, &root, &child,
                      &root_x, &root_y, &win_x, &win_y, &mask)
        return mask

    def get_info(self) -> Dict[str, Any]:
        cdef int version = XProtocolVersion(self.display)
        cdef int revision = XProtocolRevision(self.display)
        cdef char *vendor = XServerVendor(self.display)
        cdef int release = XVendorRelease(self.display)
        vendor_str = vendor.decode("utf8")
        return {
            "version": version,
            "revision": revision,
            "vendor": vendor_str,
            "release": release,
            "mask": self.query_mask(),
            "pointer": self.query_pointer(),
        }

    def show_server_info(self) -> None:
        cdef char *display = XDisplayString(self.display)
        cdef int version = XProtocolVersion(self.display)
        cdef int revision = XProtocolRevision(self.display)
        cdef char *vendor = XServerVendor(self.display)
        cdef int release = XVendorRelease(self.display)
        display_str = display.decode("latin1")
        vendor_str = vendor.decode("latin1")
        log.info("connected to X11 server %r", display_str)
        log.info(" vendor: %r", vendor_str)
        log.info(" version %i.%i release %i", version, revision, release)


cdef X11CoreBindingsInstance singleton = None


def X11CoreBindings() -> X11CoreBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11CoreBindingsInstance()
    return singleton


def get_root_xid() -> int:
    return X11CoreBindings().get_root_xid()
