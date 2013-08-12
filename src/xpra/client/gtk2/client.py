# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
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

from xpra.os_util import thread
from xpra.client.gtk_base.gtk_client_base import GTKXpraClient, xor_str
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.gtk_common.cursor_names import cursor_names
from xpra.log import Logger
log = Logger()

from xpra.client.gtk2.border_client_window import BorderClientWindow
from xpra.client.gtk2.client_window import ClientWindow
from xpra.client.gtk2.custom_client_window import CustomClientWindow
WINDOW_LAYOUTS = {
                  "border"  : BorderClientWindow,
                  "default" : ClientWindow,
                  "custom"  : CustomClientWindow,
                  }

FAKE_UI_LOCKUPS = int(os.environ.get("XPRA_FAKE_UI_LOCKUPS", "0"))


class XpraClient(GTKXpraClient):

    WINDOW_TOPLEVEL = gdk.WINDOW_TOPLEVEL
    INPUT_ONLY = gdk.INPUT_ONLY

    def __init__(self):
        GTKXpraClient.__init__(self)
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
            self.ClientWindowClass = ClientWindow
        log("init(..) ClientWindowClass=%s", self.ClientWindowClass)

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
            log("cannot load GTK3 notifier: %s", e)
        return ncs


    def get_supported_window_layouts(self):
        return  WINDOW_LAYOUTS

    def get_core_encodings(self):
        encodings = GTKXpraClient.get_core_encodings(self)
        if gdk.screen_get_default().get_rgba_visual() is not None:
            try:
                #check for bytearray which is used by PixmapBacking
                #to unpremultiply rgb32 data
                bytearray("")
                encodings.append("rgb32")
            except:
                pass
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


    def do_get_pixbuf(self, icon_filename):
        if not hasattr(gdk, "pixbuf_new_from_file"):
            return None
        return  gdk.pixbuf_new_from_file(icon_filename)

    def do_get_image(self, pixbuf, size=None):
        if not hasattr(gtk, "image_new_from_pixbuf"):
            return None
        if size:
            pixbuf = pixbuf.scale_simple(size, size, gdk.INTERP_BILINEAR)
        return  gtk.image_new_from_pixbuf(pixbuf)


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK2TrayMenu)
        return tmhc


    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        from xpra.platform.features import CLIPBOARDS, CLIPBOARD_NATIVE_CLASS
        clipboards = [x for x in CLIPBOARDS if x in self.server_clipboards]
        log("make_clipboard_helper() server_clipboards=%s, local clipboards=%s, common=%s", self.server_clipboards, CLIPBOARDS, clipboards)
        #first add the platform specific one, (may be None):
        clipboard_options = []
        if CLIPBOARD_NATIVE_CLASS:
            clipboard_options.append(CLIPBOARD_NATIVE_CLASS)
        clipboard_options.append(("xpra.clipboard.gdk_clipboard", "GDKClipboardProtocolHelper", {"clipboards" : clipboards}))
        clipboard_options.append(("xpra.clipboard.clipboard_base", "DefaultClipboardProtocolHelper", {"clipboards" : clipboards}))
        log("make_clipboard_helper() clipboard_options=%s", clipboard_options)
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
            log.error("cannot load %s.%s", module, classname, exc_info=True)
            return None
        log.error("cannot load %s.%s", module, classname)
        return None

    def setup_clipboard_helper(self, helperClass, *args, **kwargs):
        log("setup_clipboard_helper(%s, %s, %s)", helperClass, args, kwargs)
        def clipboard_send(*parts):
            if self.clipboard_enabled:
                self.send(*parts)
            else:
                log("clipboard is disabled, not sending clipboard packet")
        def clipboard_progress(local_requests, remote_requests):
            log("clipboard_progress(%s, %s)", local_requests, remote_requests)
            if local_requests is not None:
                self.local_clipboard_requests = local_requests
            if remote_requests is not None:
                self.remote_clipboard_requests = remote_requests
            n = self.local_clipboard_requests+self.remote_clipboard_requests
            self.clipboard_notify(n)
        def register_clipboard_toggled(*args):
            def clipboard_toggled(*targs):
                log("clipboard_toggled(%s) enabled=%s, server_supports_clipboard=%s", targs, self.clipboard_enabled, self.server_supports_clipboard)
                if self.clipboard_enabled and self.server_supports_clipboard:
                    assert self.clipboard_helper is not None
                    self.clipboard_helper.send_all_tokens()
                else:
                    pass    #FIXME: todo!
            self.connect("clipboard-toggled", clipboard_toggled)
        self.connect("handshake-complete", register_clipboard_toggled)
        return helperClass(clipboard_send, clipboard_progress, *args, **kwargs)

    def clipboard_notify(self, n):
        if not self.tray:
            return
        if n>0:
            self.tray.set_icon("clipboard")
            self.tray.set_tooltip("%s clipboard requests in progress" % n)
            self.tray.set_blinking(True)
        else:
            self.tray.set_icon("xpra")
            self.tray.set_tooltip("Xpra")
            self.tray.set_blinking(False)


    def make_hello(self, challenge_response=None):
        capabilities = GTKXpraClient.make_hello(self, challenge_response)
        if xor_str is not None:
            capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()]
        return capabilities

    def process_ui_capabilities(self, capabilities):
        GTKXpraClient.process_ui_capabilities(self, capabilities)
        if self.server_randr:
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        #if server supports it, enable UI thread monitoring workaround when needed:
        if self.suspend_resume and (sys.platform.startswith("darwin") or FAKE_UI_LOCKUPS>0):
            self.start_UI_thread_polling()
            if FAKE_UI_LOCKUPS>0:
                def sleep_in_ui_thread(*args):
                    time.sleep(FAKE_UI_LOCKUPS)
                    return True
                gobject.timeout_add((10+FAKE_UI_LOCKUPS)*1000, sleep_in_ui_thread)

    def start_UI_thread_polling(self):
        log("start_UI_thread_polling()")
        self.UI_blocked_sent = False
        def UI_thread_wakeup(*args):
            log("UI_thread_wakeup()")
            self.last_UI_thread_time = time.time()
            #UI thread was blocked?
            if self.UI_blocked_sent:
                log.info("UI thread is running again, resuming")
                self.send("resume", True, self._id_to_window.keys())
                self.UI_blocked_sent = False
            return self.exit_code is None
        UI_thread_wakeup()
        gobject.timeout_add(1000, UI_thread_wakeup)
        def poll_UI_loop(*args):
            log("poll_UI_loop() running")
            while self.exit_code is None:
                delta = time.time()-self.last_UI_thread_time
                log("poll_UI_loop() last_UI_thread_time was %.1f seconds ago, UI_blocked_sent=%s", delta, self.UI_blocked_sent)
                if delta>2.0:
                    #UI thread is (still?) blocked:
                    if not self.UI_blocked_sent:
                        log.info("UI thread is blocked, pausing server")
                        self.send("suspend", True, self._id_to_window.keys())
                        self.UI_blocked_sent = True
                time.sleep(1.0)
        thread.start_new_thread(poll_UI_loop, ())

    def _screen_size_changed(self, *args):
        def update_size(current=None):
            root_w, root_h = self.get_root_size()
            ss = self.get_screen_sizes()
            log("update_size(%s) sizes=%s", current, ss)
            if current is not None and current==ss:
                #unchanged
                return
            log.info("sending updated screen size to server: %sx%s, screen sizes: %s", root_w, root_h, ss)
            self.send("desktop_size", root_w, root_h, ss)
            #update the max packet size (may have gone up):
            self.set_max_packet_size()
            #check again soon:
            gobject.timeout_add(1000, update_size, ss)
        #update via idle_add so the data is actually up to date when we query it!
        self.idle_add(update_size)

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


    def get_root_size(self):
        return gdk.get_default_root_window().get_size()

    def set_windows_cursor(self, gtkwindows, new_cursor):
        cursor = None
        if len(new_cursor)>0:
            cursor = None
            if len(new_cursor)>=9 and cursor_names:
                cursor_name = new_cursor[8]
                if cursor_name:
                    gdk_cursor = cursor_names.get(cursor_name.upper())
                    if gdk_cursor is not None:
                        try:
                            from xpra.x11.gtk_x11.error import trap
                            log("setting new cursor: %s=%s", cursor_name, gdk_cursor)
                            cursor = trap.call_synced(gdk.Cursor, gdk_cursor)
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
            if gtk.gtk_version>=(2,14):
                gdkwin = gtkwindow.get_window()
            else:
                gdkwin = gtkwindow.window
            #trays don't have a gdk window
            if gdkwin:
                gdkwin.set_cursor(cursor)


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
                log.warn("OpenGL enabled despite: %s", check)
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
        group_leader_window = gdk.Window(None, 1, 1, self.WINDOW_TOPLEVEL, 0, self.INPUT_ONLY, title)
        self._ref_to_group_leader[refkey] = group_leader_window
        #spec says window should point to itself
        group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid, window):
        #override so we can cleanup the group-leader if needed:
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


    def get_client_window_class(self, metadata, override_redirect):
        #only enable GL for normal windows:
        window_types = metadata.get("window-type", ())
        log("get_client_window_class(%s, %s) GLClientWindowClass=%s, opengl_enabled=%s, mmap_enabled=%s, window_types=%s, encoding=%s", metadata, override_redirect, self.GLClientWindowClass, self.opengl_enabled, self.mmap_enabled, window_types, self.encoding)
        if self.GLClientWindowClass is None or not self.opengl_enabled or override_redirect:
            return self.ClientWindowClass
        if metadata.get("has-alpha", False):
            #GL cannot do transparency yet:
            return self.ClientWindowClass
        if self.mmap_enabled or self.encoding not in ("x264", "vpx"):
            return self.ClientWindowClass
        if ("NORMAL" not in window_types) and ("_NET_WM_WINDOW_TYPE_NORMAL" not in window_types):
            return self.ClientWindowClass
        return self.GLClientWindowClass

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
            auto_refresh_delay = window._auto_refresh_delay
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
                window = self.make_new_window(wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
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
