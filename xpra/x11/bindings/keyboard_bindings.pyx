# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.log import Logger
log = Logger("x11", "bindings", "keyboard")

from xpra.os_util import bytestostr, strtobytes
from xpra.x11.bindings.xlib cimport (
    Display, XID, Bool, KeySym, KeyCode, Atom, Window, Status, Time, XRectangle, CARD32,
    XModifierKeymap,
    XDefaultRootWindow,
    XOpenDisplay, XCloseDisplay, XFlush, XFree, XInternAtom,
    XQueryPointer,
    XDisplayKeycodes, XQueryKeymap,
    XGetModifierMapping, XSetModifierMapping,
    XFreeModifiermap, XChangeKeyboardMapping, XGetKeyboardMapping, XInsertModifiermapEntry,
    XStringToKeysym, XKeysymToString,
    XGrabKey, XUngrabKey,
    MappingBusy, GrabModeAsync, AnyKey, AnyModifier, NoSymbol,
    )
from libc.stdint cimport uintptr_t      #pylint: disable=syntax-error
from libc.stdlib cimport free, malloc


DEF PATH_MAX = 1024
DEF DFLT_XKB_RULES_FILE = b"base"

###################################
# Headers, python magic
###################################
cdef extern from "locale.h":
    char *setlocale(int category, const char *locale)
    int LC_ALL

######
# Xlib primitives and constants
######
DEF XkbKeyTypesMask             = 1<<0
DEF XkbKeySymsMask              = 1<<1
DEF XkbModifierMapMask          = 1<<2
DEF XkbExplicitComponentsMask   = 1<<3
DEF XkbKeyActionsMask           = 1<<4
DEF XkbKeyBehaviorsMask         = 1<<5
DEF XkbVirtualModsMask          = 1<<6
DEF XkbAllComponentsMask        = 1<<7

DEF XkbNumKbdGroups = 4

cdef extern from "X11/extensions/XKB.h":
    unsigned long XkbUseCoreKbd
    unsigned long XkbDfltXIId
    unsigned long XkbBellNotifyMask
    unsigned long XkbMapNotifyMask
    unsigned long XkbStateNotifyMask
    unsigned int XkbGBN_AllComponentsMask
    unsigned int XkbGBN_GeometryMask

cdef extern from "X11/extensions/XKBstr.h":
    ctypedef struct XkbComponentNamesRec:
        char *                   keymap
        char *                   keycodes
        char *                   types
        char *                   compat
        char *                   symbols
        char *                   geometry
    ctypedef XkbComponentNamesRec*  XkbComponentNamesPtr
    ctypedef void * XkbKeyTypePtr
    ctypedef struct XkbSymMapRec:
        unsigned char    kt_index[XkbNumKbdGroups]
        unsigned char    group_info
        unsigned char    width
        unsigned short   offset
    ctypedef XkbSymMapRec* XkbSymMapPtr
    ctypedef struct XkbClientMapRec:
        unsigned char            size_types
        unsigned char            num_types
        XkbKeyTypePtr            types
        unsigned short           size_syms
        unsigned short           num_syms
        KeySym                  *syms
        XkbSymMapPtr             key_sym_map
        unsigned char           *modmap
    ctypedef XkbClientMapRec* XkbClientMapPtr

    ctypedef void * XkbControlsPtr
    ctypedef void * XkbServerMapPtr
    ctypedef void * XkbIndicatorPtr
    ctypedef void * XkbNamesPtr
    ctypedef void * XkbCompatMapPtr
    ctypedef void * XkbGeometryPtr
    ctypedef struct XkbDescRec:
        Display                 *dpy
        unsigned short          flags
        unsigned short          device_spec
        KeyCode                 min_key_code
        KeyCode                 max_key_code

        XkbControlsPtr          ctrls
        XkbServerMapPtr         server
        XkbClientMapPtr         map
        XkbIndicatorPtr         indicators
        XkbNamesPtr             names
        XkbCompatMapPtr         compat
        XkbGeometryPtr          geom
    ctypedef XkbDescRec* XkbDescPtr
    ctypedef struct _XkbStateRec:
        unsigned char   group
    ctypedef _XkbStateRec XkbStateRec
    ctypedef _XkbStateRec *XkbStatePtr


cdef extern from "X11/extensions/XKBrules.h":
    #define _XKB_RF_NAMES_PROP_ATOM         "_XKB_RULES_NAMES"
    #unsigned int _XKB_RF_NAMES_PROP_MAXLEN

    ctypedef struct XkbRF_RulesRec:
        pass

    ctypedef XkbRF_RulesRec* XkbRF_RulesPtr

    ctypedef struct XkbRF_VarDefsRec:
        char *                  model
        char *                  layout
        char *                  variant
        char *                  options
        unsigned short          sz_extra
        unsigned short          num_extra
        char *                  extra_names
        char **                 extra_values

    ctypedef XkbRF_VarDefsRec* XkbRF_VarDefsPtr

    Bool XkbLibraryVersion(int *major , int *minor)

    Bool XkbRF_GetNamesProp(Display *dpy, char **rules_file_rtrn, XkbRF_VarDefsPtr var_defs_rtrn)
    Bool XkbRF_SetNamesProp(Display *dpy, char *rules_file, XkbRF_VarDefsPtr var_defs)
    Bool XkbRF_GetComponents(XkbRF_RulesPtr rules, XkbRF_VarDefsPtr var_defs, XkbComponentNamesPtr names)
    XkbRF_RulesPtr XkbRF_Load(char *base, char *locale, Bool wantDesc, Bool wantRules)


cdef extern from "X11/XKBlib.h":
    KeySym XkbKeycodeToKeysym(Display *display, KeyCode kc, int group, int level)
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *eventBaseReturn, int *errorBaseReturn, int *majorRtrn, int *minorRtrn)
    Bool XkbSelectEvents(Display *, unsigned int deviceID, unsigned int affect, unsigned int values)
    Bool XkbDeviceBell(Display *, Window w, int deviceSpec, int bellClass, int bellID, int percent, Atom name)
    Bool XkbSetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int delay, unsigned int interval)
    Bool XkbGetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int *delayRtrn, unsigned int *intervalRtrn)

    XkbDescPtr XkbGetKeyboardByName(Display *display, unsigned int deviceSpec, XkbComponentNamesPtr names,
                                    unsigned int want, unsigned int need, Bool load)
    Status XkbGetState(Display *dpy, unsigned int deviceSpec, XkbStatePtr statePtr)
    Bool   XkbLockGroup(Display *dpy, unsigned int deviceSpec, unsigned int group)
    XkbDescPtr XkbGetKeyboard(Display *display, unsigned int which, unsigned int device_spec)

    int XkbKeyNumSyms(XkbDescPtr xkb, KeyCode keycode)
    XkbDescPtr XkbGetMap(Display *display, unsigned int which, unsigned int device_spec)
    void XkbFreeKeyboard(XkbDescPtr xkb, unsigned int which, Bool free_all)


cdef extern from "X11/extensions/XTest.h":
    Bool XTestQueryExtension(Display *display, int *event_base_return, int *error_base_return,
                                int * major, int * minor)
    int XTestFakeKeyEvent(Display *, unsigned int keycode,
                          Bool is_press, unsigned long delay)
    int XTestFakeButtonEvent(Display *, unsigned int button,
                             Bool is_press, unsigned long delay)
    int XTestFakeMotionEvent(Display * display, int screen_number, int x, int y, unsigned long delay)
    int XTestFakeRelativeMotionEvent(Display * display, int x, int y, unsigned long delay)

cdef extern from "X11/extensions/Xfixes.h":
    ctypedef struct XFixesCursorNotify:
        char* subtype
        Window XID
        int cursor_serial
        int time
        char* cursor_name
    ctypedef struct XFixesCursorImage:
        short x
        short y
        unsigned short width
        unsigned short height
        unsigned short xhot
        unsigned short yhot
        unsigned long cursor_serial
        unsigned long* pixels
        Atom atom
        char* name
    ctypedef struct XFixesCursorNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        Window window
        int subtype
        unsigned long cursor_serial
        Time timestamp
        Atom cursor_name

    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)
    XFixesCursorImage* XFixesGetCursorImage(Display *)

    ctypedef XID XserverRegion
    XserverRegion XFixesCreateRegion(Display *, XRectangle *, int nrectangles)
    void XFixesDestroyRegion(Display *, XserverRegion)

cdef extern from "X11/extensions/xfixeswire.h":
    unsigned long XFixesDisplayCursorNotifyMask
    void XFixesSelectCursorInput(Display *, Window w, long mask)


cdef NS(char *v):
    if v==NULL:
        return "NULL"
    b = v
    return b.decode("latin1")

cdef s(const char *v):
    pytmp = v[:]
    try:
        return pytmp.decode()
    except:
        return str(v[:])


# xmodmap's "keycode" action done implemented in python
# some of the methods aren't very pythonic
# that's intentional so as to keep as close as possible
# to the original C xmodmap code


from xpra.x11.bindings.core_bindings cimport X11CoreBindingsInstance

cdef X11KeyboardBindingsInstance singleton = None
def X11KeyboardBindings():
    global singleton
    if singleton is None:
        singleton = X11KeyboardBindingsInstance()
    return singleton

cdef class X11KeyboardBindingsInstance(X11CoreBindingsInstance):

    cdef XModifierKeymap* work_keymap
    cdef int min_keycode
    cdef int max_keycode
    cdef int Xkb_checked
    cdef int Xkb_version_major
    cdef int Xkb_version_minor
    cdef int XTest_checked
    cdef int XTest_version_major
    cdef int XTest_version_minor
    cdef int XFixes_checked
    cdef int XFixes_present

    def __init__(self):
        self.work_keymap = NULL
        self.min_keycode = -1
        self.max_keycode = -1

    def __repr__(self):
        return "X11KeyboardBindings(%s)" % self.display_name


    def setxkbmap(self, rules_name, model, layout, variant, options):
        self.context_check("setxkbmap")
        log("setxkbmap(%s, %s, %s, %s, %s)", rules_name, model, layout, variant, options)
        if not self.hasXkb():
            log.error("Error: no Xkb support in this X11 server, cannot set keymap")
            return False
        cdef XkbRF_RulesPtr rules = NULL
        cdef XkbRF_VarDefsRec rdefs
        cdef XkbComponentNamesRec rnames
        cdef char *locale = setlocale(LC_ALL, NULL)
        log("setxkbmap: using locale=%s", NS(locale))

        #we have to use a temporary value for older versions of Cython:
        v = strtobytes(model or "")
        rdefs.model = v
        layout = strtobytes(layout)
        rdefs.layout = layout
        if variant:
            variant = strtobytes(variant)
            rdefs.variant = variant
        else:
            rdefs.variant = NULL
        if options:
            options = strtobytes(options)
            rdefs.options = options
        else:
            rdefs.options = NULL
        if not rules_name:
            rules_name = DFLT_XKB_RULES_FILE

        log("setxkbmap: using %s", {
            "rules" : bytestostr(rules_name),
            "model" : NS(rdefs.model),
            "layout" : NS(rdefs.layout),
            "variant" : NS(rdefs.variant),
            "options" : NS(rdefs.options),
            })
        #try to load rules files from all include paths until
        #we find one that works:
        XKB_CONFIG_ROOT = os.environ.get("XPRA_XKB_CONFIG_ROOT", "%s/share/X11/xkb" % sys.prefix).encode()
        for include_path in (b".", XKB_CONFIG_ROOT):
            rules_path = os.path.join(include_path, b"rules", strtobytes(rules_name))
            if len(rules_path)>=PATH_MAX:
                log.warn("Warning: rules path too long: %. Ignored.", rules_path)
                continue
            log("setxkbmap: trying to load rules file %s...", rules_path)
            rules_path = strtobytes(rules_path)
            rules = XkbRF_Load(rules_path, locale, True, True)
            if rules:
                log("setxkbmap: loaded rules from %s", bytestostr(rules_path))
                break
        if rules==NULL:
            log.error("Error: cannot find rules file '%s'", bytestostr(rules_name))
            return False

        # Let the rules file do the magic:
        cdef Bool r = XkbRF_GetComponents(rules, &rdefs, &rnames)
        log("XkbRF_GetComponents(%#x, %#x, %#x)=%s", <uintptr_t> rules, <uintptr_t> &rdefs, <uintptr_t> &rnames, bool(r))
        assert r, "failed to get components"
        props = self.getXkbProperties()
        if rnames.keycodes:
            props["keycodes"] = bytestostr(rnames.keycodes)
        if rnames.symbols:
            props["symbols"] = bytestostr(rnames.symbols)
        if rnames.types:
            props["types"] = bytestostr(rnames.types)
        if rnames.compat:
            props["compat"] = bytestostr(rnames.compat)
        if rnames.geometry:
            props["geometry"] = bytestostr(rnames.geometry)
        if rnames.keymap:
            props["keymap"] = bytestostr(rnames.keymap)
        #note: this value is from XkbRF_VarDefsRec as XkbComponentNamesRec has no layout attribute
        #(and we want to make sure we don't use the default value from getXkbProperties above)
        if rdefs.layout:
            props["layout"] = bytestostr(rdefs.layout)
        log("setxkbmap: properties=%s", props)
        #strip out strings inside parenthesis if any:
        filtered_props = {}
        for k,v in props.items():
            ps = v.find("(")
            if ps>=0:
                v = v[:ps]
            filtered_props[k] = v
        log("setxkbmap: filtered properties=%s", filtered_props)
        cdef XkbDescPtr xkb = XkbGetKeyboardByName(self.display, XkbUseCoreKbd, &rnames,
                                   XkbGBN_AllComponentsMask,
                                   XkbGBN_AllComponentsMask & (~XkbGBN_GeometryMask), True)
        log("setxkbmap: XkbGetKeyboardByName returned %#x", <unsigned long> xkb)
        if not xkb:
            log.error("Error loading new keyboard description")
            return False
        # update the XKB root property:
        if rules_name and (model or layout):
            rules_name = strtobytes(rules_name)
            if not XkbRF_SetNamesProp(self.display, rules_name, &rdefs):
                log.error("Error updating the XKB names property")
                return False
            log("X11 keymap property updated: %s", self.getXkbProperties())
        return True

    def set_layout_group(self, int grp):
        log("setting XKB layout group %s", grp)
        if XkbLockGroup(self.display, XkbUseCoreKbd, grp):
            XFlush(self.display)
        else:
            log.warn("Warning: cannot lock on keyboard layout group '%s'", grp)
        return self.get_layout_group()

    def get_layout_group(self):
        self.context_check("XkbGetState")
        cdef XkbStateRec xkb_state
        cdef Status r = XkbGetState(self.display, XkbUseCoreKbd, &xkb_state)
        if r:
            log.warn("Warning: cannot get keyboard layout group")
            return 0
        return xkb_state.group

    def hasXkb(self):
        if self.Xkb_checked:
            return self.Xkb_version_major>0 or self.Xkb_version_minor>0
        cdef int major, minor, opr
        cdef int evbase, errbase
        self.Xkb_checked = True
        if os.environ.get("XPRA_X11_XKB", "1")!="1":
            log.warn("Xkb disabled using XPRA_X11_XKB")
            return False
        cdef int r = XkbQueryExtension(self.display, &opr, &evbase, &errbase, &major, &minor)
        log("XkbQueryExtension version present: %s", bool(r))
        if not r:
            log.warn("Warning: Xkb server extension is missing")
            return False
        log("XkbQueryExtension version %i.%i, opcode result=%i, event base=%i, error base=%i", major, minor, opr, evbase, errbase)
        r = XkbLibraryVersion(&major, &minor)
        log("XkbLibraryVersion version %i.%i, compatible: %s", major, minor, bool(r))
        if not bool(r):
            log.warn("Warning: Xkb extension version is incompatible")
            return False
        self.Xkb_version_major = major
        self.Xkb_version_minor = minor
        return True


    def get_default_properties(self):
        return {
            "rules"    : "base",
            "model"    : "pc105",
            "layout"   : "us",
            }

    def getXkbProperties(self):
        self.context_check("getXkbProperties")
        if not self.hasXkb():
            log.warn("Warning: no Xkb support")
            return {}
        cdef XkbRF_VarDefsRec vd
        cdef char *tmp = NULL
        cdef Display *display = NULL
        cdef int r = XkbRF_GetNamesProp(self.display, &tmp, &vd)
        try:
            if r==0 or tmp==NULL:
                #if the display points to a specific screen (ie: DISPLAY=:20.1)
                #we may have to connect to the first screen to get the properties:
                nohost = self.display_name.split(b":")[-1]
                if nohost.find(b".")>0:
                    display_name = self.display_name[:self.display_name.rfind(b".")]
                    log("getXkbProperties retrying on '%s'", bytestostr(display_name))
                    display = XOpenDisplay(display_name)
                    if display:
                        r = XkbRF_GetNamesProp(display, &tmp, &vd)
            if r==0 or tmp==NULL:
                log.warn("Error: XkbRF_GetNamesProp failed on %s", self.display_name)
                return {}
            v = {}
            if len(tmp)>0:
                v["rules"] = s(tmp)
                XFree(tmp)
            if vd.model:
                v["model"]  = s(vd.model)
                XFree(vd.model)
            if vd.layout:
                v["layout"] = s(vd.layout)
                XFree(vd.layout)
            if vd.options!=NULL:
                v["options"] = s(vd.options)
                XFree(vd.options)
            if vd.variant!=NULL:
                simplified = ",".join(x for x in s(vd.variant).split(",") if x)
                if simplified=="":
                    v["variant"] = ""
                else:
                    v["variant"] = s(vd.variant)
                XFree(vd.variant)
            #log("vd.num_extra=%s", vd.num_extra)
            if vd.extra_names:
                #no idea how to use this!
                #if vd.num_extra>0:
                #    for i in range(vd.num_extra):
                #        v[vd.extra_names[i][:]] = vd.extra_values[] ???
                XFree(vd.extra_names)
            log("getXkbProperties()=%s", v)
            return v
        finally:
            if display!=NULL:
                XCloseDisplay(display)


    cdef _get_minmax_keycodes(self):
        if self.min_keycode==-1 and self.max_keycode==-1:
            XDisplayKeycodes(self.display, &self.min_keycode, &self.max_keycode)
        return self.min_keycode, self.max_keycode

    def get_modifier_map(self):
        cdef XModifierKeymap *xmodmap = NULL
        try:
            xmodmap = XGetModifierMapping(self.display)
            assert xmodmap
            keycode_array = []
            for i in range(8 * xmodmap.max_keypermod):
                keycode_array.append(xmodmap.modifiermap[i])
            return (xmodmap.max_keypermod, keycode_array)
        finally:
            if xmodmap!=NULL:
                XFreeModifiermap(xmodmap)


    def get_xkb_keycode_mappings(self):
        self.context_check("get_xkb_keycode_mappings")
        if not self.hasXkb():
            return {}
        mask = 255
        cdef XkbDescPtr xkb = XkbGetMap(self.display, mask, XkbUseCoreKbd)
        if xkb==NULL:
            return {}
        cdef KeySym sym
        keysyms = {}
        for keycode in range(xkb.min_key_code, xkb.max_key_code):
            sym_map = xkb.map.key_sym_map[keycode]
            width = sym_map.width
            offset = sym_map.offset
            #num_groups = sym_map.group_info
            #group_width = 0
            syms = []
            for i in range(width):
                sym = xkb.map.syms[offset+i]
                syms.append(sym)
            #log("%3i: width=%i, offset=%3i, num_groups=%i, syms=%s / %s",
            #keycode, width, offset, num_groups, syms, symstrs)
            keynames = self.keysyms_to_strings(syms)
            if len(keynames)>0:
                keysyms[keycode] = keynames
        XkbFreeKeyboard(xkb, 0, 1)
        return keysyms


    def get_minmax_keycodes(self):
        if self.min_keycode==-1 and self.max_keycode==-1:
            self._get_minmax_keycodes()
        return self.min_keycode, self.max_keycode

    cdef XModifierKeymap* get_keymap(self, load):
        self.context_check("get_keymap")
        if self.work_keymap==NULL and load:
            self.work_keymap = XGetModifierMapping(self.display)
            log("retrieved work keymap: %#x", <unsigned long> self.work_keymap)
        return self.work_keymap

    cdef set_work_keymap(self, XModifierKeymap* new_keymap):
        log("setting new work keymap: %#x", <unsigned long> new_keymap)
        self.work_keymap = new_keymap

    cdef KeySym _parse_keysym(self, symbol):
        s = strtobytes(symbol)
        if s in [b"NoSymbol", b"VoidSymbol"]:
            return  NoSymbol
        cdef KeySym keysym = XStringToKeysym(s)
        if keysym==NoSymbol:
            if s.startswith(b"U+"):
                s = b"0x"+s[2:]
            if s.lower().startswith(b"0x"):
                return int(s, 16)
            if len(s)>0:
                try:
                    return int(s)
                except ValueError:
                    pass
            return NoSymbol
        return keysym

    def parse_keysym(self, symbol):
        self.context_check("parse_keysym")
        return int(self._parse_keysym(symbol))

    cdef _keysym_str(self, keysym_val):
        cdef KeySym keysym = int(keysym_val)
        cdef char *s = XKeysymToString(keysym)
        if s==NULL:
            return ""
        return bytestostr(s)

    def keysym_str(self, keysym_val):
        return self._keysym_str(keysym_val)

    def get_keysym_list(self, symbols):
        """ convert a list of key symbols into a list of KeySym values
            by calling parse_keysym on each one
        """
        keysymlist = []
        cdef KeySym keysym
        for x in symbols:
            keysym = self._parse_keysym(x)
            if keysym!=NoSymbol:
                keysymlist.append(keysym)
        return keysymlist

    cdef int _parse_keycode(self, keycode_str):
        cdef int keycode
        if keycode_str=="any":
            #find a free one:
            keycode = 0
        elif keycode_str[:1]=="x":
            #int("0x101", 16)=257
            keycode = int("0"+keycode_str, 16)
        else:
            keycode = int(keycode_str)
        min_keycode, max_keycode = self._get_minmax_keycodes()
        if keycode!=0 and keycode<min_keycode or keycode>max_keycode:
            log.error("Error for keycode '%s': value %i is out of range (%s-%s)", keycode_str, keycode, min_keycode, max_keycode)
            return -1
        return keycode

    def parse_keycode(self, keycode_str):
        return self._parse_keycode(keycode_str)

    cdef xmodmap_setkeycodes(self, keycodes, new_keysyms):
        self.context_check("xmodmap_setkeycodes")
        cdef KeySym keysym
        cdef int keycode, i
        cdef int first_keycode = min(keycodes.keys())
        cdef int last_keycode = max(keycodes.keys())
        cdef int num_codes = 1+last_keycode-first_keycode
        MAX_KEYSYMS_PER_KEYCODE = 8
        cdef int keysyms_per_keycode = min(MAX_KEYSYMS_PER_KEYCODE, max([1]+[len(keysyms) for keysyms in keycodes.values()]))
        log("xmodmap_setkeycodes using %s keysyms_per_keycode", keysyms_per_keycode)
        cdef size_t l = sizeof(KeySym)*num_codes*keysyms_per_keycode
        cdef KeySym* ckeysyms = <KeySym*> malloc(l)
        if ckeysyms==NULL:
            log.error("Error: failed to allocate %i bytes of memory for keysyms" % l)
            return False
        try:
            missing_keysyms = []
            for i in range(0, num_codes):
                keycode = first_keycode+i
                keysyms_strs = keycodes.get(keycode)
                log("setting keycode %i: %s", keycode, keysyms_strs)
                if keysyms_strs is None:
                    if len(new_keysyms)>0:
                        #no keysyms for this keycode yet, assign one of the "new_keysyms"
                        keysyms = new_keysyms[:1]
                        new_keysyms = new_keysyms[1:]
                        log("assigned keycode %i to %s", keycode, keysyms[0])
                    else:
                        keysyms = []
                        log("keycode %i is still free", keycode)
                else:
                    keysyms = []
                    for ks in keysyms_strs:
                        if ks in (None, ""):
                            keysym = NoSymbol
                        elif isinstance(ks, (long, int)):
                            keysym = ks
                        else:
                            keysym = self._parse_keysym(ks)
                        if keysym!=NoSymbol:
                            keysyms.append(keysym)
                        else:
                            keysyms.append(NoSymbol)
                            if ks:
                                missing_keysyms.append(str(ks))
                for j in range(keysyms_per_keycode):
                    keysym = NoSymbol
                    if keysyms and j<len(keysyms) and keysyms[j] is not None:
                        keysym = keysyms[j]
                    ckeysyms[i*keysyms_per_keycode+j] = keysym
            if len(missing_keysyms)>0:
                log.info("could not find the following keysyms: %s", " ".join(set(missing_keysyms)))
            return XChangeKeyboardMapping(self.display, first_keycode, keysyms_per_keycode, ckeysyms, num_codes)==0
        finally:
            free(ckeysyms)

    cdef KeysymToKeycodes(self, KeySym keysym):
        self.context_check("KeysymToKeycodes")
        if not self.hasXkb():
            return []
        cdef int i, j
        min_keycode, max_keycode = self._get_minmax_keycodes()
        keycodes = []
        for i in range(min_keycode, max_keycode+1):
            for j in range(0,8):
                if XkbKeycodeToKeysym(self.display, <KeyCode> i, j//4, j%4) == keysym:
                    keycodes.append(i)
                    break
        return keycodes

    cdef _get_raw_keycode_mappings(self):
        """
            returns a dict: {keycode, [keysyms]}
            for all the keycodes
        """
        self.context_check("XGetKeyboardMapping")
        cdef int keysyms_per_keycode
        cdef KeySym keysym
        cdef KeyCode keycode
        min_keycode,max_keycode = self._get_minmax_keycodes()
        cdef int keycode_count = max_keycode - min_keycode + 1
        cdef KeySym * keyboard_map = XGetKeyboardMapping(self.display, min_keycode, keycode_count, &keysyms_per_keycode)
        log("XGetKeyboardMapping keysyms_per_keycode=%i, keyboard_map=%#x", keysyms_per_keycode, <uintptr_t> keyboard_map)
        mappings = {}
        cdef int i
        for i in range(keycode_count):
            keycode = min_keycode + i
            keysyms = []
            for keysym_index in range(keysyms_per_keycode):
                keysym = keyboard_map[i*keysyms_per_keycode + keysym_index]
                keysyms.append(keysym)
            mappings[keycode] = keysyms
        XFree(keyboard_map)
        return mappings

    def get_keycode_mappings(self):
        """
        the mappings from _get_raw_keycode_mappings are in raw format
        (keysyms as numbers), so here we convert into names:
        """
        raw_mappings = self._get_raw_keycode_mappings()
        mappings = {}
        for keycode, keysyms in raw_mappings.items():
            keynames = self.keysyms_to_strings(keysyms)
            if len(keynames)>0:
                mappings[keycode] = keynames
        return mappings

    def keysyms_to_strings(self, keysyms):
        keynames = []
        for keysym in keysyms:
            key = ""
            if keysym!=NoSymbol:
                keyname = XKeysymToString(keysym)
                if keyname!=NULL:
                    key = bytestostr(keyname)
            keynames.append(key)
        #now remove trailing empty entries:
        while len(keynames)>0 and keynames[-1]=="":
            keynames = keynames[:-1]
        return keynames


    def get_keycodes(self, keyname):
        codes = []
        cdef KeySym keysym = self._parse_keysym(keyname)
        if not keysym:
            return  codes
        return self.KeysymToKeycodes(keysym)

    def parse_modifier(self, name):
        return {
                "shift"     : 0,
                "lock"      : 1,
                "control"   : 2,
                "ctrl"      : 2,
                "mod1"      : 3,
                "mod2"      : 4,
                "mod3"      : 5,
                "mod4"      : 6,
                "mod5"      : 7,
                }.get(name.lower(), -1)

    def modifier_name(self, modifier_index):
        return {
                0 : "shift",
                1 : "lock",
                2 : "control",
                3 : "mod1",
                4 : "mod2",
                5 : "mod3",
                6 : "mod4",
                7 : "mod5",
                }.get(modifier_index)


    cdef _get_raw_modifier_mappings(self):
        """
            returns a dict: {modifier_index, [keycodes]}
            for all keycodes (see above for list)
        """
        self.context_check("XGetKeyboardMapping")
        cdef int keysyms_per_keycode
        cdef KeyCode keycode
        min_keycode,max_keycode = self._get_minmax_keycodes()
        cdef KeySym *keyboard_map = XGetKeyboardMapping(self.display, min_keycode, max_keycode - min_keycode + 1, &keysyms_per_keycode)
        mappings = {}
        i = 0
        cdef XModifierKeymap* keymap = self.get_keymap(False)
        assert keymap==NULL
        keymap = self.get_keymap(True)
        modifiermap = <KeyCode*> keymap.modifiermap
        for modifier in range(0, 8):
            keycodes = []
            k = 0
            while k<keymap.max_keypermod:
                keycode = modifiermap[i]
                if keycode!=NoSymbol:
                    keycodes.append(keycode)
                k += 1
                i += 1
            mappings[modifier] = keycodes
        XFreeModifiermap(keymap)
        self.set_work_keymap(NULL)
        XFree(keyboard_map)
        return (keysyms_per_keycode, mappings)

    cdef _get_modifier_mappings(self):
        """
        the mappings from _get_raw_modifier_mappings are in raw format
        (index and keycode), so here we convert into names:
        """
        cdef KeySym keysym
        cdef char *keyname
        keysyms_per_keycode, raw_mappings = self._get_raw_modifier_mappings()
        mappings = {}
        for mod, keycodes in raw_mappings.items():
            modifier = self.modifier_name(mod)
            if not modifier:
                log.error("cannot find name for modifier %s", mod)
                continue
            keynames = []
            for keycode in keycodes:
                keysym = 0
                index = 0
                while (keysym==0 and index<keysyms_per_keycode):
                    keysym = XkbKeycodeToKeysym(self.display, keycode, index//4, index%4)
                    index += 1
                if keysym==0:
                    log.warn("Warning: no keysym found for keycode %i of modifier %s", keycode, modifier)
                    continue
                keyname = XKeysymToString(keysym)
                if keyname==NULL:
                    log.warn("Warning: cannot convert keysym %i to a string", keysym)
                    continue
                kstr = bytestostr(keyname)
                if kstr not in keynames:
                    keynames.append((keycode, kstr))
            mappings[modifier] = keynames
        return mappings

    def get_modifier_mappings(self):
        return self._get_modifier_mappings()

    cdef xmodmap_clearmodifier(self, int modifier):
        cdef XModifierKeymap* keymap = self.get_keymap(True)
        cdef KeyCode* keycode = <KeyCode*> keymap.modifiermap
        log("clear modifier: clearing all %i for modifier=%s", keymap.max_keypermod, modifier)
        for i in range(0, keymap.max_keypermod):
            keycode[modifier*keymap.max_keypermod+i] = 0

    cdef xmodmap_addmodifier(self, int modifier, keysyms):
        self.context_check("xmodmap_addmodifier")
        cdef KeyCode keycode
        cdef KeySym keysym
        cdef XModifierKeymap* keymap = self.get_keymap(True)
        success = True
        log("add modifier: modifier %s=%s", modifier, keysyms)
        for keysym_str in keysyms:
            kss = strtobytes(keysym_str)
            keysym = XStringToKeysym(kss)
            log("add modifier: keysym(%s)=%s", keysym_str, keysym)
            keycodes = self.KeysymToKeycodes(keysym)
            log("add modifier: keycodes(%s)=%s", keysym, keycodes)
            if len(keycodes)==0:
                log.error("xmodmap_exec_add: no keycodes found for keysym %s/%s", keysym_str, keysym)
                success = False
            else:
                for k in keycodes:
                    if k!=0:
                        keycode = k
                        keymap = XInsertModifiermapEntry(keymap, keycode, modifier)
                        if keymap!=NULL:
                            self.set_work_keymap(keymap)
                            log("add modifier: added keycode=%s for modifier %s and keysym=%s", k, modifier, keysym_str)
                        else:
                            log.error("add modifier: failed keycode=%s for modifier %s and keysym=%s", k, modifier, keysym_str)
                            success = False
                    else:
                        log.info("add modifier: failed, found zero keycode for %s", modifier)
                        success = False
        return success


    cdef _get_keycodes_down(self):
        cdef char[32] keymap
        masktable = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]
        down = []
        XQueryKeymap(self.display, keymap)
        for i in range(0, 256):
            if keymap[i >> 3] & masktable[i & 7]:
                down.append(i)
        return down

    def get_keycodes_down(self):
        self.context_check("get_keycodes_down")
        if not self.hasXkb():
            {}
        cdef char* key
        cdef KeySym keysym
        cdef int group, level
        keycodes = self._get_keycodes_down()
        keys = {}
        def get_keysyms(keycode):
            keysyms = []
            for group in (0, 1):
                for level in (0, 1):
                    keysym = XkbKeycodeToKeysym(self.display, keycode, group, level)
                    if keysym==NoSymbol:
                        continue
                    key = XKeysymToString(keysym)
                    if key!=NULL:
                        keysyms.append(bytestostr(key))
            return keysyms
        for keycode in keycodes:
            keys[keycode] = get_keysyms(keycode)
        return keys

    def unpress_all_keys(self):
        if not self.hasXTest():
            return
        keycodes = self._get_keycodes_down()
        for keycode in keycodes:
            XTestFakeKeyEvent(self.display, keycode, False, 0)

    cdef native_xmodmap(self, instructions):
        self.context_check("native_xmodmap")
        cdef XModifierKeymap* keymap
        cdef int modifier
        self.set_work_keymap(NULL)
        unhandled = []
        keycodes = {}
        new_keysyms = []
        try:
            for line in instructions:
                log("processing: %s", line)
                if not line:
                    continue
                cmd = line[0]
                if cmd=="keycode":
                    #line = ("keycode", keycode, [keysyms])
                    keycode = int(line[1])
                    keysyms = line[2]
                    if keycode==0:
                        #keycode=0 means "any", ie: 'keycode any = Shift_L'
                        assert len(keysyms)==1
                        new_keysyms.append(keysyms[0])
                        continue
                    elif keycode>0:
                        keycodes[keycode] = keysyms
                        continue
                elif cmd=="clear":
                    #ie: ("clear", 1)
                    modifier = line[1]
                    if modifier>=0:
                        self.xmodmap_clearmodifier(modifier)
                        continue
                elif cmd=="add":
                    #ie: ("add", "Control", ["Control_L", "Control_R"])
                    modifier = line[1]
                    keysyms = line[2]
                    if modifier>=0:
                        if self.xmodmap_addmodifier(modifier, keysyms):
                            continue
                log.error("native_xmodmap could not handle instruction: %s", line)
                unhandled.append(line)
            if len(keycodes)>0:
                log("calling xmodmap_setkeycodes with %s", keycodes)
                self.xmodmap_setkeycodes(keycodes, new_keysyms)
        finally:
            keymap = self.get_keymap(False)
            if keymap!=NULL:
                self.set_work_keymap(NULL)
                log("saving modified keymap")
                if XSetModifierMapping(self.display, keymap)==MappingBusy:
                    log.error("cannot change keymap: mapping busy: %s" % self.get_keycodes_down())
                    unhandled = instructions
                XFreeModifiermap(keymap)
        log("modify keymap: %s instructions, %s unprocessed", len(instructions), len(unhandled))
        return unhandled

    def set_xmodmap(self, xmodmap_data):
        log("set_xmodmap(%s)", xmodmap_data)
        return self.native_xmodmap(xmodmap_data)

    def grab_key(self, xwindow, keycode, modifiers):
        self.context_check("grab_key")
        XGrabKey(self.display, keycode, modifiers,
                 xwindow,
                 # Really, grab the key even if it's also in another window we own
                 False,
                 # Don't stall the pointer upon this key being pressed:
                 GrabModeAsync,
                 # Don't stall the keyboard upon this key being pressed (need to
                 # change this if we ever want to allow for multi-key bindings
                 # a la emacs):
                 GrabModeAsync)

    def ungrab_all_keys(self):
        self.context_check("ungrab_all_keys")
        cdef Window root_window = XDefaultRootWindow(self.display)
        XUngrabKey(self.display, AnyKey, AnyModifier, root_window)


    cdef Atom get_xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        self.context_check("get_xatom")
        if isinstance(str_or_int, (int, long)):
            return <Atom> str_or_int
        bstr = strtobytes(str_or_int)
        cdef char* string = bstr
        return XInternAtom(self.display, string, False)

    def device_bell(self, xwindow, deviceSpec, bellClass, bellID, percent, name):
        self.context_check("device_bell")
        if not self.hasXkb():
            return
        cdef Atom name_atom = self.get_xatom(name)
        #until (if ever) we replicate the same devices on the server,
        #use the default device:
        #deviceSpec = XkbUseCoreKbd
        #bellID = XkbDfltXIId
        return XkbDeviceBell(self.display, xwindow, XkbUseCoreKbd, bellClass, XkbDfltXIId,  percent, name_atom)


    def hasXTest(self):
        self.context_check("hasXTest")
        if self.XTest_checked:
            return self.XTest_version_major>0 or self.XTest_version_minor>0
        self.XTest_checked = True
        if os.environ.get("XPRA_X11_XTEST", "1")!="1":
            log.warn("XTest disabled using XPRA_X11_XTEST")
            return False
        cdef int evbase, errbase
        cdef int major, minor
        cdef int r = XTestQueryExtension(self.display, &evbase, &errbase, &major, &minor)
        if not r:
            log.warn("Warning: XTest extension is missing")
            return False
        log("XTestQueryExtension found version %i.%i with event base=%i, error base=%i", major, minor, evbase, errbase)
        self.XTest_version_major = major
        self.XTest_version_minor = minor
        return True


    def xtest_fake_key(self, keycode, is_press):
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_key")
        return XTestFakeKeyEvent(self.display, keycode, is_press, 0)

    def xtest_fake_button(self, button, is_press):
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_button")
        return XTestFakeButtonEvent(self.display, button, is_press, 0)

    def xtest_fake_motion(self, int screen, int x, int y, int delay=0):
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_motion")
        return XTestFakeMotionEvent(self.display, screen, x, y, delay)

    def xtest_fake_relative_motion(self, int x, int y, int delay=0):
        if not self.hasXTest():
            return False
        self.context_check("xtest_fake_relative_motion")
        return XTestFakeRelativeMotionEvent(self.display, x, y, delay)


    def get_key_repeat_rate(self):
        if not self.hasXkb():
            return None
        cdef unsigned int deviceSpec = XkbUseCoreKbd
        cdef unsigned int delay = 0
        cdef unsigned int interval = 0
        if not XkbGetAutoRepeatRate(self.display, deviceSpec, &delay, &interval):
            return None
        return (delay, interval)

    def set_key_repeat_rate(self, delay, interval):
        self.context_check("set_key_repeat_rate")
        if not self.hasXkb():
            log.warn("Warning: cannot set key repeat rate without Xkb support")
            return False
        cdef unsigned int deviceSpec = XkbUseCoreKbd
        cdef unsigned int cdelay = delay
        cdef unsigned int cinterval = interval
        return XkbSetAutoRepeatRate(self.display, deviceSpec, cdelay, cinterval)


    def hasXFixes(self):
        self.context_check("hasXFixes")
        cdef int evbase, errbase
        if not self.XFixes_checked:
            self.XFixes_checked = True
            if os.environ.get("XPRA_X11_XFIXES", "1")!="1":
                log.warn("XFixes disabled using XPRA_X11_XFIXES")
            else:
                self.XFixes_present = XFixesQueryExtension(self.display, &evbase, &errbase)
                log("XFixesQueryExtension version present: %s", bool(self.XFixes_present))
                if self.XFixes_present:
                    log("XFixesQueryExtension event base=%i, error base=%i", evbase, errbase)
                else:
                    log.warn("Warning: XFixes extension is missing")
        return bool(self.XFixes_present)

    def get_cursor_image(self):
        self.context_check("get_cursor_image")
        if not self.hasXFixes():
            return None
        cdef XFixesCursorImage* image = NULL
        cdef int n, i = 0
        cdef unsigned char r, g, b, a
        cdef unsigned long argb
        try:
            image = XFixesGetCursorImage(self.display)
            if image==NULL:
                return  None
            n = image.width*image.height
            #Warning: we need to iterate over the input one *long* at a time
            #(even though only 4 bytes are set - and longs are 8 bytes on 64-bit..)
            pixels = bytearray(n*4)
            while i<n:
                argb = image.pixels[i] & 0xffffffff
                a = (argb >> 24)   & 0xff
                r = (argb >> 16)   & 0xff
                g = (argb >> 8)    & 0xff
                b = (argb)         & 0xff
                pixels[i*4]     = r
                pixels[i*4+1]   = g
                pixels[i*4+2]   = b
                pixels[i*4+3]   = a
                i += 1
            return [image.x, image.y, image.width, image.height, image.xhot, image.yhot,
                int(image.cursor_serial), bytes(pixels), bytes(image.name)]
        finally:
            if image!=NULL:
                XFree(image)


    def selectCursorChange(self, on):
        self.context_check("selectCursorChange")
        if not self.hasXFixes():
            log.warn("Warning: no cursor change notifications without XFixes support")
            return
        cdef unsigned int mask = 0
        cdef Window root_window = XDefaultRootWindow(self.display)
        if on:
            mask = XFixesDisplayCursorNotifyMask
        #no return value..
        XFixesSelectCursorInput(self.display, root_window, mask)
        return True


    def selectBellNotification(self, on):
        self.context_check("selectBellNotification")
        if not self.hasXkb():
            log.warn("Warning: no system bell events without Xkb support")
            return
        cdef int bits = XkbBellNotifyMask
        if not on:
            bits = 0
        return XkbSelectEvents(self.display, XkbUseCoreKbd, XkbBellNotifyMask, bits)


    def query_pointer(self):
        self.context_check("query_pointer")
        cdef Window root_window = XDefaultRootWindow(self.display)
        cdef Window root, child
        cdef int root_x, root_y
        cdef int win_x, win_y
        cdef unsigned int mask
        XQueryPointer(self.display, root_window, &root, &child,
                      &root_x, &root_y, &win_x, &win_y, &mask)
        return root_x, root_y
