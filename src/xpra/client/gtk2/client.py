# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()
import gtk
from gtk import gdk


from xpra.gtk_common.gtk_util import gtk_main, color_parse
from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.client.window_border import WindowBorder
from xpra.net.compression import Compressible
from xpra.log import Logger

log = Logger("gtk", "client")
clipboardlog = Logger("gtk", "client", "clipboard")
grablog = Logger("gtk", "client", "grab")

from xpra.client.gtk2.border_client_window import BorderClientWindow


class XpraClient(GTKXpraClient):

    def __init__(self):
        GTKXpraClient.__init__(self)
        self.UI_watcher = None
        self.border = None
        self.local_clipboard_requests = 0
        self.remote_clipboard_requests = 0
        #only used with the translated clipboard class:
        self.local_clipboard = ""
        self.remote_clipboard = ""

    def init(self, opts):
        GTKXpraClient.init(self, opts)
        self.ClientWindowClass = BorderClientWindow
        self.remote_clipboard = opts.remote_clipboard
        self.local_clipboard = opts.local_clipboard
        log("init(..) ClientWindowClass=%s", self.ClientWindowClass)
        from xpra.platform.ui_thread_watcher import get_UI_watcher
        self.UI_watcher = get_UI_watcher(self.timeout_add)


    def parse_border(self, border_str, extra_args):
        enabled = not border_str.endswith(":off")
        parts = [x.strip() for x in border_str.replace(":off", "").split(",")]
        color_str = parts[0]
        def border_help():
            log.info(" border format: color[,size][:off]")
            log.info("  eg: red,10")
            log.info("  eg: ,5")
            log.info("  eg: auto,5")
            log.info("  eg: blue")
        if color_str.lower() in ("none", "no", "off", "0"):
            return
        if color_str.lower()=="help":
            border_help()
            return
        color_str = color_str.replace(":off", "")
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
        self.border = WindowBorder(enabled, color.red/65536.0, color.green/65536.0, color.blue/65536.0, alpha, size)
        log("parse_border(%s)=%s", border_str, self.border)


    def gtk_main(self):
        gtk_main()

    def cleanup(self):
        uw = self.UI_watcher
        if uw:
            self.UI_watcher = None
            uw.stop()
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

    def do_get_core_encodings(self):
        encodings = GTKXpraClient.do_get_core_encodings(self)
        #we can handle rgb32 format (but not necessarily transparency!)
        def add(x):
            if x in self.allowed_encodings and x not in encodings:
                encodings.append(x)
        add("rgb32")
        return encodings


    def _process_startup_complete(self, *args):
        GTKXpraClient._process_startup_complete(self, *args)
        gdk.notify_startup_complete()


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK2TrayMenu)
        return tmhc


    def process_clipboard_packet(self, packet):
        clipboardlog("process_clipboard_packet(%s) level=%s", packet, gtk.main_level())
        #check for clipboard loops:
        from xpra.clipboard.clipboard_base import nesting_check
        if not nesting_check():
            self.clipboard_enabled = False
            self.emit("clipboard-toggled")
            return
        self.idle_add(self.clipboard_helper.process_clipboard_packet, packet)


    def get_clipboard_helper_classes(self):
        from xpra.scripts.config import TRUE_OPTIONS, FALSE_OPTIONS
        ct = self.client_clipboard_type
        if ct and ct.lower() in FALSE_OPTIONS:
            return []
        from xpra.platform.features import CLIPBOARD_NATIVE_CLASS
        from xpra.scripts.main import CLIPBOARD_CLASS
        #first add the platform specific one, (may be None):
        clipboard_options = []
        if CLIPBOARD_CLASS:
            clipboard_options.append(CLIPBOARD_CLASS)
        if CLIPBOARD_NATIVE_CLASS:
            clipboard_options.append(CLIPBOARD_NATIVE_CLASS)
        clipboard_options.append("xpra.clipboard.gdk_clipboard.GDKClipboardProtocolHelper")
        clipboard_options.append("xpra.clipboard.clipboard_base.DefaultClipboardProtocolHelper")
        clipboard_options.append("xpra.clipboard.translated_clipboard.TranslatedClipboardProtocolHelper")
        clipboardlog("get_clipboard_helper_classes() unfiltered list=%s", clipboard_options)
        if ct and ct.lower()!="auto" and ct.lower() not in TRUE_OPTIONS:
            #try to match the string specified:
            filtered = [x for x in clipboard_options if x.lower().find(self.client_clipboard_type)>=0]
            if len(filtered)==0:
                clipboardlog.warn("Warning: no clipboard types matching '%s'", self.client_clipboard_type)
                clipboardlog.warn(" clipboard synchronization is disabled")
                return []
            clipboardlog(" found %i clipboard types matching '%s'", len(filtered), self.client_clipboard_type)
            clipboard_options = filtered
        #now try to load them:
        clipboardlog("get_clipboard_helper_classes() options=%s", clipboard_options)
        loadable = []
        for co in clipboard_options:
            try:
                parts = co.split(".")
                mod = ".".join(parts[:-1])
                module = __import__(mod, {}, {}, [parts[-1]])
                helperclass = getattr(module, parts[-1])
                loadable.append(helperclass)
            except ImportError as e:
                clipboardlog("cannot load %s: %s", co, e)
                continue
        clipboardlog("get_clipboard_helper_classes()=%s", loadable)
        return loadable

    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        clipboard_options = self.get_clipboard_helper_classes()
        clipboardlog("make_clipboard_helper() options=%s", clipboard_options)
        for helperclass in clipboard_options:
            try:
                return self.setup_clipboard_helper(helperclass)
            except ImportError as e:
                clipboardlog.error("Error: cannot instantiate %s:", helperclass)
                clipboardlog.error(" %s", e)
            except:
                clipboardlog.error("cannot instantiate %s", helperclass, exc_info=True)
        return None

    def setup_clipboard_helper(self, helperClass):
        clipboardlog("setup_clipboard_helper(%s)", helperClass)
        #first add the platform specific one, (may be None):
        from xpra.platform.features import CLIPBOARDS
        kwargs= {
                 "clipboards.local"     : CLIPBOARDS,                   #all the local clipboards supported
                 "clipboards.remote"    : self.server_clipboards,       #all the remote clipboards supported
                 "can-send"             : self.client_clipboard_direction in ("to-server", "both"),
                 "can-receive"          : self.client_clipboard_direction in ("to-client", "both"),
                 }
        #only allow translation overrides if we have a way of telling the server about them:
        if self.server_supports_clipboard_enable_selections:
            kwargs.update({
                 "clipboard.local"      : self.local_clipboard,         #the local clipboard we want to sync to (with the translated clipboard only)
                 "clipboard.remote"     : self.remote_clipboard})       #the remote clipboard we want to we sync to (with the translated clipboard only)
        clipboardlog("setup_clipboard_helper() kwargs=%s", kwargs)
        def clipboard_send(*parts):
            if not self.clipboard_enabled:
                clipboardlog("clipboard is disabled, not sending clipboard packet")
                return
            #handle clipboard compression if needed:
            packet = list(parts)
            for i in range(len(packet)):
                v = packet[i]
                if type(v)==Compressible:
                    #register the compressor which will fire in protocol.encode:
                    def compress_clipboard():
                        clipboardlog("compress_clipboard() compressing %s", v)
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
                #reset tray icon:
                self.local_clipboard_requests = 0
                self.remote_clipboard_requests = 0
                self.clipboard_notify(0)
            self.connect("clipboard-toggled", clipboard_toggled)
        self.after_handshake(register_clipboard_toggled)
        return helperClass(clipboard_send, clipboard_progress, **kwargs)

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
        capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()]
        capabilities["pointer.grabs"] = True
        return capabilities

    def init_packet_handlers(self):
        GTKXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["pointer-grab"] = self._process_pointer_grab
        self._ui_packet_handlers["pointer-ungrab"] = self._process_pointer_ungrab


    def process_ui_capabilities(self):
        GTKXpraClient.process_ui_capabilities(self)
        self.UI_watcher.start()
        #if server supports it, enable UI thread monitoring workaround when needed:
        def UI_resumed():
            self.send("resume", True, self._id_to_window.keys())
        def UI_failed():
            self.send("suspend", True, self._id_to_window.keys())
        self.UI_watcher.add_resume_callback(UI_resumed)
        self.UI_watcher.add_fail_callback(UI_failed)


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
        mask = gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK | gdk.POINTER_MOTION_MASK  | gdk.POINTER_MOTION_HINT_MASK | gdk.ENTER_NOTIFY_MASK | gdk.LEAVE_NOTIFY_MASK
        gdk.pointer_grab(window.get_window(), owner_events=True, event_mask=mask)
        #also grab the keyboard so the user won't Alt-Tab away:
        gdk.keyboard_grab(window.get_window(), owner_events=False)

    def window_ungrab(self):
        gdk.pointer_ungrab()
        gdk.keyboard_ungrab()


gobject.type_register(XpraClient)
