# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import List, Dict, Tuple
from collections.abc import Iterable

from xpra.x11.bindings.xlib cimport (
    Display, Bool, KeySym, KeyCode, Atom, Window, Status, Time, XRectangle, CARD32,
    XModifierKeymap,
    XDefaultRootWindow,
    XOpenDisplay, XCloseDisplay, XFlush, XFree, XInternAtom,
    XDisplayKeycodes, XQueryKeymap,
    XGetModifierMapping, XSetModifierMapping,
    XFreeModifiermap, XChangeKeyboardMapping, XGetKeyboardMapping, XInsertModifiermapEntry,
    XStringToKeysym, XKeysymToString,
    XGrabKey, XUngrabKey,
    MappingBusy, GrabModeAsync, AnyKey, AnyModifier, NoSymbol,
)
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check
from libc.stdint cimport uintptr_t      # pylint: disable=syntax-error
from libc.stdlib cimport free, malloc

from xpra.util.str_fn import csv
from xpra.log import Logger

import_check("keyboard")

log = Logger("x11", "bindings", "keyboard")

DEF PATH_MAX = 1024
DEF DFLT_XKB_RULES_FILE = "base"


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

    ctypedef struct XkbControlsRec:
        pass
    ctypedef XkbControlsRec* XkbControlsPtr

    ctypedef struct XkbServerMapRec:
        pass
    ctypedef XkbServerMapRec* XkbServerMapPtr

    ctypedef struct XkbIndicatorRec:
        pass
    ctypedef XkbIndicatorRec* XkbIndicatorPtr

    ctypedef struct XkbNamesRec:
        pass
    ctypedef XkbNamesRec* XkbNamesPtr

    ctypedef struct XkbCompatMapRec:
        pass
    ctypedef XkbCompatMapRec* XkbCompatMapPtr

    ctypedef void* XkbGeometryPtr

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

    XkbDescPtr XkbGetMap(Display *display, unsigned int which, unsigned int device)


cdef str NS(char *v):
    if v==NULL:
        return "NULL"
    b = v
    return b.decode("latin1")


cdef str s(const char *v):
    pytmp = v[:]
    try:
        return pytmp.decode()
    except:
        return str(v[:])


cdef inline bytes b(value: str):
    return value.encode("latin1")


# xmodmap's "keycode" action done implemented in python
# some of the methods aren't very pythonic
# that's intentional so as to keep as close as possible
# to the original C xmodmap code


cdef class X11KeyboardBindingsInstance(X11CoreBindingsInstance):

    cdef XModifierKeymap* work_keymap
    cdef int min_keycode
    cdef int max_keycode
    cdef int Xkb_checked
    cdef int Xkb_version_major
    cdef int Xkb_version_minor

    def __init__(self):
        self.work_keymap = NULL
        self.min_keycode = -1
        self.max_keycode = -1

    def __repr__(self):
        return "X11KeyboardBindings(%s)" % self.display_name

    def setxkbmap(self, rules_name: str, model: str, layout: str, variant: str, options: str) -> bool:
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

        # e have to use a temporary value for older versions of Cython:
        bmodel = b(model)
        rdefs.model = bmodel
        blayout = b(layout)
        rdefs.layout = blayout
        if variant:
            bvariant = b(variant)
            rdefs.variant = bvariant
        else:
            rdefs.variant = NULL
        if options:
            boptions = b(options)
            rdefs.options = boptions
        else:
            rdefs.options = NULL
        if not rules_name:
            rules_name = DFLT_XKB_RULES_FILE

        log("setxkbmap: using %s", {
            "rules" : rules_name,
            "model" : NS(rdefs.model),
            "layout" : NS(rdefs.layout),
            "variant" : NS(rdefs.variant),
            "options" : NS(rdefs.options),
        })
        # ry to load rules files from all include paths until
        # e find one that works:
        XKB_CONFIG_ROOT = os.environ.get("XPRA_XKB_CONFIG_ROOT", "%s/share/X11/xkb" % sys.prefix)
        for include_path in (".", XKB_CONFIG_ROOT):
            rules_path = os.path.join(include_path, "rules", rules_name)
            if len(rules_path)>=PATH_MAX:
                log.warn("Warning: rules path too long: %. Ignored.", rules_path)
                continue
            log("setxkbmap: trying to load rules file %s...", rules_path)
            rules_path = b(rules_path)
            rules = XkbRF_Load(rules_path, locale, True, True)
            if rules:
                log("setxkbmap: loaded rules from %r", s(rules_path))
                break
        if rules==NULL:
            log.error("Error: cannot find rules file %r", s(rules_name))
            return False

        # Let the rules file do the magic:
        cdef Bool r = XkbRF_GetComponents(rules, &rdefs, &rnames)
        log("XkbRF_GetComponents(%#x, %#x, %#x)=%s", <uintptr_t> rules, <uintptr_t> &rdefs, <uintptr_t> &rnames, bool(r))
        assert r, "failed to get components"
        props = self.getXkbProperties()
        if rnames.keycodes:
            props["keycodes"] = s(rnames.keycodes)
        if rnames.symbols:
            props["symbols"] = s(rnames.symbols)
        if rnames.types:
            props["types"] = s(rnames.types)
        if rnames.compat:
            props["compat"] = s(rnames.compat)
        if rnames.geometry:
            props["geometry"] = s(rnames.geometry)
        if rnames.keymap:
            props["keymap"] = s(rnames.keymap)
        # ote: this value is from XkbRF_VarDefsRec as XkbComponentNamesRec has no layout attribute
        #(and we want to make sure we don't use the default value from getXkbProperties above)
        if rdefs.layout:
            props["layout"] = s(rdefs.layout)
        log("setxkbmap: properties=%s", props)
        # trip out strings inside parenthesis if any:
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
            brules = b(rules_name)
            if not XkbRF_SetNamesProp(self.display, brules, &rdefs):
                log.error("Error updating the XKB names property")
                return False
            log("X11 keymap property updated: %s", self.getXkbProperties())
        return True

    def set_layout_group(self, int grp) -> int:
        log("setting XKB layout group %s", grp)
        if XkbLockGroup(self.display, XkbUseCoreKbd, grp):
            XFlush(self.display)
        else:
            log.warn("Warning: cannot lock on keyboard layout group '%s'", grp)
        return self.get_layout_group()

    def get_layout_group(self) -> int:
        self.context_check("XkbGetState")
        cdef XkbStateRec xkb_state
        cdef Status r = XkbGetState(self.display, XkbUseCoreKbd, &xkb_state)
        if r:
            log.warn("Warning: cannot get keyboard layout group")
            return 0
        return xkb_state.group

    def hasXkb(self) -> bool:
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

    def get_default_properties(self) -> Dict[str, str]:
        return {
            "rules"    : "base",
            "model"    : "pc105",
            "layout"   : "us",
        }

    def getXkbProperties(self) -> Dict[str, str]:
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
                # f the display points to a specific screen (ie: DISPLAY=:20.1)
                # e may have to connect to the first screen to get the properties:
                nohost = self.display_name.split(":")[-1]
                if nohost.find(".")>0:
                    display_name = self.display_name[:self.display_name.rfind(".")]
                    log("getXkbProperties retrying on %r", display_name)
                    bstr = display_name.encode("latin1")
                    display = XOpenDisplay(bstr)
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
            # og("vd.num_extra=%s", vd.num_extra)
            if vd.extra_names:
                # o idea how to use this!
                # f vd.num_extra>0:
                #    for i in range(vd.num_extra):
                #        v[vd.extra_names[i][:]] = vd.extra_values[] ???
                XFree(vd.extra_names)
            log("getXkbProperties()=%s", v)
            return v
        finally:
            if display!=NULL:
                XCloseDisplay(display)

    cdef Tuple _get_minmax_keycodes(self):
        if self.min_keycode==-1 and self.max_keycode==-1:
            XDisplayKeycodes(self.display, &self.min_keycode, &self.max_keycode)
        return self.min_keycode, self.max_keycode

    def get_modifier_map(self) -> Tuple[int, List[int]]:
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

    def get_xkb_keycode_mappings(self) -> Dict[int, List[str]]:
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
            count = width * sym_map.group_info
            if count <= 0:
                continue
            syms = []
            for i in range(count):
                sym = xkb.map.syms[offset+i]
                syms.append(sym)
            # og("%3i: width=%i, offset=%3i, num_groups=%i, syms=%s / %s",
            # keycode, width, offset, num_groups, syms, ksymstrs)
            keynames = self.keysyms_to_strings(syms)
            if len(keynames)>0:
                keysyms[keycode] = keynames
        XkbFreeKeyboard(xkb, 0, 1)
        return keysyms

    def get_xkb_keysym_mappings(self) -> Dict[int, Dict[int, Sequence[int]]]:
        # returns a map with the keyval as key,
        # and a map as value: (group, list of keycodes)
        self.context_check("get_xkb_keysym_mappings")
        if not self.hasXkb():
            return {}
        mask = 255
        cdef XkbDescPtr xkb = XkbGetMap(self.display, mask, XkbUseCoreKbd)
        if xkb==NULL:
            return {}
        cdef KeySym sym
        cdef unsigned char width
        cdef XkbSymMapRec *sym_map
        keysyms: Dict[int, Dict[int, Sequence[int]]] = {}
        for keycode in range(xkb.min_key_code, xkb.max_key_code):
            sym_map = &xkb.map.key_sym_map[keycode]
            width = sym_map.width
            if width <= 0 or sym_map.group_info <= 0:
                continue
            for group in range(sym_map.group_info):
                offset = sym_map.offset + width * group
                for i in range(width):
                    keysym = xkb.map.syms[offset + i]
                    keycodes = keysyms.setdefault(keysym, {}).setdefault(group, [])
                    if keycode not in keycodes:
                        keycodes.append(keycode)
        XkbFreeKeyboard(xkb, 0, 1)
        return keysyms

    def get_minmax_keycodes(self) -> Tuple[int, int]:
        if self.min_keycode==-1 and self.max_keycode==-1:
            self._get_minmax_keycodes()
        return self.min_keycode, self.max_keycode

    cdef XModifierKeymap* get_keymap(self, load) noexcept:
        self.context_check("get_keymap")
        if self.work_keymap==NULL and load:
            self.work_keymap = XGetModifierMapping(self.display)
            log("retrieved work keymap: %#x", <unsigned long> self.work_keymap)
        return self.work_keymap

    cdef void set_work_keymap(self, XModifierKeymap* new_keymap) noexcept:
        # log("setting new work keymap: %#x", <unsigned long> new_keymap)
        self.work_keymap = new_keymap

    cdef KeySym _parse_keysym(self, symbol) noexcept:
        s = b(symbol)
        if s in [b"NoSymbol", b"VoidSymbol"]:
            return NoSymbol
        cdef KeySym keysym = XStringToKeysym(s)
        if keysym == NoSymbol:
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

    def parse_keysym(self, symbol) -> int:
        return int(self._parse_keysym(symbol))

    def keysym_str(self, keysym_val) -> str:
        cdef KeySym keysym = int(keysym_val)
        cdef char *bin = XKeysymToString(keysym)
        if bin==NULL:
            return ""
        return s(bin)

    def get_keysym_list(self, symbols) -> List[KeySym]:
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

    cdef int _parse_keycode(self, keycode_str) noexcept:
        cdef int keycode
        if keycode_str=="any":
            # find a free one:
            keycode = 0
        elif keycode_str[:1]=="x":
            # int("0x101", 16)=257
            keycode = int("0"+keycode_str, 16)
        else:
            keycode = int(keycode_str)
        min_keycode, max_keycode = self._get_minmax_keycodes()
        if keycode!=0 and keycode<min_keycode or keycode>max_keycode:
            log.error("Error for keycode '%s': value %i is out of range (%s-%s)", keycode_str, keycode, min_keycode, max_keycode)
            return -1
        return keycode

    def parse_keycode(self, keycode_str) -> int:
        return self._parse_keycode(keycode_str)

    cdef int xmodmap_setkeycodes(self, keycodes, new_keysyms):
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
            free_keycodes = []
            for i in range(0, num_codes):
                keycode = first_keycode+i
                keysyms_strs = keycodes.get(keycode)
                if keysyms_strs:
                    log("setting keycode %i: %s", keycode, keysyms_strs)
                if keysyms_strs is None:
                    if len(new_keysyms)>0:
                        # no keysyms for this keycode yet, assign one of the "new_keysyms"
                        keysyms = new_keysyms[:1]
                        new_keysyms = new_keysyms[1:]
                        log("assigned keycode %i to %s", keycode, keysyms[0])
                    else:
                        keysyms = []
                        free_keycodes.append(keycode)
                else:
                    keysyms = []
                    for ks in keysyms_strs:
                        if ks in (None, ""):
                            keysym = NoSymbol
                        elif isinstance(ks, int):
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
            log("free keycodes: %s", free_keycodes)
            if len(missing_keysyms)>0:
                log.info("could not find the following keysyms: %s", " ".join(set(missing_keysyms)))
            return XChangeKeyboardMapping(self.display, first_keycode, keysyms_per_keycode, ckeysyms, num_codes)==0
        finally:
            free(ckeysyms)

    cdef list KeysymToKeycodes(self, KeySym keysym):
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

    cdef Dict _get_raw_keycode_mappings(self):
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
        mappings: dict[int, List[str]] = {}
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

    def get_keysym_mappings(self) -> Dict[int, List[int]]:
        """
            Maps keysyms to the keycodes that can be used to produce them
        """
        raw_mappings = self._get_raw_keycode_mappings()
        mappings = {}
        for keycode, keysyms in raw_mappings.items():
            for keysym in keysyms:
                mappings.setdefault(keysym, []).append(keycode)
        return mappings

    def get_keycode_mappings(self) -> Dict[int, List[str]]:
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

    def keysyms_to_strings(self, keysyms) -> List[str]:
        keynames = []
        for keysym in keysyms:
            key = ""
            if keysym!=NoSymbol:
                keyname = XKeysymToString(keysym)
                if keyname!=NULL:
                    key = s(keyname)
            keynames.append(key)
        # now remove trailing empty entries:
        while len(keynames)>0 and keynames[-1]=="":
            keynames = keynames[:-1]
        return keynames

    def get_keycodes(self, keyname: str) -> List[int]:
        codes = []
        cdef KeySym keysym = self._parse_keysym(keyname)
        if not keysym:
            return codes
        return self.KeysymToKeycodes(keysym)

    def parse_modifier(self, name) -> int:
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

    def modifier_name(self, modifier_index: int) -> str:
        return {
            0 : "shift",
            1 : "lock",
            2 : "control",
            3 : "mod1",
            4 : "mod2",
            5 : "mod3",
            6 : "mod4",
            7 : "mod5",
        }.get(modifier_index, "")

    cdef Tuple _get_raw_modifier_mappings(self):
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

    cdef Dict _get_modifier_mappings(self):
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
                kstr = s(keyname)
                if kstr not in keynames:
                    keynames.append((keycode, kstr))
            mappings[modifier] = keynames
        return mappings

    def get_modifier_mappings(self) -> Dict[str, List[str]]:
        return self._get_modifier_mappings()

    cdef void xmodmap_clearmodifier(self, int modifier):
        cdef XModifierKeymap* keymap = self.get_keymap(True)
        cdef KeyCode* keycode = <KeyCode*> keymap.modifiermap
        log("clear modifier: clearing all %i for modifier=%s", keymap.max_keypermod, modifier)
        for i in range(0, keymap.max_keypermod):
            keycode[modifier*keymap.max_keypermod+i] = 0

    cdef int xmodmap_addmodifier(self, int modifier, keysyms: Iterable[str]):
        self.context_check("xmodmap_addmodifier")
        cdef KeyCode keycode
        cdef KeySym keysym
        cdef XModifierKeymap* keymap = self.get_keymap(True)
        success = True
        log("add modifier: modifier %s=%s", modifier, keysyms)
        for keysym_str in keysyms:
            kss = b(keysym_str)
            keysym = XStringToKeysym(kss)
            keycodes = self.KeysymToKeycodes(keysym)
            log("add modifier: keysym(%s)=%s, keycodes(%s)=%s", keysym_str, keysym, keysym, keycodes)
            if len(keycodes)==0:
                log.error(f"Error: no keycodes found for keysym {keysym_str!r} ({keysym})")
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

    cdef List _get_keycodes_down(self):
        cdef char[32] keymap
        masktable: Sequence[int] = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
        down: list[int] = []
        XQueryKeymap(self.display, keymap)
        for i in range(0, 256):
            if keymap[i >> 3] & masktable[i & 7]:
                down.append(i)
        return down

    def get_keycodes_down(self) -> Dict[int, List[str]]:
        self.context_check("get_keycodes_down")
        if not self.hasXkb():
            {}
        cdef char* key
        cdef KeySym keysym
        cdef int group, level
        keycodes = self._get_keycodes_down()
        keys = {}
        def get_keysyms(keycode) -> List[str]:
            keysyms = []
            for group in (0, 1):
                for level in (0, 1):
                    keysym = XkbKeycodeToKeysym(self.display, keycode, group, level)
                    if keysym==NoSymbol:
                        continue
                    key = XKeysymToString(keysym)
                    if key!=NULL:
                        keysyms.append(s(key))
            return keysyms
        for keycode in keycodes:
            keys[keycode] = get_keysyms(keycode)
        return keys

    cdef list native_xmodmap(self, instructions: Iterable):
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
                    # line = ("keycode", keycode, [keysyms])
                    keycode = int(line[1])
                    keysyms = line[2]
                    if keycode==0:
                        # keycode=0 means "any", ie: 'keycode any = Shift_L'
                        assert len(keysyms)==1
                        new_keysyms.append(keysyms[0])
                        continue
                    elif keycode>0:
                        keycodes[keycode] = keysyms
                        continue
                elif cmd=="clear":
                    # ie: ("clear", 1)
                    modifier = line[1]
                    if modifier>=0:
                        self.xmodmap_clearmodifier(modifier)
                        continue
                elif cmd=="add":
                    # ie: ("add", "Control", ["Control_L", "Control_R"])
                    modifier = line[1]
                    keysyms = line[2]
                    if modifier>=0:
                        if self.xmodmap_addmodifier(modifier, keysyms):
                            continue
                log.error("Error applying xmodmap change: %s", csv(line))
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

    def set_xmodmap(self, xmodmap_data) -> List:
        log("set_xmodmap(%s)", xmodmap_data)
        return self.native_xmodmap(xmodmap_data)

    def grab_key(self, xwindow: Window, keycode: int, modifiers) -> None:
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

    def ungrab_all_keys(self) -> None:
        self.context_check("ungrab_all_keys")
        cdef Window root_window = XDefaultRootWindow(self.display)
        XUngrabKey(self.display, AnyKey, AnyModifier, root_window)

    def device_bell(self, Window xwindow, deviceSpec, bellClass, bellID: int, percent: int, name: str) -> Bool:
        self.context_check("device_bell")
        if not self.hasXkb():
            return
        cdef Atom name_atom = self.str_to_atom(name)
        # until (if ever) we replicate the same devices on the server,
        # use the default device:
        # deviceSpec = XkbUseCoreKbd
        # bellID = XkbDfltXIId
        return XkbDeviceBell(self.display, xwindow, XkbUseCoreKbd, bellClass, XkbDfltXIId,  percent, name_atom)

    def get_key_repeat_rate(self) -> Tuple[int, int]:
        if not self.hasXkb():
            return None
        cdef unsigned int deviceSpec = XkbUseCoreKbd
        cdef unsigned int delay = 0
        cdef unsigned int interval = 0
        if not XkbGetAutoRepeatRate(self.display, deviceSpec, &delay, &interval):
            return None
        return (delay, interval)

    def set_key_repeat_rate(self, delay: int, interval: int) -> bool:
        self.context_check("set_key_repeat_rate")
        if not self.hasXkb():
            log.warn("Warning: cannot set key repeat rate without Xkb support")
            return False
        cdef unsigned int deviceSpec = XkbUseCoreKbd
        cdef unsigned int cdelay = delay
        cdef unsigned int cinterval = interval
        return XkbSetAutoRepeatRate(self.display, deviceSpec, cdelay, cinterval)

    def selectBellNotification(self, on: bool) -> bool:
        self.context_check("selectBellNotification")
        if not self.hasXkb():
            log.warn("Warning: no system bell events without Xkb support")
            return
        cdef int bits = XkbBellNotifyMask
        if not on:
            bits = 0
        return XkbSelectEvents(self.display, XkbUseCoreKbd, XkbBellNotifyMask, bits)



cdef X11KeyboardBindingsInstance singleton = None


def X11KeyboardBindings() -> X11KeyboardBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11KeyboardBindingsInstance()
    return singleton
