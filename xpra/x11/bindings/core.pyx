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
    "ButtonPressMask"   : ButtonPressMask,
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
    "ResizeRedirectMask": ResizeRedirectMask,
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


# The X11 atom<->name mapping is immutable for the life of a connection:
# atoms are never unmapped or reassigned, so both directions can be cached
# indefinitely, saving a round-trip on every repeated InternAtom / GetAtomName.
# All `X11CoreBindingsInstance` subclasses (window, randr, ...) share these
# through the inherited methods below. They are tied to the process-wide display
# from `display_source`; `reset_atom_cache()` clears them if it is ever replaced.
name_to_atom: dict = {}     # bytes -> Atom
atom_to_name: dict = {}     # Atom  -> str

# the entries are only valid for the connection they were interned on:
cdef Display *cache_display = NULL


cdef inline bint atom_cache_valid(Display *display) noexcept:
    # Anchor the cache to the process-wide display from `display_source`.
    # Subclasses that open their own X connection (e.g. the record extension)
    # inherit these same methods but run on a different `Display*`; an atom is
    # only meaningful on the connection it was interned on, so they must bypass.
    global cache_display
    if display == NULL or display != get_display():
        return False
    if display != cache_display:
        # first use, or the canonical display was replaced: drop stale entries
        name_to_atom.clear()
        atom_to_name.clear()
        cache_display = display
    return True


def reset_atom_cache() -> None:
    global cache_display
    name_to_atom.clear()
    atom_to_name.clear()
    cache_display = NULL


cdef str get_atom_name_cached(Display *display, Atom atom):
    # Module-level counterpart of `X11CoreBindingsInstance.get_atom_name`,
    # for callers that hold a raw `Display*` rather than a bindings instance
    # (e.g. X11 event parsing). The caller is responsible for the error trap.
    cdef bint cache = atom_cache_valid(display)
    if cache:
        name = atom_to_name.get(atom)
        if name is not None:
            return name
    cdef char *v = XGetAtomName(display, atom)
    if v == NULL:
        return ""
    bname = v[:]
    XFree(v)
    name = bname.decode("latin1")
    if cache:
        atom_to_name[atom] = name
        name_to_atom[bname] = atom
    return name


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

    cdef Atom str_to_atom(self, atomstr) noexcept:
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        cdef bint cache = atom_cache_valid(self.display)
        bstr = strtobytes(atomstr)
        cdef Atom atom = 0
        if cache:
            atom = name_to_atom.get(bstr, 0)
            if atom:
                return atom
        self.context_check("str_to_atom")
        assert self.display!=NULL, "display is closed"
        cdef char* string = bstr
        # `only-if-exists=False`: the atom always exists afterwards, so it is safe to cache:
        atom = XInternAtom(self.display, string, False)
        if atom and cache:
            name_to_atom[bstr] = atom
            atom_to_name[atom] = bstr.decode("latin1")
        return atom

    cdef Atom xatom(self, str_or_int) noexcept:
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        if isinstance(str_or_int, int):
            return <Atom> str_or_int
        return self.str_to_atom(str_or_int)

    def intern_atoms(self, atom_names: Sequence[str]) -> None:
        cdef bint cache = atom_cache_valid(self.display)
        # only intern the atoms not already in our cache:
        if cache:
            missing = [name for name in atom_names if strtobytes(name) not in name_to_atom]
        else:
            missing = list(atom_names)
        cdef int count = len(missing)
        if count == 0:
            return
        cdef char** names = <char **> malloc(sizeof(uintptr_t)*(count+1))
        assert names!=NULL
        cdef Atom* atoms_return = <Atom*> malloc(sizeof(Atom)*(count+1))
        assert atoms_return!=NULL
        from ctypes import create_string_buffer, addressof
        str_names = [create_string_buffer(x.encode("latin1")) for x in missing]
        cdef uintptr_t ptr
        for i, x in enumerate(str_names):
            ptr = addressof(x)
            names[i] = <char*> ptr
        cdef Status s = XInternAtoms(self.display, names, count, 0, atoms_return)
        free(names)
        # keep the results, so subsequent lookups avoid a round-trip:
        cdef Atom atom
        if cache:
            for i, name in enumerate(missing):
                atom = atoms_return[i]
                if atom:
                    name_to_atom[name.encode("latin1")] = atom
                    atom_to_name[atom] = name
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
        cdef bint cache = atom_cache_valid(self.display)
        if cache:
            name = atom_to_name.get(atom)
            if name is not None:
                return name
        bin_name = self.XGetAtomName(atom)
        name = bin_name.decode("latin1")
        if bin_name and cache:
            atom_to_name[atom] = name
            name_to_atom[bin_name] = atom
        return name

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
