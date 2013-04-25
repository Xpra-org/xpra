# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()

import sys
import os
import time
import ctypes
try:
    from queue import Queue     #@UnresolvedImport @UnusedImport (python3)
except ImportError:
    from Queue import Queue     #@Reimport


from wimpiggy.util import (no_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.client.client_base import XpraClientBase, EXIT_TIMEOUT
from xpra.gtk_common.keys import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE, DEFAULT_MODIFIER_IGNORE_KEYNAMES
from xpra.gtk_common.cursor_names import cursor_names
from xpra.platform.gui import ClientExtras
from xpra.scripts.config import HAS_SOUND, ENCODINGS, get_codecs
from xpra.version_util import add_gtk_version_info
from xpra.stats.base import std_unit
from xpra.net.protocol import Compressed
from xpra.daemon_thread import make_daemon_thread
from xpra.client.client_window import ClientWindow, DRAW_DEBUG
from xpra.gtk_common.gtk_util import set_application_name


def nn(x):
    if x is None:
        return  ""
    return x

FAKE_BROKEN_CONNECTION = os.environ.get("XPRA_FAKE_BROKEN_CONNECTION", "0")=="1"
PING_TIMEOUT = int(os.environ.get("XPRA_PING_TIMEOUT", "60"))


class GTKXpraClient(XpraClientBase, gobject.GObject):
    __gsignals__ = {
        "clipboard-toggled"         : no_arg_signal,
        "keyboard-sync-toggled"     : no_arg_signal,
        "speaker-changed"           : no_arg_signal,        #bitrate or pipeline state has changed
        "microphone-changed"        : no_arg_signal,        #bitrate or pipeline state has changed
        }

    def __init__(self, conn, opts):
        gobject.GObject.__init__(self)
        XpraClientBase.__init__(self, opts)
        self.start_time = time.time()
        self._window_to_id = {}
        self._id_to_window = {}
        self._pid_to_group_leader = {}
        self._group_leader_wids = {}
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
        self._draw_thread = make_daemon_thread(self._draw_thread_loop, "draw")
        self._draw_thread.start()

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.server_auto_refresh_delay = 0
        self.pixel_counter = maxdeque(maxlen=100)
        self.server_ping_latency = maxdeque(maxlen=100)
        self.server_load = None
        self.client_ping_latency = maxdeque(maxlen=100)
        self._server_ok = True
        self.last_ping_echoed_time = 0
        self.server_info_request = False
        self.server_last_info = None
        self.info_request_pending = False

        #sound:
        self.speaker_allowed = bool(opts.speaker)
        self.speaker_enabled = False
        self.microphone_allowed = bool(opts.microphone)
        self.microphone_enabled = False
        self.speaker_codecs = opts.speaker_codec
        if len(self.speaker_codecs)==0 and self.speaker_allowed:
            self.speaker_codecs = get_codecs(True, False)
            self.speaker_allowed = len(self.speaker_codecs)>0
        self.microphone_codecs = opts.microphone_codec
        if len(self.microphone_codecs)==0 and self.microphone_allowed:
            self.microphone_codecs = get_codecs(False, False)
            self.microphone_allowed = len(self.microphone_codecs)>0
        self.sound_sink = None
        self.sound_source = None
        self.server_pulseaudio_id = None
        self.server_pulseaudio_server = None
        self.server_sound_decoders = []
        self.server_sound_encoders = []
        self.server_sound_receive = False
        self.server_sound_send = False

        #mmap:
        self.mmap_enabled = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_file = None
        self.mmap_size = 0

        #features:
        self.init_opengl(opts.opengl)
        self.toggle_cursors_bell_notify = False
        self.toggle_keyboard_sync = False
        self.window_configure = False
        self.change_quality = False
        self.change_min_quality = False
        self.change_speed = False
        self.readonly = opts.readonly
        self.windows_enabled = opts.windows
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
        self._keymap_changing = False
        try:
            self._keymap = gdk.keymap_get_default()
        except:
            self._keymap = None
        self._do_keys_changed()
        self.key_shortcuts = self.parse_shortcuts(opts.key_shortcut)
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
            self.min_quality = max(10, min(95 ,q))
            self.send_min_quality()
            return True
        if (self.max_bandwidth):
            self.last_input_bytecount = 0
            gobject.timeout_add(2000, compute_receive_bandwidth, 2000)
        if opts.pings:
            gobject.timeout_add(1000, self.send_ping)
        else:
            gobject.timeout_add(10*1000, self.send_ping)

    def get_root_size(self):
        raise Exception("override me!")

    def set_windows_cursor(self, gtkwindows, new_cursor):
        raise Exception("override me!")


    def init_mmap(self, mmap_group, socket_filename):
        log("init_mmap(%s, %s)", mmap_group, socket_filename)
        try:
            from xpra.platform.uuid_wrapper import get_int_uuid
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
            SEEK_SET = 0        #os.SEEK_SET==0 but this is not available in python2.4
            os.lseek(fd, self.mmap_size-1, SEEK_SET)
            assert os.write(fd, '\x00')
            os.lseek(fd, 0, SEEK_SET)
            self.mmap = mmap.mmap(fd, length=self.mmap_size)
            #write the 16 byte token one byte at a time - no endianness
            self.mmap_token = get_int_uuid()
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

    def init_opengl(self, enable_opengl):
        #enable_opengl can be True, False or None (auto-detect)
        self.opengl_enabled = False
        self.GLClientWindowClass = None
        self.opengl_props = {}
        from xpra.scripts.config import OpenGL_safety_check
        check = OpenGL_safety_check()
        if check:
            if enable_opengl is True:
                log.warn("OpenGL enabled despite: %s", check)
            else:
                self.opengl_props["info"] = "disabled: %s" % check
                log.warn("OpenGL disabled: %s", check)
                return
        if enable_opengl is False:
            self.opengl_props["info"] = "disabled by configuration"
            return
        if is_gtk3():
            self.opengl_props["info"] = "GTK3 does not support OpenGL"
            return
        self.opengl_props["info"] = ""
        try:
            try:
                from xpra import gl     #@UnusedImport
                from xpra.client.gl.gl_check import check_support
                w, h = self.get_root_size()
                min_texture_size = max(w, h)
                self.opengl_props = check_support(min_texture_size, force_enable=(enable_opengl is True))

                from xpra.client.gl.gl_client_window import GLClientWindow
                self.GLClientWindowClass = GLClientWindow
                self.opengl_enabled = True
            except ImportError, e:
                log.info("OpenGL support not enabled: %s", e)
                self.opengl_props["info"] = str(e)
        except Exception, e:
            log.error("Error loading OpenGL support: %s", e, exc_info=True)
            self.opengl_props["info"] = str(e)

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
            "draw":                 self._process_draw,
            # "clipboard-*" packets are handled by a special case below.
            }.items():
            self._ui_packet_handlers[k] = v
        #these handlers can run directly from the network thread:
        for k,v in {
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "info-response":        self._process_info_response,
            }.items():
            self._packet_handlers[k] = v

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()
        log("XpraClient.run() main loop ended, returning exit_code=%s", self.exit_code)
        return  self.exit_code

    def quit(self, exit_code=0):
        log("XpraClient.quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        if gtk.main_level()>0:
            #if for some reason cleanup() hangs, maybe this will fire...
            gobject.timeout_add(4*1000, gtk_main_quit_really)
            #try harder!:
            gobject.timeout_add(5*1000, os._exit, 1)
        self.cleanup()
        if gtk.main_level()>0:
            log("XpraClient.quit(%s) main loop at level %s, calling gtk quit via timeout", exit_code, gtk.main_level())
            gobject.timeout_add(500, gtk_main_quit_really)

    def cleanup(self):
        log("XpraClient.cleanup() client_extras=%s", self._client_extras)
        if self._client_extras:
            self._client_extras.cleanup()
        if self.sound_sink:
            self.stop_receiving_sound()
        if self.sound_source:
            self.stop_sending_sound()
        XpraClientBase.cleanup(self)
        self.clean_mmap()
        #the protocol has been closed, it is now safe to close all the windows:
        #(cleaner and needed when we run embedded in the client launcher)
        for w in self._id_to_window.values():
            try:
                w.destroy()
            except:
                pass
        self._id_to_window = {}
        self._window_to_id = {}
        log("XpraClient.cleanup() done")

    def clean_mmap(self):
        log("XpraClient.clean_mmap() mmap_file=%s", self.mmap_file)
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
        except KeyboardInterrupt:
            raise
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
        root_w, root_h = self.get_root_size()
        capabilities["desktop_size"] = [root_w, root_h]
        capabilities["screen_sizes"] = self.get_screen_sizes()
        if is_gtk3():
            capabilities["client_type"] = "Python/Gtk3"
        else:
            capabilities["client_type"] = "Python/Gtk2"
        key_repeat = self._client_extras.get_keyboard_repeat()
        if key_repeat:
            delay_ms,interval_ms = key_repeat
            capabilities["key_repeat"] = (delay_ms,interval_ms)
        capabilities["keyboard_sync"] = self.keyboard_sync and (key_repeat is not None)
        if self.mmap_file:
            capabilities["mmap_file"] = self.mmap_file
            capabilities["mmap_token"] = self.mmap_token
        #don't try to find the server uuid if this platform cannot run servers..
        #(doing so causes lockups on win32 and startup errors on osx)
        if self._client_extras.supports_server():
            #we may be running inside another server!
            try:
                from xpra.server_uuid import get_uuid
                capabilities["server_uuid"] = get_uuid() or ""
            except:
                pass
        capabilities["randr_notify"] = True
        capabilities["compressible_cursors"] = True
        capabilities["dpi"] = self.dpi
        capabilities["clipboard"] = self.client_supports_clipboard
        capabilities["clipboard.notifications"] = self.client_supports_clipboard
        #buggy osx clipboards:
        capabilities["clipboard.want_targets"] = sys.platform.startswith("darwin")
        #buggy osx and win32 clipboards:
        capabilities["clipboard.greedy"] = sys.platform.startswith("win") or sys.platform.startswith("darwin")
        capabilities["notifications"] = self.client_supports_notifications
        capabilities["cursors"] = self.client_supports_cursors
        capabilities["bell"] = self.client_supports_bell
        capabilities["encoding.client_options"] = True
        capabilities["encoding_client_options"] = True
        capabilities["rgb24zlib"] = True
        capabilities["encoding.rgb24zlib"] = True
        capabilities["named_cursors"] = len(cursor_names)>0
        capabilities["share"] = self.client_supports_sharing
        capabilities["auto_refresh_delay"] = int(self.auto_refresh_delay*1000)
        capabilities["windows"] = self.windows_enabled
        capabilities["raw_window_icons"] = True
        capabilities["system_tray"] = self.client_supports_system_tray
        capabilities["xsettings-tuple"] = True
        capabilities["encoding.uses_swscale"] = not self.opengl_enabled
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
                quality = os.environ.get("XPRA_X264_%s_QUALITY" % csc_mode)
                if quality:
                    capabilities["encoding.x264.%s.quality" % csc_mode] = int(quality)
                min_quality = os.environ.get("XPRA_X264_%s_MIN_QUALITY" % csc_mode)
                if min_quality:
                    capabilities["encoding.x264.%s.min_quality" % csc_mode] = int(min_quality)
            log("x264 encoding options: %s", str([(k,v) for k,v in capabilities.items() if k.startswith("encoding.x264.")]))
        iq = max(self.min_quality, self.quality)
        if iq<0:
            iq = 70
        capabilities["encoding.initial_quality"] = iq
        if is_gtk3():
            capabilities["encoding.supports_delta"] = []    #need implementing in window_backing
        else:
            capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24") if x in ENCODINGS]
        if HAS_SOUND:
            try:
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                from xpra.sound.gstreamer_util import add_gst_capabilities
                add_gst_capabilities(capabilities, receive=self.speaker_allowed, send=self.microphone_allowed,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs)
                log("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e)
        #batch options:
        for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
            evalue = os.environ.get("XPRA_BATCH_%s" % bprop.upper())
            if evalue:
                try:
                    capabilities["batch.%s" % bprop] = int(evalue)
                except:
                    log.error("invalid environment value for %s: %s", bprop, evalue)
        log("batch props=%s", [("%s=%s" % (k,v)) for k,v in capabilities.items() if k.startswith("batch.")])
        return capabilities

    def server_ok(self):
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
        last = self._server_ok
        self._server_ok = not FAKE_BROKEN_CONNECTION and self.last_ping_echoed_time>=ping_sent_time
        if last!=self._server_ok and not self._server_ok:
            log.info("check_server_echo: server is not responding, redrawing spinners over the windows")
            def timer_redraw():
                self.redraw_spinners()
                if self.server_ok():
                    log.info("check_server_echo: server is OK again, stopping redraw")
                    return False
                return True
            self.redraw_spinners()
            gobject.timeout_add(100, timer_redraw)
        return False

    def redraw_spinners(self):
        #draws spinner on top of the window, or not (plain repaint)
        #depending on whether the server is ok or not
        for w in self._id_to_window.values():
            if not w.is_tray():
                w.spinner(self.server_ok())

    def check_echo_timeout(self, ping_time):
        log("check_echo_timeout(%s) last_ping_echoed_time=%s", ping_time, self.last_ping_echoed_time)
        if self.last_ping_echoed_time<ping_time:
            self.warn_and_quit(EXIT_TIMEOUT, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self):
        now_ms = int(1000.0*time.time())
        self.send("ping", now_ms)
        gobject.timeout_add(PING_TIMEOUT*1000, self.check_echo_timeout, now_ms)
        wait = 2.0
        if len(self.server_ping_latency)>0:
            l = [x for _,x in list(self.server_ping_latency)]
            avg = sum(l) / len(l)
            wait = 1.0+avg*2.0
            log("average server latency=%.1f, using max wait %.2fs", 1000.0*avg, wait)
        gobject.timeout_add(int(1000.0*wait), self.check_server_echo, now_ms)
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = time.time()-echoedtime/1000.0
        self.server_ping_latency.append((time.time(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((time.time(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        l1,l2,l3 = 0,0,0
        if os.name=="posix":
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            except (OSError, AttributeError):
                pass
        sl = -1
        if len(self.server_ping_latency)>0:
            _, sl = self.server_ping_latency[-1]
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl))

    def _process_info_response(self, packet):
        self.info_request_pending = False
        self.server_last_info = packet[1]
        log("info-response: %s", packet)

    def send_info_request(self):
        assert self.server_info_request
        if not self.info_request_pending:
            self.info_request_pending = True
            self.send("info-request", [self.uuid], self._id_to_window.keys())

    def send_min_quality(self):
        q = self.min_quality
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        if self.change_min_quality:
            #v0.8 onwards: set min
            self.send("min-quality", q)
        elif self.change_quality:
            #v0.7 and earlier, can only set fixed quality..
            self.send("quality", q)
        else:
            #this is really old..
            self.send("jpeg-quality", q)

    def send_speed(self):
        assert self.change_speed
        s = self.speed
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("speed", s)

    def send_min_speed(self):
        assert self.change_speed
        s = self.min_speed
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("min-speed", s)

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
        set_application_name(self.session_name)
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
        self.change_min_quality = capabilities.get("change-min-quality", False)
        self.change_speed = capabilities.get("change-speed", False)
        self.change_min_speed = capabilities.get("change-min-speed", False)
        self.xsettings_tuple = capabilities.get("xsettings-tuple", False)
        if self.mmap_enabled:
            log.info("mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), self.mmap_file)
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
        self.server_info_request = capabilities.get("info-request", False)
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
        if not capabilities.get("shadow", False):
            assert server_desktop_size
            avail_w, avail_h = server_desktop_size
            root_w, root_h = self.get_root_size()
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

        #sound:
        self.server_pulseaudio_id = capabilities.get("sound.pulseaudio.id")
        self.server_pulseaudio_server = capabilities.get("sound.pulseaudio.server")
        self.server_sound_decoders = capabilities.get("sound.decoders", [])
        self.server_sound_encoders = capabilities.get("sound.encoders", [])
        self.server_sound_receive = capabilities.get("sound.receive", False)
        self.server_sound_send = capabilities.get("sound.send", False)
        if self.server_sound_send and self.speaker_allowed:
            self.start_receiving_sound()
        #dont' send sound automatically, wait for user to request it:
        #if self.server_sound_receive and self.microphone_allowed:
        #    self.start_sending_sound()

        self.key_repeat_delay, self.key_repeat_interval = capabilities.get("key_repeat", (-1,-1))
        self.emit("handshake-complete")
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        if self.server_supports_clipboard:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.send_clipboard_enabled_status)
        if self.toggle_keyboard_sync:
            self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)
        self.send_ping()

    def start_sending_sound(self):
        """ (re)start a sound source and emit client signal """
        assert self.microphone_allowed
        assert self.server_sound_receive
        if self.sound_source:
            if self.sound_source.get_state()=="active":
                log.error("already sending sound!")
                return
            self.sound_source.start()
        if not self.start_sound_source():
            return
        self.microphone_enabled = True
        self.emit("microphone-changed")

    def start_sound_source(self):
        assert self.sound_source is None
        def sound_source_state_changed(*args):
            self.emit("microphone-changed")
        def sound_source_bitrate_changed(*args):
            self.emit("microphone-changed")
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(self.server_sound_decoders, self.microphone_codecs, self.server_pulseaudio_server, self.server_pulseaudio_id)
            if not self.sound_source:
                return False
            self.sound_source.connect("new-buffer", self.new_sound_buffer)
            self.sound_source.connect("state-changed", sound_source_state_changed)
            self.sound_source.connect("bitrate-changed", sound_source_bitrate_changed)
            self.sound_source.start()
            return True
        except Exception, e:
            log.error("error setting up sound: %s", e)
            return False

    def stop_sending_sound(self):
        """ stop the sound source and emit client signal """
        log("XpraClient.stop_sending_sound()")
        if self.sound_source is None:
            log.warn("stop_sending_sound: sound not started!")
            return
        self.microphone_enabled = False
        self.sound_source.cleanup()
        self.sound_source = None
        self.emit("microphone-changed")
        log("XpraClient.stop_sending_sound() done")

    def start_receiving_sound(self):
        """ ask the server to start sending sound and emit the client signal """
        if self.sound_sink is not None and self.sound_sink.get_state()=="active":
            log("start_receiving_sound: we are already receiving sound!")
        elif not self.server_sound_send:
            log.error("cannot start receiving sound: support not enabled on the server")
        else:
            self.speaker_enabled = True
            self.send("sound-control", "start")
            self.emit("speaker-changed")

    def stop_receiving_sound(self):
        """ ask the server to stop sending sound, toggle flag so we ignore further packets and emit client signal """
        log("XpraClient.stop_receiving_sound()")
        self.send("sound-control", "stop")
        if self.sound_sink is None:
            log("stop_receiving_sound: sound not started!")
            return
        self.speaker_enabled = False
        self.sound_sink.cleanup()
        self.sound_sink = None
        self.emit("speaker-changed")
        log("XpraClient.stop_receiving_sound() done")


    def start_sound_sink(self, codec):
        assert self.sound_sink is None
        def sound_sink_state_changed(*args):
            self.emit("speaker-changed")
        def sound_sink_bitrate_changed(*args):
            self.emit("speaker-changed")
        def sound_sink_error(*args):
            log.warn("stopping sound because of error")
            self.stop_receiving_sound()
            self.emit("speaker-changed")
        try:
            log("starting %s sound sink", codec)
            from xpra.sound.sink import SoundSink
            self.sound_sink = SoundSink(codec=codec)
            self.sound_sink.connect("state-changed", sound_sink_state_changed)
            self.sound_sink.connect("bitrate-changed", sound_sink_bitrate_changed)
            self.sound_sink.connect("error", sound_sink_error)
            self.sound_sink.start()
            log("%s sound sink started", codec)
            return True
        except:
            log.error("failed to start sound sink", exc_info=True)
            return False

    def new_sound_buffer(self, sound_source, data, metadata):
        assert self.sound_source
        self.send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data), metadata)

    def _process_sound_data(self, packet):
        if not self.speaker_enabled:
            log("speaker is now disabled - dropping packet")
            return
        codec = packet[1]
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.error("sound codec change not supported! (from %s to %s)", self.sound_sink.codec, codec)
            self.sound_sink.stop()
            return
        if self.sound_sink is None:
            if not self.start_sound_sink(codec):
                return
        elif self.sound_sink.get_state()=="stopped":
            self.sound_sink.start()
        data = packet[2]
        metadata = packet[3]
        self.sound_sink.add_data(data, metadata)


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
        root_w, root_h = self.get_root_size()
        log.debug("sending updated screen size to server: %sx%s", root_w, root_h)
        self.send("desktop_size", root_w, root_h, self.get_screen_sizes())
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_screen_sizes(self):
        screen_sizes = []
        if is_gtk3():
            #where has this been moved to? - no docs to tell you :(
            return screen_sizes
        display = gdk.display_get_default()
        i=0
        while i<display.get_n_screens():
            screen = display.get_screen(i)
            j = 0
            monitors = []
            while j<screen.get_n_monitors():
                geom = screen.get_monitor_geometry(j)
                plug_name = ""
                if hasattr(screen, "get_monitor_plug_name"):
                    plug_name = screen.get_monitor_plug_name(j) or ""
                wmm = -1
                if hasattr(screen, "get_monitor_width_mm"):
                    wmm = screen.get_monitor_width_mm(j)
                hmm = -1
                if hasattr(screen, "get_monitor_height_mm"):
                    hmm = screen.get_monitor_height_mm(j)
                monitor = plug_name, geom.x, geom.y, geom.width, geom.height, wmm, hmm
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
        if not self.mmap_enabled and self.opengl_enabled and self.encoding in ("x264", "vpx"):
            #only enable GL for normal windows:
            window_types = metadata.get("window-type", ())
            if "_NET_WM_WINDOW_TYPE_NORMAL" in window_types:
                ClientWindowClass = self.GLClientWindowClass
        pid = metadata.get("pid", -1)
        group_leader = None
        #set group leader (but avoid ugly "not implemented" warning on win32):
        if pid>0 and not is_gtk3() and not sys.platform.startswith("win"):
            group_leader = self._pid_to_group_leader.get(pid)
            if not group_leader:
                if is_gtk3():
                    #does not work yet - the new gtk documentation is just terrible
                    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL
                    INPUT_ONLY = gtk.WindowWindowClass.INPUT_ONLY
                else:
                    WINDOW_TOPLEVEL = gdk.WINDOW_TOPLEVEL
                    INPUT_ONLY = gdk.INPUT_ONLY
                title = "%s group leader for %s" % (self.session_name or "Xpra", pid)
                group_leader = gdk.Window(None, 1, 1, WINDOW_TOPLEVEL, 0, INPUT_ONLY, title)
                self._pid_to_group_leader[pid] = group_leader
                log("new hidden group leader window %s for pid=%s", group_leader, pid)
            self._group_leader_wids.setdefault(group_leader, []).append(wid)
        window = ClientWindowClass(self, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
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
            except KeyboardInterrupt:
                raise
            except:
                log.error("error processing draw packet", exc_info=True)

    def _do_draw(self, packet):
        """ this runs from the draw thread above """
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        window = self._id_to_window.get(wid)
        if not window:
            #window is gone
            def draw_cleanup():
                if coding=="mmap":
                    assert self.mmap_enabled
                    def free_mmap_area():
                        #we need to ack the data to free the space!
                        data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
                        offset, length = data[-1]
                        data_start.value = offset+length
                    #clear the mmap area via idle_add so any pending draw requests
                    #will get a chance to run first (preserving the order)
                self.send_damage_sequence(wid, packet_sequence, width, height, -1)
            gobject.idle_add(draw_cleanup)
            return
        options = {}
        if len(packet)>10:
            options = packet[10]
        if DRAW_DEBUG:
            log.info("process_draw %s bytes for window %s using %s encoding with options=%s", len(data), wid, coding, options)
        start = time.time()
        def record_decode_time(success):
            if success:
                end = time.time()
                decode_time = int(end*1000*1000-start*1000*1000)
                self.pixel_counter.append((start, end, width*height))
                if DRAW_DEBUG:
                    dms = "%sms" % (int(decode_time/100)/10.0)
                    log.info("record_decode_time(%s) wid=%s, %s: %sx%s, %s", success, wid, coding, width, height, dms)
            else:
                decode_time = -1
                if DRAW_DEBUG:
                    log.info("record_decode_time(%s) decoding error on wid=%s, %s: %sx%s", success, wid, coding, width, height)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time)
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, packet_sequence, options, [record_decode_time])
        except KeyboardInterrupt:
            raise
        except:
            log.error("draw error", exc_info=True)
            gobject.idle_add(record_decode_time, False)
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
        self.set_windows_cursor(self._id_to_window.values(), new_cursor)

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
            group_leader = window.group_leader
            log("group leader=%s", group_leader)
            if group_leader:
                wids = self._group_leader_wids.get(group_leader, [])
                log("windows for group leader %s: %s", group_leader, wids)
                if wid in wids:
                    wids.remove(wid)
                    if len(wids)==0:
                        #the last window has gone, remove group leader:
                        pid = None
                        for p, gl in self._pid_to_group_leader.items():
                            if gl==group_leader:
                                pid = p
                                break
                        if pid:
                            log("last window for pid %s is gone, destroying the group leader %s", pid, group_leader)
                            del self._pid_to_group_leader[pid]
                            group_leader.destroy()
        if len(self._id_to_window)==0:
            log.debug("last window gone, clearing key repeat")
            self.clear_repeat()

    def _process_desktop_size(self, packet):
        root_w, root_h, max_w, max_h = packet[1:5]
        log("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h

    def set_max_packet_size(self):
        root_w, root_h = self.get_root_size()
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
        packet_type = packet[0]
        self.check_server_echo(0)
        if type(packet_type) in (unicode, str) and packet_type.startswith("clipboard-"):
            if self.clipboard_enabled:
                gobject.idle_add(self._client_extras.process_clipboard_packet, packet)
        else:
            XpraClientBase.process_packet(self, proto, packet)

gobject.type_register(GTKXpraClient)
