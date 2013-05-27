# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import threading
import sys
import hmac
import time
import socket
import thread
import signal

from xpra.log import Logger
log = Logger()

import xpra
from xpra.scripts.config import ENCRYPTION_CIPHERS, PREFERED_ENCODING_ORDER, python_platform, get_codecs, has_PIL, has_vpx, has_x264, has_webp
from xpra.scripts.server import deadly_signal
from xpra.net.bytestreams import SocketConnection
from xpra.os_util import get_hex_uuid, SIGNAMES
from xpra.version_util import is_compatible_with, add_version_info
from xpra.codecs.version_info import add_codec_version_info
from xpra.os_util import set_application_name
from xpra.net.protocol import Protocol, has_rencode, rencode_version, use_rencode

MAX_CONCURRENT_CONNECTIONS = 20


SERVER_CORE_ENCODINGS = ["rgb24", "rgb32"]
for test, formats in (
                      (has_vpx    , ["vpx"]),
                      (has_x264   , ["x264"]),
                      (has_webp   , ["webp"]),
                      (has_PIL    , ["png", "png/L", "png/P", "jpeg"]),
                ):
    if test:
        for enc in formats:
            if enc not in SERVER_CORE_ENCODINGS:
                SERVER_CORE_ENCODINGS.append(enc)
SERVER_ENCODINGS = [x for x in SERVER_CORE_ENCODINGS if x not in ("rgb32", )]
#renamed rgb24 to rgb in public encodings:
SERVER_ENCODINGS.remove("rgb24")
SERVER_ENCODINGS.append("rgb")


DEFAULT_ENCODING = [x for x in PREFERED_ENCODING_ORDER if x in SERVER_ENCODINGS][0]


class ServerBase(object):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See GTKServerBase/X11ServerBase and other platform specific subclasses.
    """

    def __init__(self):
        log("ServerBase.__init__()")
        self.init_uuid()
        self.start_time = time.time()

        # This must happen early, before loading in windows at least:
        self._potential_protocols = []
        self._server_sources = {}
        self._aliases = {}
        self._reverse_aliases = {}

        #so clients can store persistent attributes on windows:
        self.client_properties = {}

        self.supports_mmap = False
        self.default_encoding = DEFAULT_ENCODING
        self.session_name = "Xpra"
        self.randr = False

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Misc. state:
        self._upgrading = False

        #Features:
        self.compression_level = 1
        self.password_file = ""

        self.default_quality = -1
        self.default_min_quality = 0
        self.default_speed = -1
        self.default_min_speed = 0
        self.pulseaudio = False
        self.sharing = False
        self.bell = False
        self.cursors = False
        self.default_dpi = 96
        self.dpi = 96

        self.init_packet_handlers()
        self.init_aliases()

    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init(self, sockets, opts):
        log("ServerBase.init(%s, %s)", sockets, opts)

        self.supports_mmap = opts.mmap
        if opts.encoding not in SERVER_ENCODINGS:
            log.warn("ignored invalid default encoding option: %s", opts.encoding)
        else:
            self.default_encoding = opts.encoding
        if not self.default_encoding:
            self.default_encoding = DEFAULT_ENCODING
        self.session_name = opts.session_name
        set_application_name(self.session_name)

        #Features:
        self.compression_level = opts.compression_level
        self.password_file = opts.password_file

        self.default_quality = opts.quality
        self.default_min_quality = opts.min_quality
        self.default_speed = opts.speed
        self.default_min_speed = opts.min_speed
        self.pulseaudio = opts.pulseaudio
        self.sharing = opts.sharing
        self.bell = opts.bell
        self.cursors = opts.cursors
        self.default_dpi = int(opts.dpi)
        self.dpi = self.default_dpi

        log("starting component init")
        self.init_clipboard(opts.clipboard, opts.clipboard_filter_file)
        self.init_keyboard()
        self.init_sound(opts.speaker, opts.speaker_codec, opts.microphone, opts.microphone_codec)
        self.init_notification_forwarder(opts.notifications)

        self.load_existing_windows(opts.system_tray)

        ### All right, we're ready to accept customers:
        for sock in sockets:
            self.idle_add(self.add_listen_socket, sock)

        if opts.pings:
            self.timeout_add(1000, self.send_ping)
        else:
            self.timeout_add(10*1000, self.send_ping)


    def init_uuid(self):
        # Define a server UUID if needed:
        self.uuid = self.get_uuid()
        if not self.uuid:
            self.uuid = unicode(get_hex_uuid())
            self.save_uuid()
        log.info("server uuid is %s", self.uuid)

    def get_uuid(self):
        return  None

    def save_uuid(self):
        pass

    def init_notification_forwarder(self, notifications):
        log("init_notification_forwarder(%s)", notifications)
        self.notifications_forwarder = None
        if notifications and os.name=="posix" and not sys.platform.startswith("darwin"):
            try:
                from xpra.x11.dbus_notifications_forwarder import register
                self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.notifications_forwarder:
                    log.info("using notification forwarder: %s", self.notifications_forwarder)
            except Exception, e:
                log.error("error loading or registering our dbus notifications forwarder:")
                log.error("  %s", e)
                log.info("if you do not have a dedicated dbus session for this xpra instance,")
                log.info("  you should use the '--no-notifications' flag")
                log.info("")

    def init_sound(self, speaker, speaker_codec, microphone, microphone_codec):
        log("init_sound(%s, %s, %s, %s)", speaker, speaker_codec, microphone, microphone_codec)
        self.supports_speaker = bool(speaker)
        self.supports_microphone = bool(microphone)
        self.speaker_codecs = speaker_codec
        if len(self.speaker_codecs)==0 and self.supports_speaker:
            self.speaker_codecs = get_codecs(True, True)
            self.supports_speaker = len(self.speaker_codecs)>0
        self.microphone_codecs = microphone_codec
        if len(self.microphone_codecs)==0 and self.supports_microphone:
            self.microphone_codecs = get_codecs(False, False)
            self.supports_microphone = len(self.microphone_codecs)>0
        try:
            from xpra.sound.pulseaudio_util import add_audio_tagging_env
            add_audio_tagging_env()
        except Exception, e:
            log("failed to set pulseaudio audio tagging: %s", e)

    def init_clipboard(self, clipboard_enabled, clipboard_filter_file):
        log("init_clipboard(%s, %s)", clipboard_enabled, clipboard_filter_file)
        ### Clipboard handling:
        self._clipboard_helper = None
        self._clipboard_client = None
        self._clipboards = []
        if not clipboard_enabled:
            return
        from xpra.platform.features import CLIPBOARDS
        clipboard_filter_res = []
        if clipboard_filter_file:
            if not os.path.exists(clipboard_filter_file):
                log.error("invalid clipboard filter file: '%s' does not exist - clipboard disabled!", clipboard_filter_file)
                return
            try:
                f = open(clipboard_filter_file, "r" )
                try:
                    for line in f:
                        clipboard_filter_res.append(line.strip())
                    log("loaded %s regular expressions from clipboard filter file %s", len(clipboard_filter_res), clipboard_filter_file)
                finally:
                    f.close()
            except:
                log.error("error reading clipboard filter file %s - clipboard disabled!", clipboard_filter_file, exc_info=True)
                return
        try:
            from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
            self._clipboard_helper = GDKClipboardProtocolHelper(self.send_clipboard_packet, self.clipboard_progress, CLIPBOARDS, clipboard_filter_res)
            self._clipboards = CLIPBOARDS
        except Exception, e:
            log.error("failed to setup clipboard helper: %s" % e)

    def init_keyboard(self):
        log("init_keyboard()")
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
        self.watch_keymap_changes()

    def watch_keymap_changes(self):
        pass

    def load_existing_windows(self, system_tray):
        pass

    def is_shown(self, window):
        return True

    def init_packet_handlers(self):
        log("initializing packet handlers")
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
            "min-quality":                          self._process_min_quality,
            "speed":                                self._process_speed,
            "min-speed":                            self._process_min_speed,
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

    def init_aliases(self):
        packet_types = list(self._default_packet_handlers.keys())
        packet_types += list(self._authenticated_packet_handlers.keys())
        packet_types += list(self._authenticated_ui_packet_handlers.keys())
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("got signal %s, exiting", SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.clean_quit()

    def clean_quit(self):
        self.cleanup()
        def quit_timer(*args):
            log.debug("quit_timer()")
            self.quit(False)
        self.timeout_add(500, quit_timer)
        def force_quit(*args):
            log.debug("force_quit()")
            os._exit(1)
        self.timeout_add(5000, force_quit)

    def quit(self, upgrading):
        log("quit(%s)", upgrading)
        self._upgrading = upgrading
        log.info("xpra is terminating.")
        sys.stdout.flush()
        self.do_quit()

    def do_quit(self):
        raise NotImplementedError()

    def run(self):
        log.info("xpra server version %s" % xpra.__version__)
        def print_ready():
            log.info("xpra is ready.")
            sys.stdout.flush()
        self.idle_add(print_ready)
        self.do_run()
        return self._upgrading

    def do_run(self):
        raise NotImplementedError()

    def cleanup(self, *args):
        if self.notifications_forwarder:
            try:
                self.notifications_forwarder.release()
            except Exception, e:
                log.error("failed to release dbus notification forwarder: %s", e)
            self.notifications_forwarder = None
        log("cleanup will disconnect: %s", self._potential_protocols)
        for proto in self._potential_protocols:
            self.disconnect_client(proto, "shutting down")
        self._potential_protocols = []

    def add_listen_socket(self, socket):
        raise NotImplementedError()

    def _new_connection(self, listener, *args):
        sock, address = listener.accept()
        log("new_connection(%s) sock=%s, address=%s", args, sock, address)
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
            log.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            sock.close()
            return  True
        try:
            peername = sock.getpeername()
        except:
            peername = str(address)
        sc = SocketConnection(sock, sock.getsockname(), address, peername)
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
        self.timeout_add(10*1000, verify_connection_accepted, protocol)
        return True

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        for p in self._potential_protocols:
            try:
                self.send_disconnect(p, "server shutdown")
            except:
                pass
        self.timeout_add(1000, self.clean_quit)

    def send_disconnect(self, proto, reason):
        if proto._closed:
            return
        def force_disconnect(*args):
            self.cleanup_source(proto)
            proto.close()
        proto.send_now(["disconnect", reason])
        self.timeout_add(1000, force_disconnect)

    def cleanup_source(self, protocol):
        #this ensures that from now on we ignore any incoming packets coming
        #from this connection as these could potentially set some keys pressed, etc
        source = self._server_sources.get(protocol)
        if source:
            source.close()
            del self._server_sources[protocol]
            log.info("xpra client disconnected.")
        if protocol in self._potential_protocols:
            self._potential_protocols.remove(protocol)
        return source

    def disconnect_client(self, protocol, reason):
        if protocol:
            log.info("Disconnecting existing client %s, reason is: %s", protocol, reason)
            # send message asking client to disconnect (politely):
            protocol.flush_then_close(["disconnect", reason])
            self.cleanup_source(protocol)
        if len(self._server_sources)==0:
            self.no_more_clients()
        log.info("Connection lost")

    def no_more_clients(self):
        #so it is now safe to clear them:
        #(this may fail during shutdown - which is ok)
        try:
            self._clear_keys_pressed()
        except:
            pass
        self._focus(None, 0, [])


    def _process_disconnect(self, proto, packet):
        self.disconnect(proto, "on client request")

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
        source = self.cleanup_source(proto)
        if len(self._server_sources)==0:
            self._clear_keys_pressed()
            self._focus(source, 0, [])
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))
        self.disconnect_client(proto, "invalid packet format")

    def _send_password_challenge(self, proto, server_cipher):
        proto.salt = get_hex_uuid()
        log.info("Password required, sending challenge")
        proto.send_now(("challenge", proto.salt, server_cipher))

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
            self.timeout_add(1000, login_failed)
            return False
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def get_password(self):
        if not self.password_file:
            return None
        filename = os.path.expanduser(self.password_file)
        if not filename:
            return  None
        try:
            passwordFile = open(filename, "rU")
            password  = passwordFile.read()
            passwordFile.close()
            while password.endswith("\n") or password.endswith("\r"):
                password = password[:-1]
            return password
        except IOError, e:
            log.error("cannot open password file %s: %s", filename, e)
            return  None


    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        log("process_hello: capabilities=%s", capabilities)
        if capabilities.get("version_request", False):
            response = {"version" : xpra.__version__}
            proto.send_now(("hello", response))
            self.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
            return
        if not self.sanity_checks(proto, capabilities):
            return
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
            iv = get_hex_uuid()[:16]
            key_salt = get_hex_uuid()
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

        screenshot_req = capabilities.get("screenshot_request", False)
        info_req = capabilities.get("info_request", False)
        if not screenshot_req and not info_req:
            log.info("Handshake complete; enabling connection")

        if screenshot_req:
            #this is a screenshot request, handle it and disconnect
            try:
                packet = self.make_screenshot_packet()
                if not packet:
                    self.send_disconnect(proto, "screenshot failed")
                    return
                proto.send_now(packet)
                self.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
            except Exception, e:
                log.error("failed to capture screenshot", exc_info=True)
                self.send_disconnect(proto, "screenshot failed: %s" % e)
            return
        if info_req:
            log.info("processing info request from %s", proto._conn)
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
        if capabilities.get("rencode") and use_rencode:
            proto.enable_rencode()
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.chunked_compression = capabilities.get("chunked_compression", False)
        proto.aliases = capabilities.get("aliases", {})
        def drop_client(reason="unknown"):
            self.disconnect_client(proto, reason)
        from xpra.server.source import ServerSource
        ss = ServerSource(proto, drop_client,
                          self.get_transient_for,
                          self.supports_mmap,
                          self.default_encoding,
                          self.supports_speaker, self.supports_microphone,
                          self.speaker_codecs, self.microphone_codecs,
                          self.default_quality, self.default_min_quality,
                          self.default_speed, self.default_min_speed)
        ss.parse_hello(capabilities)
        self._server_sources[proto] = ss
        root_w, root_h = self.set_best_screen_size()
        self.calculate_workarea()
        #take the clipboard if no-one else has yet:
        if ss.clipboard_enabled and self._clipboard_helper is not None and \
            (self._clipboard_client is None or self._clipboard_client.is_closed()):
            self._clipboard_client = ss
            #deal with buggy win32 clipboards:
            greedy = capabilities.get("clipboard.greedy")
            if greedy is None:
                #old clients without the flag: take a guess based on platform:
                client_platform = capabilities.get("platform")
                greedy = client_platform is not None and \
                    (client_platform.startswith("win") or client_platform.startswith("darwin"))
            self._clipboard_helper.set_greedy_client(greedy)
            want_targets = capabilities.get("clipboard.want_targets", False)
            self._clipboard_helper.set_want_targets_client(want_targets)
        #so only activate this feature afterwards:
        self.keyboard_sync = bool(capabilities.get("keyboard_sync", True))
        key_repeat = capabilities.get("key_repeat", None)
        self.set_keyboard_repeat(key_repeat)

        #always clear modifiers before setting a new keymap
        ss.make_keymask_match(capabilities.get("modifiers", []))
        self.set_keymap(ss)

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, server_cipher)

        # now we can set the modifiers to match the client
        self.send_windows_and_cursors(ss)

    def set_keyboard_repeat(self, key_repeat):
        pass

    def set_keymap(self, ss):
        pass

    def get_transient_for(self, window):
        return  None

    def send_windows_and_cursors(self, ss):
        pass

    def sanity_checks(self, proto, capabilities):
        server_uuid = capabilities.get("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display that the server it connects to is managing - this would create a loop!")
                return  False
            log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def make_hello(self):
        capabilities = {}
        capabilities["hostname"] = socket.gethostname()
        capabilities["max_desktop_size"] = self.get_max_screen_size()
        capabilities["version"] = xpra.__version__
        capabilities["platform"] = sys.platform
        capabilities["python_version"] = python_platform.python_version()
        capabilities["encodings"] = SERVER_ENCODINGS
        capabilities["encodings.core"] = SERVER_CORE_ENCODINGS
        capabilities["encodings.with_speed"] = [x for x in SERVER_ENCODINGS if x in ("png", "png/P", "png/L", "jpeg", "x264", "rgb")]
        capabilities["encodings.with_quality"] = [x for x in SERVER_ENCODINGS if x in ("jpeg", "webp", "x264")]
        capabilities["clipboards"] = self._clipboards
        if self.session_name:
            capabilities["session_name"] = self.session_name
        capabilities["start_time"] = int(self.start_time)
        now = time.time()
        capabilities["current_time"] = int(now)
        capabilities["elapsed_time"] = int(now - self.start_time)
        capabilities["notifications"] = self.notifications_forwarder is not None
        capabilities["toggle_cursors_bell_notify"] = True
        capabilities["toggle_keyboard_sync"] = True
        capabilities["bell"] = self.bell
        capabilities["cursors"] = self.cursors
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["rencode"] = has_rencode
        if has_rencode:
            capabilities["rencode.version"] = rencode_version
        capabilities["window_configure"] = True
        capabilities["xsettings-tuple"] = True
        capabilities["change-quality"] = True
        capabilities["change-min-quality"] = True
        capabilities["change-speed"] = True
        capabilities["change-min-speed"] = True
        capabilities["client_window_properties"] = True
        capabilities["info-request"] = True
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        capabilities["server_type"] = "base"
        add_version_info(capabilities)
        add_codec_version_info(capabilities)
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
        server_source.hello(capabilities)

    def send_hello_info(self, proto):
        proto.send_now(("hello", self.get_info(proto)))
        self.timeout_add(5*1000, self.send_disconnect, proto, "info sent")

    def _process_info_request(self, proto, packet):
        client_uuids, wids = packet[1:3]
        sources = [ss for ss in self._server_sources.values() if ss.uuid in client_uuids]
        log("info-request: sources=%s, wids=%s", sources, wids)
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        try:
            info = self.do_get_info(proto, sources, wids)
            ss.send_info_response(info)
        except Exception, e:
            log.error("error during info request: %s", e, exc_info=True)

    def get_info(self, proto):
        return self.do_get_info(proto, self._server_sources.values(), self._id_to_window.keys())

    def do_get_info(self, proto, server_sources, window_ids):
        start = time.time()
        info = {}
        add_version_info(info)
        add_codec_version_info(info)
        info["server_type"] = "Python"
        info["hostname"] = socket.gethostname()
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
        info["encodings"] = ",".join(SERVER_ENCODINGS)
        info["encodings.core"] = ",".join(SERVER_CORE_ENCODINGS)
        info["platform"] = sys.platform
        info["python_version"] = python_platform.python_version()
        info["windows"] = len([window for window in list(self._id_to_window.values()) if window.is_managed()])
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
        #platform specific bits:
        try:
            from xpra.platform.info import get_sys_info
            for k,v in get_sys_info().items():
                info[k] = v
        except:
            log.error("error getting system info", exc_info=True)
        log("get_info took %.1fms", 1000.0*(time.time()-start))
        return info

    def clipboard_progress(self, local_requests, remote_requests):
        assert self._clipboard_helper is not None
        if self._clipboard_client and self._clipboard_client.clipboard_notifications:
            log("sending clipboard-pending-requests=%s to %s", local_requests, self._clipboard_client)
            self._clipboard_client.send("clipboard-pending-requests", local_requests)

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


    def _keys_changed(self, *args):
        if not self.keymap_changing:
            for ss in self._server_sources.values():
                ss.keys_changed()

    def _clear_keys_pressed(self):
        pass


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
            wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
            ss.new_window(ptype, wid, window, x, y, w, h, properties, wprops)


    def _screen_size_changed(self, *args):
        log("_screen_size_changed(%s)", args)
        #randr has resized the screen, tell the client (if it supports it)
        self.calculate_workarea()
        self.idle_add(self.send_updated_screen_size)

    def get_root_window_size(self):
        raise NotImplementedError()

    def send_updated_screen_size(self):
        max_w, max_h = self.get_max_screen_size()
        root_w, root_h = self.get_root_window_size()
        log.info("sending updated screen size to clients: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        for ss in self._server_sources.values():
            ss.updated_desktop_size(root_w, root_h, max_w, max_h)

    def get_max_screen_size(self):
        max_w, max_h = self.get_root_window_size()
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
        root_w, root_h = self.get_root_window_size()
        return root_w, root_h


    def _process_desktop_size(self, proto, packet):
        width, height = packet[1:3]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        log("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        if len(packet)>=4:
            ss.set_screen_sizes(packet[3])
            self.calculate_workarea()

    def calculate_workarea(self):
        raise NotImplementedError()

    def set_workarea(self, workarea):
        pass


    def _process_encoding(self, proto, packet):
        encoding = packet[1]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
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
        ss.set_encoding(encoding, wids)
        self.refresh_windows(proto, wid_windows)


    def send_ping(self):
        for ss in self._server_sources.values():
            ss.ping()
        return True

    def _process_ping_echo(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.process_ping_echo(packet)

    def _process_ping(self, proto, packet):
        time_to_echo = packet[1]
        ss = self._server_sources.get(proto)
        if ss:
            ss.process_ping(time_to_echo)

    def _process_screenshot(self, proto, packet):
        packet = self.make_screenshot_packet()
        ss = self._server_sources.get(proto)
        if packet and ss:
            ss.send(*packet)

    def make_screenshot_packet(self):
        return  None


    def _process_set_notify(self, proto, packet):
        assert self.notifications_forwarder is not None, "cannot toggle notifications: the feature is disabled"
        ss = self._server_sources.get(proto)
        if ss:
            ss.send_notifications = bool(packet[1])

    def _process_set_cursors(self, proto, packet):
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        ss = self._server_sources.get(proto)
        if ss:
            ss.send_cursors = bool(packet[1])

    def _process_set_bell(self, proto, packet):
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        ss = self._server_sources.get(proto)
        if ss:
            ss.send_bell = bool(packet[1])

    def _process_set_deflate(self, proto, packet):
        level = packet[1]
        log("client has requested compression level=%s", level)
        proto.set_compression_level(level)
        #echo it back to the client:
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_deflate(level)

    def _process_sound_control(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.sound_control(*packet[1:])

    def _process_sound_data(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.sound_data(*packet[1:])

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


    def _set_client_properties(self, proto, wid, new_client_properties):
        ss = self._server_sources.get(proto)
        if ss:
            client_properties = self.client_properties.setdefault("%s|%s" % (wid, ss.uuid), {})
            log("set_client_properties updating %s with %s", client_properties, new_client_properties)
            client_properties.update(new_client_properties)


    def _process_focus(self, proto, packet):
        wid = packet[1]
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self._server_sources.get(proto)
        if ss:
            self._focus(ss, wid, modifiers)

    def _process_layout(self, proto, packet):
        layout, variant = packet[1:3]
        ss = self._server_sources.get(proto)
        if ss and ss.set_layout(layout, variant):
            self.set_keymap(ss, force=True)

    def _process_keymap(self, proto, packet):
        props = packet[1]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        log.info("received new keymap from client %s", proto)
        if ss.assign_keymap_options(props):
            self.set_keymap(ss, True)
        modifiers = props.get("modifiers")
        ss.make_keymask_match(modifiers)

    def _process_key_action(self, proto, packet):
        wid, keyname, pressed, modifiers, keyval, _, client_keycode = packet[1:8]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        keycode = self.get_keycode(ss, client_keycode, keyname, modifiers)
        log("process_key_action(%s) server keycode=%s", packet, keycode)
        #currently unused: (group, is_modifier) = packet[8:10]
        self._focus(ss, wid, None)
        ss.make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>0:
            self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers)
        ss.user_event()

    def get_keycode(self, ss, client_keycode, keyname, modifiers):
        return ss.get_keycode(client_keycode, keyname, modifiers)


    def fake_key(self, keycode, press):
        pass

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
            self.source_remove(timer)
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                now = time.time()
                log("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.keys_repeat_timers[keycode] = self.timeout_add(delay_ms, _key_repeat_timeout, now)

    def _process_key_repeat(self, proto, packet):
        wid, keyname, keyval, client_keycode, modifiers = packet[1:6]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
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
        raise NotImplementedError()

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        pass

    def _process_button_action(self, proto, packet):
        pass

    def _process_pointer_position(self, proto, packet):
        wid, pointer, modifiers = packet[1:4]
        self._process_mouse_common(proto, wid, pointer, modifiers)


    def _process_damage_sequence(self, proto, packet):
        packet_sequence = packet[1]
        if len(packet)>=6:
            wid, width, height, decode_time = packet[2:6]
            ss = self._server_sources.get(proto)
            if ss:
                ss.client_ack_damage(packet_sequence, wid, width, height, decode_time)


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
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            if not window.is_OR() and not self.is_shown(window):
                log("window is no longer shown, ignoring buffer refresh which would fail")
                continue
            ss.refresh(wid, window, opts)

    def _process_quality(self, proto, packet):
        quality = packet[1]
        log("Setting quality to ", quality)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_quality(quality)
            self.refresh_windows(proto, self._id_to_window)

    def _process_min_quality(self, proto, packet):
        min_quality = packet[1]
        log("Setting min quality to ", min_quality)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_min_quality(min_quality)
            self.refresh_windows(proto, self._id_to_window)

    def _process_speed(self, proto, packet):
        speed = packet[1]
        log("Setting speed to ", speed)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_speed(speed)
            self.refresh_windows(proto, self._id_to_window)

    def _process_min_speed(self, proto, packet):
        min_speed = packet[1]
        log("Setting min speed to ", min_speed)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_min_speed(min_speed)
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
        if type(packet_type)==int:
            packet_type = self._aliases.get(packet_type)
        assert isinstance(packet_type, (str, unicode)), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
        if packet_type.startswith("clipboard-"):
            ss = self._server_sources.get(proto)
            if not ss:
                #protocol has been dropped!
                return
            assert self._clipboard_client==ss, \
                    "the clipboard packet '%s' does not come from the clipboard owner!" % packet_type
            assert ss.clipboard_enabled, "received a clipboard packet from a source which does not have clipboard enabled!"
            assert self._clipboard_helper, "received a clipboard packet but we do not support clipboard sharing"
            self.idle_add(self._clipboard_helper.process_clipboard_packet, packet)
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
            self.idle_add(handler, proto, packet)
            return
        log.error("unknown or invalid packet type: %s from %s", packet_type, proto)
        if proto not in self._server_sources:
            proto.close()
