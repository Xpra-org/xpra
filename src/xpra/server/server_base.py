# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import time

from xpra.log import Logger
log = Logger()

from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.server.server_core import ServerCore
from xpra.os_util import thread, get_hex_uuid
from xpra.version_util import add_version_info
from xpra.util import alnum
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, codec_versions, has_codec, get_codec
from xpra.codecs.video_helper import getVideoHelper

if sys.version > '3':
    unicode = str           #@ReservedAssignment


MAX_CONCURRENT_CONNECTIONS = 20


class ServerBase(ServerCore):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See GTKServerBase/X11ServerBase and other platform specific subclasses.
    """

    def __init__(self):
        ServerCore.__init__(self)
        log("ServerBase.__init__()")
        self.init_uuid()

        # This must happen early, before loading in windows at least:
        self._server_sources = {}

        #so clients can store persistent attributes on windows:
        self.client_properties = {}

        self.supports_mmap = False
        self.randr = False

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

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
        self.supports_clipboard = False
        self.supports_dbus_proxy = False
        self.dbus_helper = None

        #encodings:
        self.core_encodings = []
        self.encodings = []
        self.lossless_encodings = []
        self.lossless_mode_encodings = []
        self.default_encoding = None

        self.init_encodings()
        self.init_packet_handlers()
        self.init_aliases()

    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()

    def init(self, opts):
        ServerCore.init(self, opts)
        log("ServerBase.init(%s)", opts)
        self.supports_mmap = opts.mmap
        self.init_encoding(opts.encoding)

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
        self.supports_clipboard = opts.clipboard
        self.supports_dbus_proxy = opts.dbus_proxy

        log("starting component init")
        self.init_clipboard(self.supports_clipboard, opts.clipboard_filter_file)
        self.init_keyboard()
        self.init_sound(opts.speaker, opts.speaker_codec, opts.microphone, opts.microphone_codec)
        self.init_notification_forwarder(opts.notifications)
        self.init_dbus_helper()

        self.load_existing_windows(opts.system_tray)

        if opts.pings:
            self.timeout_add(1000, self.send_ping)
        else:
            self.timeout_add(10*1000, self.send_ping)
        thread.start_new_thread(self.threaded_init, ())

    def threaded_init(self):
        log("threaded_init() start")
        #try to load video encoders in advance as this can take some time:
        getVideoHelper().may_init()
        log("threaded_init() end")

    def init_encodings(self):
        #core encodings: all the specific encoding formats we can encode:
        self.core_encodings = ["rgb24", "rgb32"]
        #encodings: the format families we can encode (same as core, except for rgb):
        self.encodings = ["rgb"]

        def add_encodings(encodings):
            for e in encodings:
                if e not in self.encodings:
                    self.encodings.append(e)
                if e not in self.core_encodings:
                    self.core_encodings.append(e)

        #video encoders (actual encodings supported are queried):
        for codec_name in ("enc_vpx", "enc_x264", "enc_nvenc"):
            codec = get_codec(codec_name)
            if codec:
                #codec.get_type()    #ie: "vpx", "x264" or "nvenc"
                log("init_encodings() codec %s found, adding: %s", codec.get_type(), codec.get_encodings())
                add_encodings(codec.get_encodings())  #ie: ["vp8"] or ["h264"]

        for module, encodings in {
                              "enc_webp"  : ["webp"],
                              "PIL"       : ["png", "png/L", "png/P", "jpeg"],
                              }.items():
            if not has_codec(module):
                log("init_encodings() codec module %s is missing, not adding: %s", module, encodings)
                continue
            add_encodings(encodings)

        self.lossless_encodings = [x for x in self.core_encodings if (x.startswith("png") or x.startswith("rgb"))]
        self.lossless_mode_encodings = []
        if has_codec("enc_webp_lossless"):
            self.lossless_mode_encodings.append("webp")
            self.lossless_encodings.append("webp")

        self.default_encoding = [x for x in PREFERED_ENCODING_ORDER if x in self.encodings][0]

    def init_encoding(self, cmdline_encoding):
        if cmdline_encoding and cmdline_encoding not in self.encodings:
            log.warn("ignored invalid default encoding option: %s", cmdline_encoding)
        else:
            self.default_encoding = cmdline_encoding

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
        try:
            from xpra.sound.gstreamer_util import has_gst, get_sound_codecs
        except Exception, e:
            log("cannot load gstreamer: %s", e)
            has_gst = False
        log("init_sound(%s, %s, %s, %s) has_gst=%s", speaker, speaker_codec, microphone, microphone_codec, has_gst)
        self.supports_speaker = bool(speaker) and has_gst
        self.supports_microphone = bool(microphone) and has_gst
        self.speaker_codecs = speaker_codec
        if len(self.speaker_codecs)==0 and self.supports_speaker:
            self.speaker_codecs = get_sound_codecs(True, True)
            self.supports_speaker = len(self.speaker_codecs)>0
        self.microphone_codecs = microphone_codec
        if len(self.microphone_codecs)==0 and self.supports_microphone:
            self.microphone_codecs = get_sound_codecs(False, False)
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

    def init_dbus_helper(self):
        if not self.supports_dbus_proxy:
            return
        try:
            from xpra.x11.dbus_helper import DBusHelper
            self.dbus_helper = DBusHelper()
        except Exception, e:
            log.warn("cannot load dbus helper: %s", e)
            self.supports_dbus_proxy = False


    def load_existing_windows(self, system_tray):
        pass

    def is_shown(self, window):
        return True

    def init_packet_handlers(self):
        ServerCore.init_packet_handlers(self)
        self._authenticated_packet_handlers = {
            "set-clipboard-enabled":                self._process_clipboard_enabled_status,
            "set-keyboard-sync-enabled":            self._process_keyboard_sync_enabled_status,
            "damage-sequence":                      self._process_damage_sequence,
            "ping":                                 self._process_ping,
            "ping_echo":                            self._process_ping_echo,
            "set-cursors":                          self._process_set_cursors,
            "set-notify":                           self._process_set_notify,
            "set-bell":                             self._process_set_bell,
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
            "suspend":                              self._process_suspend,
            "resume":                               self._process_resume,
            #dbus:
            "rpc":                                  self._process_rpc,
            #sound:
            "sound-control":                        self._process_sound_control,
            "sound-data":                           self._process_sound_data,
            #requests:
            "shutdown-server":                      self._process_shutdown_server,
            "exit-server":                          self._process_exit_server,
            "buffer-refresh":                       self._process_buffer_refresh,
            "screenshot":                           self._process_screenshot,
            "disconnect":                           self._process_disconnect,
            # Note: "clipboard-*" packets are handled via a special case..
            })

    def init_aliases(self):
        packet_types = list(self._default_packet_handlers.keys())
        packet_types += list(self._authenticated_packet_handlers.keys())
        packet_types += list(self._authenticated_ui_packet_handlers.keys())
        self.do_init_aliases(packet_types)


    def cleanup(self, *args):
        if self.notifications_forwarder:
            thread.start_new_thread(self.notifications_forwarder.release, ())
            self.notifications_forwarder = None
        ServerCore.cleanup(self)

    def add_listen_socket(self, socktype, socket):
        raise NotImplementedError()

    def _disconnect_all(self, message):
        for p in self._potential_protocols:
            try:
                self.send_disconnect(p, message)
            except:
                pass

    def _process_exit_server(self, proto, packet):
        log.info("Exiting response to request")
        self._disconnect_all("server exiting")
        self.timeout_add(1000, self.clean_quit, False, ServerCore.EXITING_CODE)

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        self._disconnect_all("server shutdown")
        self.timeout_add(1000, self.clean_quit)

    def force_disconnect(self, proto):
        self.cleanup_source(proto)
        ServerCore.force_disconnect(self, proto)

    def disconnect_protocol(self, protocol, reason):
        ServerCore.disconnect_protocol(self, protocol, reason)
        self.cleanup_source(protocol)

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

    def is_timedout(self, protocol):
        return ServerCore.is_timedout(self, protocol) and protocol not in self._server_sources

    def no_more_clients(self):
        #so it is now safe to clear them:
        #(this may fail during shutdown - which is ok)
        try:
            self._clear_keys_pressed()
        except:
            pass
        self._focus(None, 0, [])


    def _process_disconnect(self, proto, packet):
        self.disconnect_protocol(proto, "on client request")

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
        source = self.cleanup_source(proto)
        if len(self._server_sources)==0:
            self._clear_keys_pressed()
            self._focus(source, 0, [])
        sys.stdout.flush()


    def hello_oked(self, proto, packet, c, auth_caps):
        if c.boolget("screenshot_request"):
            self.send_screenshot(proto)
            return
        if c.boolget("info_request", False):
            self.send_hello_info(proto)
            return
        command_req = c.strlistget("command_request")
        if len(command_req)>0:
            self.handle_command_request(proto, command_req)
            return

        #"normal" connection, so log welcome message:
        log.info("Handshake complete; enabling connection")

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        share_count = 0
        for p,ss in self._server_sources.items():
            #check existing sessions are willing to share:
            if not self.sharing:
                self.disconnect_client(p, "new valid connection received, this session does not allow sharing")
            elif not c.boolget("share"):
                self.disconnect_client(p, "new valid connection received, the new client does not wish to share")
            elif not ss.share:
                self.disconnect_client(p, "new valid connection received, this client had not enabled sharing ")
            else:
                share_count += 1
        if share_count>0:
            log.info("sharing with %s other session(s)", share_count)
        self.dpi = c.intget("dpi", self.default_dpi)
        if self.dpi>0:
            #some non-posix clients never send us 'resource-manager' settings
            #so just use a fake one to ensure the dpi gets applied:
            self.update_server_settings({'resource-manager' : ""})
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.aliases = c.dictget("aliases")
        #use blocking sockets from now on:
        self.set_socket_timeout(proto._conn, None)

        def drop_client(reason="unknown"):
            self.disconnect_client(proto, reason)
        def get_window_id(wid):
            return self._window_to_id.get(wid)
        from xpra.server.source import ServerSource
        ss = ServerSource(proto, drop_client,
                          self.idle_add, self.timeout_add, self.source_remove,
                          self.get_transient_for, self.get_focus,
                          get_window_id,
                          self.supports_mmap,
                          self.core_encodings, self.encodings, self.default_encoding,
                          self.supports_speaker, self.supports_microphone,
                          self.speaker_codecs, self.microphone_codecs,
                          self.default_quality, self.default_min_quality,
                          self.default_speed, self.default_min_speed)
        log("process_hello serversource=%s", ss)
        ss.parse_hello(c)
        self._server_sources[proto] = ss
        root_w, root_h = self.set_best_screen_size()
        self.calculate_workarea()
        #take the clipboard if no-one else has yet:
        if ss.clipboard_enabled and self._clipboard_helper is not None and \
            (self._clipboard_client is None or self._clipboard_client.is_closed()):
            self._clipboard_client = ss
            #deal with buggy win32 clipboards:
            if "clipboard.greedy" not in c:
                #old clients without the flag: take a guess based on platform:
                client_platform = c.strget("platform", "")
                greedy = client_platform.startswith("win") or client_platform.startswith("darwin")
            else:
                greedy = c.boolget("clipboard.greedy")
            self._clipboard_helper.set_greedy_client(greedy)
            want_targets = c.boolget("clipboard.want_targets")
            self._clipboard_helper.set_want_targets_client(want_targets)
            #the selections the client supports (default to all):
            from xpra.platform.features import CLIPBOARDS
            client_selections = c.strlistget("clipboard.selections", CLIPBOARDS)
            log("process_hello server has clipboards: %s, client supports: %s", self._clipboards, client_selections)
            self._clipboard_helper.enable_selections(client_selections)

        #so only activate this feature afterwards:
        self.keyboard_sync = c.boolget("keyboard_sync", True)
        key_repeat = c.intpair("key_repeat")
        self.set_keyboard_repeat(key_repeat)

        #always clear modifiers before setting a new keymap
        ss.make_keymask_match(c.strlistget("modifiers", []))
        self.set_keymap(ss)

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, auth_caps)

        # now we can set the modifiers to match the client
        self.send_windows_and_cursors(ss)

        ss.startup_complete()

    def update_server_settings(self, settings):
        log("server settings ignored: ", settings)

    def set_keyboard_repeat(self, key_repeat):
        pass

    def set_keymap(self, ss):
        pass

    def get_transient_for(self, window):
        return  None

    def send_windows_and_cursors(self, ss):
        pass

    def sanity_checks(self, proto, c):
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display that the server it connects to is managing - this would create a loop!")
                return  False
            log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def make_hello(self):
        capabilities = ServerCore.make_hello(self)
        capabilities.update({
             "max_desktop_size"             : self.get_max_screen_size(),
             "clipboards"                   : self._clipboards,
             "notifications"                : self.notifications_forwarder is not None,
             "bell"                         : self.bell,
             "cursors"                      : self.cursors,
             "dbus_proxy"                   : self.supports_dbus_proxy,
             "toggle_cursors_bell_notify"   : True,
             "toggle_keyboard_sync"         : True,
             "window_configure"             : True,
             "window_unmap"                 : True,
             "xsettings-tuple"              : True,
             "change-quality"               : True,
             "change-min-quality"           : True,
             "change-speed"                 : True,
             "change-min-speed"             : True,
             "client_window_properties"     : True,
             "sound_sequence"               : True,
             "notify-startup-complete"      : True,
             "suspend-resume"               : True,
             "encoding.generic"             : True,
             "exit_server"                  : True,
             "sound.server_driven"          : True,
             "server_type"                  : "base",
             })
        add_version_info(capabilities)
        for k,v in codec_versions.items():
            capabilities["encoding.%s.version" % k] = v
        return capabilities

    def get_encoding_info(self):
        """
            Warning: the encodings values may get
            re-written on the way out.
            (see ServerSource.rewrite_encoding_values)
        """
        return  {
             "encodings"                : self.encodings,
             "encodings.core"           : self.core_encodings,
             "encodings.lossless"       : self.lossless_encodings,
             "encodings.with_speed"     : [x for x in self.core_encodings if x in ("png", "png/P", "png/L", "jpeg", "h264", "rgb")],
             "encodings.with_quality"   : [x for x in self.core_encodings if x in ("jpeg", "webp", "h264")],
             "encodings.with_lossless_mode" : self.lossless_mode_encodings}

    def send_hello(self, server_source, root_w, root_h, key_repeat, server_cipher):
        capabilities = self.make_hello()
        capabilities.update(self.get_encoding_info())
        capabilities.update({
                     "actual_desktop_size"  : (root_w, root_h),
                     "root_window_size"     : (root_w, root_h),
                     "desktop_size"         : self._get_desktop_size_capability(server_source, root_w, root_h),
                     })
        if key_repeat:
            capabilities.update({
                     "key_repeat"           : key_repeat,
                     "key_repeat_modifiers" : True})
        capabilities["clipboard"] = self._clipboard_helper is not None and self._clipboard_client == server_source
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.hello(capabilities)


    def handle_command_request(self, proto, args):
        try:
            self.do_handle_command_request(proto, args)
        except Exception, e:
            log.error("error processing command %s", args, exc_info=True)
            proto.send_now(("hello", {"command_response"  : (127, "error processing command: %s" % e)}))

    def do_handle_command_request(self, proto, args):
        assert len(args)>0
        log("handle_command_request(%s, %s)", proto, args)
        command = args[0]
        def respond(error=0, response=""):
            log("command request response(%s)=%s", command, response)
            hello = {"command_response"  : (error, response)}
            proto.send_now(("hello", hello))
        def argn_err(argn):
            respond(4, "invalid number of arguments: %s expected" % argn)
        def arg_err(n, msg):
            respond(5, "invalid argument %s: %s" % (n, msg))
        def success():
            respond(0, "success")

        commands = ("hello",
                    "compression", "encoder",
                    "sound-output",
                    "scaling",
                    "suspend", "resume", "name",
                    "client")
        if command=="help":
            return respond(0, "control supports: %s" % (", ".join(commands)))

        if command not in commands:
            return respond(6, "invalid command")

        if command=="hello":
            return respond(0, "hello")
        #from here on, we assume the command applies to the
        #current client connection, of which there must only be one:
        sss = list(self._server_sources.items())
        if len(sss)==0:
            return respond(2, "no client connected")
        elif len(sss)>1:
            return respond(3, "more than one client connected")
        cproto, csource = sss[0]

        def may_forward_client_command(client_command):
            if client_command[0] not in csource.control_commands:
                log.info("not forwarded to client (not supported)")
                return  False
            csource.send_client_command(*client_command)
            return True

        log("handle_command_request will apply to client: %s", csource)
        if command=="compression":
            if len(args)!=2:
                return argn_err(2)
            compression = args[1].lower()
            opts = ("lz4", "zlib")
            if compression=="lz4":
                cproto.enable_lz4()
                may_forward_client_command(["enable_lz4"])
                return success()
            elif compression=="zlib":
                cproto.enable_zlib()
                may_forward_client_command(["enable_zlib"])
                return success()
            return arg_err(1, "must be one of: %s" % (", ".join(opts)))
        elif command=="encoder":
            if len(args)!=2:
                return argn_err(2)
            encoder = args[1].lower()
            opts = ("bencode", "rencode")
            if encoder=="bencode":
                cproto.enable_bencode()
                may_forward_client_command(["enable_bencode"])
                return success()
            elif encoder=="rencode":
                cproto.enable_rencode()
                may_forward_client_command(["enable_rencode"])
                return success()
            return arg_err(1, "must be one of: %s" % (", ".join(opts)))
        elif command=="sound-output":
            if len(args)<2:
                return argn_err("more than 1")
            msg = csource.sound_control(*args[1:])
            return respond(0, msg)
        elif command=="suspend":
            csource.suspend(True, self._id_to_window)
            return respond(0, "suspended")
        elif command=="resume":
            csource.resume(True, self._id_to_window)
            return respond(0, "resumed")
        elif command=="scaling":
            if len(args)!=3:
                return argn_err(3)
            if args[1]=="*":
                wids = csource.window_sources.keys()
            else:
                try:
                    wid = int(args[1])
                    csource.window_sources[wid]
                    wids = [wid]
                except:
                    return respond(10, "cannot find window id %s" % args[1])
            try:
                from xpra.server.window_video_source import parse_scaling_value
                scaling = parse_scaling_value(args[2])
            except:
                return respond(11, "invalid scaling value %s" % args[2])
            for wid in wids:
                window = self._id_to_window.get(wid)
                if not window:
                    continue
                ws = csource.window_sources.get(wid)
                if ws:
                    ws.set_scaling(scaling)
                    csource.refresh(wid, window, {})
            return respond(0, "scaling set to %s" % str(scaling))
        elif command=="name":
            if len(args)!=2:
                return argn_err(1)
            self.session_name = args[1]
            log.info("changed session name: %s", self.session_name)
            may_forward_client_command(["name"])
            return respond(0, "session name set")
        elif command=="client":
            if len(args)<2:
                return argn_err("at least 2")
            client_command = args[1:]
            if client_command[0] not in csource.control_commands:
                return respond(12, "client does not support control command '%s'" % client_command[0])
            csource.send_client_command(*client_command)
            return respond(0, "client control command '%s' forwarded" % (client_command[0]))
        else:
            return respond(9, "internal state error: invalid command '%s'", command)


    def send_screenshot(self, proto):
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

    def send_hello_info(self, proto):
        log.info("processing info request from %s", proto._conn)
        self.get_all_info(self.do_send_info, proto, self._id_to_window.keys())

    def get_ui_info(self, proto, wids, *args):
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        info = {"server.max_desktop_size" : self.get_max_screen_size()}
        #window info:
        self.add_windows_info(info, wids)
        return info

    def get_info(self, proto, client_uuids=None, wids=None, *args):
        start = time.time()
        info = ServerCore.get_info(self, proto)
        if client_uuids:
            sources = [ss for ss in self._server_sources.values() if ss.uuid in client_uuids]
        else:
            sources = self._server_sources.values()
        if not wids:
            wids = self._id_to_window.keys()
        log("info-request: sources=%s, wids=%s", sources, wids)
        ei = self.do_get_info(proto, sources, wids)
        info.update(ei)
        log("get_info took %.1fms", 1000.0*(time.time()-start))
        return info

    def do_get_info(self, proto, server_sources=None, window_ids=None):
        info = {
             "features.randr"           : self.randr,
             "features.cursors"         : self.cursors,
             "features.bell"            : self.bell,
             "features.notifications"   : self.notifications_forwarder is not None,
             "features.pulseaudio"      : self.pulseaudio,
             "features.dbus_proxy"      : self.supports_dbus_proxy,
             "features.clipboard"       : self.supports_clipboard}
        if self._clipboard_helper is not None:
            for k,v in self._clipboard_helper.get_info().items():
                info["clipboard.%s" % k] = v
        info.update(self.get_encoding_info())
        for k,v in codec_versions.items():
            info["encoding.%s.version" % k] = v
        info["windows"] = len([window for window in list(self._id_to_window.values()) if window.is_managed()])
        info.update({
             "keyboard.sync"            : self.keyboard_sync,
             "keyboard.repeat.delay"    : self.key_repeat_delay,
             "keyboard.repeat.interval" : self.key_repeat_interval,
             "keyboard.keys_pressed"    : self.keys_pressed.values(),
             "keyboard.modifiers"       : self.xkbmap_mod_meanings})
        if self.keyboard_config:
            for k,v in self.keyboard_config.get_info().items():
                if v is not None:
                    info["keyboard."+k] = v
        # csc and video encoders:
        info.update(getVideoHelper().get_info())

        # other clients:
        info["clients"] = len([p for p in self._server_sources.keys() if p!=proto])
        info["clients.unauthenticated"] = len([p for p in self._potential_protocols if ((p is not proto) and (p not in self._server_sources.keys()))])
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
        return info

    def add_windows_info(self, info, window_ids):
        for wid, window in self._id_to_window.items():
            if wid not in window_ids:
                continue
            for k,v in self.get_window_info(window).items():
                wp = "window[%s]." % wid
                info[wp + k] = v

    def get_window_info(self, window):
        from xpra.server.source import make_window_metadata
        info = {}
        for prop in window.get_property_names():
            if prop=="icon" or prop is None:
                continue
            metadata = make_window_metadata(window, prop,
                                            generic_window_types=True, client_supports_png=False,
                                            get_transient_for=self.get_transient_for)
            info.update(metadata)
        if "size-constraints" in info:
            size_constraints = info["size-constraints"]
            del info["size-constraints"]
            for k,v in size_constraints.items():
                info["size-constraints.%s" % k] = v
        info.update({
             "override-redirect"    : window.is_OR(),
             "tray"                 : window.is_tray(),
             "size"                 : window.get_dimensions(),
             "position"             : window.get_position()})
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
        log("notify_callback(%s,%s,%s,%s,%s,%s,%s,%s)", dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)
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

    def get_focus(self):
        #can be overriden by subclasses that do manage focus
        #(ie: not shadow servers which only have a single window)
        #default: no focus
        return -1

    def _add_new_window_common(self, window):
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        return wid

    def _do_send_new_window_packet(self, ptype, window, geometry):
        wid = self._window_to_id[window]
        x, y, w, h = geometry
        for ss in self._server_sources.values():
            wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
            ss.new_window(ptype, wid, window, x, y, w, h, wprops)


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


    def _process_rpc(self, proto, packet):
        ss = self._server_sources.get(proto)
        assert ss is not None
        rpc_type, rpcid, _, bus_name, path, interface, function, args = packet[1:9]
        assert rpc_type=="dbus", "unsupported rpc request type: %s" % rpc_type
        assert self.supports_dbus_proxy, "server does not support dbus proxy calls"
        def native(args):
            if args is None:
                return ""
            return [self.dbus_helper.dbus_to_native(x) for x in args]
        def ok_back(*args):
            log("rpc: ok_back%s", args)
            ss.rpc_reply(rpc_type, rpcid, True, native(args))
        def err_back(*args):
            log("rpc: err_back%s", args)
            ss.rpc_reply(rpc_type, rpcid, False, native(args))
        self.dbus_helper.call_function(bus_name, path, interface, function, args, ok_back, err_back)


    def _get_window_dict(self, wids):
        wd = {}
        for wid in wids:
            window = self._id_to_window.get(wid)
            if window:
                wd[wid] = window
        return wd

    def _process_suspend(self, proto, packet):
        log("suspend(%s)", packet[1:])
        ui = packet[1]
        wd = self._get_window_dict(packet[2])
        ss = self._server_sources.get(proto)
        if ss:
            ss.suspend(ui, wd)

    def _process_resume(self, proto, packet):
        log("resume(%s)", packet[1:])
        ui = packet[1]
        wd = self._get_window_dict(packet[2])
        ss = self._server_sources.get(proto)
        if ss:
            ss.resume(ui, wd)

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
        ss = self._server_sources.get(proto)
        self.set_clipboard_enabled_status(ss, clipboard_enabled)

    def set_clipboard_enabled_status(self, ss, clipboard_enabled):
        if not self._clipboard_helper:
            log.warn("client toggled clipboard-enabled but we do not support clipboard at all! ignoring it")
            return
        assert self._clipboard_client==ss, \
                "the request to change the clipboard enabled status does not come from the clipboard owner!"
        self._clipboard_client.clipboard_enabled = clipboard_enabled
        log("toggled clipboard to %s", clipboard_enabled)

    def _process_keyboard_sync_enabled_status(self, proto, packet):
        self.keyboard_sync = bool(packet[1])
        log("toggled keyboard-sync to %s", self.keyboard_sync)


    def _process_server_settings(self, proto, packet):
        #only used by x11 servers
        pass


    def _set_client_properties(self, proto, wid, window, new_client_properties):
        """
        Allows us to keep window properties for a client after disconnection.
        (we keep it in a map with the client's uuid as key)
        """
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_client_properties(wid, window, new_client_properties)
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
        cinfo = alnum(ss.hostname) or str(proto)
        log.info("received new keymap from client %s @ %s", ss.uuid, cinfo)
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

    def is_modifier(self, keyname, keycode):
        return keyname in DEFAULT_MODIFIER_MEANINGS.keys()

    def fake_key(self, keycode, press):
        pass

    def _handle_key(self, wid, pressed, name, keyval, keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log("handle_key(%s,%s,%s,%s,%s,%s) keyboard_sync=%s", wid, pressed, name, keyval, keycode, modifiers, self.keyboard_sync)
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
        is_mod = self.is_modifier(name, keycode)
        if not is_mod and self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
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


    def _move_pointer(self, wid, pos):
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


    def process_clipboard_packet(self, ss, packet):
        if not ss:
            #protocol has been dropped!
            return
        assert self._clipboard_client==ss, \
                "the clipboard packet '%s' does not come from the clipboard owner!" % packet[0]
        if not ss.clipboard_enabled:
            #this can happen when we disable clipboard in the middle of transfers
            #(especially when there is a clipboard loop)
            log.warn("received a clipboard packet from a source which does not have clipboard enabled!")
            return
        assert self._clipboard_helper, "received a clipboard packet but we do not support clipboard sharing"
        self.idle_add(self._clipboard_helper.process_clipboard_packet, packet)


    def process_packet(self, proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            if type(packet_type)==int:
                packet_type = self._aliases.get(packet_type)
            assert isinstance(packet_type, (str, unicode)), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
            if packet_type.startswith("clipboard-"):
                handler = self.process_clipboard_packet
                ss = self._server_sources.get(proto)
                self.process_clipboard_packet(ss, packet)
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
        except KeyboardInterrupt:
            raise
        except:
            log.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
