# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import time

from xpra.log import Logger
log = Logger("server")
keylog = Logger("keyboard")
focuslog = Logger("focus")
commandlog = Logger("command")

from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.server.server_core import ServerCore
from xpra.os_util import thread, get_hex_uuid
from xpra.util import typedict, updict, log_screen_sizes, SERVER_EXIT, SERVER_ERROR, SERVER_SHUTDOWN, CLIENT_REQUEST, DETACH_REQUEST, NEW_CLIENT, DONE
from xpra.scripts.config import python_platform, parse_bool_or_int
from xpra.scripts.main import sound_option
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS, codec_versions, has_codec, get_codec
from xpra.codecs.codec_constants import get_PIL_encodings
from xpra.codecs.video_helper import getVideoHelper, ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS
if sys.version > '3':
    unicode = str           #@ReservedAssignment


DETECT_LEAKS = os.environ.get("XPRA_DETECT_LEAKS", "0")=="1"
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
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias = {}
        #duplicated from Server Source...
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        self.supports_clipboard = False
        self.supports_dbus_proxy = False
        self.dbus_helper = None

        #encodings:
        self.allowed_encodings = None
        self.core_encodings = []
        self.encodings = []
        self.lossless_encodings = []
        self.lossless_mode_encodings = []
        self.default_encoding = None

        #control mode:
        self.control_commands = ["hello", "help",
                    "debug",
                    "encoding", "auto-refresh",
                    "quality", "min-quality", "speed", "min-speed",
                    "compression", "encoder", "refresh",
                    "sound-output",
                    "scaling", "scaling-control",
                    "suspend", "resume", "name", "ungrab",
                    "key", "focus",
                    "client"]

        self.init_encodings()
        self.init_packet_handlers()
        self.init_aliases()

        if DETECT_LEAKS:
            from xpra.util import detect_leaks
            detailed = []
            #example: warning, uses ugly direct import:
            #try:
            #    from xpra.x11.bindings.ximage import XShmImageWrapper       #@UnresolvedImport
            #    detailed.append(XShmImageWrapper)
            #except:
            #    pass
            print_leaks = detect_leaks(log, detailed)
            self.timeout_add(10*1000, print_leaks)

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
        self.allowed_encodings = opts.encodings
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
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias = {}
        self.supports_clipboard = opts.clipboard
        self.supports_dbus_proxy = opts.dbus_proxy
        self.send_pings = opts.pings
        self.scaling_control = parse_bool_or_int("scaling", opts.scaling)

        log("starting component init")
        self.init_clipboard(self.supports_clipboard, opts.clipboard_filter_file)
        self.init_keyboard()
        self.init_sound(opts.sound_source, opts.speaker, opts.speaker_codec, opts.microphone, opts.microphone_codec)
        self.init_notification_forwarder(opts.notifications)
        self.init_dbus_helper()

        #video init: default to ALL if not specified
        video_encoders = opts.video_encoders or ALL_VIDEO_ENCODER_OPTIONS
        csc_modules = opts.csc_modules or ALL_CSC_MODULE_OPTIONS
        getVideoHelper().set_modules(video_encoders=video_encoders, csc_modules=csc_modules)

        self.load_existing_windows(opts.system_tray)
        thread.start_new_thread(self.threaded_init, ())

    def threaded_init(self):
        log("threaded_init() start")
        #try to load video encoders in advance as this can take some time:
        getVideoHelper().init()
        #re-init list of encodings now that we have video initialized
        self.init_encodings()
        log("threaded_init() end")

    def init_encodings(self):
        encs, core_encs = [], []
        def add_encodings(encodings):
            for ce in encodings:
                e = {"rgb32" : "rgb", "rgb24" : "rgb"}.get(ce, ce)
                if self.allowed_encodings is not None and e not in self.allowed_encodings:
                    #not in whitelist (if it exists)
                    continue
                if e not in encs:
                    encs.append(e)
                if ce not in core_encs:
                    core_encs.append(ce)

        add_encodings(["rgb24", "rgb32"])

        #video encoders (empty when first called - see threaded_init)
        ve = getVideoHelper().get_encodings()
        log("init_encodings() adding video encodings: %s", ve)
        add_encodings(ve)  #ie: ["vp8", "h264"]
        #Pithon Imaging Libary:
        PIL = get_codec("PIL")
        if PIL:
            pil_encs = get_PIL_encodings(PIL)
            add_encodings(pil_encs)
            #Note: webp will only be enabled if we have a Python-PIL fallback
            #(either "webp" or "png")
            if has_codec("enc_webp") and ("webp" in pil_encs or "png" in pil_encs):
                add_encodings(["webp"])
                self.lossless_mode_encodings.append("webp")
        #now update the variables:
        self.encodings = encs
        self.core_encodings = core_encs
        self.lossless_encodings = [x for x in self.core_encodings if (x.startswith("png") or x.startswith("rgb") or x=="webp")]
        self.lossless_mode_encodings = []
        pref = [x for x in PREFERED_ENCODING_ORDER if x in self.encodings]
        if pref:
            self.default_encoding = pref[0]
        else:
            self.default_encoding = None


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
            except Exception as e:
                log.error("error loading or registering our dbus notifications forwarder:")
                log.error("  %s", e)
                log.info("  if you do not have a dedicated dbus session for this xpra instance,")
                log.info("  you should use the '--no-notifications' flag")
                log.info("")

    def init_sound(self, sound_source_plugin, speaker, speaker_codec, microphone, microphone_codec):
        try:
            from xpra.sound.gstreamer_util import has_gst, get_sound_codecs
        except Exception as e:
            log("cannot load gstreamer: %s", e)
            has_gst = False
        log("init_sound%s has_gst=%s", (sound_source_plugin, speaker, speaker_codec, microphone, microphone_codec), has_gst)
        self.sound_source_plugin = sound_source_plugin
        self.supports_speaker = sound_option(speaker) in ("on", "off") and has_gst
        self.supports_microphone = sound_option(microphone) in ("on", "off") and has_gst
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
        except Exception as e:
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
                with open(clipboard_filter_file, "r" ) as f:
                    for line in f:
                        clipboard_filter_res.append(line.strip())
                    log("loaded %s regular expressions from clipboard filter file %s", len(clipboard_filter_res), clipboard_filter_file)
            except:
                log.error("error reading clipboard filter file %s - clipboard disabled!", clipboard_filter_file, exc_info=True)
                return
        try:
            from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
            self._clipboard_helper = GDKClipboardProtocolHelper(self.send_clipboard_packet, self.clipboard_progress, CLIPBOARDS, clipboard_filter_res)
            self._clipboards = CLIPBOARDS
        except Exception as e:
            log.error("failed to setup clipboard helper: %s" % e)

    def init_keyboard(self):
        keylog("init_keyboard()")
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
        self.key_repeat_timer = None
        self.watch_keymap_changes()

    def watch_keymap_changes(self):
        pass

    def init_dbus_helper(self):
        if not self.supports_dbus_proxy:
            return
        try:
            from xpra.x11.dbus_helper import DBusHelper
            self.dbus_helper = DBusHelper()
        except Exception as e:
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
            "command_request":                      self._process_command_request,
                                          }
        self._authenticated_ui_packet_handlers = self._default_packet_handlers.copy()
        self._authenticated_ui_packet_handlers.update({
            #windows:
            "map-window":                           self._process_map_window,
            "unmap-window":                         self._process_unmap_window,
            "configure-window":                     self._process_configure_window,
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
            "info-request":                         self._process_info_request,
            # Note: "clipboard-*" packets are handled via a special case..
            })

    def init_aliases(self):
        packet_types = list(self._default_packet_handlers.keys())
        packet_types += list(self._authenticated_packet_handlers.keys())
        packet_types += list(self._authenticated_ui_packet_handlers.keys())
        self.do_init_aliases(packet_types)


    def run(self):
        if self.send_pings:
            self.timeout_add(1000, self.send_ping)
        else:
            self.timeout_add(10*1000, self.send_ping)
        return ServerCore.run(self)


    def cleanup(self, *args):
        if self.notifications_forwarder:
            thread.start_new_thread(self.notifications_forwarder.release, ())
            self.notifications_forwarder = None
        ServerCore.cleanup(self)
        getVideoHelper().cleanup()

    def add_listen_socket(self, socktype, socket):
        raise NotImplementedError()

    def _disconnect_all(self, message, *extra):
        for p in self._potential_protocols:
            try:
                self.send_disconnect(p, message, *extra)
            except:
                pass

    def _process_exit_server(self, proto, packet):
        log.info("Exiting response to request")
        self._disconnect_all(SERVER_EXIT)
        self.timeout_add(1000, self.clean_quit, False, ServerCore.EXITING_CODE)

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        self._disconnect_all(SERVER_SHUTDOWN)
        self.timeout_add(1000, self.clean_quit)

    def force_disconnect(self, proto):
        self.cleanup_source(proto)
        ServerCore.force_disconnect(self, proto)

    def disconnect_protocol(self, protocol, reason, *extra):
        ServerCore.disconnect_protocol(self, protocol, reason, *extra)
        self.cleanup_source(protocol)

    def cleanup_source(self, protocol):
        #this ensures that from now on we ignore any incoming packets coming
        #from this connection as these could potentially set some keys pressed, etc
        if protocol in self._potential_protocols:
            self._potential_protocols.remove(protocol)
        source = self._server_sources.get(protocol)
        if source:
            self.server_event("connection-lost", source.uuid)
            source.close()
            del self._server_sources[protocol]
            if self.exit_with_client:
                log.info("Last client has disconnected, terminating")
                self.quit(0)
            else:
                log.info("xpra client disconnected.")
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
        info = packet[1]
        if len(packet)>2:
            info += " (%s)" % (", ".join(packet[2:]))
        log.info("client %s has requested disconnection: %s", proto, info)
        self.disconnect_protocol(proto, CLIENT_REQUEST)

    def _process_connection_lost(self, proto, packet):
        ServerCore._process_connection_lost(self, proto, packet)
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

        detach_request  = c.boolget("detach_request", False)
        stop_request    = c.boolget("stop_request", False)
        exit_request    = c.boolget("exit_request", False)
        event_request   = c.boolget("event_request", False)
        is_request = detach_request or stop_request or exit_request or event_request
        if not is_request:
            #"normal" connection, so log welcome message:
            log.info("Handshake complete; enabling connection")
        self.server_event("handshake-complete")

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        # (but only if this is going to be a UI session - control sessions can co-exist)
        ui_client = c.boolget("ui_client", True)
        share_count = 0
        disconnected = 0
        for p,ss in self._server_sources.items():
            if detach_request and p!=proto:
                self.disconnect_client(p, DETACH_REQUEST)
                disconnected += 1
            elif ui_client and ss.ui_client:
                #check if existing sessions are willing to share:
                if not self.sharing:
                    self.disconnect_client(p, NEW_CLIENT, "this session does not allow sharing")
                    disconnected += 1
                elif not c.boolget("share"):
                    self.disconnect_client(p, NEW_CLIENT, "the new client does not wish to share")
                    disconnected += 1
                elif not ss.share:
                    self.disconnect_client(p, NEW_CLIENT, "this client had not enabled sharing")
                    disconnected += 1
                else:
                    share_count += 1

        if detach_request:
            self.disconnect_client(proto, DONE, "%i other clients have been disconnected" % disconnected)
            return

        if not is_request and ui_client:
            #a bit of explanation:
            #normally these things are synchronized using xsettings, which we handle already
            #but non-posix clients have no such thing and we don't won't to expose that as an interface (it's not very nice and very X11 specific)
            #also, clients may want to override what is in their xsettings..
            #so if the client specifies what it wants to use, we patch the xsettings with it
            if share_count>0:
                log.info("sharing with %s other client(s)", share_count)
                self.dpi = 0
                self.xdpi = 0
                self.ydpi = 0
                self.double_click_time = -1
                self.double_click_distance = -1, -1
            else:
                self.dpi = c.intget("dpi", 0)
                self.xdpi = c.intget("dpi.x", 0)
                self.ydpi = c.intget("dpi.y", 0)
                self.double_click_time = c.intget("double_click.time", -1)
                self.double_click_distance = c.intpair("double_click.distance", (-1, -1))
            self.antialias = c.dictget("antialias")
            log("dpi=%s, dpi.x=%s, dpi.y=%s, double_click_time=%s, double_click_distance=%s, antialias=%s", self.dpi, self.xdpi, self.ydpi, self.double_click_time, self.double_click_distance, self.antialias)
            #if we're not sharing, reset all the settings:
            reset = share_count==0
            #some non-posix clients never send us 'resource-manager' settings
            #so just use a fake one to ensure the overrides get applied:
            self.update_server_settings({'resource-manager' : ""}, reset=reset)
            #same for xsettings and double click settings:
            #fake an empty xsettings update:
            self.update_server_settings({"xsettings-blob" : (0, [])}, reset=reset)
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.send_aliases = c.dictget("aliases")
        #use blocking sockets from now on:
        self.set_socket_timeout(proto._conn, None)

        def drop_client(reason="unknown", *args):
            self.disconnect_client(proto, reason, *args)
        def get_window_id(wid):
            return self._window_to_id.get(wid)
        from xpra.server.source import ServerSource
        ss = ServerSource(proto, drop_client,
                          self.idle_add, self.timeout_add, self.source_remove,
                          self.get_transient_for, self.get_focus, self.get_cursor_data,
                          get_window_id,
                          self.supports_mmap,
                          self.core_encodings, self.encodings, self.default_encoding, self.scaling_control,
                          self.sound_source_plugin,
                          self.supports_speaker, self.supports_microphone,
                          self.speaker_codecs, self.microphone_codecs,
                          self.default_quality, self.default_min_quality,
                          self.default_speed, self.default_min_speed)
        log("process_hello serversource=%s", ss)
        try:
            ss.parse_hello(c)
        except:
            #close it already
            ss.close()
            raise
        self._server_sources[proto] = ss
        #process ui half in ui thread:
        send_ui = ui_client and not is_request
        self.idle_add(self.parse_hello_ui, ss, c, auth_caps, send_ui, share_count)

    def parse_hello_ui(self, ss, c, auth_caps, send_ui, share_count):
        #adds try:except around parse hello ui code:
        try:
            self.do_parse_hello_ui(ss, c, auth_caps, send_ui, share_count)
        except Exception as e:
            #log exception but don't disclose internal details to the client
            p = ss.protocol
            log.error("server error processing new connection from %s: %s", p or ss, e, exc_info=True)
            if p:
                self.disconnect_client(p, SERVER_ERROR, "error accepting new connection")

    def do_parse_screen_info(self, ss):
        dw, dh = None, None
        if ss.desktop_size:
            try:
                dw, dh = ss.desktop_size
                if not ss.screen_sizes:
                    log.info("client root window size is %sx%s", dw, dh)
                else:
                    log.info("client root window size is %sx%s with %s displays:", dw, dh, len(ss.screen_sizes))
                    log_screen_sizes(dw, dh, ss.screen_sizes)
            except:
                dw, dh = None, None
        root_w, root_h = self.set_best_screen_size()
        self.calculate_workarea()
        self.set_desktop_geometry(dw or root_w, dh or root_h)
        return root_w, root_h

    def do_parse_hello_ui(self, ss, c, auth_caps, send_ui, share_count):
        #process screen size (if needed)
        if send_ui:
            root_w, root_h = self.do_parse_screen_info(ss)
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

            #keyboard:
            ss.keyboard_config = self.get_keyboard_config(c)

            #so only activate this feature afterwards:
            self.keyboard_sync = c.boolget("keyboard_sync", True)
            key_repeat = c.intpair("key_repeat")
            self.set_keyboard_repeat(key_repeat)

            #always clear modifiers before setting a new keymap
            ss.make_keymask_match(c.strlistget("modifiers", []))
            self.set_keymap(ss)
        else:
            root_w, root_h = self.get_root_window_size()
            key_repeat = (0, 0)

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, auth_caps)

        if send_ui:
            # now we can set the modifiers to match the client
            self.send_windows_and_cursors(ss, share_count>0)

        ss.startup_complete()
        self.server_event("startup-complete", ss.uuid)


    def server_event(self, *args):
        for s in self._server_sources.values():
            s.send_server_event(*args)


    def update_server_settings(self, settings, reset=False):
        log("server settings ignored: ", settings)


    def get_keyboard_config(self, props):
        return None

    def set_keyboard_repeat(self, key_repeat):
        pass

    def set_keymap(self, ss):
        pass

    def get_transient_for(self, window):
        return  None

    def send_windows_and_cursors(self, ss, sharing=False):
        pass

    def sanity_checks(self, proto, c):
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display that the server it connects to is managing - this would create a loop!")
                return  False
            log.warn("This client is running within the Xpra server %s", server_uuid)
        return True

    def get_server_features(self):
        #these are flags that have been added over time with new versions
        #to expose new server features:
        return ("toggle_cursors_bell_notify", "toggle_keyboard_sync",
                "window_configure", "window_unmap", "window_refresh_config",
                "xsettings-tuple",
                "change-quality", "change-min-quality", "change-speed", "change-min-speed",
                "client_window_properties",
                "sound_sequence", "notify-startup-complete", "suspend-resume",
                "encoding.generic", "encoding.strict_control",
                "sound.server_driven",
                "command_request",
                "event_request", "server-events")

    def make_hello(self, source):
        capabilities = ServerCore.make_hello(self, source)
        capabilities["server_type"] = "base"
        if source.wants_display:
            capabilities.update({
                 "max_desktop_size"             : self.get_max_screen_size(),
                 })
        if source.wants_features:
            capabilities.update({
                 "clipboards"                   : self._clipboards,
                 "notifications"                : self.notifications_forwarder is not None,
                 "bell"                         : self.bell,
                 "cursors"                      : self.cursors,
                 "dbus_proxy"                   : self.supports_dbus_proxy,
                 })
            for x in self.get_server_features():
                capabilities[x] = True
        #this is a feature, but we would need the hello request
        #to know if it is really needed.. so always include it:
        capabilities["exit_server"] = True

        if source.wants_encodings:
            updict(capabilities, "encoding", codec_versions, "version")
        return capabilities

    def send_hello(self, server_source, root_w, root_h, key_repeat, server_cipher):
        capabilities = self.make_hello(server_source)
        if server_source.wants_encodings:
            for k,v in self.get_encoding_info().items():
                if k=="":
                    k = "encodings"
                else:
                    k = "encodings.%s" % k
                capabilities[k] = v
        if server_source.wants_display:
            capabilities.update({
                         "actual_desktop_size"  : (root_w, root_h),
                         "root_window_size"     : (root_w, root_h),
                         "desktop_size"         : self._get_desktop_size_capability(server_source, root_w, root_h),
                         })
        if key_repeat:
            capabilities.update({
                     "key_repeat"           : key_repeat,
                     "key_repeat_modifiers" : True})
        if server_source.wants_features:
            capabilities["clipboard"] = self._clipboard_helper is not None and self._clipboard_client == server_source
        if self._reverse_aliases and server_source.wants_aliases:
            capabilities["aliases"] = self._reverse_aliases
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.hello(capabilities)


    def _process_command_request(self, proto, packet):
        """ client sent a command request through its normal channel """
        assert len(packet)>=2, "invalid command request packet (too small!)"
        command = packet[1]
        args = packet[2:]
        try:
            code, msg = self.do_handle_command_request(command, args)
            commandlog("command request %s returned: %s (%s)", command, code, msg)
        except:
            commandlog.error("error processing command %s", command, exc_info=True)

    def do_handle_command_request(self, command, args):
        #note: this may get called from handle_command_request or from _process_command_request
        commandlog("handle_command_request(%s, %s)", command, args)
        def argn_err(argn):
            return 4, "invalid number of arguments, '%s' expects: %s" % (command, argn)
        def arg_err(msg):
            return 5, "invalid argument for '%s': %s" % (command, msg)
        def success():
            return 0, "%s success" % command

        sources = list(self._server_sources.values())
        protos = list(self._server_sources.keys())
        def forward_all_clients(client_command):
            """ forwards the command to all clients """
            for source in sources:
                """ forwards to *the* client, if there is *one* """
                if client_command[0] not in source.control_commands:
                    commandlog.info("client command '%s' not forwarded to client %s (not supported)", client_command, source)
                    return  False
                source.send_client_command(*client_command)

        def for_all_window_sources(wids, callback):
            for csource in sources:
                for wid in wids:
                    window = self._id_to_window.get(wid)
                    ws = csource.window_sources.get(wid)
                    if window and ws:
                        callback(ws, wid, window)

        def get_wids_from_args(args):
            #converts all the remaining args to window ids
            if len(args)==0 or len(args)==1 and args[0]=="*":
                #default to all if unspecified:
                return self._id_to_window.keys()
            wids = []
            for x in args:
                try:
                    wid = int(x)
                    if wid in self._id_to_window:
                        wids.append(wid)
                    else:
                        commandlog("window id %s does not exist", wid)
                except:
                    raise Exception("invalid window id: %s" % x)
            return wids

        #handle commands that either don't require a client,
        #or can work on more than one connected client:
        if command in ("help", "hello"):
            #generic case:
            return ServerCore.do_handle_command_request(self, command, args)
        elif command=="debug":
            def debug_usage():
                return arg_err("usage: 'debug enable|disable category' or 'debug status'")
            if len(args)==1 and args[0]=="status":
                from xpra.log import get_all_loggers
                return 0, "logging is enabled for: %s" % str(list([str(x) for x in get_all_loggers() if x.is_debug_enabled()]))
            if len(args)<2:
                return debug_usage()
            log_cmd = args[0]
            if log_cmd not in ("enable", "disable"):
                return debug_usage()
            category = args[1]
            from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
            if log_cmd=="enable":
                add_debug_category(category)
                enable_debug_for(category)
            else:
                assert log_cmd=="disable"
                add_disabled_category(category)
                disable_debug_for(category)
            return 0, "logging %sd for %s" % (log_cmd, category)
        elif command=="name":
            if len(args)!=1:
                return argn_err(1)
            self.session_name = args[0]
            commandlog.info("changed session name: %s", self.session_name)
            forward_all_clients(["name"])
            return 0, "session name set"
        elif command=="compression":
            if len(args)!=1:
                return argn_err(1)
            c = args[0].lower()
            from xpra.net import compression
            opts = compression.get_enabled_compressors()    #ie: [lz4, lzo, zlib]
            if c in opts:
                for cproto in protos:
                    cproto.enable_compressor(c)
                forward_all_clients(["enable_%s" % c])
                return success()
            return arg_err("must be one of: %s" % (", ".join(opts)))
        elif command=="encoder":
            if len(args)!=1:
                return argn_err(1)
            e = args[0].lower()
            from xpra.net import packet_encoding
            opts = packet_encoding.get_enabled_encoders()   #ie: [rencode, bencode, yaml]
            if e in opts:
                for cproto in protos:
                    cproto.enable_encoder(e)
                forward_all_clients(["enable_%s" % e])
                return success()
            return arg_err("must be one of: %s" % (", ".join(opts)))
        elif command=="sound-output":
            if len(args)<1:
                return arg_err("more than 1")
            msg = []
            for csource in sources:
                msg.append("%s : %s" % (csource, csource.sound_control(*args[1:])))
            return 0, ", ".join(msg)
        elif command=="suspend":
            for csource in sources:
                csource.suspend(True, self._id_to_window)
            return 0, "suspended %s clients" % len(sources)
        elif command=="resume":
            for csource in sources:
                csource.resume(True, self._id_to_window)
            return 0, "resumed %s clients" % len(sources)
        elif command=="ungrab":
            for csource in sources:
                csource.pointer_ungrab(-1)
            return 0, "ungrabbed %s clients" % len(sources)
        elif command=="encoding":
            if len(args)<1:
                return argn_err(1)
            encoding = args[0]
            strict = None       #means no change
            args = args[1:]
            if len(args)>0 and args[0] in ("strict", "nostrict"):
                #remove "strict" marker
                strict = args[0]=="strict"
                args = args[1:]
            wids = get_wids_from_args(args)
            def set_new_encoding(ws, wid, window):
                ws.set_new_encoding(encoding, strict)
            for_all_window_sources(wids, set_new_encoding)
            #now also do a refresh:
            def refresh(ws, wid, window):
                ws.refresh(window, {})
            for_all_window_sources(wids, refresh)
            return 0, "set encoding to %s%s for %s windows" % (encoding, ["", " (strict)"][int(strict or 0)], len(wids))
        elif command=="auto-refresh":
            if len(args)<1:
                return argn_err(1)
            try:
                delay = int(float(args[0])*1000.0)      # ie: 0.5 -> 500 (milliseconds)
            except:
                raise Exception("failed to parse delay string '%s' as a number" % args[0])
            wids = get_wids_from_args(args[1:])
            def set_auto_refresh_delay(ws, wid, window):
                ws.set_auto_refresh_delay(delay)
            for_all_window_sources(wids, set_auto_refresh_delay)
            return 0, "set auto-refresh delay to %sms for %s windows" % (delay, len(wids))
        elif command=="refresh":
            wids = get_wids_from_args(args)
            def full_quality_refresh(ws, wid, window):
                ws.full_quality_refresh(window, {})
            for_all_window_sources(wids, full_quality_refresh)
            return 0, "refreshed %s window for %s clients" % (len(wids), len(sources))
        elif command=="scaling-control":
            if len(args)==0:
                return argn_err("2: scaling-control value and window ids (or '*')")
            try:
                scaling_control = int(args[0])
                assert 0<=scaling_control<=100, "value must be between 0 and 100"
            except Exception as e:
                return 11, "invalid scaling value %s: %s" % (args[1], e)
            wids = get_wids_from_args(args[1:])
            def set_scaling_control(ws, wid, window):
                ws.set_scaling_control(scaling_control)
                ws.refresh(window)
            for_all_window_sources(wids, set_scaling)
            return 0, "scaling-control set to %s on window %s for %s clients" % (scaling_control, wids, len(sources))
        elif command=="scaling":
            if len(args)==0:
                return argn_err("2: scaling value and window ids (or '*')")
            from xpra.server.window_video_source import parse_scaling_value
            try:
                scaling = parse_scaling_value(args[0])
            except:
                return 11, "invalid scaling value %s" % args[1]
            wids = get_wids_from_args(args[1:])
            def set_scaling(ws, wid, window):
                ws.set_scaling(scaling)
                ws.refresh(window)
            for_all_window_sources(wids, set_scaling)
            return 0, "scaling set to %s on window %s for %s clients" % (str(scaling), wids, len(sources))
        elif command in ("quality", "min-quality", "speed", "min-speed"):
            if len(args)==0:
                return argn_err(1)
            try:
                v = int(args[0])
            except:
                v = -9999999
            if v<0 or v>100:
                return 11, "invalid quality or speed value (must be a number between 0 and 100): %s" % args[0]
            def set_value(ws, wid, window):
                if command=="quality":
                    ws.set_quality(v)
                elif command=="min-quality":
                    ws.set_min_quality(v)
                elif command=="speed":
                    ws.set_speed(v)
                elif command=="min-speed":
                    ws.set_min_speed(v)
                else:
                    assert False, "invalid command: %s" % command
            wids = get_wids_from_args(args[1:])
            for_all_window_sources(wids, set_value)
            #update the default encoding options
            #so new windows will also inherit those settings:
            for csource in sources:
                csource.default_encoding_options[command] = v
            return 0, "%s set to %s on windows %s for %s clients" % (command, v, wids, len(sources))
        elif command=="key":
            if len(args) not in (1, 2):
                return argn_err("1 or 2")
            key = args[0]
            try:
                if key.startswith("0x"):
                    keycode = int(key, 16)
                else:
                    keycode = int(key)
                assert keycode>0 and keycode<=255
            except:
                raise Exception("invalid keycode specified: '%s' (must be a number between 1 and 255)" % key)
            press = True
            if len(args)==2:
                if args[1] in ("1", "press"):
                    press = True
                elif args[1] in ("0", "unpress"):
                    press = False
                else:
                    return arg_err("if present, the second argument must be one of: %s", ("1", "press", "0", "unpress"))
            self.fake_key(keycode, press)
            return 0, "%spressed key %s" % (["un", ""][int(press)], keycode)
        elif command=="focus":
            if len(args)!=1:
                return argn_err(1)
            wid = int(args[0])
            self._focus(None, wid, None)
            return 0, "gave focus to window %s" % wid
        elif command=="client":
            if len(args)==0:
                return argn_err("at least 1")
            client_command = args
            count = 0
            for source in sources:
                if client_command[0] in source.control_commands:
                    count += 1
                    source.send_client_command(*client_command)
                else:
                    commandlog.warn("client %s does not support client command %s", source, client_command[0])
            return 0, "client control command '%s' forwarded to %s clients" % (client_command[0], count)
        else:
            return ServerCore.do_handle_command_request(self, command, args)


    def send_screenshot(self, proto):
        #this is a screenshot request, handle it and disconnect
        try:
            packet = self.make_screenshot_packet()
            if not packet:
                self.send_disconnect(proto, "screenshot failed")
                return
            proto.send_now(packet)
            self.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
        except Exception as e:
            log.error("failed to capture screenshot", exc_info=True)
            self.send_disconnect(proto, "screenshot failed: %s" % e)


    def _process_info_request(self, proto, packet):
        ss = self._server_sources.get(proto)
        assert ss, "cannot find server source for %s" % proto
        def info_callback(_proto, info):
            assert proto==_proto
            ss.send_info_response(info)
        self.get_all_info(info_callback, proto, *packet[1:])

    def send_hello_info(self, proto):
        log.info("processing info request from %s", proto._conn)
        self.get_all_info(self.do_send_info, proto, self._id_to_window.keys())

    def get_ui_info(self, proto, wids, *args):
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        info = {"server.max_desktop_size" : self.get_max_screen_size()}
        if self.keyboard_config:
            info["state.modifiers"] = self.keyboard_config.get_current_mask()
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
        updict(info, "dpi", {
                             "default"      : self.default_dpi,
                             "value"        : self.dpi,
                             "x"            : self.xdpi,
                             "y"            : self.ydpi
                             })
        updict(info, "antialias", self.antialias)
        log("get_info took %.1fms", 1000.0*(time.time()-start))
        return info


    def get_features_info(self):
        i = {
             "randr"            : self.randr,
             "cursors"          : self.cursors,
             "bell"             : self.bell,
             "notifications"    : self.notifications_forwarder is not None,
             "pulseaudio"       : self.pulseaudio,
             "dbus_proxy"       : self.supports_dbus_proxy,
             "clipboard"        : self.supports_clipboard}
        for x in self.get_server_features():
            i[x] = True
        return i

    def get_encoding_info(self):
        """
            Warning: the encodings values may get
            re-written on the way out.
            (see ServerSource.rewrite_encoding_values)
        """
        return  {
             ""                     : self.encodings,
             "core"                 : self.core_encodings,
             "allowed"              : self.allowed_encodings,
             "lossless"             : self.lossless_encodings,
             "problematic"          : [x for x in self.core_encodings if x in PROBLEMATIC_ENCODINGS],
             "with_speed"           : [x for x in self.core_encodings if x in ("h264", "vp8", "vp9", "rgb", "png", "png/P", "png/L")],
             "with_quality"         : [x for x in self.core_encodings if x in ("jpeg", "webp", "h264", "vp8", "vp9")],
             "with_lossless_mode"   : self.lossless_mode_encodings}

    def get_keyboard_info(self):
        info = {
             "sync"             : self.keyboard_sync,
             "repeat.delay"     : self.key_repeat_delay,
             "repeat.interval"  : self.key_repeat_interval,
             "keys_pressed"     : self.keys_pressed.values(),
             "modifiers"        : self.xkbmap_mod_meanings}
        if self.keyboard_config:
            for k,v in self.keyboard_config.get_info().items():
                if v is not None:
                    info[k] = v
        return info

    def get_clipboard_info(self):
        if self._clipboard_helper is None:
            return {}
        return self._clipboard_helper.get_info()

    def do_get_info(self, proto, server_sources=None, window_ids=None):
        info = {"server.python.version" : python_platform.python_version()}

        def up(prefix, d, suffix=""):
            updict(info, prefix, d, suffix)

        up("features",  self.get_features_info())
        up("clipboard", self.get_clipboard_info())
        up("keyboard",  self.get_keyboard_info())
        up("encodings", self.get_encoding_info())
        up("encoding",  codec_versions, "version")
        # csc and video encoders:
        info.update(getVideoHelper().get_info())

        info["windows"] = len([window for window in list(self._id_to_window.values()) if window.is_managed()])
        # other clients:
        info["clients"] = len([p for p in self._server_sources.keys() if p!=proto])
        info["clients.unauthenticated"] = len([p for p in self._potential_protocols if ((p is not proto) and (p not in self._server_sources.keys()))])
        #find the server source to report on:
        n = len(server_sources or [])
        if n==1:
            ss = server_sources[0]
            up("client", ss.get_info())
            info.update(ss.get_window_info(window_ids))
        elif n>1:
            for i, ss in enumerate(server_sources):
                up("client[%i]" % i, ss.get_info())
                wi = ss.get_window_info(window_ids)
                up("client[%i]" % i, wi)
                #this means that the last source overrides previous ones
                #(bad decision was made on the namespace for this..)
                info.update(wi)
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
            self._clipboard_client.send_clipboard(parts)

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
        focuslog("_focus(%s,%s)", wid, modifiers)

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
        count = 0
        for ss in self._server_sources.values():
            if ss.updated_desktop_size(root_w, root_h, max_w, max_h):
                count +=1
        if count>0:
            log.info("sent updated screen size to %s clients: %sx%s (max %sx%s)", count, root_w, root_h, max_w, max_h)

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
        if len(packet)>=4:
            ss.set_screen_sizes(packet[3])
        log("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        if len(packet)>=4:
            log.info("received updated display dimensions")
            log.info("client root window size is %sx%s with %s displays:", width, height, len(ss.screen_sizes))
            log_screen_sizes(width, height, ss.screen_sizes)
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
        keylog("toggled keyboard-sync to %s", self.keyboard_sync)


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
            ss.set_client_properties(wid, window, typedict(new_client_properties))
            client_properties = self.client_properties.setdefault("%s|%s" % (wid, ss.uuid), {})
            #filter out encoding properties, which are expected to be set everytime:
            ncp = {}
            for k,v in new_client_properties.items():
                if not k.startswith("encoding"):
                    ncp[k] = v
            log("set_client_properties updating window %s with %s", wid, ncp)
            client_properties.update(ncp)


    def _process_focus(self, proto, packet):
        wid = packet[1]
        focuslog("process_focus: wid=%s", wid)
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
        props = typedict(packet[1])
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        log("received new keymap from client")
        kc = ss.keyboard_config
        if kc and kc.enabled:
            kc.parse_options(props)
            self.set_keymap(ss, True)
        modifiers = props.get("modifiers", [])
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
        if keyname in DEFAULT_MODIFIER_MEANINGS.keys():
            return True
        #keyboard config should always exist if we are here?
        if self.keyboard_config:
            return self.keyboard_config.is_modifier(keycode)
        return False

    def fake_key(self, keycode, press):
        pass

    def _handle_key(self, wid, pressed, name, keyval, keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        keylog("handle_key(%s,%s,%s,%s,%s,%s) keyboard_sync=%s", wid, pressed, name, keyval, keycode, modifiers, self.keyboard_sync)
        if pressed and (wid is not None) and (wid not in self._id_to_window):
            keylog("window %s is gone, ignoring key press", wid)
            return
        if keycode<0:
            keylog.warn("ignoring invalid keycode=%s", keycode)
            return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]
        def press():
            keylog("handle keycode pressing %s: key %s", keycode, name)
            self.keys_pressed[keycode] = name
            self.fake_key(keycode, True)
        def unpress():
            keylog("handle keycode unpressing %s: key %s", keycode, name)
            if keycode in self.keys_pressed:
                del self.keys_pressed[keycode]
            self.fake_key(keycode, False)
        is_mod = self.is_modifier(name, keycode)
        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not self.keyboard_sync and not is_mod:
                    #keyboard is not synced: client manages repeat so unpress
                    #it immediately unless this is a modifier key
                    #(as modifiers are synced via many packets: key, focus and mouse events)
                    unpress()
            else:
                keylog("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                keylog("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if not is_mod and self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, pressed, name, keyval, keycode, modifiers, self.key_repeat_delay)

    def cancel_key_repeat_timer(self):
        if self.key_repeat_timer:
            self.source_remove(self.key_repeat_timer)
            self.key_repeat_timer = None

    def _key_repeat(self, wid, pressed, keyname, keyval, keycode, modifiers, delay_ms=0):
        """ Schedules/cancels the key repeat timeouts """
        self.cancel_key_repeat_timer()
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            keylog("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                self.key_repeat_timer = None
                now = time.time()
                keylog("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.key_repeat_timer = self.timeout_add(delay_ms, _key_repeat_timeout, now)

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
                keylog("key %s/%s, had timed out, re-pressing it", keycode, keyname)
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
        """ can be used for requesting a refresh, or tuning batch config, or both """
        wid, _, qual = packet[1:4]
        if len(packet)>=6:
            options = typedict(packet[4])
            client_properties = packet[5]
        else:
            options = typedict({})
            client_properties = {}
        if wid==-1:
            wid_windows = self._id_to_window
        elif wid in self._id_to_window:
            wid_windows = {wid : self._id_to_window.get(wid)}
        else:
            log.warn("invalid window specified for refresh: %s", wid)
            return
        log("process_buffer_refresh for windows: %s options=%s, client_properties=%s", wid_windows, options, client_properties)
        batch_props = options.dictget("batch", {})
        if batch_props or client_properties:
            #change batch config and/or client properties
            self.update_batch_config(proto, wid_windows, typedict(batch_props), client_properties)
        #default to True for backwards compatibility:
        if options.get("refresh-now", True):
            refresh_opts = {"quality"           : qual,
                            "override_options"  : True}
            self.refresh_windows(proto, wid_windows, refresh_opts)

    def update_batch_config(self, proto, wid_windows, batch_props, client_properties):
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            self._set_client_properties(proto, wid, window, client_properties)
            ss.update_batch(wid, window, batch_props)

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
