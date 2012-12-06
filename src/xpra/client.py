# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()

#for the cursor stuff, we need both cursor_names and trap
from xpra.cursor_names import cursor_names
from wimpiggy.error import trap
if is_gtk3():
    def get_root_size():
        return gdk.get_default_root_window().get_geometry()[2:]
    def set_windows_cursor(gtkwindows, new_cursor):
        pass
        #window.override_cursor(cursor, None)
else:
    def get_root_size():
        return gdk.get_default_root_window().get_size()
    def set_windows_cursor(gtkwindows, new_cursor):
        cursor = None
        if len(new_cursor)>0:
            cursor = None
            if len(new_cursor)>=9 and cursor_names:
                cursor_name = new_cursor[8]
                if cursor_name:
                    gdk_cursor = cursor_names.get(cursor_name.upper())
                    if gdk_cursor is not None:
                        try:
                            log("setting new cursor: %s=%s", cursor_name, gdk_cursor)
                            cursor = trap.call(gdk.Cursor, gdk_cursor)
                        except:
                            pass
            if cursor is None:
                w, h, xhot, yhot, serial, pixels = new_cursor[2:8]
                log("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s" % (xhot,yhot, serial, w,h, len(pixels)))
                pixbuf = gdk.pixbuf_new_from_data(pixels, gdk.COLORSPACE_RGB, True, 8, w, h, w * 4)
                x = max(0, min(xhot, w-1))
                y = max(0, min(yhot, h-1))
                size = gdk.display_get_default().get_default_cursor_size()
                if size>0 and (size<w or size<h):
                    ratio = float(max(w,h))/size
                    pixbuf = pixbuf.scale_simple(int(w/ratio), int(h/ratio), gdk.INTERP_BILINEAR)
                    x = int(x/ratio)
                    y = int(y/ratio)
                cursor = gdk.Cursor(gdk.display_get_default(), pixbuf, x, y)
        for gtkwindow in gtkwindows:
            gdkwin = gtkwindow.get_window()
            #trays don't have a gdk window
            if gdkwin:
                gdkwin.set_cursor(cursor)

import sys
import uuid
import os
import time
import ctypes
from threading import Thread
try:
    from queue import Queue     #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue     #@Reimport


from wimpiggy.util import (n_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.client_base import XpraClientBase, EXIT_TIMEOUT
from xpra.keys import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE, DEFAULT_MODIFIER_IGNORE_KEYNAMES
from xpra.platform.gui import ClientExtras
from xpra.scripts.main import ENCODINGS
from xpra.version_util import add_gtk_version_info
from xpra.maths import std_unit
from xpra.protocol import Compressed

from xpra.client_window import ClientWindow
USE_OPENGL = os.environ.get("XPRA_OPENGL", "0")=="1"
GLClientWindowClass = None
#the GL backend only works with gtk2:
if USE_OPENGL and not is_gtk3():
    try:
        from xpra.gl_client_window import GLClientWindow
        GLClientWindowClass = GLClientWindow
    except ImportError, e:
        log.warn("Disabled OpenGL output: %s" % e)
        USE_OPENGL = False

def nn(x):
    if x is None:
        return  ""
    return x



class XpraClient(XpraClientBase):
    __gsignals__ = {
        "clipboard-toggled": n_arg_signal(0),
        "keyboard-sync-toggled": n_arg_signal(0),
        }

    def __init__(self, conn, opts):
        XpraClientBase.__init__(self, opts)
        self.start_time = time.time()
        self._window_to_id = {}
        self._id_to_window = {}
        self._ui_events = 0
        self.title = opts.title
        self.session_name = opts.session_name
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.max_bandwidth = opts.max_bandwidth
        if self.max_bandwidth>0.0 and self.quality==0:
            """ quality was not set, use a better start value """
            self.quality = 80
        self.dpi = int(opts.dpi)

        #draw thread:
        self._draw_queue = Queue()
        self._draw_thread = Thread(target=self._draw_thread_loop, name="draw_loop")
        self._draw_thread.setDaemon(True)
        self._draw_thread.start()

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.pixel_counter = maxdeque(maxlen=100)
        self.server_ping_latency = maxdeque(maxlen=100)
        self.server_load = None
        self.client_ping_latency = maxdeque(maxlen=100)
        self.last_ping_echoed_time = 0

        #sound:
        self.speaker_enabled = bool(opts.speaker)
        self.microphone_enabled = bool(opts.microphone)
        self.speaker_codecs = opts.speaker_codec
        self.microphone_codecs = opts.microphone_codec
        self.sound_sink = None
        self.sound_source = None
        self.server_pulseaudio_id = None
        self.server_pulseaudio_server = None
        self.server_sound_decoders = []
        self.server_sound_encoders = []
        self.server_sound_receive = False
        self.server_sound_send = False

        #features:
        self.toggle_cursors_bell_notify = False
        self.toggle_keyboard_sync = False
        self.window_configure = False
        self.change_quality = False
        self.readonly = opts.readonly
        self.windows_enabled = opts.windows_enabled
        self._client_extras = ClientExtras(self, opts, conn)
        self.client_supports_notifications = opts.notifications and self._client_extras.can_notify()
        self.client_supports_system_tray = opts.system_tray and self._client_extras.supports_system_tray()
        self.client_supports_clipboard = opts.clipboard and self._client_extras.supports_clipboard() and not self.readonly
        self.client_supports_cursors = opts.cursors
        self.client_supports_bell = opts.bell
        self.client_supports_sharing = opts.sharing
        self.notifications_enabled = self.client_supports_notifications
        self.clipboard_enabled = self.client_supports_clipboard
        self.cursors_enabled = self.client_supports_cursors
        self.bell_enabled = self.client_supports_bell

        #mmap:
        self.mmap_enabled = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_file = None
        self.mmap_size = 0
        self.supports_mmap = opts.mmap and ("rgb24" in ENCODINGS) and self._client_extras.supports_mmap()
        if self.supports_mmap:
            self.init_mmap(opts.mmap_group, conn.filename)

        self.init_packet_handlers()
        self.ready(conn)

        #keyboard:
        self.keyboard_sync = opts.keyboard_sync
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.keys_pressed = {}
        self._remote_version = None
        self._keymap_changing = False
        try:
            self._keymap = gdk.keymap_get_default()
        except:
            self._keymap = None
        self._do_keys_changed()
        self.key_shortcuts = self.parse_shortcuts(opts.key_shortcuts)
        self.send_hello()

        if self._keymap:
            self._keymap.connect("keys-changed", self._keys_changed)

        self._focused = None
        def compute_receive_bandwidth(delay):
            bytecount = conn.input_bytecount
            bw = ((bytecount - self.last_input_bytecount) / 1024) * 1000 / delay
            self.last_input_bytecount = bytecount;
            log.debug("Bandwidth is ", bw, "kB/s, max ", self.max_bandwidth, "kB/s")
            q = self.quality
            if bw > self.max_bandwidth:
                q -= 10
            elif bw < self.max_bandwidth:
                q += 5
            q = max(10, min(95 ,q))
            self.send_quality(q)
            return True
        if (self.max_bandwidth):
            self.last_input_bytecount = 0
            gobject.timeout_add(2000, compute_receive_bandwidth, 2000)
        if opts.send_pings:
            gobject.timeout_add(1000, self.send_ping)
        else:
            gobject.timeout_add(20*1000, self.send_ping)

    def init_mmap(self, mmap_group, socket_filename):
        log("init_mmap(%s, %s)", mmap_group, socket_filename)
        try:
            import mmap
            import tempfile
            from stat import S_IRUSR,S_IWUSR,S_IRGRP,S_IWGRP
            mmap_dir = os.getenv("TMPDIR", "/tmp")
            if not os.path.exists(mmap_dir):
                raise Exception("TMPDIR %s does not exist!" % mmap_dir)
            #create the mmap file, the mkstemp that is called via NamedTemporaryFile ensures
            #that the file is readable and writable only by the creating user ID
            temp = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".mmap", dir=mmap_dir)
            #keep a reference to it so it does not disappear!
            self._mmap_temp_file = temp
            self.mmap_file = temp.name
            fd = temp.file.fileno()
            #set the group permissions and gid if the mmap-group option is specified
            if mmap_group and type(socket_filename)==str and os.path.exists(socket_filename):
                s = os.stat(socket_filename)
                os.fchown(fd, -1, s.st_gid)
                os.fchmod(fd, S_IRUSR|S_IWUSR|S_IRGRP|S_IWGRP)
            self.mmap_size = max(4096, mmap.PAGESIZE)*32*1024   #generally 128MB
            log("using mmap file %s, fd=%s, size=%s", self.mmap_file, fd, self.mmap_size)
            os.lseek(fd, self.mmap_size-1, os.SEEK_SET)
            assert os.write(fd, '\x00')
            os.lseek(fd, 0, os.SEEK_SET)
            self.mmap = mmap.mmap(fd, length=self.mmap_size)
            #write the 16 byte token one byte at a time - no endianness
            self.mmap_token = uuid.uuid4().int
            log.debug("mmap_token=%s", self.mmap_token)
            v = self.mmap_token
            for i in range(0,16):
                poke = ctypes.c_ubyte.from_buffer(self.mmap, 512+i)
                poke.value = v % 256
                v = v>>8
            assert v==0
        except Exception, e:
            log.error("failed to setup mmap: %s", e)
            self.supports_mmap = False
            self.clean_mmap()
            self.mmap = None
            self.mmap_file = None
            self.mmap_size = 0

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        for k,v in {
            "hello":                self._process_hello,
            "new-window":           self._process_new_window,
            "new-override-redirect":self._process_new_override_redirect,
            "new-tray":             self._process_new_tray,
            "window-resized":       self._process_window_resized,
            "cursor":               self._process_cursor,
            "bell":                 self._process_bell,
            "notify_show":          self._process_notify_show,
            "notify_close":         self._process_notify_close,
            "window-metadata":      self._process_window_metadata,
            "configure-override-redirect":  self._process_configure_override_redirect,
            "lost-window":          self._process_lost_window,
            "desktop_size":         self._process_desktop_size,
            "window-icon":          self._process_window_icon,
            "sound-data":           self._process_sound_data,
            # "clipboard-*" packets are handled by a special case below.
            }.items():
            self._ui_packet_handlers[k] = v
        #these handlers can run directly from the network thread:
        for k,v in {
            "draw":                 self._process_draw,
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            }.items():
            self._packet_handlers[k] = v

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()
        return  self.exit_code

    def quit(self, exit_code=0):
        if self.exit_code is None:
            self.exit_code = exit_code
        self.cleanup()
        gobject.timeout_add(50, gtk_main_quit_really)

    def cleanup(self):
        if self._client_extras:
            self._client_extras.cleanup()
        XpraClientBase.cleanup(self)
        self.clean_mmap()

    def clean_mmap(self):
        if self.mmap_file and os.path.exists(self.mmap_file):
            os.unlink(self.mmap_file)
            self.mmap_file = None

    def parse_shortcuts(self, strs):
        #TODO: maybe parse with re instead?
        if len(strs)==0:
            """ if none are defined, add this as default
            it would be nicer to specify it via OptionParser in main
            but then it would always have to be there with no way of removing it
            whereas now it is enough to define one (any shortcut)
            """
            strs = ["meta+shift+F4:quit"]
        log.debug("parse_shortcuts(%s)" % str(strs))
        shortcuts = {}
        #modifier names contains the internal modifiers list, ie: "mod1", "control", ...
        #but the user expects the name of the key to be used, ie: "alt" or "super"
        #whereas at best, we keep "Alt_L" : "mod1" mappings... (xposix)
        #so generate a map from one to the other:
        modifier_names = {}
        meanings = self.xkbmap_mod_meanings or DEFAULT_MODIFIER_MEANINGS
        for pub_name,mod_name in meanings.items():
            if mod_name in DEFAULT_MODIFIER_NUISANCE or pub_name in DEFAULT_MODIFIER_IGNORE_KEYNAMES:
                continue
            #just hope that xxx_L is mapped to the same modifier as xxx_R!
            if pub_name.endswith("_L") or pub_name.endswith("_R"):
                pub_name = pub_name[:-2]
            elif pub_name=="ISO_Level3_Shift":
                pub_name = "AltGr"
            if pub_name not in modifier_names:
                modifier_names[pub_name.lower()] = mod_name

        for s in strs:
            #example for s: Control+F8:some_action()
            parts = s.split(":", 1)
            if len(parts)!=2:
                log.error("invalid shortcut: %s" % s)
                continue
            #example for action: "quit"
            action = parts[1]
            #example for keyspec: ["Alt", "F8"]
            keyspec = parts[0].split("+")
            modifiers = []
            if len(keyspec)>1:
                valid = True
                #ie: ["Alt"]
                for mod in keyspec[:len(keyspec)-1]:
                    #ie: "alt_l" -> "mod1"
                    imod = modifier_names.get(mod.lower())
                    if not imod:
                        log.error("invalid modifier: %s, valid modifiers are: %s", mod, modifier_names.keys())
                        valid = False
                        break
                    modifiers.append(imod)
                if not valid:
                    continue
            keyname = keyspec[len(keyspec)-1]
            shortcuts[keyname] = (modifiers, action)
        log.debug("parse_shortcuts(%s)=%s" % (str(strs), shortcuts))
        return  shortcuts

    def key_handled_as_shortcut(self, window, key_name, modifiers, depressed):
        shortcut = self.key_shortcuts.get(key_name)
        if not shortcut:
            return  False
        (req_mods, action) = shortcut
        for rm in req_mods:
            if rm not in modifiers:
                #modifier is missing, bail out
                return False
        if not depressed:
            """ when the key is released, just ignore it - do NOT send it to the server! """
            return  True
        try:
            method = getattr(window, action)
            log.info("key_handled_as_shortcut(%s,%s,%s,%s) has been handled by shortcut=%s", window, key_name, modifiers, depressed, shortcut)
        except AttributeError, e:
            log.error("key dropped, invalid method name in shortcut %s: %s", action, e)
            return  True
        try:
            method()
        except Exception, e:
            log.error("key_handled_as_shortcut(%s,%s,%s,%s) failed to execute shortcut=%s: %s", window, key_name, modifiers, depressed, shortcut, e)
        return  True

    def handle_key_action(self, event, window, pressed):
        if self.readonly:
            return
        #NOTE: handle_key_event may fire send_key_action more than once (see win32 AltGr)
        wid = self._window_to_id[window]
        self._client_extras.handle_key_event(self.send_key_action, event, wid, pressed)

    def send_key_action(self, wid, keyname, pressed, modifiers, keyval, string, keycode, group, is_modifier):
        window = self._id_to_window[wid]
        if self.key_handled_as_shortcut(window, keyname, modifiers, pressed):
            return
        log("send_key_action(%s, %s, %s, %s, %s, %s, %s, %s, %s)", wid, keyname, pressed, modifiers, keyval, string, keycode, group, is_modifier)
        self.send("key-action", wid, nn(keyname), pressed, modifiers, nn(keyval), string, nn(keycode), group, is_modifier)
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, pressed, keyname, keyval, keycode)

    def _key_repeat(self, wid, depressed, name, keyval, keycode):
        """ this method takes care of scheduling the sending of
            "key-repeat" packets to the server so that it can
            maintain a consistent keyboard state.
        """
        #we keep track of which keys are still pressed in a dict,
        if keycode<0:
            key = name
        else:
            key = keycode
        if not depressed and key in self.keys_pressed:
            """ stop the timer and clear this keycode: """
            log.debug("key repeat: clearing timer for %s / %s", name, keycode)
            gobject.source_remove(self.keys_pressed[key])
            del self.keys_pressed[key]
        elif depressed and key not in self.keys_pressed:
            """ we must ping the server regularly for as long as the key is still pressed: """
            #TODO: we can have latency measurements (see ping).. use them?
            LATENCY_JITTER = 100
            MIN_DELAY = 5
            delay = max(self.key_repeat_delay-LATENCY_JITTER, MIN_DELAY)
            interval = max(self.key_repeat_interval-LATENCY_JITTER, MIN_DELAY)
            log.debug("scheduling key repeat for %s: delay=%s, interval=%s (from %s and %s)", name, delay, interval, self.key_repeat_delay, self.key_repeat_interval)
            def send_key_repeat():
                modifiers = self.get_current_modifiers()
                self.send_now("key-repeat", wid, name, keyval, keycode, modifiers)
            def continue_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and continue, otherwise stop
                log.debug("continue_key_repeat for %s / %s", name, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    return  True
                else:
                    del self.keys_pressed[key]
                    return  False
            def start_key_repeat(*args):
                #if the key is still pressed (redundant check?)
                #confirm it and start repeat:
                log.debug("start_key_repeat for %s / %s", name, keycode)
                if key in self.keys_pressed:
                    send_key_repeat()
                    self.keys_pressed[key] = gobject.timeout_add(interval, continue_key_repeat)
                else:
                    del self.keys_pressed[key]
                return  False   #never run this timer again
            log.debug("key repeat: starting timer for %s / %s with delay %s and interval %s", name, keycode, delay, interval)
            self.keys_pressed[key] = gobject.timeout_add(delay, start_key_repeat)

    def clear_repeat(self):
        for timer in self.keys_pressed.values():
            gobject.source_remove(timer)
        self.keys_pressed = {}

    def query_xkbmap(self):
        if self.readonly:
            self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_variants = "", "", []
            self.xkbmap_print, self.xkbmap_query = "", ""
        else:
            self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_variants = self._client_extras.get_layout_spec()
            self.xkbmap_print, self.xkbmap_query = self._client_extras.get_keymap_spec()
        self.xkbmap_keycodes = self._client_extras.get_gtk_keymap()
        self.xkbmap_x11_keycodes = self._client_extras.get_x11_keymap()
        self.xkbmap_mod_meanings, self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing = self._client_extras.get_keymap_modifiers()
        log.debug("layout=%s, variant=%s", self.xkbmap_layout, self.xkbmap_variant)
        log.debug("print=%s, query=%s", self.xkbmap_print, self.xkbmap_query)
        log.debug("keycodes=%s", str(self.xkbmap_keycodes)[:80]+"...")
        log.debug("x11 keycodes=%s", str(self.xkbmap_x11_keycodes)[:80]+"...")
        log.debug("xkbmap_mod_meanings: %s", self.xkbmap_mod_meanings)

    def _keys_changed(self, *args):
        log.debug("keys_changed")
        self._keymap = gdk.keymap_get_default()
        if not self._keymap_changing:
            self._keymap_changing = True
            gobject.timeout_add(500, self._do_keys_changed, True)

    def _do_keys_changed(self, sendkeymap=False):
        self._keymap_changing = False
        self.query_xkbmap()
        try:
            self._modifier_map = self._client_extras.grok_modifier_map(gdk.display_get_default(), self.xkbmap_mod_meanings)
        except:
            self._modifier_map = {}
        log.debug("do_keys_changed() modifier_map=%s" % self._modifier_map)
        if sendkeymap and not self.readonly:
            if self.xkbmap_layout:
                self.send_layout()
            self.send_keymap()

    def send_layout(self):
        self.send("layout-changed", nn(self.xkbmap_layout), nn(self.xkbmap_variant))

    def send_keymap(self):
        self.send("keymap-changed", self.get_keymap_properties())

    def get_keymap_properties(self):
        props = {"modifiers" : self.get_current_modifiers()}
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
              "xkbmap_mod_managed", "xkbmap_mod_pointermissing", "xkbmap_keycodes", "xkbmap_x11_keycodes"]:
            props[x] = nn(getattr(self, x))
        return  props

    def send_focus(self, wid):
        self.send("focus", wid, self.get_current_modifiers())

    def update_focus(self, wid, gotit):
        log("update_focus(%s,%s) _focused=%s", wid, gotit, self._focused)
        if gotit and self._focused is not wid:
            self.clear_repeat()
            self.send_focus(wid)
            self._focused = wid
        if not gotit and self._focused is wid:
            self.clear_repeat()
            self.send_focus(0)
            self._focused = None

    def get_current_modifiers(self):
        modifiers_mask = gdk.get_default_root_window().get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)

    def mask_to_names(self, mask):
        if self._client_extras is None:
            return []
        return self._client_extras.mask_to_names(mask)

    def send_positional(self, packet):
        p = self._protocol
        if p is not None:
            s = p.source
            if s:
                s.queue_positional_packet(packet)

    def send_mouse_position(self, packet):
        p = self._protocol
        if p is not None:
            s = p.source
            if s:
                s.queue_mouse_position_packet(packet)

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        add_gtk_version_info(capabilities, gtk)
        for k,v in self.get_keymap_properties().items():
            capabilities[k] = v
        if self.readonly:
            #don't bother sending keyboard info, as it won't be used
            capabilities["keyboard"] = False
        else:
            capabilities["xkbmap_layout"] = nn(self.xkbmap_layout)
            capabilities["xkbmap_variant"] = nn(self.xkbmap_variant)
        capabilities["modifiers"] = self.get_current_modifiers()
        root_w, root_h = get_root_size()
        capabilities["desktop_size"] = [root_w, root_h]
        capabilities["screen_sizes"] = self.get_screen_sizes()
        capabilities["client_type"] = "Python/Gtk"
        key_repeat = self._client_extras.get_keyboard_repeat()
        if key_repeat:
            delay_ms,interval_ms = key_repeat
            capabilities["key_repeat"] = (delay_ms,interval_ms)
        capabilities["keyboard_sync"] = self.keyboard_sync and (key_repeat is not None)
        if self.mmap_file:
            capabilities["mmap_file"] = self.mmap_file
            capabilities["mmap_token"] = self.mmap_token
        capabilities["randr_notify"] = True
        capabilities["compressible_cursors"] = True
        capabilities["dpi"] = self.dpi
        capabilities["clipboard"] = self.client_supports_clipboard
        capabilities["notifications"] = self.client_supports_notifications
        capabilities["cursors"] = self.client_supports_cursors
        capabilities["bell"] = self.client_supports_bell
        capabilities["encoding_client_options"] = True
        capabilities["rgb24zlib"] = True
        capabilities["named_cursors"] = len(cursor_names)>0
        capabilities["share"] = self.client_supports_sharing
        capabilities["auto_refresh_delay"] = int(self.auto_refresh_delay*1000)
        capabilities["windows"] = self.windows_enabled
        capabilities["raw_window_icons"] = True
        capabilities["system_tray"] = self.client_supports_system_tray
        capabilities["xsettings-tuple"] = True
        capabilities["uses_swscale"] = not USE_OPENGL
        if "x264" in ENCODINGS:
            # some profile options: "baseline", "main", "high", "high10", ...
            # set the default to "high" for i420 as the python client always supports all the profiles
            # whereas on the server side, the default is baseline to accomodate less capable clients.
            for csc_mode, default_profile in {"I420" : "high",
                                              "I422" : "",
                                              "I444" : ""}.items():
                profile = os.environ.get("XPRA_X264_%s_PROFILE" % csc_mode, default_profile)
                if profile:
                    capabilities["encoding.x264.%s.profile" % csc_mode] = profile
            for csc_mode in ("I422", "I444"):
                min_quality = os.environ.get("XPRA_X264_%s_MIN_QUALITY" % csc_mode)
                if min_quality:
                    capabilities["encoding.x264.%s.min_quality" % csc_mode] = int(min_quality)
            log("x264 encoding options: %s", str([(k,v) for k,v in capabilities.items() if k.startswith("encoding.x264.")]))
        capabilities["encoding.initial_quality"] = 70
        try:
            import xpra.sound
            try:
                assert xpra.sound
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                from xpra.sound.gstreamer_util import add_gst_capabilities
                add_gst_capabilities(capabilities, receive=True, send=True,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs)
                log("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e)
        except ImportError, e:
            log("sound modules were not included in this installation")
        return capabilities

    def send_ping(self):
        now_ms = int(1000*time.time())
        self.send("ping", now_ms)
        wait = 60
        def check_echo_received(*args):
            if self.last_ping_echoed_time<now_ms:
                self.warn_and_quit(EXIT_TIMEOUT, "server ping timeout - waited %s seconds without a response" % wait)
        gobject.timeout_add(wait*1000, check_echo_received)
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        server_ping_latency = time.time()-echoedtime/1000.0
        self.server_ping_latency.append((time.time(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((time.time(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        sl = -1
        if len(self.server_ping_latency)>0:
            _, sl = self.server_ping_latency[-1]
        self.idle_send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl))

    def send_quality(self, q):
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        self.quality = q
        if self.change_quality:
            self.send("quality", self.quality)
        else:
            self.send("jpeg-quality", self.quality)

    def send_refresh(self, wid):
        self.send("buffer-refresh", wid, True, 95)

    def send_refresh_all(self):
        log.debug("Automatic refresh for all windows ")
        self.send_refresh(-1)

    def parse_server_capabilities(self, capabilities):
        if not XpraClientBase.parse_server_capabilities(self, capabilities):
            return
        if not self.session_name:
            self.session_name = capabilities.get("session_name", "Xpra")
        self.window_configure = capabilities.get("window_configure", False)
        self.server_supports_notifications = capabilities.get("notifications", False)
        self.notifications_enabled = self.server_supports_notifications and self.client_supports_notifications
        self.server_supports_cursors = capabilities.get("cursors", True)    #added in 0.5, default to True!
        self.cursors_enabled = self.server_supports_cursors and self.client_supports_cursors
        self.server_supports_bell = capabilities.get("bell", True)          #added in 0.5, default to True!
        self.bell_enabled = self.server_supports_bell and self.client_supports_bell
        self.server_supports_clipboard = capabilities.get("clipboard", False)
        self.clipboard_enabled = self.client_supports_clipboard and self.server_supports_clipboard
        self.mmap_enabled = self.supports_mmap and self.mmap_file and capabilities.get("mmap_enabled")
        self.server_auto_refresh_delay = capabilities.get("auto_refresh_delay", 0)/1000
        self.change_quality = capabilities.get("change-quality", False)
        if self.mmap_enabled:
            log.info("mmap is enabled using %sBytes area in %s", std_unit(self.mmap_size), self.mmap_file)
        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()
        self.server_start_time = capabilities.get("start_time", -1)
        self.server_platform = capabilities.get("platform")
        self.toggle_cursors_bell_notify = capabilities.get("toggle_cursors_bell_notify", False)
        self.toggle_keyboard_sync = capabilities.get("toggle_keyboard_sync", False)
        self.server_max_desktop_size = capabilities.get("max_desktop_size")
        self.server_display = capabilities.get("display")
        self.server_actual_desktop_size = capabilities.get("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.server_randr = capabilities.get("resize_screen", False)
        log.debug("server has randr: %s", self.server_randr)
        e = capabilities.get("encoding")
        if e and e!=self.encoding:
            log.debug("server is using %s encoding" % e)
            self.encoding = e
        #process the rest from the UI thread:
        gobject.idle_add(self.process_ui_capabilities, capabilities)

    def process_ui_capabilities(self, capabilities):
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        self.set_max_packet_size()
        self.send_deflate_level()
        server_desktop_size = capabilities.get("desktop_size")
        log("server desktop size=%s", server_desktop_size)
        assert server_desktop_size
        avail_w, avail_h = server_desktop_size
        root_w, root_h = get_root_size()
        if avail_w<root_w or avail_h<root_h:
            log.warn("Server's virtual screen is too small -- "
                     "(server: %sx%s vs. client: %sx%s)\n"
                     "You may see strange behavior.\n"
                     "Please see "
                     "https://www.xpra.org/trac/ticket/10"
                     % (avail_w, avail_h, root_w, root_h))
        if self.server_randr and not is_gtk3():
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        modifier_keycodes = capabilities.get("modifier_keycodes")
        if modifier_keycodes:
            self._client_extras.set_modifier_mappings(modifier_keycodes)

        try:
            import glib
            glib.set_application_name(self.session_name)
        except ImportError, e:
            log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)

        #sound:
        self.server_pulseaudio_id = capabilities.get("sound.pulseaudio.id")
        self.server_pulseaudio_server = capabilities.get("sound.pulseaudio.server")
        self.server_sound_decoders = capabilities.get("sound.decoders", [])
        self.server_sound_encoders = capabilities.get("sound.encoders", [])
        self.server_sound_receive = capabilities.get("sound.receive", False)
        self.server_sound_send = capabilities.get("sound.send", False)
        if self.server_sound_send and self.speaker_enabled:
            self.start_receiving_sound()
        if self.server_sound_receive and self.microphone_enabled:
            self.start_sending_sound()

        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        self.key_repeat_delay, self.key_repeat_interval = capabilities.get("key_repeat", (-1,-1))
        self.emit("handshake-complete")
        if self.clipboard_enabled:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.send_clipboard_enabled_status)
        if self.toggle_keyboard_sync:
            self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)
        self.send_ping()

    def start_sending_sound(self):
        assert self.sound_source is None
        assert self.microphone_enabled
        assert self.server_sound_receive
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(self.server_sound_decoders, self.microphone_codecs, self.server_pulsesound_server, self.server_pulseaudio_id)
            if self.sound_source:
                self.sound_source.connect("new-buffer", self.new_sound_buffer)
                self.sound_source.start()
        except Exception, e:
            log.error("error setting up sound: %s", e)

    def stop_sending_sound(self):
        if self.sound_source:
            self.sound_source.stop()
            self.sound_source.cleanup()
            self.sound_source = None

    def start_receiving_sound(self):
        assert self.server_sound_send
        self.send("sound-control", "start")

    def stop_receiving_sound(self):
        self.send("sound-control", "stop")

    def new_sound_buffer(self, sound_source, data):
        assert self.sound_source
        self.send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data))

    def _process_sound_data(self, packet):
        codec = packet[1]
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.stop()
            self.sound_sink.cleanup()
            self.sound_sink = None
        if not self.sound_sink:
            try:
                from xpra.sound.sink import SoundSink
                self.sound_sink = SoundSink(codec=codec)
                self.sound_sink.start()
            except Exception, e:
                log.error("failed to setup sound: %s", e)
                return
        data = packet[2]
        self.sound_sink.add_data(data)


    def send_notify_enabled(self):
        assert self.client_supports_notifications, "cannot toggle notifications: the feature is disabled by the client"
        assert self.server_supports_notifications, "cannot toggle notifications: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle notifications: server lacks the feature"
        self.send("set-notify", self.notifications_enabled)

    def send_bell_enabled(self):
        assert self.client_supports_bell, "cannot toggle bell: the feature is disabled by the client"
        assert self.server_supports_bell, "cannot toggle bell: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle bell: server lacks the feature"
        self.send("set-bell", self.bell_enabled)

    def send_cursors_enabled(self):
        assert self.client_supports_cursors, "cannot toggle cursors: the feature is disabled by the client"
        assert self.server_supports_cursors, "cannot toggle cursors: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle cursors: server lacks the feature"
        self.send("set-cursors", self.cursors_enabled)

    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        self._protocol.set_compression_level(self.compression_level)
        self.send("set_deflate", self.compression_level)

    def send_clipboard_enabled_status(self, *args):
        self.send("set-clipboard-enabled", self.clipboard_enabled)

    def send_keyboard_sync_enabled_status(self, *args):
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)

    def set_encoding(self, encoding):
        assert encoding in ENCODINGS
        server_encodings = self.server_capabilities.get("encodings", [])
        assert encoding in server_encodings, "encoding %s is not supported by the server! (only: %s)" % (encoding, server_encodings)
        self.encoding = encoding
        self.send("encoding", encoding)

    def _screen_size_changed(self, *args):
        root_w, root_h = get_root_size()
        log.debug("sending updated screen size to server: %sx%s", root_w, root_h)
        self.send("desktop_size", root_w, root_h, self.get_screen_sizes())
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_screen_sizes(self):
        screen_sizes = []
        display = gdk.display_get_default()
        i=0
        while i<display.get_n_screens():
            screen = display.get_screen(i)
            j = 0
            monitors = []
            while j<screen.get_n_monitors():
                geom = screen.get_monitor_geometry(j)
                monitor = (screen.get_monitor_plug_name(j) or "", geom.x, geom.y, geom.width, geom.height,
                            screen.get_monitor_width_mm(j), screen.get_monitor_height_mm(j))
                monitors.append(monitor)
                j += 1
            root = screen.get_root_window()
            work_x, work_y = 0, 0
            work_width, work_height = screen.get_width(), screen.get_height()
            if not sys.platform.startswith("win"):
                try:
                    p = gtk.gdk.atom_intern('_NET_WORKAREA')
                    work_x, work_y, work_width, work_height = root.property_get(p)[2][:4]
                except:
                    pass
            item = (screen.make_display_name(), screen.get_width(), screen.get_height(),
                        screen.get_width_mm(), screen.get_height_mm(),
                        monitors,
                        work_x, work_y, work_width, work_height)
            screen_sizes.append(item)
            i += 1
        log("get_screen_sizes()=%s", screen_sizes)
        return screen_sizes

    def _ui_event(self):
        if self._ui_events==0:
            self.emit("first-ui-received")
        self._ui_events += 1

    def _process_new_common(self, packet, override_redirect):
        self._ui_event()
        wid, x, y, w, h, metadata = packet[1:7]
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        if w<=0 or h<=0:
            log.error("window dimensions are wrong: %sx%s", w, h)
            w = 10
            h = 5
        client_properties = {}
        if len(packet)>=8:
            client_properties = packet[7]
        if self.server_auto_refresh_delay>0:
            auto_refresh_delay = 0                          #server takes care of it
        else:
            auto_refresh_delay = self.auto_refresh_delay    #we do it
        ClientWindowClass = ClientWindow
        if not self.mmap_enabled and GLClientWindowClass:
            ClientWindowClass = GLClientWindowClass
        window = ClientWindowClass(self, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        window.show_all()

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_new_tray(self, packet):
        self._ui_event()
        wid, w, h = packet[1:4]
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        tray = self._client_extras.make_system_tray(self, wid, w, h)
        log("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid

    def _process_window_resized(self, packet):
        (wid, w, h) = packet[1:4]
        window = self._id_to_window.get(wid)
        log("_process_window_resized resizing window %s (id=%s) to %s", window, wid, (w,h))
        if window:
            window.resize(w, h)

    def _process_draw(self, packet):
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid, packet_sequence, width, height, decode_time):
        self.send_now("damage-sequence", packet_sequence, wid, width, height, decode_time)

    def _draw_thread_loop(self):
        while self.exit_code is None:
            packet = self._draw_queue.get()
            try:
                self._do_draw(packet)
                time.sleep(0)
            except:
                log.error("error processing draw packet", exc_info=True)

    def _do_draw(self, packet):
        """ this runs from the draw thread above """
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        window = self._id_to_window.get(wid)
        if not window:
            #window is gone
            if coding=="mmap":
                assert self.mmap_enabled
                def free_mmap_area():
                    #we need to ack the data to free the space!
                    data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
                    offset, length = data[-1]
                    data_start.value = offset+length
                #clear the mmap area via idle_add so any pending draw requests
                #will get a chance to run first
                gobject.idle_add(free_mmap_area)
            self.send_damage_sequence(wid, packet_sequence, width, height, -1)
            return
        options = {}
        if len(packet)>10:
            options = packet[10]
        log("process_draw %s bytes for window %s using %s encoding with options=%s", len(data), wid, coding, options)
        start = time.time()
        def record_decode_time(success):
            if success:
                end = time.time()
                decode_time = int(end*1000*1000-start*1000*1000)
                self.pixel_counter.append((end, width*height))
            else:
                decode_time = -1
            log("record_decode_time(%s) wid=%s, %s: %sx%s, %sms", success, wid, coding, width, height, int(decode_time/100)/10.0)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time)
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, packet_sequence, options, [record_decode_time])
        except:
            record_decode_time(False)
            raise

    def _process_cursor(self, packet):
        if not self.cursors_enabled:
            return
        if len(packet)==2:
            new_cursor = packet[1]
        elif len(packet)>=8:
            new_cursor = packet[1:]
        else:
            raise Exception("invalid cursor packet: %s items" % len(packet))
        if len(new_cursor)>0:
            pixels = new_cursor[7]
            if type(pixels)==tuple:
                #newer versions encode as a list, see "compressible_cursors" capability
                import array
                a = array.array('b', '\0'* len(pixels))
                a.fromlist(list(pixels))
                new_cursor = list(new_cursor)
                new_cursor[7] = a
        set_windows_cursor(self._id_to_window.values(), new_cursor)

    def _process_bell(self, packet):
        if not self.bell_enabled:
            return
        (wid, device, percent, pitch, duration, bell_class, bell_id, bell_name) = packet[1:9]
        gdkwindow = None
        if wid!=0:
            try:
                gdkwindow = self._id_to_window[wid].get_window()
            except:
                pass
        if gdkwindow is None:
            gdkwindow = gdk.get_default_root_window()
        log("_process_bell(%s) gdkwindow=%s", packet, gdkwindow)
        self._client_extras.system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def _process_notify_show(self, packet):
        if not self.notifications_enabled:
            return
        self._ui_event()
        dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout = packet[1:9]
        log("_process_notify_show(%s)", packet)
        self._client_extras.show_notify(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)

    def _process_notify_close(self, packet):
        if not self.notifications_enabled:
            return
        nid = packet[1]
        log("_process_notify_close(%s)", nid)
        self._client_extras.close_notify(nid)

    def _process_window_metadata(self, packet):
        wid, metadata = packet[1:3]
        window = self._id_to_window.get(wid)
        if window:
            window.update_metadata(metadata)

    def _process_window_icon(self, packet):
        log("_process_window_icon(%s,%s bytes)", packet[1:5], len(packet[5]))
        wid, w, h, pixel_format, data = packet[1:6]
        window = self._id_to_window.get(wid)
        if window:
            window.update_icon(w, h, pixel_format, data)

    def _process_configure_override_redirect(self, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window[wid]
        window.move_resize(x, y, w, h)

    def _process_lost_window(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            del self._id_to_window[wid]
            del self._window_to_id[window]
            window.destroy()
        if len(self._id_to_window)==0:
            log.debug("last window gone, clearing key repeat")
            self.clear_repeat()

    def _process_desktop_size(self, packet):
        root_w, root_h, max_w, max_h = packet[1:5]
        log("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h

    def set_max_packet_size(self):
        root_w, root_h = get_root_size()
        maxw, maxh = root_w, root_h
        try:
            server_w, server_h = self.server_actual_desktop_size
            maxw = max(root_w, server_w)
            maxh = max(root_h, server_h)
        except:
            pass
        assert maxw>0 and maxh>0 and maxw<32768 and maxh<32768, "problems calculating maximum desktop size: %sx%s" % (maxw, maxh)
        #full screen at 32bits times 4 for safety
        self._protocol.max_packet_size = maxw*maxh*4*4
        log("set maximum packet size to %s", self._protocol.max_packet_size)

    def process_packet(self, proto, packet):
        packet_type = str(packet[0])
        if packet_type.startswith("clipboard-"):
            if self.clipboard_enabled:
                gobject.idle_add(self._client_extras.process_clipboard_packet, packet)
        else:
            XpraClientBase.process_packet(self, proto, packet)

gobject.type_register(XpraClient)
