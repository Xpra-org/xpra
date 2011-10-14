# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2011 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
import cairo
import re

from wimpiggy.util import (n_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol
from xpra.keys import mask_to_names, MODIFIER_NAMES
from xpra.platform.gui import ClipboardProtocolHelper, ClientExtras
from xpra.scripts.main import ENCODINGS

import xpra
default_capabilities = {"__prerelease_version": xpra.__version__}

class ClientSource(object):
    def __init__(self, protocol):
        self._ordinary_packets = []
        self._mouse_position = None
        self._protocol = protocol
        self._protocol.source = self

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
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
            return packet, (bool(self._ordinary_packets)
                            or self._mouse_position is not None)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            self._mouse_position = None
            return packet, False
        else:
            return None, False

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
        self._failed_pixbuf_index = 0
        self._refresh_timer = None
        self._refresh_requested = False

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
        self._client.send(["buffer-refresh", self._id, True, 95])
        self._refresh_requested = True

    def draw(self, x, y, width, height, coding, img_data):
        gc = self._backing.new_gc()
        if coding != "rgb24":
            loader = gtk.gdk.PixbufLoader(coding)
            loader.write(img_data, len(img_data))
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf:
                if self._failed_pixbuf_index<10:
                    log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
                elif self._failed_pixbuf_index==10:
                    log.error("too many pixbuf failures! (will no longer be logged)")
                    self._failed_pixbuf_index += 1
            else:
                self._backing.draw_pixbuf(gc, pixbuf, 0, 0, x, y, width, height)
        else:
            assert len(img_data) == width * height * 3
            self._backing.draw_rgb_image(gc, x, y, width, height, gtk.gdk.RGB_DITHER_NONE, img_data)
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

    def do_unmap_event(self, event):
        if not self._override_redirect:
            self._client.send(["unmap-window", self._id])

    def do_delete_event(self, event):
        self._client.send(["close-window", self._id])
        return True

    def quit(self):
        self._client.quit()

    def void(self):
        pass

    def _key_action(self, event, depressed):
        log.debug("key_action(%s,%s)" % (event, depressed))
        modifiers = self._client.mask_to_names(event.state)
        name = gtk.gdk.keyval_name(event.keyval)
        shortcut = self._client.key_shortcuts.get(name)
        if shortcut:
            (req_mods, action) = shortcut
            mods_found = True
            for rm in req_mods:
                if rm not in modifiers:
                    mods_found = False
                    break
            if mods_found:
                if not depressed:
                    """ when the key is released, just ignore it - do NOT send it to the server! """
                    return
                try:
                    method = getattr(self, action)
                    log.info("key_action(%s,%s) has been handled by shortcut=%s" % (event, depressed, shortcut))
                except AttributeError, e:
                    log.error("key dropped, invalid method name in shortcut %s: %s" % (action, e))
                    return
                try:
                    method()
                    return
                except Exception, e:
                    log.error("key_action(%s,%s) failed to execute shortcut=%s: %s" % (event, depressed, shortcut, e))
        
        def nn(arg):
            if arg is not None:
                return  arg
            return  ""
        if self._client._raw_keycodes_feature:
            """ for versions newer than 0.0.7.24, we send ALL the raw information we have """
            keycode = event.hardware_keycode
            log.debug("key_action(%s,%s) modifiers=%s, name=%s, state=%s, keyval=%s, string=%s, keycode=%s" % (event, depressed, modifiers, name, event.state, event.keyval, event.string, keycode))
            self._client.send(["key-action", self._id, nn(name), depressed, modifiers, nn(event.keyval), nn(event.string), nn(keycode)])
        else:
            """ versions before 0.0.7.24 only accept 4 parameters (no keyval, keycode, ...) """
            # Apparently some weird keys (e.g. "media keys") can have no keyval or
            # no keyval name (I believe that both give us a None here).  Another
            # reason to upgrade to the version above
            if name is not None:
                self._client.send(["key-action", self._id, nn(name), depressed, modifiers])

    def do_key_press_event(self, event):
        self._key_action(event, True)

    def do_key_release_event(self, event):
        self._key_action(event, False)

    def _pointer_modifiers(self, event):
        pointer = (int(event.x_root), int(event.y_root))
        modifiers = self._client.mask_to_names(event.state)
        return pointer, modifiers

    def do_motion_notify_event(self, event):
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers])

    def _button_action(self, button, event, depressed):
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      pointer, modifiers])

    def do_button_press_event(self, event):
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
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
        log.debug("_focus_change(%s)" % str(args))
        self._client.update_focus(self._id,
                                  self.get_property("has-toplevel-focus"))

gobject.type_register(ClientWindow)

class XpraClient(gobject.GObject):
    __gsignals__ = {
        "handshake-complete": n_arg_signal(0),
        "received-gibberish": n_arg_signal(1),
        }

    def __init__(self, conn, opts):
        gobject.GObject.__init__(self)
        self._window_to_id = {}
        self._id_to_window = {}
        title = opts.title
        if opts.title_suffix is not None:
            title = "@title@ %s" % opts.title_suffix
        self.title = title
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
        
        self._client_extras = ClientExtras(self, opts)

        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)

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

        # FIXME: these should perhaps be merged.
        if opts.clipboard:
            self._clipboard_helper = ClipboardProtocolHelper(self.send)
        else:
            self._clipboard_helper = None

        self._focused = None
        def compute_receive_bandwidth(delay):
            bw = (self._protocol._recv_counter / 1024) * 1000/ delay;
            self._protocol._recv_counter = 0;
            log.debug("Bandwidth is ", bw, "kB/s, max ", self.max_bandwidth, "kB/s")

            if bw > self.max_bandwidth:
                self.jpegquality -= 10;
            elif bw < self.max_bandwidth:
                self.jpegquality += 5;

            if self.jpegquality > 95:
                self.jpegquality = 95;
            elif self.jpegquality < 10:
                self.jpegquality = 10;

            self.send_jpeg_quality()
            return True

        if (self.max_bandwidth):
            gobject.timeout_add(2000, compute_receive_bandwidth, 2000);


    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()
        self._client_extras.exit()
        if self._protocol:
            self._protocol.close()

    def quit(self):
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

    def query_xkbmap(self):
        self.xkbmap_print, self.xkbmap_query, self.xmodmap_data = self._client_extras.get_keymap_spec()

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
            (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
            def nn(x):
                if x is None:
                    return  ""
                return x
            self.send(["keymap-changed", nn(self.xkbmap_print), nn(self.xkbmap_query), nn(self.xmodmap_data), self.mask_to_names(current_mask)])

    def update_focus(self, id, gotit):
        def send_focus(_id):
            """ with v0.0.7.24 onwards, we want to set the modifier map when we get focus """
            if self._focus_modifiers_feature:
                (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
                self.send(["focus", _id, self.mask_to_names(current_mask)])
            else:
                self.send(["focus", _id])

        if gotit and self._focused is not id:
            send_focus(id)
            self._focused = id
        if not gotit and self._focused is id:
            send_focus(0)
            self._focused = None

    def mask_to_names(self, mask):
        return mask_to_names(mask, self._modifier_map)

    def send(self, packet):
        self._protocol.source.queue_ordinary_packet(packet)

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
        if self.xkbmap_print:
            capabilities_request["keymap"] = self.xkbmap_print
        if self.xkbmap_query:
            capabilities_request["xkbmap_query"] = self.xkbmap_query
        if self.xmodmap_data:
            capabilities_request["xmodmap_data"] = self.xmodmap_data
        capabilities_request["cursors"] = True
        capabilities_request["bell"] = True
        capabilities_request["notifications"] = self._client_extras.can_notify()
        capabilities_request["packet_size"] = True
        (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
        modifiers = self.mask_to_names(current_mask)
        log.debug("sending modifiers=%s" % str(modifiers))
        capabilities_request["modifiers"] = modifiers
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        capabilities_request["desktop_size"] = [root_w, root_h]
        capabilities_request["png_window_icons"] = True
        self.send(["hello", capabilities_request])

    def send_jpeg_quality(self):
        self.send(["jpeg-quality", self.jpegquality])

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

    def version_no_minor(self, version):
        if not version:
            return version
        p = version.rfind(".")
        if p>0:
            return version[:p]
        return version

    def _process_hello(self, packet):
        (_, capabilities) = packet
        self._raw_keycodes_feature = capabilities.get("raw_keycodes_feature", False) and \
                            (self.xkbmap_print is not None or self.xkbmap_query is not None or self.xmodmap_data is not None)
        self._focus_modifiers_feature = capabilities.get("raw_keycodes_feature", False)
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        self._remote_version = capabilities.get("__prerelease_version")
        if self.version_no_minor(self._remote_version) != self.version_no_minor(xpra.__version__):
            log.error("sorry, I only know how to talk to v%s.x servers", self.version_no_minor(xpra.__version__))
            self.quit()
            return
        if "desktop_size" in capabilities:
            avail_w, avail_h = capabilities["desktop_size"]
            root_w, root_h = gtk.gdk.get_default_root_window().get_size()
            if (avail_w, avail_h) < (root_w, root_h):
                log.warn("Server's virtual screen is too small -- "
                         "(server: %sx%s vs. client: %sx%s)\n"
                         "You may see strange behavior.\n"
                         "Please complain to "
                         "parti-discuss@partiwm.org"
                         % (avail_w, avail_h, root_w, root_h))
        if self._clipboard_helper:
            self._clipboard_helper.send_all_tokens()
        self._protocol._send_size = capabilities.get("packet_size", False)
        randr = capabilities.get("resize_screen", False)
        log.debug("server has randr: %s" % randr)
        if randr:
            display = gtk.gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        self.emit("handshake-complete")

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
        (_, id, x, y, width, height, coding, data) = packet
        window = self._id_to_window[id]
        window.draw(x, y, width, height, coding, data)

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
            cursor = gtk.gdk.Cursor(gtk.gdk.display_get_default(), pixbuf, x, y)
        for window in self._window_to_id.keys():
            window.window.set_cursor(cursor)
    
    def _process_bell(self, packet):
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
        (_, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout) = packet
        log("_process_notify_show(%s)", packet)
        self._client_extras.show_notify(dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout)

    def _process_notify_close(self, packet):
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

    def _process_connection_lost(self, packet):
        log.error("Connection lost")
        self.quit()

    def _process_gibberish(self, packet):
        [_, data] = packet
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
            if self._clipboard_helper:
                self._clipboard_helper.process_clipboard_packet(packet)
        else:
            self._packet_handlers[packet_type](self, packet)

gobject.type_register(XpraClient)
