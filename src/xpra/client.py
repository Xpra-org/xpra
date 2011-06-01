# This file is part of Parti.
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
import cairo

from wimpiggy.util import (n_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.protocol import Protocol
from xpra.keys import mask_to_names, grok_modifier_map
from xpra.platform.gui import ClipboardProtocolHelper, ClientExtras

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
        
        title_main = self._metadata.get("title", "<untitled window>").decode("utf-8")
        if "client-machine" in self._metadata:
            title_addendum = ("on %s, "
                              % (self._metadata["client-machine"].decode("utf-8"),))
        else:
            title_addendum = ""
        self.set_title(u"%s (%svia xpra)" % (title_main, title_addendum))

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

    def draw(self, x, y, width, height, rgb_data):
        assert len(rgb_data) == width * height * 3
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height,
                                     gtk.gdk.RGB_DITHER_NONE, rgb_data)
        self.window.invalidate_rect(gtk.gdk.Rectangle(x, y, width, height),
                                    False)

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
        if name is not None:
            self._client.send(["key-action", self._id, name, depressed, modifiers])

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

    def __init__(self, conn, compression_level):
        gobject.GObject.__init__(self)
        self._window_to_id = {}
        self._id_to_window = {}

        self._protocol = Protocol(conn, self.process_packet)
        ClientSource(self._protocol)
        capabilities_request = dict(default_capabilities)
        if compression_level:
            capabilities_request["deflate"] = compression_level
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        capabilities_request["desktop_size"] = [root_w, root_h]
        self.send(["hello", capabilities_request])

        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        self._xsettings_watcher = None
        self._root_props_watcher = None

        # FIXME: these should perhaps be merged.
        self._clipboard_helper = ClipboardProtocolHelper(self.send)
        self._client_extras = ClientExtras(self.send)

        self._focused = None

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()

    def _keys_changed(self, *args):
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())

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

    def _process_hello(self, packet):
        (_, capabilities) = packet
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        if capabilities.get("__prerelease_version") != xpra.__version__:
            log.error("sorry, I only know how to talk to v%s servers",
                      xpra.__version__)
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
        assert coding == "rgb24"
        window.draw(x, y, width, height, data)

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
        window.destroy()

    def _process_connection_lost(self, packet):
        log.error("Connection lost")
        gtk_main_quit_really()

    def _process_gibberish(self, packet):
        [_, data] = packet
        self.emit("received-gibberish", data)

    _packet_handlers = {
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
            self._clipboard_helper.process_clipboard_packet(packet)
        else:
            self._packet_handlers[packet_type](self, packet)

gobject.type_register(XpraClient)
