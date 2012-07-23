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
            (_, _, w, h, xhot, yhot, serial, pixels) = new_cursor
            log.debug("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s" % (xhot,yhot, serial, w,h, len(pixels)))
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
            gtkwindow.get_window().set_cursor(cursor)


import os
import time
import ctypes

from wimpiggy.util import (n_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.client_base import XpraClientBase
from xpra.keys import mask_to_names, DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE, DEFAULT_MODIFIER_IGNORE_KEYNAMES
from xpra.platform.gui import ClientExtras
from xpra.scripts.main import ENCODINGS

from xpra.client_window import ClientWindow
ClientWindowClass = ClientWindow
#the GL backend only works with gtk2
USE_OPENGL = False
if USE_OPENGL and not is_gtk3():
    try:
        from xpra.gl_client_window import GLClientWindow
        ClientWindowClass = GLClientWindow
    except ImportError, e:
        log.info("Disabled OpenGL output: %s" % e)

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
        self.title = opts.title
        self.readonly = opts.readonly
        self.session_name = opts.session_name
        self.compression_level = opts.compression_level
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.max_bandwidth = opts.max_bandwidth
        if self.max_bandwidth>0.0 and self.jpegquality==0:
            """ jpegquality was not set, use a better start value """
            self.jpegquality = 50

        self.mmap_enabled = False
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_randr = False
        self.pixel_counter = maxdeque(maxlen=100)
        self.server_latency = maxdeque(maxlen=100)
        self.server_load = None
        self.client_latency = maxdeque(maxlen=100)
        self.toggle_cursors_bell_notify = False
        self.toggle_keyboard_sync = False
        self.bell_enabled = True
        self.cursors_enabled = True
        self.notifications_enabled = True
        self.clipboard_enabled = False
        self.window_configure = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_file = None
        self.mmap_size = 0
        self.last_ping_echoed_time = 0

        self._client_extras = ClientExtras(self, opts)
        self.clipboard_enabled = not self.readonly and opts.clipboard and self._client_extras.supports_clipboard()
        self.supports_mmap = opts.mmap and ("rgb24" in ENCODINGS) and self._client_extras.supports_mmap()
        if self.supports_mmap:
            try:
                import mmap
                import tempfile
                import uuid
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
                if opts.mmap_group and type(conn.target)==str and os.path.exists(conn.target):
                    s = os.stat(conn.target)
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

        self.init_packet_handlers()
        self.ready(conn)

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
        self._xsettings_watcher = None
        self._root_props_watcher = None

        self._focused = None
        def compute_receive_bandwidth(delay):
            bytecount = self._protocol.input_bytecount
            bw = ((bytecount - self.last_input_bytecount) / 1024) * 1000 / delay
            self.last_input_bytecount = bytecount;
            log.debug("Bandwidth is ", bw, "kB/s, max ", self.max_bandwidth, "kB/s")
            q = self.jpegquality
            if bw > self.max_bandwidth:
                q -= 10
            elif bw < self.max_bandwidth:
                q += 5
            q = max(10, min(95 ,q))
            self.send_jpeg_quality(q)
            return True
        if (self.max_bandwidth):
            self.last_input_bytecount = 0
            gobject.timeout_add(2000, compute_receive_bandwidth, 2000)
        if opts.send_pings:
            gobject.timeout_add(1000, self.send_ping)
        else:
            gobject.timeout_add(20*1000, self.send_ping)

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        for k,v in {
            "hello":                self._process_hello,
            "new-window":           self._process_new_window,
            "new-override-redirect":self._process_new_override_redirect,
            "window-resized":       self._process_window_resized,
            "draw":                 self._process_draw,
            "cursor":               self._process_cursor,
            "bell":                 self._process_bell,
            "notify_show":          self._process_notify_show,
            "notify_close":         self._process_notify_close,
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "window-metadata":      self._process_window_metadata,
            "configure-override-redirect":  self._process_configure_override_redirect,
            "lost-window":          self._process_lost_window,
            "desktop_size":         self._process_desktop_size,
            # "clipboard-*" packets are handled by a special case below.
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
            self._client_extras.exit()
            self._client_extras = None
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

    def handle_key_action(self, event, window, depressed):
        if self.readonly:
            return
        log.debug("handle_key_action(%s,%s,%s)", event, window, depressed)
        modifiers = self.mask_to_names(event.state)
        name = gdk.keyval_name(event.keyval)
        keyval = nn(event.keyval)
        keycode = event.hardware_keycode
        group = event.group
        #meant to be in PyGTK since 2.10, not used yet so just return False if we don't have it:
        is_modifier = hasattr(event, "is_modifier") and event.is_modifier
        translated = self._client_extras.translate_key(depressed, keyval, name, keycode, group, is_modifier, modifiers)
        if translated is None:
            return
        depressed, keyval, name, keycode, group, is_modifier, modifiers = translated
        if self.key_handled_as_shortcut(window, name, modifiers, depressed):
            return
        if keycode<0:
            log.debug("key_action(%s,%s,%s) translated keycode is %s, ignoring it", event, window, depressed, keycode)
            return
        log.debug("key_action(%s,%s,%s) modifiers=%s, name=%s, state=%s, keyval=%s, string=%s, keycode=%s", event, window, depressed, modifiers, name, event.state, event.keyval, event.string, keycode)
        wid = self._window_to_id[window]
        self.send(["key-action", wid, nn(name), depressed, modifiers, keyval, nn(event.string), nn(keycode), group, is_modifier])
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, depressed, name, keyval, keycode)

    def _key_repeat(self, wid, depressed, name, keyval, keycode):
        """ this method takes care of scheduling the sending of
            "key-repeat" packets to the server so that it can
            maintain a consistent keyboard state.
        """
        #we keep track of which keys are still pressed in a dict,
        if keycode==0:
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
                self.send_now(["key-repeat", wid, name, keyval, keycode, modifiers])
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
        self.xkbmap_mod_meanings, self.xkbmap_mod_managed, self.xkbmap_mod_pointermissing = self._client_extras.get_keymap_modifiers()
        log.debug("layout=%s, variant=%s", self.xkbmap_layout, self.xkbmap_variant)
        log.debug("print=%s, query=%s", self.xkbmap_print, self.xkbmap_query)
        log.debug("keycodes=%s", str(self.xkbmap_keycodes)[:80]+"...")
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
        self.send(["layout-changed", nn(self.xkbmap_layout), nn(self.xkbmap_variant)])

    def send_keymap(self):
        self.send(["keymap-changed", self.get_keymap_properties()])

    def get_keymap_properties(self):
        props = {"modifiers" : self.get_current_modifiers()}
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
              "xkbmap_mod_managed", "xkbmap_mod_pointermissing", "xkbmap_keycodes"]:
            props[x] = nn(getattr(self, x))
        return  props

    def send_focus(self, wid):
        self.send(["focus", wid, self.get_current_modifiers()])

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
        mn = mask_to_names(mask, self._modifier_map)
        names = mn
        if self._client_extras:
            names = self._client_extras.current_modifiers(mn)
        return  names

    def send_positional(self, packet):
        self._protocol.source.queue_positional_packet(packet)

    def send_mouse_position(self, packet):
        self._protocol.source.queue_mouse_position_packet(packet)

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        for k,v in self.get_keymap_properties().items():
            capabilities[k] = v
        if self.readonly:
            #don't bother sending keyboard info, as it won't be used
            capabilities["keyboard"] = False
        else:
            capabilities["xkbmap_layout"] = nn(self.xkbmap_layout)
            capabilities["xkbmap_variant"] = nn(self.xkbmap_variant)
        capabilities["clipboard"] = self.clipboard_enabled
        capabilities["notifications"] = self._client_extras.can_notify()
        capabilities["modifiers"] = self.get_current_modifiers()
        root_w, root_h = get_root_size()
        capabilities["desktop_size"] = [root_w, root_h]
        key_repeat = self._client_extras.get_keyboard_repeat()
        if key_repeat:
            delay_ms,interval_ms = key_repeat
            capabilities["key_repeat"] = (delay_ms,interval_ms)
        capabilities["keyboard_sync"] = self.keyboard_sync and (key_repeat is not None)
        if self.mmap_file:
            capabilities["mmap_file"] = self.mmap_file
            capabilities["mmap_token"] = self.mmap_token
        capabilities["randr_notify"] = True
        #these should be turned into options:
        capabilities["cursors"] = True
        capabilities["bell"] = True
        capabilities["png_window_icons"] = "png" in ENCODINGS
        return capabilities

    def send_ping(self):
        now_ms = int(1000*time.time())
        self.send(["ping", now_ms])
        wait = 15
        def check_echo_received(*args):
            if self.last_ping_echoed_time<now_ms:
                log.error("check_echo_received: we sent a ping to the server %s seconds ago and we have not received its echo!", wait)
                log.error("    assuming that the connection is dead and disconnecting")
                self.quit(1)
        gobject.timeout_add(wait*1000, check_echo_received)
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        diff = int(1000*time.time()-echoedtime)
        self.server_latency.append(diff)
        self.server_load = (l1, l2, l3)
        if cl>=0:
            self.client_latency.append(cl)
        log("ping echo server load=%s, measured client latency=%s", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        sl = -1
        if len(self.server_latency)>0:
            sl = self.server_latency[-1]
        self.send(["ping_echo", echotime, l1, l2, l3, sl])

    def send_jpeg_quality(self, q):
        assert q>0 and q<100
        self.jpegquality = q
        self.send(["jpeg-quality", self.jpegquality])

    def send_refresh(self, wid):
        self.send(["buffer-refresh", wid, True, 95])
        self._refresh_requested = True

    def send_refresh_all(self):
        log.debug("Automatic refresh for all windows ")
        self.send_refresh(-1)

    def parse_server_capabilities(self, capabilities):
        XpraClientBase.parse_server_capabilities(self, capabilities)
        if not self.session_name:
            self.session_name = capabilities.get("session_name", "Xpra")
        try:
            import glib
            glib.set_application_name(self.session_name)
        except ImportError, e:
            log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        self.server_actual_desktop_size = capabilities.get("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.set_max_packet_size()
        self.server_max_desktop_size = capabilities.get("max_desktop_size")
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
        self.server_randr = capabilities.get("resize_screen", False)
        log.debug("server has randr: %s", self.server_randr)
        if self.server_randr and not is_gtk3():
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        e = capabilities.get("encoding")
        if e and e!=self.encoding:
            log.debug("server is using %s encoding" % e)
            self.encoding = e
        self.window_configure = capabilities.get("window_configure", False)
        self.notifications_enabled = capabilities.get("notifications", False)
        clipboard_server_support = capabilities.get("clipboard", True)
        self.clipboard_enabled = clipboard_server_support and self._client_extras.supports_clipboard()
        self.mmap_enabled = self.supports_mmap and self.mmap_file and capabilities.get("mmap_enabled")
        if self.mmap_enabled:
            log.info("mmap enabled using %s", self.mmap_file)
        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()
        self.send_deflate_level()
        self.server_start_time = capabilities.get("start_time", -1)
        self.server_platform = capabilities.get("platform")
        self.toggle_cursors_bell_notify = capabilities.get("toggle_cursors_bell_notify", False)
        self.toggle_keyboard_sync = capabilities.get("toggle_keyboard_sync", False)
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        self.key_repeat_delay, self.key_repeat_interval = capabilities.get("key_repeat", (-1,-1))
        self.emit("handshake-complete")
        if clipboard_server_support:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.send_clipboard_enabled_status)
        if self.toggle_keyboard_sync:
            self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)

    def send_notify_enabled(self):
        if self.toggle_cursors_bell_notify:
            self.send(["set-notify", self.notifications_enabled])

    def send_bell_enabled(self):
        if self.toggle_cursors_bell_notify:
            self.send(["set-bell", self.bell_enabled])

    def send_cursors_enabled(self):
        if self.toggle_cursors_bell_notify:
            self.send(["set-cursors", self.cursors_enabled])

    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        self._protocol.set_compression_level(self.compression_level)
        self.send(["set_deflate", self.compression_level])

    def send_clipboard_enabled_status(self, *args):
        self.send(["set-clipboard-enabled", self.clipboard_enabled])

    def send_keyboard_sync_enabled_status(self, *args):
        self.send(["set-keyboard-sync-enabled", self.keyboard_sync])

    def set_encoding(self, encoding):
        assert encoding in ENCODINGS
        server_encodings = self.server_capabilities.get("encodings", [])
        assert encoding in server_encodings, "encoding %s is not supported by the server! (only: %s)" % (encoding, server_encodings)
        self.encoding = encoding
        self.send(["encoding", encoding])

    def _screen_size_changed(self, *args):
        root_w, root_h = get_root_size()
        log.debug("sending updated screen size to server: %sx%s", root_w, root_h)
        self.send(["desktop_size", root_w, root_h])
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def _process_new_common(self, packet, override_redirect):
        (wid, x, y, w, h, metadata) = packet[1:7]
        if w<=0 or h<=0:
            log.error("window dimensions are wrong: %sx%s", w, h)
            w = 10
            h = 5
        window = ClientWindowClass(self, wid, x, y, w, h, metadata, override_redirect)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        window.show_all()

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_window_resized(self, packet):
        (wid, w, h) = packet[1:4]
        window = self._id_to_window.get(wid)
        log("_process_window_resized resizing window %s (id=%s) to %s", window, wid, (w,h))
        if window:
            window.resize(w, h)

    def _process_draw(self, packet):
        (wid, x, y, width, height, coding, data, packet_sequence, rowstride) = packet[1:10]
        window = self._id_to_window.get(wid)
        decode_time = 0
        if window:
            start = time.time()
            if window.draw_region(x, y, width, height, coding, data, rowstride):
                end = time.time()
                self.pixel_counter.append((end, width*height))
                decode_time = int(end*1000*1000-start*1000*1000)
        else:
            #window is gone
            if coding=="mmap":
                #we need to ack the data to free the space!
                assert self.mmap_enabled
                data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
                offset, length = data[-1]
                data_start.value = offset+length
        self.send_now(["damage-sequence", packet_sequence, wid, width, height, decode_time])

    def _process_cursor(self, packet):
        (_, new_cursor) = packet
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
        (dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout) = packet[1:9]
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

    def _process_configure_override_redirect(self, packet):
        (wid, x, y, w, h) = packet[1:6]
        window = self._id_to_window[wid]
        window.move_resize(x, y, w, h)

    def _process_lost_window(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            del self._id_to_window[wid]
            del self._window_to_id[window]
            if window._refresh_timer:
                gobject.source_remove(window._refresh_timer)
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
                self._client_extras.process_clipboard_packet(packet)
        else:
            XpraClientBase.process_packet(self, proto, packet)

gobject.type_register(XpraClient)
