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
from xpra.keys import mask_to_names
from xpra.platform.gui import ClipboardProtocolHelper, ClientExtras, grok_modifier_map

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
        self._refresh_requested = 0

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
            assert coding == "premult_argb32"
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

    def _automatic_refresh_cb(self):
        log.debug("Automatic refresh for id ", self._id)
        self._client.send(["buffer-refresh", self._id, True, 95])
        self._refresh_requested = 1

    def draw(self, x, y, width, height, coding, img_data):
        gc = self._backing.new_gc()
        if coding != "rgb24":
            loader = gtk.gdk.PixbufLoader(coding)
            loader.write(img_data, len(img_data))
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf:
                if self._failed_pixbuf_index<10:
                    import os.path, sys
                    if sys.platform.startswith("win"):
                        appdata = os.environ.get("APPDATA")
                        if not os.path.exists(appdata):
                            os.mkdir(appdata)
                        xpra_path = os.path.join(appdata, "Xpra")
                        if not os.path.exists(xpra_path):
                            os.mkdir(xpra_path)
                    else:
                        xpra_path = os.path.expanduser("~/.xpra")
                    failed_pixbuf_file = os.path.join(xpra_path, "failed-%s.%s" % (self._failed_pixbuf_index, coding))
                    f = open(failed_pixbuf_file, 'wb')
                    f.write(img_data)
                    f.close()
                    self._failed_pixbuf_index += 1
                    log.error("failed %s pixbuf=%s data saved to %s, len=%s" % (coding, pixbuf, failed_pixbuf_file, len(img_data)))
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
            self._refresh_requested = 0
        else:
            if self._refresh_timer:
                gobject.source_remove(self._refresh_timer)
            if self._client.refresh_delay:
                self._refresh_timer = gobject.timeout_add(int(1000 * self._client.refresh_delay), self._automatic_refresh_cb)

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

    def _key_action(self, event, depressed):
        modifiers = self._client.mask_to_names(event.state)
        name = gtk.gdk.keyval_name(event.keyval)
        # Apparently some weird keys (e.g. "media keys") can have no keyval or
        # no keyval name (I believe that both give us a None here).  Another
        # reason to overhaul keyboard support:
        def nn(arg):
            if arg is not None:
                return  arg
            return  ""
        v = self._client.minor_version_int(self._client._remote_version)
        if v>=24:
            """ for versions newer than 0.0.7.24, we send ALL the raw information we have """
            keycode = event.hardware_keycode
            log.debug("key_action(%s,%s) modifiers=%s, name=%s, state=%s, keyval=%s, string=%s, keycode=%s" % (event, depressed, modifiers, name, event.state, event.keyval, event.string, keycode))
            self._client.send(["key-action", self._id, nn(name), depressed, modifiers, nn(event.keyval), nn(event.string), nn(keycode)])
        else:
            """ versions before 0.0.7.24 only accept 4 parameters (no keyval, keycode, ...) """
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
        self._client.update_focus(self._id,
                                  self.get_property("has-toplevel-focus"))

gobject.type_register(ClientWindow)

class XpraClient(gobject.GObject):
    __gsignals__ = {
        "handshake-complete": n_arg_signal(0),
        "received-gibberish": n_arg_signal(1),
        }

    def __init__(self, conn, compression_level, jpegquality, title, password_file,
                 pulseaudio, clipboard, refresh_delay, max_bandwidth, opts):
        gobject.GObject.__init__(self)
        self._window_to_id = {}
        self._id_to_window = {}
        self.title = title
        self.password_file = password_file
        self.compression_level = compression_level
        self.jpegquality = jpegquality
        self.refresh_delay = refresh_delay
        self.max_bandwidth = max_bandwidth
        if self.max_bandwidth>0.0 and self.jpegquality==0:
            """ jpegquality was not set, use a better start value """
            self.jpegquality = 50

        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)

        self._remote_version = None
        self._keymap_changing = False
        self._keymap = gtk.gdk.keymap_get_default()
        self._do_keys_changed()
        self.send_hello()

        self._keymap.connect("keys-changed", self._keys_changed)
        self._xsettings_watcher = None
        self._root_props_watcher = None

        # FIXME: these should perhaps be merged.
        if clipboard:
            self._clipboard_helper = ClipboardProtocolHelper(self.send)
        else:
            self._clipboard_helper = None
        self._client_extras = ClientExtras(self.send, pulseaudio, opts)

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

    def query_xkbmap(self):
        def get_keyboard_data(command, arg):
            # Find the client's current keymap so we can send it to the server:
            try:
                import subprocess
                cmd = [command, arg]
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
                (out,_) = process.communicate(None)
                if process.returncode==0:
                    return out
                log.error("'%s %s' failed with exit code %s\n" % (command, arg, process.returncode))
            except Exception, e:
                log.error("error running '%s %s': %s\n" % (command, arg, e))
            return None
        self.xkbmap_print = get_keyboard_data("setxkbmap", "-print")
        if self.xkbmap_print is None:
            log.error("your keyboard mapping will probably be incorrect unless you are using a 'us' layout");
        self.xkbmap_query = get_keyboard_data("setxkbmap", "-query")
        if self.xkbmap_query is None and self.xkbmap_print is not None:
            log.error("the server will try to guess your keyboard mapping, which works reasonably well in most cases");
            log.error("however, upgrading 'setxkbmap' to a version that supports the '-query' parameter is preferred");
        self.xmodmap_data = get_keyboard_data("xmodmap", "-pke");

    def _keys_changed(self, *args):
        self._keymap = gtk.gdk.keymap_get_default()
        if not self._keymap_changing:
            self._keymap_changing = True
            gobject.timeout_add(500, self._do_keys_changed, True)

    def _do_keys_changed(self, sendkeymap=False):
        self._keymap_changing = False
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())
        if sendkeymap:
            #old clients won't know what to do with it, but that's ok
            self.query_xkbmap()
            log.info("keys_changed")
            (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
            self.send(["keymap-changed", self.xkbmap_print, self.xkbmap_query, self.xmodmap_data, self.mask_to_names(current_mask)])

    def update_focus(self, id, gotit):
        if gotit and self._focused is not id:
            self.send(["focus", id])
            self._focused = id
        if not gotit and self._focused is id:
            self.send(["focus", 0])
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
        if self.jpegquality:
            capabilities_request["jpeg"] = self.jpegquality
        self.query_xkbmap()
        if self.xkbmap_print:
            capabilities_request["keymap"] = self.xkbmap_print
        if self.xkbmap_query:
            capabilities_request["xkbmap_query"] = self.xkbmap_query
        if self.xmodmap_data:
            capabilities_request["xmodmap_data"] = self.xmodmap_data
        (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
        modifiers = self.mask_to_names(current_mask)
        log.debug("sending modifiers=%s" % str(modifiers))
        capabilities_request["modifiers"] = modifiers
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        capabilities_request["desktop_size"] = [root_w, root_h]
        self.send(["hello", capabilities_request])

    def send_jpeg_quality(self):
        self.send(["jpeg-quality", self.jpegquality])

    def _process_disconnect(self, packet):
        log.error("server requested disconnect: %s" % str(packet))
        gtk.main_quit()
        return

    def _process_challenge(self, packet):
        if not self.password_file:
            log.error("password is required by the server")
            gtk.main_quit()
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

    def minor_version_int(self, version):
        if not version:
            return 0
        p = version.rfind(".")
        if p>0:
            return int(version[p+1:])
        return 0

    def _process_hello(self, packet):
        (_, capabilities) = packet
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        self._remote_version = capabilities.get("__prerelease_version")
        if self.version_no_minor(self._remote_version) != self.version_no_minor(xpra.__version__):
            log.error("sorry, I only know how to talk to v%s.x servers", self.version_no_minor(xpra.__version__))
            gtk.main_quit()
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
        self._client_extras.handshake_complete(capabilities)
        self.emit("handshake-complete")

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
        gtk_main_quit_really()

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
