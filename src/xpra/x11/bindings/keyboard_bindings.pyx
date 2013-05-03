# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.util import dump_exc, AdHocStruct
from xpra.log import Logger
log = Logger("xpra.x11.bindings.keyboard_bindings")


###################################
# Headers, python magic
###################################
cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from "X11/Xutil.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1


######
# Xlib primitives and constants
######

include "constants.pxi"
ctypedef unsigned long CARD32

cdef extern from "X11/X.h":
    unsigned long NoSymbol

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    # To make it easier to translate stuff in the X header files into
    # appropriate pyrex declarations, without having to untangle the typedefs
    # over and over again, here are some convenience typedefs.  (Yes, CARD32
    # really is 64 bits on 64-bit systems.  Why?  I have no idea.)
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef CARD32 Atom
    ctypedef XID Window
    ctypedef XID KeySym
    ctypedef CARD32 Time

    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height


    Atom XInternAtom(Display * display, char * atom_name, Bool only_if_exists)
    int XFree(void * data)
    void XGetErrorText(Display * display, int code, char * buffer_return, int length)

    Window XDefaultRootWindow(Display * display)

    # Keyboard bindings
    ctypedef unsigned char KeyCode
    ctypedef struct XModifierKeymap:
        int max_keypermod
        KeyCode * modifiermap # an array with 8*max_keypermod elements
    XModifierKeymap* XGetModifierMapping(Display* display)
    int XFreeModifiermap(XModifierKeymap* modifiermap)
    int XDisplayKeycodes(Display* display, int* min_keycodes, int* max_keycodes)
    KeySym XStringToKeysym(char* string)
    KeySym* XGetKeyboardMapping(Display* display, KeyCode first_keycode, int keycode_count, int* keysyms_per_keycode_return)
    int XChangeKeyboardMapping(Display* display, int first_keycode, int keysyms_per_keycode, KeySym* keysyms, int num_codes)
    XModifierKeymap* XInsertModifiermapEntry(XModifierKeymap* modifiermap, KeyCode keycode_entry, int modifier)
    KeySym XKeycodeToKeysym(Display* display, KeyCode keycode, int index)
    KeySym XStringToKeysym(char* string)
    char* XKeysymToString(KeySym keysym)

    int XChangeKeyboardMapping(Display* display, int first_keycode, int keysyms_per_keycode, KeySym* keysyms, int num_codes)
    int XSetModifierMapping(Display* display, XModifierKeymap* modifiermap)

    int XGrabKey(Display * display, int keycode, unsigned int modifiers,
                 Window grab_window, Bool owner_events,
                 int pointer_mode, int keyboard_mode)
    int XUngrabKey(Display * display, int keycode, unsigned int modifiers,
                   Window grab_window)
    int XQueryKeymap(Display * display, char [32] keys_return)



cdef extern from "X11/extensions/XKB.h":
    unsigned long XkbUseCoreKbd
    unsigned long XkbDfltXIId
    unsigned long XkbBellNotifyMask

cdef extern from "X11/XKBlib.h":
    KeySym XkbKeycodeToKeysym(Display *display, KeyCode kc, int group, int level)
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *eventBaseReturn, int *errorBaseReturn, int *majorRtrn, int *minorRtrn)
    Bool XkbSelectEvents(Display *, unsigned int deviceID, unsigned int affect, unsigned int values)
    Bool XkbDeviceBell(Display *, Window w, int deviceSpec, int bellClass, int bellID, int percent, Atom name)
    Bool XkbSetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int delay, unsigned int interval)
    Bool XkbGetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int *delayRtrn, unsigned int *intervalRtrn)


cdef extern from "X11/extensions/XTest.h":
    Bool XTestQueryExtension(Display *, int *, int *,
                             int * major, int * minor)
    int XTestFakeKeyEvent(Display *, unsigned int keycode,
                          Bool is_press, unsigned long delay)
    int XTestFakeButtonEvent(Display *, unsigned int button,
                             Bool is_press, unsigned long delay)


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





cdef argbdata_to_pixdata(unsigned long* data, len):
    if len <= 0:
        return None
    import array
    # Create byte array
    b = array.array('b', '\0'* len*4)
    cdef int offset = 0
    cdef int i = 0
    cdef unsigned long rgba
    cdef unsigned long argb
    cdef char b1, b2, b3, b4
    while i < len:
        argb = data[i] & 0xffffffff
        rgba = <unsigned long> ((argb << 8) | (argb >> 24)) & 0xffffffff
        b1 = (rgba >> 24) & 0xff
        b2 = (rgba >> 16) & 0xff
        b3 = (rgba >> 8) & 0xff
        b4 = rgba & 0xff
        b[offset] = b1
        b[offset+1] = b2
        b[offset+2] = b3
        b[offset+3] = b4
        offset = offset + 4
        i = i + 1
    return b




# xmodmap's "keycode" action done implemented in python
# some of the methods aren't very pythonic
# that's intentional so as to keep as close as possible
# to the original C xmodmap code


from core_bindings cimport X11CoreBindings


cdef class X11KeyboardBindings(X11CoreBindings):

    cdef XModifierKeymap* work_keymap
    cdef int min_keycode
    cdef int max_keycode
    cdef int xtest_supported

    def __init__(self):
        self.work_keymap = NULL
        self.min_keycode = -1
        self.max_keycode = -1
        self.xtest_supported = -1

    cdef _get_minmax_keycodes(self):
        if self.min_keycode==-1 and self.max_keycode==-1:
            XDisplayKeycodes(self.display, &self.min_keycode, &self.max_keycode)
        return self.min_keycode, self.max_keycode

    def get_modifier_map(self):
        cdef XModifierKeymap * xmodmap
        xmodmap = XGetModifierMapping(self.display)
        try:
            keycode_array = []
            for i in range(8 * xmodmap.max_keypermod):
                keycode_array.append(xmodmap.modifiermap[i])
            return (xmodmap.max_keypermod, keycode_array)
        finally:
            XFreeModifiermap(xmodmap)


    def get_minmax_keycodes(self):
        if self.min_keycode==-1 and self.max_keycode==-1:
            self._get_minmax_keycodes()
        return self.min_keycode, self.max_keycode

    cdef XModifierKeymap* get_keymap(self, load):
        if self.work_keymap==NULL and load:
            log.debug("retrieving keymap")
            self.work_keymap = XGetModifierMapping(self.display)
        return self.work_keymap

    cdef set_keymap(self, XModifierKeymap* new_keymap):
        log.debug("setting new keymap")
        self.work_keymap = new_keymap

    cdef _parse_keysym(self, symbol):
        cdef KeySym keysym
        if symbol in ["NoSymbol", "VoidSymbol"]:
            return  NoSymbol
        keysym = XStringToKeysym(symbol)
        if keysym==NoSymbol:
            if symbol.lower().startswith("0x"):
                return int(symbol, 16)
            if len(symbol)>0 and symbol[0] in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                return int(symbol)
            return  None
        return keysym

    def parse_keysym(self, symbol):
        return self._parse_keysym(symbol)

    cdef _keysym_str(self, keysym_val):
        cdef KeySym keysym                      #@DuplicatedSignature
        keysym = int(keysym_val)
        s = XKeysymToString(keysym)
        return s

    def keysym_str(self, keysym_val):
        return self._keysym_str(keysym_val)
    
    def get_keysym_list(self, symbols):
        """ convert a list of key symbols into a list of KeySym values
            by calling parse_keysym on each one
        """
        keysymlist = []
        for x in symbols:
            keysym = self._parse_keysym(x)
            if keysym is not None:
                keysymlist.append(keysym)
        return keysymlist
    
    cdef _parse_keycode(self, keycode_str):
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
            log.error("keycode %s: value %s is out of range (%s-%s)", keycode_str, keycode, min_keycode, max_keycode)
            return -1
        return keycode

    def parse_keycode(self, keycode_str):
        return self._parse_keycode(keycode_str)

    cdef xmodmap_setkeycodes(self, keycodes, new_keysyms):
        cdef KeySym keysym                      #@DuplicatedSignature
        cdef KeySym* ckeysyms
        cdef int num_codes
        cdef int keysyms_per_keycode
        cdef first_keycode
        first_keycode = min(keycodes.keys())
        last_keycode = max(keycodes.keys())
        num_codes = 1+last_keycode-first_keycode
        MAX_KEYSYMS_PER_KEYCODE = 8
        keysyms_per_keycode = min(MAX_KEYSYMS_PER_KEYCODE, max([1]+[len(keysyms) for keysyms in keycodes.values()]))
        log.debug("xmodmap_setkeycodes using %s keysyms_per_keycode", keysyms_per_keycode)
        ckeysyms = <KeySym*> malloc(sizeof(KeySym)*num_codes*keysyms_per_keycode)
        try:
            missing_keysyms = []
            for i in range(0, num_codes):
                keycode = first_keycode+i
                keysyms_strs = keycodes.get(keycode)
                log.debug("setting keycode %s: %s", keycode, keysyms_strs)
                if keysyms_strs is None:
                    if len(new_keysyms)>0:
                        #no keysyms for this keycode yet, assign one of the "new_keysyms"
                        keysyms = new_keysyms[:1]
                        new_keysyms = new_keysyms[1:]
                        log.debug("assigned keycode %s to %s", keycode, keysyms[0])
                    else:
                        keysyms = []
                        log.debug("keycode %s is still free", keycode)
                else:
                    keysyms = []
                    for ks in keysyms_strs:
                        if ks in (None, ""):
                            k = None
                        elif type(ks) in [long, int]:
                            k = ks
                        else:
                            k = self.parse_keysym(ks)
                        if k is not None:
                            keysyms.append(k)
                        else:
                            keysyms.append(NoSymbol)
                            if ks is not None:
                                missing_keysyms.append(str(ks))
                for j in range(0, keysyms_per_keycode):
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
        cdef int keysyms_per_keycode                    #@DuplicatedSignature
        cdef XModifierKeymap* keymap
        cdef KeySym * keyboard_map
        cdef KeySym keysym                              #@DuplicatedSignature
        cdef KeyCode keycode
        min_keycode,max_keycode = self._get_minmax_keycodes()
        keyboard_map = XGetKeyboardMapping(self.display, min_keycode, max_keycode - min_keycode + 1, &keysyms_per_keycode)
        log.debug("XGetKeyboardMapping keysyms_per_keycode=%s", keysyms_per_keycode)
        mappings = {}
        i = 0
        keycode = min_keycode
        while keycode<max_keycode:
            keysyms = []
            for keysym_index in range(0, keysyms_per_keycode):
                keysym = keyboard_map[i*keysyms_per_keycode + keysym_index]
                keysyms.append(keysym)
            mappings[keycode] = keysyms
            i += 1
            keycode += 1
        XFree(keyboard_map)
        return mappings

    def get_keycode_mappings(self):
        """
        the mappings from _get_raw_keycode_mappings are in raw format
        (keysyms as numbers), so here we convert into names:
        """
        cdef Display * display                          #@DuplicatedSignature
        cdef KeySym keysym                              #@DuplicatedSignature
        cdef char* keyname
        raw_mappings = self._get_raw_keycode_mappings()
        mappings = {}
        for keycode, keysyms in raw_mappings.items():
            keynames = []
            for keysym in keysyms:
                key = ""
                if keysym!=NoSymbol:
                    keyname = XKeysymToString(keysym)
                    if keyname!=NULL:
                        key = str(keyname)
                keynames.append(key)
            #now remove trailing empty entries:
            while len(keynames)>0 and keynames[-1]=="":
                keynames = keynames[:-1]
            if len(keynames)>0:
                mappings[keycode] = keynames
        return mappings
    

    def get_keycodes(self, keyname):
        codes = []
        keysym = self._parse_keysym(keyname)
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
        cdef int keysyms_per_keycode                    #@DuplicatedSignature
        cdef XModifierKeymap* keymap                    #@DuplicatedSignature
        cdef KeySym * keyboard_map                      #@DuplicatedSignature
        cdef KeySym keysym                              #@DuplicatedSignature
        cdef KeyCode keycode                            #@DuplicatedSignature
        min_keycode,max_keycode = self._get_minmax_keycodes()
        keyboard_map = XGetKeyboardMapping(self.display, min_keycode, max_keycode - min_keycode + 1, &keysyms_per_keycode)
        mappings = {}
        i = 0
        keymap = self.get_keymap(False)
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
        self.set_keymap(NULL)
        XFree(keyboard_map)
        return (keysyms_per_keycode, mappings)
    
    cdef _get_modifier_mappings(self):
        """
        the mappings from _get_raw_modifier_mappings are in raw format
        (index and keycode), so here we convert into names:
        """
        cdef KeySym keysym                      #@DuplicatedSignature
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
                    log.info("no keysym found for keycode %s", keycode)
                    continue
                keyname = XKeysymToString(keysym)
                if keyname not in keynames:
                    keynames.append((keycode, keyname))
            mappings[modifier] = keynames
        return mappings

    def get_modifier_mappings(self):
        return self._get_modifier_mappings()

    cdef xmodmap_clearmodifier(self, int modifier):
        cdef KeyCode* keycode
        cdef XModifierKeymap* keymap                    #@DuplicatedSignature
        keymap = self.get_keymap(True)
        keycode = <KeyCode*> keymap.modifiermap
        log.debug("clear modifier: clearing all %s for modifier=%s", keymap.max_keypermod, modifier)
        for i in range(0, keymap.max_keypermod):
            keycode[modifier*keymap.max_keypermod+i] = 0

    cdef xmodmap_addmodifier(self, int modifier, keysyms):
        cdef XModifierKeymap* keymap                    #@DuplicatedSignature
        cdef KeyCode keycode                            #@DuplicatedSignature
        cdef KeySym keysym                              #@DuplicatedSignature
        keymap = self.get_keymap(True)
        success = True
        log.debug("add modifier: modifier %s=%s", modifier, keysyms)
        for keysym_str in keysyms:
            keysym = XStringToKeysym(keysym_str)
            log.debug("add modifier: keysym(%s)=%s", keysym_str, keysym)
            keycodes = self.KeysymToKeycodes(keysym)
            log.debug("add modifier: keycodes(%s)=%s", keysym, keycodes)
            if len(keycodes)==0:
                log.error("xmodmap_exec_add: no keycodes found for keysym %s/%s", keysym_str, keysym)
                success = False
            else:
                for k in keycodes:
                    if k!=0:
                        keycode = k
                        keymap = XInsertModifiermapEntry(keymap, keycode, modifier)
                        if keymap!=NULL:
                            self.set_keymap(keymap)
                            log.debug("add modifier: added keycode=%s for modifier %s and keysym=%s", k, modifier, keysym_str)
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
        cdef Display * display                          #@DuplicatedSignature
        cdef char* key
        keycodes = self._get_keycodes_down()
        keys = {}
        for keycode in keycodes:
            keysym = XkbKeycodeToKeysym(self.display, keycode, 0, 0)
            key = XKeysymToString(keysym)
            keys[keycode] = str(key)
        return keys

    def unpress_all_keys(self):
        keycodes = self._get_keycodes_down()
        for keycode in keycodes:
            XTestFakeKeyEvent(self.display, keycode, False, 0)

    cdef native_xmodmap(self, instructions):
        cdef XModifierKeymap* keymap                    #@DuplicatedSignature
        cdef int modifier
        self.set_keymap(NULL)
        unhandled = []
        map = None
        keycodes = {}
        new_keysyms = []
        try:
            for line in instructions:
                log.debug("processing: %s", line)
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
                log.debug("calling xmodmap_setkeycodes with %s", keycodes)
                self.xmodmap_setkeycodes(keycodes, new_keysyms)
        finally:
            keymap = self.get_keymap(False)
            if keymap!=NULL:
                self.set_keymap(NULL)
                log.debug("saving modified keymap")
                if XSetModifierMapping(self.display, keymap)==MappingBusy:
                    log.error("cannot change keymap: mapping busy: %s" % self.get_keycodes_down())
                    unhandled = instructions
                XFreeModifiermap(keymap)
        log.debug("modify keymap: %s instructions, %s unprocessed", len(instructions), len(unhandled))
        return unhandled

    def set_xmodmap(self, xmodmap_data):
        return self.native_xmodmap(xmodmap_data)
    
    def grab_key(self, xwindow, keycode, modifiers):
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
        cdef Window root_window
        root_window = XDefaultRootWindow(self.display)
        XUngrabKey(self.display, AnyKey, AnyModifier, root_window)


    cdef get_xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        cdef char* string
        if isinstance(str_or_int, (int, long)):
            return <Atom> str_or_int
        string = str_or_int
        return XInternAtom(self.display, string, False)

    def device_bell(self, xwindow, deviceSpec, bellClass, bellID, percent, name):
        name_atom = self.get_xatom(name)
        #until (if ever) we replicate the same devices on the server,
        #use the default device:
        deviceSpec = XkbUseCoreKbd
        bellID = XkbDfltXIId
        return XkbDeviceBell(self.display, xwindow, deviceSpec, bellClass, bellID,  percent, name_atom)




    def _ensure_XTest_support(self):
        cdef int ignored = 0
        if self.xtest_supported==-1:
            try:
                XTestQueryExtension(self.display, &ignored, &ignored, &ignored, &ignored)
                self.xtest_supported = 1
            except:
                self.xtest_supported = 0
        assert self.xtest_supported==1
    
    def xtest_fake_key(self, keycode, is_press):
        self._ensure_XTest_support()
        XTestFakeKeyEvent(self.display, keycode, is_press, 0)
    
    def xtest_fake_button(self, button, is_press):
        self._ensure_XTest_support()
        XTestFakeButtonEvent(self.display, button, is_press, 0)




    def get_key_repeat_rate(self):
        cdef unsigned int deviceSpec = XkbUseCoreKbd
        cdef unsigned int delay = 0
        cdef unsigned int interval = 0
        if not XkbGetAutoRepeatRate(self.display, deviceSpec, &delay, &interval):
            return None
        return (delay, interval)

    def set_key_repeat_rate(self, delay, interval):
        cdef unsigned int deviceSpec = XkbUseCoreKbd    #@DuplicatedSignature
        cdef unsigned int cdelay = delay
        cdef unsigned int cinterval = interval
        return XkbSetAutoRepeatRate(self.display, deviceSpec, cdelay, cinterval)


    
    def get_cursor_image(self):
        cdef XFixesCursorImage* image
        #cdef char* pixels
        try:
            image = XFixesGetCursorImage(self.display)
            if image==NULL:
                return  None
            l = image.width*image.height
            pixels = argbdata_to_pixdata(image.pixels, l)
            name = str(image.name)
            return [image.x, image.y, image.width, image.height, image.xhot, image.yhot,
                image.cursor_serial, pixels, name]
        finally:
            XFree(image)
    
    def get_XFixes_event_base(self):
        cdef int event_base = 0                             #@DuplicatedSignature
        cdef int error_base = 0                             #@DuplicatedSignature
        XFixesQueryExtension(self.display, &event_base, &error_base)
        return int(event_base)
    
    def selectCursorChange(self, on):
        root_window = XDefaultRootWindow(self.display)
        if on:
            v = XFixesDisplayCursorNotifyMask
        else:
            v = 0
        XFixesSelectCursorInput(self.display, root_window, v)
    

    def selectBellNotification(self, on):
        cdef int bits = XkbBellNotifyMask
        if not on:
            bits = 0
        XkbSelectEvents(self.display, XkbUseCoreKbd, XkbBellNotifyMask, bits)
