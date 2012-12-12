# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
gtk.gdk.threads_init()

import os.path
import threading
import gobject
import sys
import hmac
import uuid
import time
import socket
import thread
import signal

from wimpiggy.util import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from wimpiggy.lowlevel import (xtest_fake_key,              #@UnresolvedImport
                               xtest_fake_button,           #@UnresolvedImport
                               set_key_repeat_rate,         #@UnresolvedImport
                               unpress_all_keys,            #@UnresolvedImport
                               has_randr, get_screen_sizes, #@UnresolvedImport
                               set_screen_size,             #@UnresolvedImport
                               get_screen_size,             #@UnresolvedImport
                               get_xatom,                   #@UnresolvedImport
                               )
from wimpiggy.prop import prop_set, prop_get
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.scripts.main import python_platform
from xpra.scripts.server import deadly_signal
from xpra.server_source import ServerSource
from xpra.bytestreams import SocketConnection
from xpra.protocol import Protocol, has_rencode
from xpra.platform.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.xkbhelper import clean_keyboard_state
from xpra.xposix.xsettings import XSettingsManager
from xpra.scripts.main import ENCODINGS, ENCRYPTION_CIPHERS
from xpra.version_util import is_compatible_with, add_version_info, add_gtk_version_info

MAX_CONCURRENT_CONNECTIONS = 20


def save_uuid(uuid):
    prop_set(gtk.gdk.get_default_root_window(),
                           "_XPRA_SERVER_UUID", "latin1", uuid)    
def get_uuid():
    return prop_get(gtk.gdk.get_default_root_window(),
                                  "_XPRA_SERVER_UUID", "latin1", ignore_errors=True)

class XpraServerBase(object):

    def __init__(self, clobber, sockets, opts):

        self.x11_init(clobber)

        self.init_uuid()
        self.start_time = time.time()

        # This must happen early, before loading in windows at least:
        self._potential_protocols = []
        self._server_sources = {}

        #so clients can store persistent attributes on windows:
        self.client_properties = {}

        self.default_dpi = int(opts.dpi)
        self.dpi = self.default_dpi

        self.supports_mmap = opts.mmap
        self.default_encoding = opts.encoding
        assert self.default_encoding in ENCODINGS
        self.session_name = opts.session_name
        try:
            import glib
            glib.set_application_name(self.session_name or "Xpra")
        except ImportError, e:
            log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None
        self._upgrading = False
        self._tray = None

        self.load_existing_windows(opts.system_tray)

        ## These may get set by the client:
        self.xkbmap_mod_meanings = {}

        self.keyboard_config = None
        self.keymap_changing = False            #to ignore events when we know we are changing the configuration
        self.keyboard_sync = True
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        #store list of currently pressed keys
        #(using a dict only so we can display their names in debug messages)
        self.keys_pressed = {}
        self.keys_timedout = {}
        #timers for cancelling key repeat when we get jitter
        self.keys_repeat_timers = {}
        ### Set up keymap change notification:
        gtk.gdk.keymap_get_default().connect("keys-changed", self._keys_changed)
        #clear all modifiers
        clean_keyboard_state()

        ### Clipboard handling:
        self._clipboard_helper = None
        self._clipboard_client = None
        if opts.clipboard:
            self._clipboard_helper = GDKClipboardProtocolHelper(self.send_clipboard_packet)

        self.compression_level = opts.compression_level
        self.password_file = opts.password_file

        self.randr = has_randr()
        if self.randr and len(get_screen_sizes())<=1:
            #disable randr when we are dealing with a Xvfb
            #with only one resolution available
            #since we don't support adding them on the fly yet
            self.randr = False
        if self.randr:
            display = gtk.gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        log("randr enabled: %s", self.randr)

        # note: not just True/False here: if None, allow it
        # (the client can then use this None value as False to
        # prevent microphone from being enabled by default whilst still being allowed)
        self.supports_speaker = bool(opts.speaker) or opts.speaker is None
        self.supports_microphone = bool(opts.microphone) or opts.microphone is None
        self.speaker_codecs = opts.speaker_codec
        self.microphone_codecs = opts.microphone_codec
        try:
            from xpra.sound.pulseaudio_util import add_audio_tagging_env
            add_audio_tagging_env()
        except Exception, e:
            log("failed to set pulseaudio audio tagging: %s", e)

        self.default_quality = opts.quality
        self.pulseaudio = opts.pulseaudio
        self.sharing = opts.sharing
        self.bell = opts.bell
        self.cursors = opts.cursors
        self.notifications_forwarder = None
        if opts.notifications:
            try:
                from xpra.dbus_notifications_forwarder import register
                self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.notifications_forwarder:
                    log.info("using notification forwarder: %s", self.notifications_forwarder)
            except Exception, e:
                log.error("error loading or registering our dbus notifications forwarder:")
                log.error("  %s", e)
                log.info("if you do not have a dedicated dbus session for this xpra instance,")
                log.info("  you should use the '--no-notifications' flag")
                log.info("")

        ### All right, we're ready to accept customers:
        self.init_packet_handlers()
        for sock in sockets:
            self.add_listen_socket(sock)

    def init_uuid(self):
        # Define a server UUID if needed:
        self.uuid = get_uuid()
        if not self.uuid:
            self.uuid = unicode(uuid.uuid4().hex)
            save_uuid(self.uuid)
        log.info("server uuid is %s", self.uuid)

    def x11_init(self, clobber):
        self.init_x11_atoms()

    def load_existing_windows(self, system_tray):
        pass

    def is_shown(self, window):
        return True

    def init_x11_atoms(self):
        #some applications (like openoffice), do not work properly
        #if some x11 atoms aren't defined, so we define them in advance:
        for atom_name in ["_NET_WM_WINDOW_TYPE",
                          "_NET_WM_WINDOW_TYPE_NORMAL",
                          "_NET_WM_WINDOW_TYPE_DESKTOP",
                          "_NET_WM_WINDOW_TYPE_DOCK",
                          "_NET_WM_WINDOW_TYPE_TOOLBAR",
                          "_NET_WM_WINDOW_TYPE_MENU",
                          "_NET_WM_WINDOW_TYPE_UTILITY",
                          "_NET_WM_WINDOW_TYPE_SPLASH",
                          "_NET_WM_WINDOW_TYPE_DIALOG",
                          "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
                          "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                          "_NET_WM_WINDOW_TYPE_TOOLTIP",
                          "_NET_WM_WINDOW_TYPE_NOTIFICATION",
                          "_NET_WM_WINDOW_TYPE_COMBO",
                          "_NET_WM_WINDOW_TYPE_DND",
                          "_NET_WM_WINDOW_TYPE_NORMAL"
                          ]:
            get_xatom(atom_name)

    def init_packet_handlers(self):
        self._default_packet_handlers = {
            "hello":                                self._process_hello,
            Protocol.CONNECTION_LOST:               self._process_connection_lost,
            Protocol.GIBBERISH:                     self._process_gibberish,
            }
        self._authenticated_packet_handlers = {
            "set-clipboard-enabled":                self._process_clipboard_enabled_status,
            "set-keyboard-sync-enabled":            self._process_keyboard_sync_enabled_status,
            "damage-sequence":                      self._process_damage_sequence,
            "ping":                                 self._process_ping,
            "ping_echo":                            self._process_ping_echo,
            "set-cursors":                          self._process_set_cursors,
            "set-notify":                           self._process_set_notify,
            "set-bell":                             self._process_set_bell,
            "info-request":                         self._process_info_request,
                                          }
        self._authenticated_ui_packet_handlers = self._default_packet_handlers.copy()
        self._authenticated_ui_packet_handlers.update({
            #windows:
            "map-window":                           self._process_map_window,
            "unmap-window":                         self._process_unmap_window,
            "configure-window":                     self._process_configure_window,
            "move-window":                          self._process_move_window,
            "resize-window":                        self._process_resize_window,
            "close-window":                         self._process_close_window,
            "focus":                                self._process_focus,
            #keyboard:
            "key-action":                           self._process_key_action,
            "key-repeat":                           self._process_key_repeat,
            "layout-changed":                       self._process_layout,
            "keymap-changed":                       self._process_keymap,
            #mouse:
            "button-action":                        self._process_button_action,
            "pointer-position":                     self._process_pointer_position,
            #attributes / settings:
            "server-settings":                      self._process_server_settings,
            "jpeg-quality":                         self._process_quality,
            "quality":                              self._process_quality,
            "set_deflate":                          self._process_set_deflate,
            "desktop_size":                         self._process_desktop_size,
            "encoding":                             self._process_encoding,
            #sound:
            "sound-control":                        self._process_sound_control,
            "sound-data":                           self._process_sound_data,
            #requests:
            "shutdown-server":                      self._process_shutdown_server,
            "buffer-refresh":                       self._process_buffer_refresh,
            "screenshot":                           self._process_screenshot,
            "disconnect":                           self._process_disconnect,
            # Note: "clipboard-*" packets are handled via a special case..
            })

    def signal_quit(self, signum, frame):
        log.info("got signal %s, exiting", signum)
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        gobject.idle_add(self.quit, False)

    def quit(self, upgrading):
        self._upgrading = upgrading
        log.info("xpra is terminating.")
        sys.stdout.flush()
        gtk_main_quit_really()

    def run(self):
        log.info("xpra server version %s" % xpra.__version__)
        gtk_main_quit_on_fatal_exceptions_enable()
        def print_ready():
            log.info("xpra is ready.")
            sys.stdout.flush()
        gobject.idle_add(print_ready)
        gtk.main()
        log.info("xpra end of gtk.main().")
        return self._upgrading

    def cleanup(self, *args):
        if self._tray:
            self._tray.cleanup()
        if self.notifications_forwarder:
            try:
                self.notifications_forwarder.release()
            except Exception, e:
                log.error("failed to release dbus notification forwarder: %s", e)
        log("cleanup will disconnect: %s", self._potential_protocols)
        for proto in self._potential_protocols:
            self.disconnect_client(proto, "shutting down")

    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def _new_connection(self, listener, *args):
        sock, address = listener.accept()
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
            log.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            sock.close()
            return  True
        sc = SocketConnection(sock, sock.getsockname(), address, sock.getpeername())
        log.info("New connection received: %s", sc)
        protocol = Protocol(sc, self.process_packet)
        protocol.large_packets.append("info-response")
        protocol.salt = None
        protocol.set_compression_level(self.compression_level)
        self._potential_protocols.append(protocol)
        protocol.start()
        def verify_connection_accepted(protocol):
            if not protocol._closed and protocol in self._potential_protocols and protocol not in self._server_sources:
                log.error("connection timedout: %s", protocol)
                self.send_disconnect(protocol, "login timeout")
        gobject.timeout_add(10*1000, verify_connection_accepted, protocol)
        return True

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        for p in self._potential_protocols:
            try:
                self.send_disconnect(p, "server shutdown")
            except:
                pass
        gobject.timeout_add(1000, self.quit, False)

    def send_disconnect(self, proto, reason):
        if proto._closed:
            return
        def force_disconnect(*args):
            proto.close()
        proto._add_packet_to_queue(["disconnect", reason])
        gobject.timeout_add(1000, force_disconnect)

    def disconnect_client(self, protocol, reason):
        ss = None
        if protocol:
            log.info("Disconnecting existing client %s, reason is: %s", protocol, reason)
            # send message asking client to disconnect (politely):
            protocol.flush_then_close(["disconnect", reason])
            #this ensures that from now on we ignore any incoming packets coming
            #from this connection as these could potentially set some keys pressed, etc
            ss = self._server_sources.get(protocol)
            if ss:
                ss.close()
                del self._server_sources[protocol]
                log.info("xpra client disconnected.")
        #so it is now safe to clear them:
        #(this may fail during shutdown - which is ok)
        try:
            self._clear_keys_pressed()
        except:
            pass
        self._focus(ss, 0, [])
        log.info("Connection lost")

    def _process_disconnect(self, proto, packet):
        self.disconnect(proto, "on client request")

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
        source = self._server_sources.get(proto)
        if source:
            del self._server_sources[proto]
            source.close()
            log.info("xpra client disconnected.")
        if len(self._server_sources)==0:
            self._clear_keys_pressed()
            self._focus(source, 0, [])
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))


    def _send_password_challenge(self, proto, server_cipher):
        proto.salt = uuid.uuid4().hex
        log.info("Password required, sending challenge")
        packet = ("challenge", proto.salt, server_cipher)
        proto._add_packet_to_queue(packet)

    def _verify_password(self, proto, client_hash, password):
        salt = proto.salt
        proto.salt = None
        if not salt:
            self.send_disconnect(proto, "illegal challenge response received - salt cleared or unset")
            return
        password_hash = hmac.HMAC(password, salt)
        if client_hash != password_hash.hexdigest():
            def login_failed(*args):
                log.error("Password supplied does not match! dropping the connection.")
                self.send_disconnect(proto, "invalid password")
            gobject.timeout_add(1000, login_failed)
            return False
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def get_password(self):
        if not self.password_file or not os.path.exists(self.password_file):
            return  None
        try:
            passwordFile = open(self.password_file, "rU")
            password  = passwordFile.read()
            passwordFile.close()
            while password.endswith("\n") or password.endswith("\r"):
                password = password[:-1]
            return password
        except IOError, e:
            log.error("cannot open password file %s: %s", self.password_file, e)
            return  None


    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        log("process_hello: capabilities=%s", capabilities)
        if capabilities.get("version_request", False):
            response = {"version" : xpra.__version__}
            packet = ["hello", response]
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
            return
        if not self.sanity_checks(proto, capabilities):
            return

        screenshot_req = capabilities.get("screenshot_request", False)
        info_req = capabilities.get("info_request", False)
        if not screenshot_req and not info_req:
            log.info("Handshake complete; enabling connection")

        remote_version = capabilities.get("version")
        if not is_compatible_with(remote_version):
            proto.close()
            return

        #client may have requested encryption:
        cipher = capabilities.get("cipher")
        cipher_iv = capabilities.get("cipher.iv")
        key_salt = capabilities.get("cipher.key_salt")
        iterations = capabilities.get("cipher.key_stretch_iterations")
        password = None
        if self.password_file or (cipher and cipher_iv):
            #we will need the password:
            password = self.get_password()
            if not password:
                self.send_disconnect(proto, "password not found")
                return
        server_cipher = None
        if cipher and cipher_iv:
            if cipher not in ENCRYPTION_CIPHERS:
                log.warn("unsupported cipher: %s", cipher)
                self.send_disconnect(proto, "unsupported cipher")
                return
            proto.set_cipher_out(cipher, cipher_iv, password, key_salt, iterations)
            #use the same cipher as used by the client:
            iv = uuid.uuid4().hex[:16]
            key_salt = uuid.uuid4().hex
            iterations = 1000
            proto.set_cipher_in(cipher, iv, password, key_salt, iterations)
            server_cipher = {
                             "cipher"           : cipher,
                             "cipher.iv"        : iv,
                             "cipher.key_salt"  : key_salt,
                             "cipher.key_stretch_iterations" : iterations
                             }
            log("server cipher=%s", server_cipher)

        if self.password_file:
            log("password auth required")
            #send challenge if this is not a response:
            client_hash = capabilities.get("challenge_response")
            if not client_hash or not proto.salt:
                self._send_password_challenge(proto, server_cipher or "")
                return
            if not self._verify_password(proto, client_hash, password):
                return

        if screenshot_req:
            #this is a screenshot request, handle it and disconnect
            try:
                packet = trap.call(self.make_screenshot_packet)
                proto._add_packet_to_queue(packet)
                gobject.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
            except:
                log.error("failed to capture screenshot", exc_info=True)
                self.send_disconnect(proto, "screenshot failed")
            return
        if info_req:
            thread.start_new_thread(self.send_hello_info, (proto,))
            return

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        share_count = 0
        for p,ss in self._server_sources.items():
            #check existing sessions are willing to share:
            if not self.sharing:
                self.disconnect_client(p, "new valid connection received, this session does not allow sharing")
            elif not capabilities.get("share", False):
                self.disconnect_client(p, "new valid connection received, the new client does not wish to share")
            elif not ss.share:
                self.disconnect_client(p, "new valid connection received, this client had not enabled sharing ")
            else:
                share_count += 1
        if share_count>0:
            log.info("sharing with %s other session(s)", share_count)
        self.dpi = capabilities.get("dpi", self.default_dpi)
        if self.dpi>0:
            #some non-posix clients never send us 'resource-manager' settings
            #so just use a fake one to ensure the dpi gets applied:
            self.update_server_settings({'resource-manager' : ""})
        if capabilities.get("rencode") and has_rencode:
            proto.enable_rencode()
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.chunked_compression = capabilities.get("chunked_compression", False)
        ss = ServerSource(proto, self.get_transient_for,
                          self.supports_mmap,
                          self.supports_speaker, self.supports_microphone,
                          self.speaker_codecs, self.microphone_codecs,
                          self.default_quality)
        ss.parse_hello(capabilities)
        self._server_sources[proto] = ss
        if self.randr:
            root_w, root_h = self.set_best_screen_size()
        else:
            root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        self.calculate_workarea()
        #take the clipboard if no-one else has yet:
        if ss.clipboard_enabled and self._clipboard_helper is not None and \
            (self._clipboard_client is None or self._clipboard_client.closed):
            self._clipboard_client = ss
        #so only activate this feature afterwards:
        self.keyboard_sync = bool(capabilities.get("keyboard_sync", True))
        key_repeat = capabilities.get("key_repeat", None)
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                log.info("setting key repeat rate from client: %sms delay / %sms interval", self.key_repeat_delay, self.key_repeat_interval)
        else:
            #dont do any jitter compensation:
            self.key_repeat_delay = -1
            self.key_repeat_interval = -1
            #but do set a default repeat rate:
            set_key_repeat_rate(500, 30)
        #always clear modifiers before setting a new keymap
        ss.make_keymask_match(capabilities.get("modifiers", []))
        self.set_keymap(ss)

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, server_cipher)

        # now we can set the modifiers to match the client
        self.send_windows_and_cursors(ss)

    def sanity_checks(self, proto, capabilities):
        server_uuid = capabilities.get("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display that the server it connects to is managing - this would create a loop!")
                return  False
            log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def get_transient_for(self, window):
        return  None

    def send_windows_and_cursors(self, ss):
        pass

    def make_hello(self):
        capabilities = {}
        capabilities["hostname"] = socket.gethostname()
        capabilities["max_desktop_size"] = self.get_max_screen_size()
        capabilities["display"] = gtk.gdk.display_get_default().get_name()
        capabilities["version"] = xpra.__version__
        capabilities["platform"] = sys.platform
        capabilities["python_version"] = python_platform.python_version()
        capabilities["encodings"] = ENCODINGS
        capabilities["resize_screen"] = self.randr
        if self.session_name:
            capabilities["session_name"] = self.session_name
        capabilities["start_time"] = int(self.start_time)
        capabilities["notifications"] = self.notifications_forwarder is not None
        capabilities["toggle_cursors_bell_notify"] = True
        capabilities["toggle_keyboard_sync"] = True
        capabilities["bell"] = self.bell
        capabilities["cursors"] = self.cursors
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["rencode"] = has_rencode
        capabilities["window_configure"] = True
        capabilities["xsettings-tuple"] = True
        capabilities["change-quality"] = True
        capabilities["client_window_properties"] = True
        capabilities["info-request"] = True
        return capabilities

    def send_hello(self, server_source, root_w, root_h, key_repeat, server_cipher):
        capabilities = self.make_hello()
        capabilities["actual_desktop_size"] = root_w, root_h
        capabilities["root_window_size"] = root_w, root_h
        capabilities["desktop_size"] = self._get_desktop_size_capability(server_source, root_w, root_h)
        if key_repeat:
            capabilities["key_repeat"] = key_repeat
            capabilities["key_repeat_modifiers"] = True
        capabilities["clipboard"] = self._clipboard_helper is not None and self._clipboard_client == server_source
        if server_cipher:
            capabilities.update(server_cipher)
        add_version_info(capabilities)
        add_gtk_version_info(capabilities, gtk)
        server_source.hello(capabilities)

    def send_hello_info(self, proto):
        packet = ["hello", self.get_info(proto)]
        proto._add_packet_to_queue(packet)
        gobject.timeout_add(5*1000, self.send_disconnect, proto, "info sent")

    def _process_info_request(self, proto, packet):
        client_uuids, wids = packet[1:3]
        sources = [ss for ss in self._server_sources.values() if ss.uuid in client_uuids]
        log("info-request: sources=%s, wids=%s", proto, packet, sources, wids)
        try:
            info = self.do_get_info(proto, sources, wids)
            self._server_sources.get(proto).send_info_response(info)
        except Exception, e:
            log.error("error during info request: %s", e, exc_info=True)

    def get_info(self, proto):
        return self.do_get_info(proto, self._server_sources.values(), self._id_to_window.keys())

    def do_get_info(self, proto, server_sources, window_ids):
        start = time.time()
        info = {}
        add_version_info(info)
        add_gtk_version_info(info, gtk)
        info["hostname"] = socket.gethostname()
        info["root_window_size"] = gtk.gdk.get_default_root_window().get_size()
        info["max_desktop_size"] = self.get_max_screen_size()
        info["session_name"] = self.session_name or ""
        info["password_file"] = self.password_file or ""
        info["randr"] = self.randr
        info["clipboard"] = self._clipboard_helper is not None
        info["cursors"] = self.cursors
        info["bell"] = self.bell
        info["notifications"] = self.notifications_forwarder is not None
        info["pulseaudio"] = self.pulseaudio
        info["start_time"] = int(self.start_time)
        info["encodings"] = ",".join(ENCODINGS)
        info["platform"] = sys.platform
        info["python_version"] = python_platform.python_version()
        info["windows"] = len(self._id_to_window)
        info["keyboard_sync"] = self.keyboard_sync
        info["key_repeat_delay"] = self.key_repeat_delay
        info["key_repeat_interval"] = self.key_repeat_interval
        # other clients:
        info["clients"] = len([p for p in self._server_sources.keys() if p!=proto])
        info["potential_clients"] = len([p for p in self._potential_protocols if ((p is not proto) and (p not in self._server_sources.keys()))])
        #find the source to report on:
        n = len(server_sources)
        if n==1:
            ss = server_sources[0]
            ss.add_info(info)
            ss.add_stats(info, window_ids)
        elif n>1:
            i = 0
            for ss in server_sources:
                ss.add_info(info, suffix="{%s}" % i)
                ss.add_stats(info, window_ids, suffix="{%s}" % i)
                i += 1
        #threads:
        info_threads = proto.get_threads()
        info["threads"] = threading.active_count() - len(info_threads)
        info["info_threads"] = len(info_threads)
        i = 0
        #threads used by the "info" client:
        for t in info_threads:
            info["info_thread[%s]" % i] = t.name
            i += 1
        i = 0
        #all non-info threads:
        for t in threading.enumerate():
            if t not in info_threads:
                info["thread[%s]" % i] = t.name
                i += 1
        log("get_info took %s", time.time()-start)
        return info


    def send_clipboard_packet(self, *parts):
        assert self._clipboard_helper is not None
        if self._clipboard_client:
            self._clipboard_client.send(*parts)

    def notify_callback(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        assert self.notifications_forwarder
        log("notify_callback(%s,%s,%s,%s,%s,%s,%s,%s) send_notifications=%s", dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, self.send_notifications)
        for ss in self._server_sources.values():
            ss.notify(dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))

    def notify_close_callback(self, nid):
        assert self.notifications_forwarder
        log("notify_close_callback(%s)", nid)
        for ss in self._server_sources.values():
            ss.notify_close(int(nid))


    def set_keymap(self, server_source, force=False):
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True

            self.keyboard_config = server_source.set_keymap(self.keyboard_config, self.keys_pressed, force)
        finally:
            # re-enable via idle_add to give all the pending
            # events a chance to run first (and get ignored)
            def reenable_keymap_changes(*args):
                self.keymap_changing = False
                self._keys_changed()
            gobject.idle_add(reenable_keymap_changes)

    def _keys_changed(self, *args):
        if not self.keymap_changing:
            for ss in self._server_sources.values():
                ss.keys_changed()

    def _clear_keys_pressed(self):
        #make sure the timers don't fire and interfere:
        if len(self.keys_repeat_timers)>0:
            for timer in self.keys_repeat_timers.values():
                gobject.source_remove(timer)
            self.keys_repeat_timers = {}
        #clear all the keys we know about:
        if len(self.keys_pressed)>0:
            log("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        unpress_all_keys(gtk.gdk.display_get_default())


    def _focus(self, server_source, wid, modifiers):
        log("_focus(%s,%s)", wid, modifiers)


    def _add_new_window_common(self, window):
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        return wid

    def _do_send_new_window_packet(self, ptype, window, geometry, properties):
        wid = self._window_to_id[window]
        x, y, w, h = geometry
        for ss in self._server_sources.values():
            ss.new_window(ptype, wid, window, x, y, w, h, properties, self.client_properties.get(ss.uuid))


    def _screen_size_changed(self, *args):
        log("_screen_size_changed(%s)", args)
        #randr has resized the screen, tell the client (if it supports it)
        self.calculate_workarea()
        gobject.idle_add(self.send_updated_screen_size)

    def send_updated_screen_size(self):
        max_w, max_h = self.get_max_screen_size()
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        log.info("sending updated screen size to clients: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        for ss in self._server_sources.values():
            ss.updated_desktop_size(root_w, root_h, max_w, max_h)

    def get_max_screen_size(self):
        max_w, max_h = gtk.gdk.get_default_root_window().get_size()
        sizes = get_screen_sizes()
        if self.randr and len(sizes)>=1:
            for w,h in sizes:
                max_w = max(max_w, w)
                max_h = max(max_h, h)
        return max_w, max_h

    def _get_desktop_size_capability(self, server_source, root_w, root_h):
        client_size = server_source.desktop_size
        log("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            """ client did not specify size, just return what we have """
            return    root_w, root_h
        client_w, client_h = client_size
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return    w, h

    def set_best_screen_size(self):
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        max_w, max_h = 0, 0
        sizes = []
        for ss in self._server_sources.values():
            client_size = ss.desktop_size
            if not client_size:
                continue
            sizes.append(client_size)
            w, h = client_size
            max_w = max(max_w, w)
            max_h = max(max_h, h)
        log.info("max client resolution is %sx%s (from %s), current server resolution is %sx%s", max_w, max_h, sizes, root_w, root_h)
        if max_w>0 and max_h>0:
            return self.set_screen_size(max_w, max_h)
        return  root_w, root_h

    def set_screen_size(self, desired_w, desired_h):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        if desired_w==root_w and desired_h==root_h:
            return    root_w,root_h    #unlikely: perfect match already!
        #try to find the best screen size to resize to:
        new_size = None
        for w,h in get_screen_sizes():
            if w<desired_w or h<desired_h:
                continue            #size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue        #we found a better (smaller) candidate already
            new_size = w,h
        log("best resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        if not new_size:
            return  root_w, root_h
        w, h = new_size
        if w==root_w and h==root_h:
            log.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return  root_w, root_h
        try:
            set_screen_size(w, h)
            root_w, root_h = get_screen_size()
            if root_w!=w or root_h!=h:
                log.error("odd, failed to set the new resolution, "
                          "tried to set it to %sx%s and ended up with %sx%s", w, h, root_w, root_h)
            else:
                log.info("new resolution matching %sx%s : screen now set to %sx%s", desired_w, desired_h, root_w, root_h)
        except Exception, e:
            log.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        return  root_w, root_h

    def _process_desktop_size(self, proto, packet):
        width, height = packet[1:3]
        log("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        if len(packet)>=4:
            self._server_sources.get(proto).set_screen_sizes(packet[3])
            self.calculate_workarea()

    def calculate_workarea(self):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        workarea = gtk.gdk.Rectangle(0, 0, root_w, root_h)
        for ss in self._server_sources.values():
            screen_sizes = ss.screen_sizes
            log("screen_sizes(%s)=%s", ss, screen_sizes)
            if not screen_sizes:
                continue
            for display in screen_sizes:
                #avoid error with old/broken clients:
                if not display or type(display) not in (list, tuple):
                    continue
                #display: [':0.0', 2560, 1600, 677, 423, [['DFP2', 0, 0, 2560, 1600, 646, 406]], 0, 0, 2560, 1574]
                if len(display)>10:
                    work_x, work_y, work_w, work_h = display[6:10]
                    display_workarea = gtk.gdk.Rectangle(work_x, work_y, work_w, work_h)
                    log("found workarea % for display %s", display_workarea, display[0])
                    workarea = workarea.intersect(display_workarea)
        #sanity checks:
        if workarea.width==0 or workarea.height==0:
            log.warn("failed to calculate a common workarea - using the full display area")
            workarea = gtk.gdk.Rectangle(0, 0, root_w, root_h)
        self.set_workarea(workarea)

    def set_workarea(self, workarea):
        pass


    def _process_encoding(self, proto, packet):
        encoding = packet[1]
        if len(packet)>=3:
            #client specified which windows this is for:
            in_wids = packet[2]
            wids = []
            wid_windows = {}
            for wid in in_wids:
                if wid not in self._id_to_window:
                    continue
                wids.append(wid)
                wid_windows[wid] = self._id_to_window.get(wid)
        else:
            #apply to all windows:
            wids = None
            wid_windows = self._id_to_window
        self._server_sources.get(proto).set_encoding(encoding, wids)
        self.refresh_windows(proto, wid_windows)


    def send_ping(self):
        for ss in self._server_sources.values():
            ss.ping()

    def _process_ping_echo(self, proto, packet):
        self._server_sources.get(proto).process_ping_echo(packet)

    def _process_ping(self, proto, packet):
        time_to_echo = packet[1]
        self._server_sources.get(proto).process_ping(time_to_echo)

    def _process_screenshot(self, proto, packet):
        packet = self.make_screenshot_packet()
        if packet:
            self._server_sources.get(proto).send(*packet)

    def make_screenshot_packet(self):
        return  None


    def _process_set_notify(self, proto, packet):
        assert self.notifications_forwarder is not None, "cannot toggle notifications: the feature is disabled"
        self._server_sources.get(proto).send_notifications = bool(packet[1])

    def _process_set_cursors(self, proto, packet):
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        self._server_sources.get(proto).send_cursors = bool(packet[1])

    def _process_set_bell(self, proto, packet):
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        self._server_sources.get(proto).send_bell = bool(packet[1])

    def _process_set_deflate(self, proto, packet):
        level = packet[1]
        log("client has requested compression level=%s", level)
        proto.set_compression_level(level)
        #echo it back to the client:
        self._server_sources.get(proto).set_deflate(level)

    def _process_sound_control(self, proto, packet):
        self._server_sources.get(proto).sound_control(*packet[1:])

    def _process_sound_data(self, proto, packet):
        self._server_sources.get(proto).sound_data(*packet[1:])

    def _process_clipboard_enabled_status(self, proto, packet):
        clipboard_enabled = packet[1]
        if self._clipboard_helper:
            assert self._clipboard_client==self._server_sources.get(proto), \
                    "the request to change the clipboard enabled status does not come from the clipboard owner!"
            self._clipboard_client.clipboard_enabled = clipboard_enabled
            log("toggled clipboard to %s", clipboard_enabled)
        else:
            log.warn("client toggled clipboard-enabled but we do not support clipboard at all! ignoring it")

    def _process_keyboard_sync_enabled_status(self, proto, packet):
        self.keyboard_sync = bool(packet[1])
        log("toggled keyboard-sync to %s", self.keyboard_sync)


    def _process_server_settings(self, proto, packet):
        self.update_server_settings(packet[1])

    def update_server_settings(self, settings):
        old_settings = dict(self._settings)
        log("server_settings: old=%s, updating with=%s", old_settings, settings)
        self._settings.update(settings)
        root = gtk.gdk.get_default_root_window()
        for k, v in settings.items():
            #cook the "resource-manager" value to add the DPI:
            if k == "resource-manager" and self.dpi>0:
                value = v.decode("utf-8")
                #parse the resources into a dict:
                values={}
                options = value.split("\n")
                for option in options:
                    if not option:
                        continue
                    parts = option.split(":\t")
                    if len(parts)!=2:
                        continue
                    values[parts[0]] = parts[1]
                values["Xft.dpi"] = self.dpi
                log("server_settings: resource-manager values=%s", values)
                #convert the dict back into a resource string:
                value = ''
                for vk, vv in values.items():
                    value += "%s:\t%s\n" % (vk, vv)
                value += '\n'
                #record the actual value used
                self._settings["resource-manager"] = value
                v = value.encode("utf-8")

            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    log("server_settings: setting %s to %s", p, v)
                    prop_set(root, p, "latin1", v.decode("utf-8"))
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


    def _set_client_properties(self, proto, new_client_properties):
        ss = self._server_sources.get(proto)
        client_properties = self.client_properties.setdefault(ss.uuid, {})
        log("set_client_properties updating %s with %s", client_properties, new_client_properties)
        client_properties.update(new_client_properties)


    def _process_focus(self, proto, packet):
        wid = packet[1]
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self._server_sources.get(proto)
        self._focus(ss, wid, modifiers)

    def _process_layout(self, proto, packet):
        layout, variant = packet[1:3]
        ss = self._server_sources.get(proto)
        if ss.set_layout(layout, variant):
            self.set_keymap(ss, force=True)

    def _process_keymap(self, proto, packet):
        props = packet[1]
        ss = self._server_sources.get(proto)
        if ss.assign_keymap_options(props):
            self.set_keymap(ss, True)
        modifiers = props.get("modifiers")
        ss.make_keymask_match(modifiers)

    def _process_key_action(self, proto, packet):
        wid, keyname, pressed, modifiers, keyval, _, client_keycode = packet[1:8]
        ss = self._server_sources.get(proto)
        keycode = ss.get_keycode(client_keycode, keyname, modifiers)
        log("process_key_action(%s) server keycode=%s", packet, keycode)
        #currently unused: (group, is_modifier) = packet[8:10]
        self._focus(ss, wid, None)
        ss.make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>0:
            self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers)
        ss.user_event()

    def fake_key(self, keycode, press):
        trap.call(xtest_fake_key, gtk.gdk.display_get_default(), keycode, press)

    def _handle_key(self, wid, pressed, name, keyval, keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log("handle_key(%s,%s,%s,%s,%s,%s)", wid, pressed, name, keyval, keycode, modifiers)
        if pressed and (wid is not None) and (wid not in self._id_to_window):
            log("window %s is gone, ignoring key press", wid)
            return
        if keycode<0:
            log.warn("ignoring invalid keycode=%s", keycode)
            return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]
        def press():
            log("handle keycode pressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                self.keys_pressed[keycode] = name
            self.fake_key(keycode, True)
        def unpress():
            log("handle keycode unpressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                del self.keys_pressed[keycode]
            self.fake_key(keycode, False)
        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not self.keyboard_sync:
                    #keyboard is not synced: client manages repeat so unpress
                    #it immediately
                    unpress()
            else:
                log("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                log("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, pressed, name, keyval, keycode, modifiers, self.key_repeat_delay)

    def _key_repeat(self, wid, pressed, keyname, keyval, keycode, modifiers, delay_ms=0):
        """ Schedules/cancels the key repeat timeouts """
        timer = self.keys_repeat_timers.get(keycode, None)
        if timer:
            log("cancelling key repeat timer: %s for %s / %s", timer, keyname, keycode)
            gobject.source_remove(timer)
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                now = time.time()
                log("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.keys_repeat_timers[keycode] = gobject.timeout_add(delay_ms, _key_repeat_timeout, now)

    def _process_key_repeat(self, proto, packet):
        wid, keyname, keyval, client_keycode, modifiers = packet[1:6]
        ss = self._server_sources.get(proto)
        keycode = ss.get_keycode(client_keycode, keyname, modifiers)
        #key repeat uses modifiers from a pointer event, so ignore mod_pointermissing:
        ss.make_keymask_match(modifiers)
        if not self.keyboard_sync:
            #this check should be redundant: clients should not send key-repeat without
            #having keyboard_sync enabled
            return
        if keycode not in self.keys_pressed:
            #the key is no longer pressed, has it timed out?
            when_timedout = self.keys_timedout.get(keycode, None)
            if when_timedout:
                del self.keys_timedout[keycode]
            now = time.time()
            if when_timedout and (now-when_timedout)<30:
                #not so long ago, just re-press it now:
                log("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                self.fake_key(keycode, True)
        self._key_repeat(wid, True, keyname, keyval, keycode, modifiers, self.key_repeat_interval)
        ss.user_event()


    def _move_pointer(self, pos):
        x, y = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        ss = self._server_sources.get(proto)
        ss.make_keymask_match(modifiers)
        window = self._id_to_window.get(wid)
        if not window:
            log("_process_mouse_common() invalid window id: %s", wid)
            return
        trap.swallow(self._move_pointer, pointer)

    def _process_button_action(self, proto, packet):
        wid, button, pressed, pointer, modifiers = packet[1:6]
        self._process_mouse_common(proto, wid, pointer, modifiers)
        self._server_sources.get(proto).user_event()
        display = gtk.gdk.display_get_default()
        try:
            trap.call(xtest_fake_button, display, button, pressed)
        except XError:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        wid, pointer, modifiers = packet[1:4]
        self._process_mouse_common(proto, wid, pointer, modifiers)


    def _process_damage_sequence(self, proto, packet):
        packet_sequence = packet[1]
        log("received sequence: %s", packet_sequence)
        if len(packet)>=6:
            wid, width, height, decode_time = packet[2:6]
            self._server_sources.get(proto).client_ack_damage(packet_sequence, wid, width, height, decode_time)


    def _damage(self, window, x, y, width, height, options=None):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.damage(wid, window, x, y, width, height, options)

    def _cancel_damage(self, wid, window):
        for ss in self._server_sources.values():
            ss.cancel_damage(wid, window)


    def _process_buffer_refresh(self, proto, packet):
        [wid, _, qual] = packet[1:4]
        if wid==-1:
            wid_windows = self._id_to_window
        elif wid in self._id_to_window:
            wid_windows = {wid : self._id_to_window.get(wid)}
        else:
            return
        opts = {"quality" : qual,
                "override_options" : True}
        log("process_buffer_refresh for windows: %s, with options=%s", wid_windows, opts)
        self.refresh_windows(proto, wid_windows, opts)

    def refresh_windows(self, proto, wid_windows, opts=None):
        for wid, window in wid_windows.items():
            if window is None:
                continue
            if not window.is_OR() and not self.is_shown(window):
                log("window is no longer shown, ignoring buffer refresh which would fail")
                continue
            self._server_sources.get(proto).refresh(wid, window, opts)

    def _process_quality(self, proto, packet):
        quality = packet[1]
        log("Setting quality to ", quality)
        self._server_sources.get(proto).set_quality(quality)
        self.refresh_windows(proto, self._id_to_window)


    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)

    def _process_move_window(self, proto, packet):
        log.info("_process_move_window(%s, %s)", proto, packet)

    def _process_resize_window(self, proto, packet):
        log.info("_process_resize_window(%s, %s)", proto, packet)


    def process_packet(self, proto, packet):
        packet_type = packet[0]
        assert isinstance(packet_type, str) or isinstance(packet_type, unicode), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
        if packet_type.startswith("clipboard-"):
            ss = self._server_sources.get(proto)
            assert self._clipboard_client==ss, \
                    "the clipboard packet '%s' does not come from the clipboard owner!" % packet_type
            assert ss.clipboard_enabled, "received a clipboard packet from a source which does not have clipboard enabled!"
            assert self._clipboard_helper, "received a clipboard packet but we do not support clipboard sharing"
            gobject.idle_add(self._clipboard_helper.process_clipboard_packet, packet)
            return
        if proto in self._server_sources:
            handlers = self._authenticated_packet_handlers
            ui_handlers = self._authenticated_ui_packet_handlers
        else:
            handlers = {}
            ui_handlers = self._default_packet_handlers
        handler = handlers.get(packet_type)
        if handler:
            log("process non-ui packet %s", packet_type)
            handler(proto, packet)
            return
        handler = ui_handlers.get(packet_type)
        if handler:
            log("will process ui packet %s", packet_type)
            gobject.idle_add(handler, proto, packet)
            return
        log.error("unknown or invalid packet type: %s", packet_type)
        if proto not in self._server_sources:
            proto.close()
