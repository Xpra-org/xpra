# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2011 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   cursors
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk
import gobject
import cairo
import sys
import subprocess
import hmac
import uuid
import Image
import StringIO
import re
import os

from wimpiggy.wm import Wm
from wimpiggy.util import (AdHocStruct,
                           one_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from wimpiggy.lowlevel import (get_rectangle_from_region, #@UnresolvedImport
                               xtest_fake_key, #@UnresolvedImport
                               xtest_fake_button, #@UnresolvedImport
                               is_override_redirect, is_mapped, #@UnresolvedImport
                               add_event_receiver, #@UnresolvedImport
                               get_children, #@UnresolvedImport
                               has_randr, get_screen_sizes, set_screen_size) #@UnresolvedImport
from wimpiggy.prop import prop_set
from wimpiggy.window import OverrideRedirectWindowModel, Unmanageable
from wimpiggy.keys import grok_modifier_map
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.protocol import Protocol, SocketConnection
from xpra.keys import mask_to_names
from xpra.xposix.xclipboard import ClipboardProtocolHelper
from xpra.xposix.xsettings import XSettingsManager

class DesktopManager(gtk.Widget):
    def __init__(self):
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)
        self._models = {}

    ## For communicating with the main WM:

    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = AdHocStruct()
        s.shown = False
        s.geom = (x, y, w, h)
        s.window = None
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def configure_window(self, model, x, y, w, h):
        self._models[model].geom = (x, y, w, h)
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def raise_window(self, model):
        if isinstance(model, OverrideRedirectWindowModel):
            model.get_property("client-window").raise_()
        else:
            window = self._models[model].window
            if window is not None:
                window.raise_()

    ## For communicating with WindowModels:

    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self.visible(model):
            return (1, self)
        else:
            return (-1, self)

    def take_window(self, model, window):
        window.reparent(self.window, 0, 0)
        self._models[model].window = window

    def window_size(self, model):
        (x, y, w, h) = self._models[model].geom
        return (w, h)

    def window_position(self, model, w, h):
        (x, y, w0, h0) = self._models[model].geom
        if (w0, h0) != (w, h):
            log.warn("Uh-oh, our size doesn't fit window sizing constraints!")
        return (x, y)

gobject.type_register(DesktopManager)

class ServerSource(object):
    # Strategy: if we have ordinary packets to send, send those.  When we
    # don't, then send window updates.
    def __init__(self, protocol):
        self._ordinary_packets = []
        self._protocol = protocol
        self._damage = {}
        protocol.source = self
        if self._have_more():
            protocol.source_has_more()

    def _have_more(self):
        return bool(self._ordinary_packets) or bool(self._damage)

    def send_packet_now(self, packet):
        assert self._protocol
        self._ordinary_packets.insert(0, packet)
        self._protocol.source_has_more()

    def queue_ordinary_packet(self, packet):
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def cancel_damage(self, id):
        if id in self._damage:
            del self._damage[id]

    def damage(self, id, window, x, y, w, h):
        log("damage %s (%s, %s, %s, %s)", id, x, y, w, h)
        window, region = self._damage.setdefault(id,
                                                 (window, gtk.gdk.Region()))
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._protocol.source_has_more()

    def next_packet(self):
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._damage:
            id, (window, damage) = self._damage.items()[0]
            (x, y, w, h) = get_rectangle_from_region(damage)
            rect = gtk.gdk.Rectangle(x, y, w, h)
            damage.subtract(gtk.gdk.region_rectangle(rect))
            if damage.empty():
                del self._damage[id]
            # It's important to acknowledge changes *before* we extract them,
            # to avoid a race condition.
            window.acknowledge_changes(x, y, w, h)
            pixmap = window.get_property("client-contents")
            if pixmap is None:
                log.error("wtf, pixmap is None?")
                packet = None
            else:
                (x2, y2, w2, h2, coding, data) = self._get_rgb_data(pixmap, x, y, w, h)
                if not w2 or not h2:
                    packet = None
                else:
                    packet = ["draw", id, x2, y2, w2, h2, coding, data]
        else:
            packet = None
        return packet, self._have_more()

    def _get_rgb_data(self, pixmap, x, y, width, height):
        pixmap_w, pixmap_h = pixmap.get_size()
        coding = "rgb24"
        # Just in case we somehow end up with damage larger than the pixmap,
        # we don't want to start requesting random chunks of memory (this
        # could happen if a window is resized but we don't throw away our
        # existing damage map):
        assert x >= 0
        assert y >= 0
        if x + width > pixmap_w:
            width = pixmap_w - x
        if y + height > pixmap_h:
            height = pixmap_h - y
        if width <= 0 or height <= 0:
            return (0, 0, 0, 0, coding, "")
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(),
                                 x, y, 0, 0, width, height)
        raw_data = pixbuf.get_pixels()
        rowwidth = width * 3
        rowstride = pixbuf.get_rowstride()
        if rowwidth == rowstride:
            data = raw_data
        else:
            rows = []
            for i in xrange(height):
                rows.append(raw_data[i*rowstride : i*rowstride+rowwidth])
            data = "".join(rows)
        # should probably have some other conditions for
        # enabling jpeg compression (for example len(data) > N and/or
        # width*height > M)
        if self._protocol.jpegquality > 0:
            log.debug("sending with quality ", self._protocol.jpegquality)
            im = Image.fromstring("RGB", (width,height), data)
            buf=StringIO.StringIO()
            im.save(buf,"JPEG", quality=self._protocol.jpegquality)
            data=buf.getvalue()
            buf.close()
            coding = "jpeg"

        return (x, y, width, height, coding, data)


class XpraServer(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets, password_file, pulseaudio, clipboard, randr):
        gobject.GObject.__init__(self)

        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
        add_event_receiver(root, self)

        # This must happen early, before loading in windows at least:
        self._protocol = None
        self._potential_protocols = []

        ### Create the WM object
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        for window in get_children(root):
            if (is_override_redirect(window) and is_mapped(window)):
                self._add_new_or_window(window)
        
        ## These may get set by the client:
        self.xkbmap_print = None
        self.xkbmap_query = None

        ### Set up keymap:
        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        try:
            self.signal_safe_exec(["xmodmap", "-"],
                            """clear Lock
                               clear Shift
                               clear Control
                               clear Mod1
                               clear Mod2
                               clear Mod3
                               clear Mod4
                               clear Mod5
                               keycode any = Shift_L
                               keycode any = Control_L
                               keycode any = Meta_L
                               keycode any = Alt_L
                               keycode any = Hyper_L
                               keycode any = Super_L
                               add Shift = Shift_L Shift_R
                               add Control = Control_L Control_R
                               add Mod1 = Meta_L Meta_R
                               add Mod2 = Alt_L Alt_R
                               add Mod3 = Hyper_L Hyper_R
                               add Mod4 = Super_L Super_R
                            """
                            # Really stupid hack to force backspace to work.
                            # Remove this once we have real keymap support.
                            + "keycode any = BackSpace")
        except OSError, e:
            sys.stderr.write("Error running xmodmap: %s\n" % (e,))
        self._keyname_for_mod = {
            "shift": "Shift_L",
            "control": "Control_L",
            "meta": "Meta_L",
            "super": "Super_L",
            "hyper": "Hyper_L",
            "alt": "Alt_L",
            }

        ### Clipboard handling:
        if clipboard:
            self._clipboard_helper = ClipboardProtocolHelper(self._send)
        else:
            self._clipboard_helper = None

        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None
        self._has_focus = 0
        self._upgrading = False

        self.password_file = password_file
        self.salt = None

        self.randr = randr and has_randr()
        log.info("randr enabled: %s" % self.randr)

        self.pulseaudio = pulseaudio

        ### All right, we're ready to accept customers:
        for sock in sockets:
            self.add_listen_socket(sock)

    def set_keymap(self):
        """ xkbmap_print is the output of setxkbmap -print on the client
            xkbmap_query is the output of setxkbmap -query on the client
            Use those to try to setup the correct keyboard map for the client
            so that all the keycodes sent will be mapped
        """
        def exec_setxkbmap(args):
            try:
                self.signal_safe_exec(["setxkbmap"]+args, None)
                log.info("successfully called setxkbmap %s" % str(args))
            except Exception, e:
                log.info("error calling 'setxkbmap %s': %s" % (str(args), e))
        #First we try to use data from setxkbmap -query
        if self.xkbmap_query:
            """ The xkbmap_query data will look something like this:
            rules:      evdev
            model:      evdev
            layout:     gb
            options:    grp:shift_caps_toggle
            And we want to call something like:
            setxkbmap -rules evdev -model evdev -layout gb
            setxkbmap -option "" -option grp:shift_caps_toggle
            (we execute the options separately in case that fails..)
            """
            #parse the data into a dict:
            settings = {}
            opt_re = re.compile("(\w*):\s*(.*)")
            for line in self.xkbmap_query.splitlines():
                m = opt_re.match(line)
                if m:
                    settings[m.group(1)] = m.group(2).strip()
            #construct the command line arguments for setxkbmap:
            args = []
            for setting in ["rules", "model", "layout"]:
                if setting in settings:
                    args += ["-%s" % setting, settings.get(setting)]
            if len(args)>0:
                exec_setxkbmap(args)
            #try to set the options:
            if "options" in settings:
                exec_setxkbmap(["-option", "", "-option", settings.get("options")])
        elif self.xkbmap_print:
            #try to guess the layout by parsing "setxkbmap -print"
            try: 
                sym_re = re.compile("\s*xkb_symbols\s*{\s*include\s*\"([\w\+]*)") 
                for line in self.xkbmap_print.splitlines(): 
                    m = sym_re.match(line) 
                    if m:
                        layout = m.group(1) 
                        log.info("guessing keyboard layout='%s'" % layout) 
                        exec_setxkbmap([layout])
                        break 
            except Exception, e: 
                log.info("error setting keymap: %s" % e) 

        if self.xkbmap_print:
            try:
                returncode = self.signal_safe_exec(["xkbcomp", "-", os.environ.get("DISPLAY")], self.xkbmap_print)
                if returncode==0:
                    log.info("xkbcomp successfully applied new keymap")
                else:
                    log.info("xkbcomp failed with exit code %s\n" % returncode)
            except Exception, e:
                log.info("error setting keymap: %s" % e)

    def signal_safe_exec(self, cmd, stdin):
        """ this is a bit of a hack,
        the problem is that we won't catch SIGCHLD at all while this command is running! """
        import signal
        try:
            oldsignal = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            process.communicate(stdin)
            return  process.poll()
        finally:
            signal.signal(signal.SIGCHLD, oldsignal)


    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def quit(self, upgrading):
        self._upgrading = upgrading
        log.info("\nxpra is terminating.")
        sys.stdout.flush()
        gtk_main_quit_really()

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        def print_ready():
            log.info("\nxpra is ready.")
            sys.stdout.flush()
        gobject.idle_add(print_ready)
        gtk.main()
        log.info("\nxpra end of gtk.main().")
        return self._upgrading

    def _new_connection(self, listener, *args):
        log.info("New connection received")
        sock, addr = listener.accept()
        self._potential_protocols.append(Protocol(SocketConnection(sock),
                                                  self.process_packet))
        return True

    def _keys_changed(self, *args):
        self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default())

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_child_map_event(self, event):
        raw_window = event.window
        if event.override_redirect:
            self._add_new_or_window(raw_window)

    _window_export_properties = ("title", "size-hints")

    def _add_new_window_common(self, window):
        id = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = id
        self._id_to_window[id] = window
        window.connect("client-contents-changed", self._contents_changed)
        window.connect("unmanaged", self._lost_window)

    def _add_new_window(self, window):
        log("Discovered new ordinary window")
        self._add_new_window_common(window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, depth) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)

    def _add_new_or_window(self, raw_window):
        log("Discovered new override-redirect window")
        try:
            window = OverrideRedirectWindowModel(raw_window)
        except Unmanageable:
            return
        self._add_new_window_common(window)
        window.connect("notify::geometry", self._or_window_geometry_changed)
        self._send_new_or_window_packet(window)

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        id = self._window_to_id[window]
        self._send(["configure-override-redirect", id, x, y, w, h])

    # These are the names of WindowModel properties that, when they change,
    # trigger updates in the xpra window metadata:
    _all_metadata = ("title", "size-hints", "class-instance", "icon", "client-machine")

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property:
    def _make_metadata(self, window, propname):
        assert propname in self._all_metadata
        if propname == "title":
            if window.get_property("title") is not None:
                return {"title": window.get_property("title").encode("utf-8")}
            else:
                return {}
        elif propname == "size-hints":
            hints_metadata = {}
            hints = window.get_property("size-hints")
            for attr, metakey in [
                ("max_size", "maximum-size"),
                ("min_size", "minimum-size"),
                ("base_size", "base-size"),
                ("resize_inc", "increment"),
                ("min_aspect_ratio", "minimum-aspect"),
                ("max_aspect_ratio", "maximum-aspect"),
                ]:
                if hints is not None and getattr(hints, attr) is not None:
                    hints_metadata[metakey] = getattr(hints, attr)
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is not None:
                return {"class-instance": [x.encode("utf-8") for x in c_i]}
            else:
                return {}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is not None:
                assert surf.get_format() == cairo.FORMAT_ARGB32
                assert surf.get_stride() == 4 * surf.get_width()
                return {"icon": (surf.get_width(), surf.get_height(),
                                 "premult_argb32", str(surf.get_data()))
                        }
            else:
                return {}
        elif propname == "client-machine":
            client_machine = window.get_property("client-machine")
            if client_machine is not None:
                return {"client-machine": client_machine.encode("utf-8")}
            else:
                return {}

        else:
            assert False

    def _keycodes(self, keyname):
        keyval = gtk.gdk.keyval_from_name(keyname)
        entries = self._keymap.get_entries_for_keyval(keyval)
        keycodes = []
        for _keycode,_group,_level in entries:
            keycodes.append(_keycode)
        return  keycodes

    def _keycode(self, keycode, string, keyval, keyname, group=0, level=0):
        log.debug("keycode(%s,%s,%s,%s,%s,%s)" % (keycode, string, keyval, keyname, group, level))
        if keycode and self.xkbmap_print is not None:
            """ versions 0.0.7.24 and above give us the raw keycode,
                we can only use this if we have applied the same keymap - if the client sent one
            """
            return  keycode
        # fallback code for older versions:
        if not keyval:
            keyval = gtk.gdk.keyval_from_name(keyname)
        entries = self._keymap.get_entries_for_keyval(keyval)
        if not entries:
            log.error("no keycode found for keyname=%s, keyval=%s" % (keyname, keyval))
            return None
        kc = -1
        if group>=0:
            for _keycode,_group,_level in entries:
                if _group!=group:
                    continue
                if kc==-1 or _level==level:
                    kc = _keycode
        log.debug("keycode(%s,%s,%s,%s,%s,%s)=%s" % (keycode, string, keyval, keyname, group, level, kc))
        if kc>0:
            return  kc
        return entries[0][0]    #nasty fallback!

    def _make_keymask_match(self, modifier_list):
        #FIXME: we should probably cache the keycode
        # and clear the cache in _keys_changed
        def get_current_mask():
            (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
            return  mask_to_names(current_mask, self._modifier_map)
        current = set(get_current_mask())
        wanted = set(modifier_list)
        #print("_make_keymask_match(%s) current mask: %s, wanted: %s\n" % (modifier_list, current, wanted))
        display = gtk.gdk.display_get_default()
        for modifier in current.difference(wanted):
            keyname = self._keyname_for_mod[modifier]
            keycodes = self._keycodes(keyname)
            for keycode in keycodes:
                xtest_fake_key(display, keycode, False)
                new_mask = get_current_mask()
                #print("_make_keymask_match(%s) removed modifier %s using %s: %s" % (modifier_list, modifier, keycode, (modifier not in new_mask)))
                if modifier not in new_mask:
                    break
        for modifier in wanted.difference(current):
            keyname = self._keyname_for_mod[modifier]
            keycodes = self._keycodes(keyname)
            for keycode in keycodes:
                xtest_fake_key(display, keycode, True)
                new_mask = get_current_mask()
                #print("_make_keymask_match(%s) added modifier %s using %s: %s" % (modifier_list, modifier, keycode, (modifier in new_mask)))
                if modifier in new_mask:
                    break

    def _focus(self, id):
        if self._has_focus != id:
            if id == 0:
                # FIXME: kind of a hack:
                self._wm.get_property("toplevel").reset_x_focus()
            else:
                window = self._id_to_window[id]
                window.give_client_focus()
            self._has_focus = id

    def _move_pointer(self, pos):
        (x, y) = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _send(self, packet):
        if self._protocol is not None:
            log("Queuing packet: %s", packet)
            self._protocol.source.queue_ordinary_packet(packet)

    def _damage(self, window, x, y, width, height):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.damage(id, window, x, y, width, height)

    def _cancel_damage(self, window):
        if self._protocol is not None and self._protocol.source is not None:
            id = self._window_to_id[window]
            self._protocol.source.cancel_damage(id)

    def _send_new_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = self._desktop_manager.window_geometry(window)
        metadata = {}
        for propname in self._all_metadata:
            metadata.update(self._make_metadata(window, propname))
        self._send(["new-window", id, x, y, w, h, metadata])

    def _send_new_or_window_packet(self, window):
        id = self._window_to_id[window]
        (x, y, w, h) = window.get_property("geometry")
        self._send(["new-override-redirect", id, x, y, w, h, {}])
        self._damage(window, 0, 0, w, h)

    def _update_metadata(self, window, pspec):
        id = self._window_to_id[window]
        metadata = self._make_metadata(window, pspec.name)
        self._send(["window-metadata", id, metadata])

    def _lost_window(self, window, wm_exiting):
        id = self._window_to_id[window]
        self._send(["lost-window", id])
        self._cancel_damage(window)
        del self._window_to_id[window]
        del self._id_to_window[id]

    def _contents_changed(self, window, event):
        if (isinstance(window, OverrideRedirectWindowModel)
            or self._desktop_manager.visible(window)):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _calculate_capabilities(self, client_capabilities):
        capabilities = {}
        for cap in ("deflate", "__prerelease_version", "challenge_response", "jpeg", "keymap", "xkbmap_query"):
            if cap in client_capabilities:
                capabilities[cap] = client_capabilities[cap]
        return capabilities

    def _get_desktop_size_capability(self, client_capabilities):
        (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
        if "desktop_size" not in client_capabilities:
            """ client did not specify size, just return what we have """
            return	root_w, root_h
        client_w, client_h = client_capabilities["desktop_size"]
        if not self.randr:
            """ server does not support randr - return minimum of the client/server dimensions """
            w = min(client_w, root_w)
            h = min(client_h, root_h)
            return	w,h

        if client_w==root_w or client_h==root_h:
            return	root_w,root_h	#unlikely: perfect match!

        log.debug("client resolution is %sx%s, current server resolution is %sx%s" % (client_w,client_h,root_w,root_h))

        #try to find the best screen size to resize to:
        new_size = None
        for w,h in get_screen_sizes():
            if w<client_w or h<client_h:
                continue			#size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue		#we found a better (smaller) candidate already
            new_size = w,h
        log.info("best resolution for client(%sx%s) is: %s" % (client_w,client_h,new_size))
        if new_size:
            w, h = new_size
            try:
                set_screen_size(w, h)
                (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
                log.info("our new resolution is: %sx%s" % (root_w,root_h))
            except Exception, e:
                log.error("failed to set new resolution: %s" % e)
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return w,h

    def version_no_minor(self, version):
        if not version:
            return    version
        p = version.rfind(".")
        if p>0:
            return version[:p]
        else:
            return version

    def _process_hello(self, proto, packet):
        (_, client_capabilities) = packet
        log.info("Handshake complete; enabling connection")
        capabilities = self._calculate_capabilities(client_capabilities)
        remote_version = capabilities.get("__prerelease_version")
        if self.version_no_minor(remote_version) != self.version_no_minor(xpra.__version__):
            log.error("Sorry, this pre-release server only works with clients "
                      + "of the same major version (v%s), but this client is using v%s", xpra.__version__, remote_version)
            proto.close()
            return
        if self.password_file:
            log.debug("password auth required")
            client_hash = capabilities.get("challenge_response")
            if not client_hash or not self.salt:
                self.salt = "%s" % uuid.uuid4()
                capabilities["challenge"] = self.salt
                log.info("Password required, sending challenge")
                packet = ("challenge", self.salt)
                socket = proto._conn._s
                log.debug("proto=%s, conn=%s, socket=%s" % (repr(proto), repr(proto._conn), socket))
                from xpra.bencode import bencode
                import select
                data = bencode(packet)
                written = 0
                while written < len(data):
                    select.select([], [socket], [])
                    written += socket.send(data[written:])
                return
            passwordFile = open(self.password_file, "rU")
            password  = passwordFile.read()
            hash = hmac.HMAC(password, self.salt)
            if client_hash != hash.hexdigest():
                log.error("Password supplied does not match! dropping the connection.")
                def login_failed(*args):
                    proto.close()
                gobject.timeout_add(1000, login_failed)
                return
            else:
                log.info("Password matches!")
                sys.stdout.flush()
                del capabilities["challenge_response"]
                self.salt = None            #prevent replay attacks

        # Okay, things are okay, so let's boot out any existing connection and
        # set this as our new one:
        if self._protocol is not None:
            log.info("Disconnecting existing client")
            # send message asking for disconnection politely:
            self._protocol.source.send_packet_now(["disconnect", "new valid connection received"])
            def force_disconnect(protocol):
                protocol.close()
            #give 5 seconds for the write buffer to flush then we force disconnect it:
            gobject.timeout_add(5000, force_disconnect, self._protocol)
        self._protocol = proto
        ServerSource(self._protocol)
        # do screen size calculations/modifications:
        capabilities["desktop_size"] = self._get_desktop_size_capability(client_capabilities)
        self._send(["hello", capabilities])
        if "deflate" in capabilities:
            self._protocol.enable_deflate(capabilities["deflate"])
        if "jpeg" in capabilities:
            self._protocol.jpegquality = capabilities["jpeg"]
        if "keymap" in capabilities:
            self.xkbmap_print = capabilities["keymap"]
            self.xkbmap_query = capabilities.get("xkbmap_query", None)
            self.set_keymap()
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        for id in sorted(self._id_to_window.iterkeys()):
            window = self._id_to_window[id]
            if isinstance(window, OverrideRedirectWindowModel):
                self._send_new_or_window_packet(window)
            else:
                self._desktop_manager.hide_window(window)
                self._send_new_window_packet(window)

    def _process_server_settings(self, proto, packet):
        (_, settings) = packet
        old_settings = dict(self._settings)
        self._settings.update(settings)
        for k, v in settings.iteritems():
            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    prop_set(gtk.gdk.get_default_root_window(),
                             p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self._xsettings_manager = XSettingsManager(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
                elif self.pulseaudio:
                    if k == "pulse-cookie":
                        root_set("PULSE_COOKIE")
                    elif k == "pulse-id":
                        root_set("PULSE_ID")
                    elif k == "pulse-server":
                        root_set("PULSE_SERVER")

    def _process_map_window(self, proto, packet):
        (_, id, x, y, width, height) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        self._damage(window, 0, 0, width, height)

    def _process_unmap_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.hide_window(window)
        self._cancel_damage(window)

    def _process_move_window(self, proto, packet):
        (_, id, x, y) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        (_, id, w, h) = packet
        window = self._id_to_window[id]
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._cancel_damage(window)
        if self._desktop_manager.visible(window):
            self._damage(window, 0, 0, w, h)
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_focus(self, proto, packet):
        (_, id) = packet
        self._focus(id)
    
    def _process_keymap(self, proto, packet):
        (_, keymap, xkbmap_query) = packet
        self.xkbmap_print = keymap
        self.xkbmap_query = xkbmap_query
        self.set_keymap()

    def _process_key_action(self, proto, packet):
        if len(packet)==5:
            (_, id, keyname, depressed, modifiers) = packet
            keyval = None
            keycode = None
            string = None
        elif len(packet)==8:
            (_, id, keyname, depressed, modifiers, keyval, string, keycode) = packet
        else:
            raise Exception("invalid number of arguments for key-action: %s" % len(packet))
        self._make_keymask_match(modifiers)
        self._focus(id)
        level = 0
        if "shift" in modifiers:
            level = 1
        group = 0
        #not sure this is right...
        if "meta" in modifiers:
            group = 1
        if not keycode:
            keycode = self._keycode(string, keyval, keyname, group=group, level=level)
        log.debug("now %spressing keycode=%s, keyname=%s", depressed, keycode, keyname)
        if keycode:
            xtest_fake_key(gtk.gdk.display_get_default(), keycode, depressed)

    def _process_button_action(self, proto, packet):
        (_, id, button, depressed, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        self._desktop_manager.raise_window(self._id_to_window[id])
        self._move_pointer(pointer)
        try:
            trap.call_unsynced(xtest_fake_button,
                               gtk.gdk.display_get_default(),
                               button, depressed)
        except XError:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        (_, id, pointer, modifiers) = packet
        self._make_keymask_match(modifiers)
        if id in self._id_to_window:
            self._desktop_manager.raise_window(self._id_to_window[id])
            self._move_pointer(pointer)
        else:
            log.error("_process_pointer_position() invalid window id: %s" % id)

    def _process_close_window(self, proto, packet):
        (_, id) = packet
        window = self._id_to_window[id]
        window.request_close()

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        self.quit(False)

    def _process_buffer_refresh(self, proto, packet):
        (_, id, _, jpeg_qual) = packet
        window = self._id_to_window[id]
        log.debug("Requested refresh for window ", id)
        qual_save = self._protocol.jpegquality
        self._protocol.jpegquality = jpeg_qual
        (_, _, w, h) = window.get_property("geometry")
        self._damage(window, 0, 0, w, h)
        self._protocol.jpegquality = qual_save

    def _process_jpeg_quality(self, proto, packet):
        (_, quality) = packet
        log.debug("Setting JPEG quality to ", quality)
        self._protocol.jpegquality = quality

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        proto.close()
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if proto is self._protocol:
            log.info("xpra client disconnected.")
            self._protocol = None
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        (_, data) = packet
        log.info("Received uninterpretable nonsense: %s", repr(data))

    _packet_handlers = {
        "hello": _process_hello,
        "server-settings": _process_server_settings,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "keymap-changed": _process_keymap,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        "jpeg-quality": _process_jpeg_quality,
        "buffer-refresh": _process_buffer_refresh,
        # "clipboard-*" packets are handled below:
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
            self._packet_handlers[packet_type](self, proto, packet)

gobject.type_register(XpraServer)
