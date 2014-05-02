# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import gobject
try:
    #we *have to* do this as early as possible on win32..
    gobject.threads_init()
except:
    pass
import gtk
from gtk import gdk
gdk.threads_init()


from xpra.platform.ui_thread_watcher import get_UI_watcher
UI_watcher = get_UI_watcher(gobject.timeout_add)

from xpra.gtk_common.gtk2common import gtk2main
from xpra.client.gtk_base.gtk_client_base import GTKXpraClient, xor_str
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.gtk_common.cursor_names import cursor_names
from xpra.client.window_border import WindowBorder
from xpra.log import Logger

log = Logger("gtk", "client")
cursorlog = Logger("gtk", "client", "cursor")
clipboardlog = Logger("gtk", "client", "clipboard")
grablog = Logger("gtk", "client", "grab")

from xpra.client.gtk2.border_client_window import BorderClientWindow
from xpra.client.gtk2.client_window import ClientWindow
from xpra.client.gtk2.custom_client_window import CustomClientWindow
WINDOW_LAYOUTS = {
                  "border"  : BorderClientWindow,
                  "default" : ClientWindow,
                  "custom"  : CustomClientWindow,
                  }

FAKE_UI_LOCKUPS = int(os.environ.get("XPRA_FAKE_UI_LOCKUPS", "0"))

missing_cursor_names = set()


class XpraClient(GTKXpraClient):

    def __init__(self):
        GTKXpraClient.__init__(self)
        self.border = None
        self.GLClientWindowClass = None
        self.local_clipboard_requests = 0
        self.remote_clipboard_requests = 0

        #avoid ugly "not implemented" warning on win32
        self.supports_group_leader = not sys.platform.startswith("win")

        self._ref_to_group_leader = {}
        self._group_leader_wids = {}

    def init(self, opts):
        GTKXpraClient.init(self, opts)
        if opts.window_layout:
            assert opts.window_layout in WINDOW_LAYOUTS
            self.ClientWindowClass = WINDOW_LAYOUTS.get(opts.window_layout)
        else:
            self.ClientWindowClass = BorderClientWindow
        log("init(..) ClientWindowClass=%s", self.ClientWindowClass)


    def parse_border(self, border_str):
        parts = [x.strip() for x in border_str.split(",")]
        color_str = parts[0]
        if color_str.lower()=="none":
            return
        if color_str=="auto":
            try:
                import hashlib
                m = hashlib.sha1()
                m.update(self._protocol._conn.target)
                color_str = "#%s" % m.hexdigest()[:6]
                log("border color derived from %s: %s", self._protocol._conn.target, color_str)
            except:
                #fail: default to red
                color_str = "red"
        try:
            color = gtk.gdk.color_parse(color_str)
        except Exception, e:
            log.warn("invalid color specified: %s (%s)", color_str, e)
            color = gtk.gdk.Color("red")
        alpha = 0.6
        size = 4
        if len(parts)==2:
            size_str = parts[1]
            try:
                size = int(size_str)
            except Exception, e:
                log.warn("invalid size specified: %s (%s)", size_str, e)
            if size<=0:
                log("border size is %s, disabling it", size)
                return
        self.border = WindowBorder(True, color.red_float, color.green_float, color.blue_float, alpha, size)
        log("parse_border(%s)=%s", border_str, self.border)


    def gtk_main(self):
        gtk2main()

    def cleanup(self):
        global UI_watcher
        UI_watcher.stop()
        GTKXpraClient.cleanup(self)

    def client_type(self):
        return "Python/Gtk2"

    def client_toolkit(self):
        return "gtk2"

    def get_notifier_classes(self):
        ncs = GTKXpraClient.get_notifier_classes(self)
        try:
            from xpra.client.gtk2.gtk2_notifier import GTK2_Notifier
            ncs.append(GTK2_Notifier)
        except Exception, e:
            log.warn("cannot load GTK2 notifier: %s", e)
        return ncs

    def make_new_window(self, *args):
        w = GTKXpraClient.make_new_window(self, *args)
        if w:
            w.border = self.border
        return w

    def get_supported_window_layouts(self):
        return  WINDOW_LAYOUTS

    def do_get_core_encodings(self):
        encodings = GTKXpraClient.do_get_core_encodings(self)
        #we can handle rgb32 format (but not necessarily transparency!)
        encodings.append("rgb32")
        #gtk2 can handle 'png' and 'jpeg' natively (without PIL)
        #(though using PIL is better since we can do that in the decode thread)
        for x in ("png", "jpeg"):
            if x not in encodings:
                encodings.append(x)
        return encodings

    def has_transparency(self):
        return gdk.screen_get_default().get_rgba_visual() is not None


    def _startup_complete(self, *args):
        GTKXpraClient._startup_complete(self, *args)
        gtk.gdk.notify_startup_complete()


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK2TrayMenu)
        return tmhc


    def process_clipboard_packet(self, packet):
        clipboardlog("process_clipboard_packet(%s) level=%s", packet, gtk.main_level())
        #check for clipboard loops:
        if gtk.main_level()>=10:
            clipboardlog.warn("loop nesting too deep: %s", gtk.main_level())
            clipboardlog.warn("you may have a clipboard forwarding loop, disabling the clipboard")
            self.clipboard_enabled = False
            self.emit("clipboard-toggled")
            return
        self.idle_add(self.clipboard_helper.process_clipboard_packet, packet)

    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        from xpra.platform.features import CLIPBOARDS, CLIPBOARD_NATIVE_CLASS
        clipboards = [x for x in CLIPBOARDS if x in self.server_clipboards]
        clipboardlog("make_clipboard_helper() server_clipboards=%s, local clipboards=%s, common=%s", self.server_clipboards, CLIPBOARDS, clipboards)
        #first add the platform specific one, (may be None):
        clipboard_options = []
        if CLIPBOARD_NATIVE_CLASS:
            clipboard_options.append(CLIPBOARD_NATIVE_CLASS)
        clipboard_options.append(("xpra.clipboard.gdk_clipboard", "GDKClipboardProtocolHelper", {"clipboards" : clipboards}))
        clipboard_options.append(("xpra.clipboard.clipboard_base", "DefaultClipboardProtocolHelper", {"clipboards" : clipboards}))
        clipboardlog("make_clipboard_helper() clipboard_options=%s", clipboard_options)
        for module_name, classname, kwargs in clipboard_options:
            c = self.try_load_clipboard_helper(module_name, classname, kwargs)
            if c:
                return c
        return None

    def try_load_clipboard_helper(self, module, classname, kwargs={}):
        try:
            m = __import__(module, {}, {}, classname)
            if m:
                if not hasattr(m, classname):
                    log.warn("cannot load %s from %s, odd", classname, m)
                    return None
                c = getattr(m, classname)
                if c:
                    return self.setup_clipboard_helper(c, **kwargs)
        except:
            clipboardlog.error("cannot load %s.%s", module, classname, exc_info=True)
            return None
        clipboardlog.error("cannot load %s.%s", module, classname)
        return None

    def setup_clipboard_helper(self, helperClass, *args, **kwargs):
        clipboardlog("setup_clipboard_helper(%s, %s, %s)", helperClass, args, kwargs)
        def clipboard_send(*parts):
            if self.clipboard_enabled:
                self.send(*parts)
            else:
                clipboardlog("clipboard is disabled, not sending clipboard packet")
        def clipboard_progress(local_requests, remote_requests):
            clipboardlog("clipboard_progress(%s, %s)", local_requests, remote_requests)
            if local_requests is not None:
                self.local_clipboard_requests = local_requests
            if remote_requests is not None:
                self.remote_clipboard_requests = remote_requests
            n = self.local_clipboard_requests+self.remote_clipboard_requests
            self.clipboard_notify(n)
        def register_clipboard_toggled(*args):
            def clipboard_toggled(*targs):
                clipboardlog("clipboard_toggled(%s) enabled=%s, server_supports_clipboard=%s", targs, self.clipboard_enabled, self.server_supports_clipboard)
                if self.clipboard_enabled and self.server_supports_clipboard:
                    assert self.clipboard_helper is not None
                    self.clipboard_helper.send_all_tokens()
                else:
                    pass    #FIXME: todo!
                #reset tray icon:
                self.local_clipboard_requests = 0
                self.remote_clipboard_requests = 0
                self.clipboard_notify(0)
            self.connect("clipboard-toggled", clipboard_toggled)
        self.connect("handshake-complete", register_clipboard_toggled)
        return helperClass(clipboard_send, clipboard_progress, *args, **kwargs)

    def clipboard_notify(self, n):
        if not self.tray:
            return
        clipboardlog("clipboard_notify(%s)", n)
        if n>0 and self.clipboard_enabled:
            self.tray.set_icon("clipboard")
            self.tray.set_tooltip("%s clipboard requests in progress" % n)
            self.tray.set_blinking(True)
        else:
            self.tray.set_icon(None)    #None means back to default icon
            self.tray.set_tooltip(self.get_tray_title())
            self.tray.set_blinking(False)


    def make_hello(self):
        capabilities = GTKXpraClient.make_hello(self)
        if xor_str is not None:
            capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()]
        capabilities["pointer.grabs"] = True
        return capabilities

    def init_packet_handlers(self):
        GTKXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["pointer-grab"] = self._process_pointer_grab
        self._ui_packet_handlers["pointer-ungrab"] = self._process_pointer_ungrab


    def process_ui_capabilities(self, capabilities):
        GTKXpraClient.process_ui_capabilities(self, capabilities)
        if self.server_randr:
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self.screen_size_changed)
                i += 1
        global UI_watcher
        UI_watcher.start()
        #if server supports it, enable UI thread monitoring workaround when needed:
        if self.suspend_resume:
            def UI_resumed():
                self.send("resume", True, self._id_to_window.keys())
            def UI_failed():
                self.send("suspend", True, self._id_to_window.keys())
            UI_watcher.add_resume_callback(UI_resumed)
            UI_watcher.add_fail_callback(UI_failed)


    def get_screen_sizes(self):
        display = gdk.display_get_default()
        i=0
        screen_sizes = []
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
            work_x, work_y = 0, 0
            work_width, work_height = screen.get_width(), screen.get_height()
            if not sys.platform.startswith("win"):
                try:
                    p = gtk.gdk.atom_intern('_NET_WORKAREA')
                    root = screen.get_root_window()
                    work_x, work_y, work_width, work_height = root.property_get(p)[2][:4]
                except:
                    pass
            item = (screen.make_display_name(), screen.get_width(), screen.get_height(),
                        screen.get_width_mm(), screen.get_height_mm(),
                        monitors,
                        work_x, work_y, work_width, work_height)
            screen_sizes.append(item)
            i += 1
        return screen_sizes


    def get_root_size(self):
        return gdk.get_default_root_window().get_size()

    def make_cursor(self, cursor_data):
        #if present, try cursor ny name:
        if len(cursor_data)>=9 and cursor_names:
            cursor_name = cursor_data[8]
            if cursor_name:
                gdk_cursor = cursor_names.get(cursor_name.upper())
                if gdk_cursor is not None:
                    cursorlog("setting new cursor by name: %s=%s", cursor_name, gdk_cursor)
                    return gdk.Cursor(gdk_cursor)
                else:
                    global missing_cursor_names
                    if cursor_name not in missing_cursor_names:
                        cursorlog("cursor name '%s' not found", cursor_name)
                        missing_cursor_names.add(cursor_name)
        #create cursor from the pixel data:
        w, h, xhot, yhot, serial, pixels = cursor_data[2:8]
        if len(pixels)<w*h*4:
            import binascii
            cursorlog.warn("not enough pixels provided in cursor data: %s needed and only %s bytes found (%s)", w*h*4, len(pixels), binascii.hexlify(pixels)[:100])
            return
        pixbuf = gdk.pixbuf_new_from_data(pixels, gdk.COLORSPACE_RGB, True, 8, w, h, w * 4)
        x = max(0, min(xhot, w-1))
        y = max(0, min(yhot, h-1))
        display = gdk.display_get_default()
        csize = display.get_default_cursor_size()
        cmaxw, cmaxh = display.get_maximal_cursor_size()
        if len(cursor_data)>=11:
            ssize = cursor_data[9]
            smax = cursor_data[10]
            cursorlog("server cursor sizes: default=%s, max=%s", ssize, smax)
        cursorlog("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s, default cursor size is %s, maximum=%s", xhot,yhot, serial, w,h, len(pixels), csize, (cmaxw, cmaxh))
        ratio = 1
        if w>cmaxw or h>cmaxh or (csize>0 and (csize<w or csize<h)):
            ratio = max(float(w)/cmaxw, float(h)/cmaxh, float(max(w,h))/csize)
            cursorlog("downscaling cursor by %.2f", ratio)
            pixbuf = pixbuf.scale_simple(int(w/ratio), int(h/ratio), gdk.INTERP_BILINEAR)
            x = int(x/ratio)
            y = int(y/ratio)
        return gdk.Cursor(gdk.display_get_default(), pixbuf, x, y)

    def set_windows_cursor(self, gtkwindows, cursor_data):
        cursor = None
        if cursor_data:
            try:
                cursor = self.make_cursor(cursor_data)
            except Exception, e:
                cursorlog.warn("error creating cursor: %s (using default)", e, exc_info=True)
            if cursor is None:
                #use default:
                cursor = gdk.Cursor(gtk.gdk.X_CURSOR)
        for gtkwindow in gtkwindows:
            if gtk.gtk_version>=(2,14):
                gdkwin = gtkwindow.get_window()
            else:
                gdkwin = gtkwindow.window
            #trays don't have a gdk window
            if gdkwin:
                gdkwin.set_cursor(cursor)


    def _process_raise_window(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        log("going to raise window %s - %s", wid, window)
        if window:
            if window.has_toplevel_focus():
                log("window already has top level focus")
                return
            window.present()


    def window_grab(self, window):
        mask = gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_RELEASE_MASK | gtk.gdk.POINTER_MOTION_MASK  | gtk.gdk.POINTER_MOTION_HINT_MASK | gtk.gdk.ENTER_NOTIFY_MASK | gtk.gdk.LEAVE_NOTIFY_MASK
        gtk.gdk.pointer_grab(window.gdk_window(), owner_events=True, event_mask=mask)
        #also grab the keyboard so the user won't Alt-Tab away:
        gtk.gdk.keyboard_grab(window.gdk_window(), owner_events=False)

    def window_ungrab(self):
        gtk.gdk.pointer_ungrab()
        gtk.gdk.keyboard_ungrab()


    def init_opengl(self, enable_opengl):
        #enable_opengl can be True, False or None (auto-detect)
        self.client_supports_opengl = False
        self.opengl_enabled = False
        self.GLClientWindowClass = None
        self.opengl_props = {}
        from xpra.scripts.config import OpenGL_safety_check
        check = OpenGL_safety_check()
        if check:
            if enable_opengl is True:
                log.warn("OpenGL loading despite: %s", check)
            else:
                self.opengl_props["info"] = "disabled: %s" % check
                log.warn("OpenGL disabled: %s", check)
                return
        if enable_opengl is False:
            self.opengl_props["info"] = "disabled by configuration"
            return
        self.opengl_props["info"] = ""
        try:
            __import__("xpra.client.gl", {}, {}, [])
            __import__("gtk.gdkgl", {}, {}, [])
            __import__("gtk.gtkgl", {}, {}, [])
            gl_check = __import__("xpra.client.gl.gl_check", {}, {}, ["check_support"])
            w, h = self.get_root_size()
            min_texture_size = max(w, h)
            self.opengl_props = gl_check.check_support(min_texture_size, force_enable=(enable_opengl is True))
            gl_client_window = __import__("xpra.client.gl.gl_client_window", {}, {}, ["GLClientWindow"])
            self.GLClientWindowClass = gl_client_window.GLClientWindow
            self.client_supports_opengl = True
            self.opengl_enabled = True
        except ImportError, e:
            log.info("OpenGL support not enabled: %s", e)
            self.opengl_props["info"] = str(e)
        except Exception, e:
            log.error("Error loading OpenGL support: %s", e, exc_info=True)
            self.opengl_props["info"] = str(e)

    def get_group_leader(self, metadata, override_redirect):
        if not self.supports_group_leader:
            return None
        wid = metadata.get("transient-for")
        if wid>0:
            client_window = self._id_to_window.get(wid)
            if client_window:
                gdk_window = client_window.gdk_window()
                if gdk_window:
                    return gdk_window
        pid = metadata.get("pid", -1)
        leader_xid = metadata.get("group-leader-xid")
        leader_wid = metadata.get("group-leader-wid")
        group_leader_window = self._id_to_window.get(leader_wid)
        if group_leader_window:
            #leader is another managed window
            log("found group leader window %s for wid=%s", group_leader_window, pid)
            return group_leader_window
        reftype = "xid"
        ref = leader_xid
        if ref is None:
            reftype = "pid"
            ref = pid
        if ref is None:
            #no reference to use! invent a unique one for this window:
            #(use its wid)
            reftype = "wid"
            ref = wid
        refkey = "%s:%s" % (reftype, ref)
        group_leader_window = self._ref_to_group_leader.get(refkey)
        if group_leader_window:
            log("found existing group leader window %s using ref=%s", group_leader_window, refkey)
            return group_leader_window
        #we need to create one:
        title = "%s group leader for %s" % (self.session_name or "Xpra", pid)
        group_leader_window = gdk.Window(None, 1, 1, gdk.WINDOW_TOPLEVEL, 0, gdk.INPUT_ONLY, title)
        self._ref_to_group_leader[refkey] = group_leader_window
        #spec says window should point to itself
        group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid, window):
        #override so we can cleanup the group-leader if needed,
        GTKXpraClient.destroy_window(self, wid, window)
        group_leader = window.group_leader
        if group_leader is None or len(self._group_leader_wids)==0:
            return
        wids = self._group_leader_wids.get(group_leader)
        if wids is None:
            #not recorded any window ids on this group leader
            #means it is another managed window, leave it alone
            return
        if wid in wids:
            wids.remove(wid)
        if len(wids)>0:
            #still has another window pointing to it
            return
        #the last window has gone, we can remove the group leader,
        #find all the references to this group leader:
        refs = []
        for ref, gl in self._ref_to_group_leader.items():
            if gl==group_leader:
                refs.append(ref)
        for ref in refs:
            del self._ref_to_group_leader[ref]
        log("last window for refs %s is gone, destroying the group leader %s", refs, group_leader)
        group_leader.destroy()


    def get_client_window_classes(self, metadata, override_redirect):
        #only enable GL for normal windows:
        window_types = metadata.get("window-type", ())
        log("get_client_window_class(%s, %s) GLClientWindowClass=%s, opengl_enabled=%s, mmap_enabled=%s, window_types=%s, encoding=%s", metadata, override_redirect, self.GLClientWindowClass, self.opengl_enabled, self.mmap_enabled, window_types, self.encoding)
        if self.GLClientWindowClass is None or not self.opengl_enabled:
            return [self.ClientWindowClass]
        return [self.GLClientWindowClass, self.ClientWindowClass]

    def toggle_opengl(self, *args):
        assert self.window_unmap, "server support for 'window_unmap' is required for toggling opengl at runtime"
        self.opengl_enabled = not self.opengl_enabled
        log("opengl_toggled: %s", self.opengl_enabled)
        def fake_send(*args):
            log("fake_send(%s)", args)
        #now replace all the windows with new ones:
        for wid, window in self._id_to_window.items():
            if window.is_tray():
                #trays are never GL enabled, so don't bother re-creating them
                #(might cause problems anyway if we did)
                continue
            #ignore packets from old window:
            window.send = fake_send
            #copy attributes:
            x, y = window._pos
            w, h = window._size
            client_properties = window._client_properties
            metadata = window._metadata
            override_redirect = window._override_redirect
            backing = window._backing
            video_decoder = None
            csc_decoder = None
            decoder_lock = None
            try:
                if backing:
                    video_decoder = backing._video_decoder
                    csc_decoder = backing._csc_decoder
                    decoder_lock = backing._decoder_lock
                    if decoder_lock:
                        decoder_lock.acquire()
                        log("toggle_opengl() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                        backing._video_decoder = None
                        backing._csc_decoder = None
                        backing._decoder_lock = None

                #now we can unmap it:
                self.destroy_window(wid, window)
                #explicitly tell the server we have unmapped it:
                #(so it will reset the video encoders, etc)
                self.send("unmap-window", wid)
                try:
                    del self._id_to_window[wid]
                except:
                    pass
                try:
                    del self._window_to_id[window]
                except:
                    pass
                #create the new window, which should honour the new state of the opengl_enabled flag:
                window = self.make_new_window(wid, x, y, w, h, metadata, override_redirect, client_properties)
                if video_decoder or csc_decoder:
                    backing = window._backing
                    backing._video_decoder = video_decoder
                    backing._csc_decoder = csc_decoder
                    backing._decoder_lock = decoder_lock
            finally:
                if decoder_lock:
                    decoder_lock.release()
        log("replaced all the windows with opengl=%s: %s", self.opengl_enabled, self._id_to_window)

gobject.type_register(XpraClient)
