# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import gobject
import glib
try:
    glib.threads_init()
except:
    pass
try:
    #we *have to* do this as early as possible on win32..
    gobject.threads_init()
except:
    pass
import gtk
from gtk import gdk
gdk.threads_init()


from xpra.platform.ui_thread_watcher import get_UI_watcher
UI_watcher = get_UI_watcher(glib.timeout_add)

from xpra.gtk_common.gtk_util import gtk_main, color_parse
from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.client.window_border import WindowBorder
from xpra.net.compression import Uncompressed
from xpra.log import Logger

log = Logger("gtk", "client")
clipboardlog = Logger("gtk", "client", "clipboard")
grablog = Logger("gtk", "client", "grab")

from xpra.client.gtk2.border_client_window import BorderClientWindow

FAKE_UI_LOCKUPS = int(os.environ.get("XPRA_FAKE_UI_LOCKUPS", "0"))


class XpraClient(GTKXpraClient):

    def __init__(self):
        GTKXpraClient.__init__(self)
        self.border = None
        self.local_clipboard_requests = 0
        self.remote_clipboard_requests = 0

    def init(self, opts):
        GTKXpraClient.init(self, opts)
        self.ClientWindowClass = BorderClientWindow
        log("init(..) ClientWindowClass=%s", self.ClientWindowClass)


    def parse_border(self, border_str, extra_args):
        parts = [x.strip() for x in border_str.split(",")]
        color_str = parts[0]
        def border_help():
            log.info(" border format: color[,size]")
            log.info("  eg: red,10")
            log.info("  eg: ,5")
            log.info("  eg: auto,5")
            log.info("  eg: blue")
        if color_str.lower() in ("none", "no", "off", "0"):
            return
        if color_str.lower()=="help":
            border_help()
            return
        if color_str=="auto" or color_str=="":
            try:
                try:
                    from hashlib import md5
                except ImportError:
                    from md5 import md5
                m = md5()
                for x in extra_args:
                    m.update(str(x))
                color_str = "#%s" % m.hexdigest()[:6]
                log("border color derived from %s: %s", extra_args, color_str)
            except:
                log.info("failed to derive border color from %s", extra_args, exc_info=True)
                #fail: default to red
                color_str = "red"
        try:
            color = color_parse(color_str)
        except Exception as e:
            log.warn("invalid border color specified: '%s' (%s)", color_str, e)
            border_help()
            color = color_parse("red")
        alpha = 0.6
        size = 4
        if len(parts)==2:
            size_str = parts[1]
            try:
                size = int(size_str)
            except Exception as e:
                log.warn("invalid size specified: %s (%s)", size_str, e)
            if size<=0:
                log("border size is %s, disabling it", size)
                return
            if size>=45:
                log.warn("border size is too high: %s, clipping it", size)
                size = 45
        self.border = WindowBorder(True, color.red/65536.0, color.green/65536.0, color.blue/65536.0, alpha, size)
        log("parse_border(%s)=%s", border_str, self.border)


    def gtk_main(self):
        gtk_main()

    def cleanup(self):
        global UI_watcher
        UI_watcher.stop()
        GTKXpraClient.cleanup(self)

    def __repr__(self):
        return "gtk2.client"

    def client_type(self):
        return "Python/Gtk2"

    def client_toolkit(self):
        return "gtk2"

    def get_notifier_classes(self):
        ncs = GTKXpraClient.get_notifier_classes(self)
        try:
            from xpra.client.gtk2.gtk2_notifier import GTK2_Notifier
            ncs.append(GTK2_Notifier)
        except Exception as e:
            log.warn("cannot load GTK2 notifier: %s", e)
        return ncs

    def make_new_window(self, *args):
        w = GTKXpraClient.make_new_window(self, *args)
        if w:
            w.border = self.border
        return w

    def do_get_core_encodings(self):
        encodings = GTKXpraClient.do_get_core_encodings(self)
        #we can handle rgb32 format (but not necessarily transparency!)
        def add(x):
            if x in self.allowed_encodings and x not in encodings:
                encodings.append(x)
        add("rgb32")
        #gtk2 can handle 'png' and 'jpeg' natively (without PIL)
        #(though using PIL is better since we can do that in the decode thread)
        for x in ("png", "jpeg"):
            add(x)
        return encodings


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
        if gtk.main_level()>=40:
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
            if not self.clipboard_enabled:
                clipboardlog("clipboard is disabled, not sending clipboard packet")
                return
            #handle clipboard compression if needed:
            packet = list(parts)
            for i in range(len(packet)):
                v = packet[i]
                if type(v)==Uncompressed:
                    #register the compressor which will fire in protocol.encode:
                    def compress_clipboard():
                        clipboardlog("compress_clipboard() compressing %s", args, v)
                        return self.compressed_wrapper(v.datatype, v.data)
                    v.compress = compress_clipboard
            self.send(*packet)
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


    def compressed_wrapper(self, datatype, data):
        #FIXME: ugly assumptions here, should pass by name!
        from xpra.net import compression
        zlib = "zlib" in self.server_compressors and compression.use_zlib
        lz4 = "lz4" in self.server_compressors and compression.use_lz4
        lzo = "lzo" in self.server_compressors and compression.use_lzo
        if zlib or lz4 or lzo:
            return compression.compressed_wrapper(datatype, data, zlib=zlib, lz4=lz4, lzo=lzo, can_inline=False)
        #we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed("raw %s" % datatype, data, can_inline=True)


    def make_hello(self):
        capabilities = GTKXpraClient.make_hello(self)
        capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()]
        capabilities["pointer.grabs"] = True
        return capabilities

    def init_packet_handlers(self):
        GTKXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["pointer-grab"] = self._process_pointer_grab
        self._ui_packet_handlers["pointer-ungrab"] = self._process_pointer_ungrab


    def process_ui_capabilities(self):
        GTKXpraClient.process_ui_capabilities(self)
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


    def get_root_size(self):
        return self.get_root_window().get_size()


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
        gtk.gdk.pointer_grab(window.get_window(), owner_events=True, event_mask=mask)
        #also grab the keyboard so the user won't Alt-Tab away:
        gtk.gdk.keyboard_grab(window.get_window(), owner_events=False)

    def window_ungrab(self):
        gtk.gdk.pointer_ungrab()
        gtk.gdk.keyboard_ungrab()


gobject.type_register(XpraClient)
