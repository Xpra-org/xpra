# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
import cairo
import re
import os
import time
from collections import deque

from wimpiggy.util import (n_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol
from xpra.keys import mask_to_names, MODIFIER_NAMES
from xpra.platform.gui import ClientExtras
from xpra.scripts.main import ENCODINGS
from xpra.version_util import is_compatible_with

import xpra
default_capabilities = {"__prerelease_version": xpra.__version__}

def nn(x):
    if x is None:
        return  ""
    return x

class ClientSource(object):
    def __init__(self, protocol):
        self._priority_packets = []
        self._ordinary_packets = []
        self._mouse_position = None
        self._protocol = protocol
        self._protocol.source = self

    def queue_priority_packet(self, packet):
        self._priority_packets.append(packet)
        self._protocol.source_has_more()

    def queue_ordinary_packet(self, packet):
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def queue_positional_packet(self, packet):
        self.queue_ordinary_packet(packet)
        self._mouse_position = None

    def queue_mouse_position_packet(self, packet):
        self._mouse_position = packet
        self._protocol.source_has_more()

    def next_packet(self):
        if self._priority_packets:
            packet = self._priority_packets.pop(0)
        elif self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            self._mouse_position = None
        else:
            packet = None
        has_more = packet is not None and \
                (bool(self._priority_packets) or bool(self._ordinary_packets) \
                 or self._mouse_position is not None)
        return packet, has_more

class ClientWindow(gtk.Window):
    def __init__(self, client, id, x, y, w, h, metadata, override_redirect):
        if override_redirect:
            type = gtk.WINDOW_POPUP
        else:
            type = gtk.WINDOW_TOPLEVEL
        gtk.Window.__init__(self, type)
        self._client = client
        self._id = id
        self._pos = (-1, -1)
        self._size = (1, 1)
        self._backing = None
        self._metadata = {}
        self._override_redirect = override_redirect
        self._new_backing(w, h)
        self._refresh_timer = None
        self._refresh_requested = False
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False

        self.update_metadata(metadata)

        self.set_app_paintable(True)
        self.add_events(gtk.gdk.STRUCTURE_MASK
                        | gtk.gdk.KEY_PRESS_MASK | gtk.gdk.KEY_RELEASE_MASK
                        | gtk.gdk.POINTER_MOTION_MASK
                        | gtk.gdk.BUTTON_PRESS_MASK
                        | gtk.gdk.BUTTON_RELEASE_MASK)

        self.move(x, y)
        self.set_default_size(w, h)

        self.connect("notify::has-toplevel-focus", self._focus_change)

    def update_metadata(self, metadata):
        self._metadata.update(metadata)

        title = self._client.title
        if title.find("@")>=0:
            #perform metadata variable substitutions:
            default_values = {"title" : u"<untitled window>",
                              "client-machine" : u"<unknown machine>"}
            def metadata_replace(match):
                atvar = match.group(0)          #ie: '@title@'
                var = atvar[1:len(atvar)-1]     #ie: 'title'
                default_value = default_values.get(var, u"<unknown %s>" % var)
                return self._metadata.get(var, default_value).decode("utf-8")
            title = re.sub("@[\w\-]*@", metadata_replace, title)
        self.set_title(u"%s" % title)

        if "size-constraints" in self._metadata:
            size_metadata = self._metadata["size-constraints"]
            hints = {}
            for (a, h1, h2) in [
                ("maximum-size", "max_width", "max_height"),
                ("minimum-size", "min_width", "min_height"),
                ("base-size", "base_width", "base_height"),
                ("increment", "width_inc", "height_inc"),
                ]:
                if a in self._metadata["size-constraints"]:
                    hints[h1], hints[h2] = size_metadata[a]
            for (a, h) in [
                ("minimum-aspect", "min_aspect_ratio"),
                ("maximum-aspect", "max_aspect_ratio"),
                ]:
                if a in self._metadata:
                    hints[h] = size_metadata[a][0] * 1.0 / size_metadata[a][1]
            self.set_geometry_hints(None, **hints)

        if not (self.flags() & gtk.REALIZED):
            self.set_wmclass(*self._metadata.get("class-instance",
                                                 ("xpra", "Xpra")))

        if "icon" in self._metadata:
            (width, height, coding, data) = self._metadata["icon"]
            if coding == "premult_argb32":
                cairo_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                cairo_surf.get_data()[:] = data
                # FIXME: We round-trip through PNG. This is ridiculous, but faster
                # than doing a bunch of alpha un-premultiplying and byte-swapping
                # by hand in Python (better still would be to write some Pyrex,
                # but I don't have time right now):
                loader = gtk.gdk.PixbufLoader()
                cairo_surf.write_to_png(loader)
                loader.close()
                pixbuf = loader.get_pixbuf()
            else:
                loader = gtk.gdk.PixbufLoader(coding)
                loader.write(data, len(data))
                loader.close()
                pixbuf = loader.get_pixbuf()
            self.set_icon(pixbuf)

    def _new_backing(self, w, h):
        old_backing = self._backing
        self._backing = gtk.gdk.Pixmap(gtk.gdk.get_default_root_window(),
                                       w, h)
        cr = self._backing.cairo_create()
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing.get_size()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def refresh_window(self):
        log.debug("Automatic refresh for id ", self._id)
        self._client.send_refresh(self._id)

    def refresh_all_windows(self):
        #this method is only here because we may want to fire it
        #from a --key-shortcut action and the event is delivered to
        #the "ClientWindow"
        self._client.send_refresh_all()

    def draw(self, x, y, width, height, coding, img_data):
        gc = self._backing.new_gc()
        if coding == "mmap":
            assert self._client.supports_mmap
            log("drawing from mmap: %s", img_data)
            data = ""
            import ctypes
            data_start = ctypes.c_uint.from_buffer(self._client.mmap, 0)
            for offset, length in img_data:
                self._client.mmap.seek(offset)
                data += self._client.mmap.read(length)
                data_start.value = offset+length
            self._backing.draw_rgb_image(gc, x, y, width, height, gtk.gdk.RGB_DITHER_NONE, data)
        elif coding == "rgb24":
            assert len(img_data) == width * height * 3
            self._backing.draw_rgb_image(gc, x, y, width, height, gtk.gdk.RGB_DITHER_NONE, img_data)
        else:
            loader = gtk.gdk.PixbufLoader(coding)
            loader.write(img_data, len(img_data))
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf:
                log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
            else:
                self._backing.draw_pixbuf(gc, pixbuf, 0, 0, x, y, width, height)
        self.window.invalidate_rect(gtk.gdk.Rectangle(x, y, width, height), False)

        if self._refresh_requested:
            self._refresh_requested = False
        else:
            if self._refresh_timer:
                gobject.source_remove(self._refresh_timer)
            if self._client.auto_refresh_delay:
                self._refresh_timer = gobject.timeout_add(int(1000 * self._client.auto_refresh_delay), self.refresh_window)

    def do_expose_event(self, event):
        if not self.flags() & gtk.MAPPED:
            return
        cr = self.window.cairo_create()
        cr.rectangle(event.area)
        cr.clip()
        cr.set_source_pixmap(self._backing, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        return False

    def _geometry(self):
        (x, y) = self.window.get_origin()
        (_, _, w, h, _) = self.window.get_geometry()
        return (x, y, w, h)

    def do_map_event(self, event):
        log("Got map event")
        gtk.Window.do_map_event(self, event)
        if not self._override_redirect:
            x, y, w, h = self._geometry()
            self._client.send(["map-window", self._id, x, y, w, h])
            self._pos = (x, y)
            self._size = (w, h)
        self._been_mapped = True
        gobject.idle_add(self._focus_change)

    def do_configure_event(self, event):
        log("Got configure event")
        gtk.Window.do_configure_event(self, event)
        if not self._override_redirect:
            x, y, w, h = self._geometry()
            if (x, y) != self._pos:
                self._pos = (x, y)
                self._client.send(["move-window", self._id, x, y])
            if (w, h) != self._size:
                self._size = (w, h)
                self._client.send(["resize-window", self._id, w, h])
                self._new_backing(w, h)

    def move_resize(self, x, y, w, h):
        assert self._override_redirect
        self.window.move_resize(x, y, w, h)
        self._new_backing(w, h)

    def destroy(self):
        self._unfocus()
        gtk.Window.destroy(self)

    def _unfocus(self):
        if self._client._focused==self._id:
            self._client.update_focus(self._id, False)

    def do_unmap_event(self, event):
        self._unfocus()
        if not self._override_redirect:
            self._client.send(["unmap-window", self._id])

    def do_delete_event(self, event):
        self._client.send(["close-window", self._id])
        return True

    def quit(self):
        self._client.quit()

    def void(self):
        pass

    def do_key_press_event(self, event):
        self._client.handle_key_action(event, self, True)

    def do_key_release_event(self, event):
        self._client.handle_key_action(event, self, False)

    def _pointer_modifiers(self, event):
        pointer = (int(event.x_root), int(event.y_root))
        modifiers = self._client.mask_to_names(event.state)
        return pointer, modifiers

    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      pointer, modifiers])

    def do_button_press_event(self, event):
        if self._client.readonly:
            return
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        if self._client.readonly:
            return
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
        if self._client.readonly:
            return
        # Map scroll directions back to mouse buttons.  Mapping is taken from
        # gdk/x11/gdkevents-x11.c.
        scroll_map = {gtk.gdk.SCROLL_UP: 4,
                      gtk.gdk.SCROLL_DOWN: 5,
                      gtk.gdk.SCROLL_LEFT: 6,
                      gtk.gdk.SCROLL_RIGHT: 7,
                      }
        self._button_action(scroll_map[event.direction], event, True)
        self._button_action(scroll_map[event.direction], event, False)

    def _focus_change(self, *args):
        log("_focus_change(%s)", args)
        if self._been_mapped:
            self._client.update_focus(self._id, self.get_property("has-toplevel-focus"))

gobject.type_register(ClientWindow)

class XpraClient(gobject.GObject):
    __gsignals__ = {
        "clipboard-toggled": n_arg_signal(0),
        "handshake-complete": n_arg_signal(0),
        "received-gibberish": n_arg_signal(1),
        }

    def __init__(self, conn, opts):
        gobject.GObject.__init__(self)
        self.start_time = time.time()
        self._window_to_id = {}
        self._id_to_window = {}
        title = opts.title
        if opts.title_suffix is not None:
            title = "@title@ %s" % opts.title_suffix
        self.title = title
        self.readonly = opts.readonly
        self.session_name = opts.session_name
        self.password_file = opts.password_file
        self.compression_level = opts.compression_level
        self.encoding = opts.encoding
        self.jpegquality = opts.jpegquality
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.max_bandwidth = opts.max_bandwidth
        self.key_shortcuts = self.parse_shortcuts(opts.key_shortcuts)
        if self.max_bandwidth>0.0 and self.jpegquality==0:
            """ jpegquality was not set, use a better start value """
            self.jpegquality = 50

        self.server_capabilities = {}

        self.can_ping = False
        self.mmap_enabled = False
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_desktop_size = None
        self.server_randr = False
        self.pixel_counter = deque(maxlen=100)
        self.server_latency = deque(maxlen=100)
        self.server_load = None
        self.client_latency = deque(maxlen=100)
        self.bell_enabled = True
        self.notifications_enabled = True
        self.send_damage_sequence = False
        self.clipboard_enabled = False
        self.mmap = None
        self.mmap_file = None
        self.mmap_size = 0

        self._client_extras = ClientExtras(self, opts)
        self.clipboard_enabled = not self.readonly and opts.clipboard and self._client_extras.supports_clipboard()
        self.supports_mmap = opts.mmap and self._client_extras.supports_mmap()
        if self.supports_mmap:
            try:
                import mmap
                import tempfile
                dotxpradir = os.path.expanduser("~/.xpra")
                if not os.path.exists(dotxpradir):
                    os.mkdir(dotxpradir, 0700)
                temp = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".mmap", dir=dotxpradir)
                #keep a reference to it so it does not disappear!
                self._mmap_temp_file = temp
                self.mmap_file = temp.name
                self.mmap_size = max(4096, mmap.PAGESIZE)*32*1024   #generally 128MB
                fd = temp.file.fileno()
                log("using mmap file %s, fd=%s, size=%s", self.mmap_file, fd, self.mmap_size)
                os.lseek(fd, self.mmap_size-1, os.SEEK_SET)
                assert os.write(fd, '\x00')
                os.lseek(fd, 0, os.SEEK_SET)
                self.mmap = mmap.mmap(fd, length=self.mmap_size)
            except Exception, e:
                log.error("failed to setup mmap: %s", e)
                self.supports_mmap = False
                self.clean_mmap()
                self.mmap = None
                self.mmap_file = None
                self.mmap_size = 0

        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)

        self.keyboard_sync = opts.keyboard_sync
        self.key_repeat_modifiers = False
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.keys_pressed = {}
        self._raw_keycodes_feature = False
        self._focus_modifiers_feature = False
        self._remote_version = None
        self._keymap_changing = False
        self._keymap = gtk.gdk.keymap_get_default()
        self._do_keys_changed()
        self.send_hello()

        self._keymap.connect("keys-changed", self._keys_changed)
        self._xsettings_watcher = None
        self._root_props_watcher = None

        self._focused = None
        def compute_receive_bandwidth(delay):
            bw = (self._protocol._recv_counter / 1024) * 1000/ delay;
            self._protocol._recv_counter = 0;
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
            gobject.timeout_add(2000, compute_receive_bandwidth, 2000);


    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()

    def cleanup(self):
        if self._client_extras:
            self._client_extras.exit()
            self._client_extras = None
        if self._protocol:
            self._protocol.close()
            self._protocol = None
        self.clean_mmap()

    def clean_mmap(self):
        if self.mmap_file and os.path.exists(self.mmap_file):
            os.unlink(self.mmap_file)
            self.mmap_file = None

    def quit(self, *args):
        gtk_main_quit_really()

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
        for s in strs:
            #example for s: Control+F8:some_action()
            parts = s.split(":", 1)
            if len(parts)!=2:
                log.error("invalid shortcut: %s" % s)
                continue
            #example for action: "quit"
            action = parts[1]
            #example for keyspec: ["Control", "F8"]
            keyspec = parts[0].split("+")
            modifiers = []
            if len(keyspec)>1:
                valid = True
                for mod in keyspec[:len(keyspec)-1]:
                    lmod = mod.lower()
                    if lmod not in MODIFIER_NAMES:
                        log.error("invalid modifier: %s" % mod)
                        valid = False
                        break
                    modifiers.append(lmod)
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
        log.debug("handle_key_action(%s,%s,%s)" % (event, window, depressed))
        modifiers = self.mask_to_names(event.state)
        name = gtk.gdk.keyval_name(event.keyval)
        if self.key_handled_as_shortcut(window, name, modifiers, depressed):
            return
        id = self._window_to_id[window]
        if not self._raw_keycodes_feature:
            """ versions before 0.0.7.24 only accept 4 parameters (no keyval, keycode, ...)
                also used on win32 and osx since those don't have valid keymaps/keycode (yet?)
            """
            # Apparently some weird keys (e.g. "media keys") can have no keyval or
            # no keyval name (I believe that both give us a None here).
            # Another reason to use the _raw_keycodes_feature wherever possible.
            if name is None:
                return
            self.send(["key-action", id, name, depressed, modifiers])
            keyval = ""
            keycode = 0
        else:
            keyval = nn(event.keyval)
            keycode = event.hardware_keycode
            log.debug("key_action(%s,%s,%s) modifiers=%s, name=%s, state=%s, keyval=%s, string=%s, keycode=%s" % (event, window, depressed, modifiers, name, event.state, event.keyval, event.string, keycode))
            self.send(["key-action", id, nn(name), depressed, modifiers, keyval, nn(event.string), nn(keycode)])
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(id, depressed, name, keyval, keycode)

    def _key_repeat(self, id, depressed, name, keyval, keycode):
        """ this method takes care of scheduling the sending of
            "key-repeat" packets to the server so that it can
            maintain a consistent keyboard state.
        """
        #we keep track of which keys are still pressed in a dict,
        #the key is either the keycode (if _raw_keycodes_feature) or the key name (otherwise)
        if keycode==0:
            if not self.key_repeat_modifiers:
                #we can't handle key-repeat by key name without this feature
                return
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
            MIN_DELAY = 20
            delay = max(self.key_repeat_delay-LATENCY_JITTER, MIN_DELAY)
            interval = max(self.key_repeat_interval-LATENCY_JITTER, MIN_DELAY)
            def send_key_repeat():
                if self.key_repeat_modifiers:
                    #supports extended mode, send the extra data:
                    (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
                    modifiers = self.mask_to_names(current_mask)
                    packet = ["key-repeat", id, name, keyval, keycode, modifiers]
                else:
                    packet = ["key-repeat", keycode]
                self.send_now(packet)
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
        self.xkbmap_layout, self.xkbmap_variant, self.xkbmap_variants = self._client_extras.get_layout_spec()
        self.xkbmap_print, self.xkbmap_query, self.xmodmap_data = self._client_extras.get_keymap_spec()
        self.xkbmap_mod_clear, self.xkbmap_mod_add = self._client_extras.get_keymap_modifiers()

    def _keys_changed(self, *args):
        self._keymap = gtk.gdk.keymap_get_default()
        if not self._keymap_changing:
            self._keymap_changing = True
            gobject.timeout_add(500, self._do_keys_changed, True)

    def _do_keys_changed(self, sendkeymap=False):
        self._keymap_changing = False
        self._modifier_map = self._client_extras.grok_modifier_map(gtk.gdk.display_get_default())
        if sendkeymap:
            #old clients won't know what to do with it, but that's ok
            self.query_xkbmap()
            log("keys_changed")
            if self.xkbmap_layout:
                self.send_layout()
            self.send_keymap()

    def send_layout(self):
        self.send(["layout-changed", nn(self.xkbmap_layout), nn(self.xkbmap_variant)])

    def send_keymap(self):
        (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
        self.send(["keymap-changed", nn(self.xkbmap_print), nn(self.xkbmap_query), nn(self.xmodmap_data), self.mask_to_names(current_mask)])


    def update_focus(self, id, gotit):
        def send_focus(_id):
            """ with v0.0.7.24 onwards, we want to set the modifier map when we get focus """
            if self._focus_modifiers_feature:
                (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
                self.send(["focus", _id, self.mask_to_names(current_mask)])
            else:
                self.send(["focus", _id])
        log("update_focus(%s,%s) _focused=%s", id, gotit, self._focused)
        if gotit and self._focused is not id:
            self.clear_repeat()
            send_focus(id)
            self._focused = id
        if not gotit and self._focused is id:
            self.clear_repeat()
            send_focus(0)
            self._focused = None

    def mask_to_names(self, mask):
        return mask_to_names(mask, self._modifier_map)

    def send(self, packet):
        self._protocol.source.queue_ordinary_packet(packet)

    def send_now(self, packet):
        self._protocol.source.queue_priority_packet(packet)

    def send_positional(self, packet):
        self._protocol.source.queue_positional_packet(packet)

    def send_mouse_position(self, packet):
        self._protocol.source.queue_mouse_position_packet(packet)

    def send_hello(self, hash=None):
        capabilities_request = dict(default_capabilities)
        if hash:
            capabilities_request["challenge_response"] = hash
        if self.compression_level:
            capabilities_request["deflate"] = self.compression_level
        if self.encoding:
            capabilities_request["encoding"] = self.encoding
        capabilities_request["encodings"] = ENCODINGS
        if self.jpegquality:
            capabilities_request["jpeg"] = self.jpegquality
        self.query_xkbmap()
        if self.xkbmap_layout:
            capabilities_request["xkbmap_layout"] = self.xkbmap_layout
            if self.xkbmap_variant:
                capabilities_request["xkbmap_variant"] = self.xkbmap_variant
        if self.xkbmap_print:
            capabilities_request["keymap"] = self.xkbmap_print
        if self.xkbmap_query:
            capabilities_request["xkbmap_query"] = self.xkbmap_query
        if self.xmodmap_data:
            capabilities_request["xmodmap_data"] = self.xmodmap_data
        if self.xkbmap_mod_clear:
            capabilities_request["xkbmap_mod_clear"] = self.xkbmap_mod_clear
        if self.xkbmap_mod_add:
            capabilities_request["xkbmap_mod_add"] = self.xkbmap_mod_add
        capabilities_request["cursors"] = True
        capabilities_request["bell"] = True
        capabilities_request["clipboard"] = self.clipboard_enabled
        capabilities_request["notifications"] = self._client_extras.can_notify()
        capabilities_request["packet_size"] = True
        (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
        modifiers = self.mask_to_names(current_mask)
        log.debug("sending modifiers=%s" % str(modifiers))
        capabilities_request["modifiers"] = modifiers
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        capabilities_request["desktop_size"] = [root_w, root_h]
        capabilities_request["png_window_icons"] = True
        capabilities_request["damage_sequence"] = True
        capabilities_request["ping"] = True
        key_repeat = self._client_extras.get_keyboard_repeat()
        if key_repeat:
            delay_ms,interval_ms = key_repeat
            capabilities_request["key_repeat"] = (delay_ms,interval_ms)
        capabilities_request["keyboard_sync"] = self.keyboard_sync and key_repeat
        if self.mmap_file:
            capabilities_request["mmap_file"] = self.mmap_file
        self.send(["hello", capabilities_request])

    def send_ping(self):
        if self.can_ping:
            self.send(["ping", long(1000*time.time())])

    def _process_ping_echo(self, packet):
        (_, echoedtime, l1, l2, l3, cl) = packet[:6]
        diff = long(1000*time.time()-echoedtime)
        self.server_latency.append(diff)
        self.server_load = (l1, l2, l3)
        if cl>=0:
            self.client_latency.append(cl)
        log("ping echo server load=%s, measured client latency=%s", self.server_load, cl)

    def _process_ping(self, packet):
        assert self.can_ping
        (_, echotime) = packet[:2]
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = long(fl1*1000), long(fl2*1000), long(fl3*1000)
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

    def send_refresh(self, id):
        self.send(["buffer-refresh", id, True, 95])
        self._refresh_requested = True

    def send_refresh_all(self):
        log.debug("Automatic refresh for all windows ")
        self.send_refresh(-1)

    def _process_disconnect(self, packet):
        log.error("server requested disconnect: %s" % str(packet))
        self.quit()
        return

    def _process_challenge(self, packet):
        if not self.password_file:
            log.error("password is required by the server")
            self.quit()
            return
        import hmac
        passwordFile = open(self.password_file, "rU")
        password = passwordFile.read()
        (_, salt) = packet
        hash = hmac.HMAC(password, salt)
        self.send_hello(hash.hexdigest())

    def _process_hello(self, packet):
        (_, capabilities) = packet
        self.server_capabilities = capabilities
        if not self.session_name:
            self.session_name = capabilities.get("session_name", "Xpra")
        import glib
        glib.set_application_name(self.session_name)
        self._raw_keycodes_feature = capabilities.get("raw_keycodes_feature", False) and self._client_extras.supports_raw_keycodes()
        self._focus_modifiers_feature = capabilities.get("raw_keycodes_feature", False)
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        self._remote_version = capabilities.get("__prerelease_version")
        if not is_compatible_with(self._remote_version):
            self.quit()
            return
        self.server_actual_desktop_size = capabilities.get("actual_desktop_size")
        self.server_desktop_size = capabilities.get("desktop_size")
        if self.server_desktop_size:
            avail_w, avail_h = self.server_desktop_size
            root_w, root_h = gtk.gdk.get_default_root_window().get_size()
            if (avail_w, avail_h) < (root_w, root_h):
                log.warn("Server's virtual screen is too small -- "
                         "(server: %sx%s vs. client: %sx%s)\n"
                         "You may see strange behavior.\n"
                         "Please see "
                         "http://xpra.org/trac/ticket/10"
                         % (avail_w, avail_h, root_w, root_h))
        self._protocol._send_size = capabilities.get("packet_size", False)
        self.server_randr = capabilities.get("resize_screen", False)
        log.debug("server has randr: %s", self.server_randr)
        if self.server_randr:
            display = gtk.gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        e = capabilities.get("encoding")
        if e and e!=self.encoding:
            log.debug("server is using %s encoding" % e)
            self.encoding = e
        self.bell_enabled = capabilities.get("bell", False)
        self.notifications_enabled = capabilities.get("notifications", False)
        clipboard_server_support = capabilities.get("clipboard", True)
        self.clipboard_enabled = clipboard_server_support and self._client_extras.supports_clipboard()
        self.send_damage_sequence = capabilities.get("damage_sequence", False)
        self.can_ping = capabilities.get("ping", False)
        self.mmap_enabled = self.supports_mmap and self.mmap_file and capabilities.get("mmap_enabled")
        if self.mmap_enabled:
            log.info("mmap enabled using %s", self.mmap_file)
        self.server_start_time = capabilities.get("start_time", -1)
        self.server_platform = capabilities.get("platform")

        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        self.key_repeat_delay, self.key_repeat_interval = capabilities.get("key_repeat", (-1,-1))
        self.key_repeat_modifiers = capabilities.get("key_repeat_modifiers", False)
        self.emit("handshake-complete")
        if clipboard_server_support:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.send_clipboard_enabled_status)

    def send_clipboard_enabled_status(self, *args):
        self.send(["set-clipboard-enabled", self.clipboard_enabled])

    def set_encoding(self, encoding):
        assert encoding in ENCODINGS
        assert encoding in self.server_capabilities.get("encodings", ["rgb24"])
        self.encoding = encoding
        self.send(["encoding", encoding])

    def _screen_size_changed(self, *args):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        log.debug("sending updated screen size to server: %sx%s", root_w, root_h)
        self.send(["desktop_size", root_w, root_h])

    def _process_new_common(self, packet, override_redirect):
        (_, id, x, y, w, h, metadata) = packet
        window = ClientWindow(self, id, x, y, w, h, metadata,
                              override_redirect)
        self._id_to_window[id] = window
        self._window_to_id[window] = id
        window.show_all()

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_draw(self, packet):
        (id, x, y, width, height, coding, data) = packet[1:8]
        if len(packet)==9:
            packet_sequence = packet[8]
        else:
            packet_sequence = None
        window = self._id_to_window.get(id)
        if not window:
            return      #window is already gone!
        window.draw(x, y, width, height, coding, data)
        self.pixel_counter.append((time.time(), width*height))
        if packet_sequence and self.send_damage_sequence:
            self.send_now(["damage-sequence", packet_sequence])

    def _process_cursor(self, packet):
        (_, new_cursor) = packet
        cursor = None
        if len(new_cursor)>0:
            (_, _, w, h, xhot, yhot, serial, pixels) = new_cursor
            log.debug("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s" % (xhot,yhot, serial, w,h, len(pixels)))
            import array
            bytes = array.array('b')
            bytes.fromstring(pixels)
            pixbuf = gtk.gdk.pixbuf_new_from_data(pixels, gtk.gdk.COLORSPACE_RGB, True, 8, w, h, w * 4)
            x = max(0, min(xhot, w-1))
            y = max(0, min(yhot, h-1))
            size = gtk.gdk.display_get_default().get_default_cursor_size()
            if size>0 and (size<w or size<h):
                ratio = float(max(w,h))/size
                pixbuf = pixbuf.scale_simple(int(w/ratio), int(h/ratio), gtk.gdk.INTERP_BILINEAR)
                x = int(x/ratio)
                y = int(y/ratio)
            cursor = gtk.gdk.Cursor(gtk.gdk.display_get_default(), pixbuf, x, y)
        for window in self._window_to_id.keys():
            window.window.set_cursor(cursor)

    def _process_bell(self, packet):
        if not self.bell_enabled:
            return
        (_, id, device, percent, pitch, duration, bell_class, bell_id, bell_name) = packet
        gdkwindow = None
        if id!=0:
            try:
                gdkwindow = self._id_to_window[id].window
            except:
                pass
        if gdkwindow is None:
            gdkwindow = gtk.gdk.get_default_root_window()
        log("_process_bell(%s) gdkwindow=%s", packet, gdkwindow)
        self._client_extras.system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def _process_notify_show(self, packet):
        if not self.notifications_enabled:
            return
        (_, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout) = packet
        log("_process_notify_show(%s)", packet)
        self._client_extras.show_notify(dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout)

    def _process_notify_close(self, packet):
        if not self.notifications_enabled:
            return
        (_, id) = packet
        log("_process_notify_close(%s)", id)
        self._client_extras.close_notify(id)

    def _process_window_metadata(self, packet):
        (_, id, metadata) = packet
        window = self._id_to_window[id]
        window.update_metadata(metadata)

    def _process_configure_override_redirect(self, packet):
        (_, id, x, y, w, h) = packet
        window = self._id_to_window[id]
        window.move_resize(x, y, w, h)

    def _process_lost_window(self, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        del self._id_to_window[id]
        del self._window_to_id[window]
        if window._refresh_timer:
            gobject.source_remove(window._refresh_timer)
        window.destroy()
        if len(self._id_to_window)==0:
            log.debug("last window gone, clearing key repeat")
            self.clear_repeat()

    def _process_connection_lost(self, packet):
        log.error("Connection lost")
        self.quit()

    def _process_gibberish(self, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.emit("received-gibberish", data)

    _packet_handlers = {
        "challenge": _process_challenge,
        "disconnect": _process_disconnect,
        "hello": _process_hello,
        "new-window": _process_new_window,
        "new-override-redirect": _process_new_override_redirect,
        "draw": _process_draw,
        "cursor": _process_cursor,
        "bell": _process_bell,
        "notify_show": _process_notify_show,
        "notify_close": _process_notify_close,
        "ping": _process_ping,
        "ping_echo": _process_ping_echo,
        "window-metadata": _process_window_metadata,
        "configure-override-redirect": _process_configure_override_redirect,
        "lost-window": _process_lost_window,
        # "clipboard-*" packets are handled by a special case below.
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        if (isinstance(packet_type, str)
            and packet_type.startswith("clipboard-")):
            if self.clipboard_enabled:
                self._client_extras.process_clipboard_packet(packet)
        else:
            self._packet_handlers[packet_type](self, packet)

gobject.type_register(XpraClient)
