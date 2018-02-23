# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from time import sleep

from xpra.log import Logger
log = Logger("server")
keylog = Logger("keyboard")
mouselog = Logger("mouse")
focuslog = Logger("focus")
execlog = Logger("exec")
clientlog = Logger("client")
screenlog = Logger("screen")
filelog = Logger("file")
netlog = Logger("network")
metalog = Logger("metadata")
geomlog = Logger("geometry")
windowlog = Logger("window")
clipboardlog = Logger("clipboard")
rpclog = Logger("rpc")
dbuslog = Logger("dbus")
notifylog = Logger("notify")
httplog = Logger("http")
bandwidthlog = Logger("bandwidth")
timeoutlog = Logger("timeout")

from xpra.platform.features import COMMAND_SIGNALS
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS
from xpra.server.server_core import ServerCore, get_thread_info
from xpra.server.mixins.server_base_controlcommands import ServerBaseControlCommands
from xpra.server.mixins.notification_forwarder import NotificationForwarder
from xpra.server.mixins.webcam_server import WebcamServer
from xpra.server.mixins.clipboard_server import ClipboardServer
from xpra.server.mixins.audio_server import AudioServer
from xpra.server.mixins.fileprint_server import FilePrintServer
from xpra.simple_stats import std_unit
from xpra.child_reaper import getChildReaper
from xpra.os_util import thread, livefds, monotonic_time, bytestostr, OSX, WIN32, POSIX, PYTHON3
from xpra.util import typedict, flatten_dict, updict, envbool, envint, log_screen_sizes, engs, csv, iround, detect_leaks, \
    SERVER_EXIT, SERVER_ERROR, SERVER_SHUTDOWN, DETACH_REQUEST, NEW_CLIENT, DONE, IDLE_TIMEOUT, SESSION_BUSY
from xpra.net.bytestreams import set_socket_timeout
from xpra.platform.paths import get_icon_filename, get_icon_dir
from xpra.notifications.common import parse_image_path, XPRA_IDLE_NOTIFICATION_ID
from xpra.child_reaper import reaper_cleanup
from xpra.scripts.parsing import parse_env
from xpra.scripts.config import parse_bool_or_int, parse_bool, FALSE_OPTIONS
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS, load_codecs, codec_versions, get_codec, has_codec
from xpra.codecs.video_helper import getVideoHelper, ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS


PRIVATE_PULSEAUDIO = envbool("XPRA_PRIVATE_PULSEAUDIO", POSIX and not OSX)
DETECT_MEMLEAKS = envbool("XPRA_DETECT_MEMLEAKS", False)
DETECT_FDLEAKS = envbool("XPRA_DETECT_FDLEAKS", False)
MAX_CONCURRENT_CONNECTIONS = 20
SAVE_PRINT_JOBS = os.environ.get("XPRA_SAVE_PRINT_JOBS", None)
CLIENT_CAN_SHUTDOWN = envbool("XPRA_CLIENT_CAN_SHUTDOWN", True)
TERMINATE_DELAY = envint("XPRA_TERMINATE_DELAY", 1000)/1000.0
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert AUTO_BANDWIDTH_PCT>1 and AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT



class ServerBase(ServerCore, ServerBaseControlCommands, NotificationForwarder, WebcamServer, ClipboardServer, AudioServer, FilePrintServer):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See GTKServerBase/X11ServerBase and other platform specific subclasses.
    """

    def __init__(self):
        for c in ServerBase.__bases__:
            c.__init__(self)
        log("ServerBase.__init__()")
        self.init_uuid()

        self._authenticated_packet_handlers = {}
        self._authenticated_ui_packet_handlers = {}

        # This must happen early, before loading in windows at least:
        self._server_sources = {}

        #so clients can store persistent attributes on windows:
        self.client_properties = {}

        self.supports_mmap = False
        self.mmap_filename = None
        self.min_mmap_size = 64*1024*1024
        self.randr = False

        self._window_to_id = {}
        self._id_to_window = {}
        self.window_filters = []
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1
        self.ui_driver = None

        self.default_quality = -1
        self.default_min_quality = 0
        self.default_speed = -1
        self.default_min_speed = 0
        self.sharing = None
        self.lock = None
        self.bell = False
        self.cursors = False
        self.default_dpi = 96
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias = {}
        self.cursor_size = 0
        self.idle_timeout = 0
        #duplicated from Server Source...
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        self.supports_dbus_proxy = False
        self.dbus_helper = None
        #starting child commands:
        self.child_display = None
        self.start_commands = []
        self.start_child_commands = []
        self.start_after_connect = []
        self.start_child_after_connect = []
        self.start_on_connect = []
        self.start_child_on_connect = []
        self.exit_with_children = False
        self.start_after_connect_done = False
        self.start_new_commands = False
        self.remote_logging = False
        self.start_env = []
        self.exec_cwd = None
        self.exec_wrapper = None
        self.terminate_children = False
        self.children_started = []
        self.child_reaper = None
        self.pings = 0
        self.scaling_control = False
        self.rpc_handlers = {}
        self.input_devices = "auto"
        self.input_devices_format = None
        self.input_devices_data = None
        self.mem_bytes = 0
        self.client_shutdown = CLIENT_CAN_SHUTDOWN

        #encodings:
        self.allowed_encodings = None
        self.core_encodings = []
        self.encodings = []
        self.lossless_encodings = []
        self.lossless_mode_encodings = []
        self.default_encoding = None

        self.init_encodings()
        self.init_packet_handlers()
        self.init_aliases()

        if DETECT_MEMLEAKS:
            print_leaks = detect_leaks()
            if print_leaks:
                def leak_thread():
                    while True:
                        print_leaks()
                        sleep(10)
                from xpra.make_thread import start_thread
                start_thread(leak_thread, "leak thread", daemon=True)
        if DETECT_FDLEAKS:
            self.fds = livefds()
            self.timeout_add(10, self.print_fds)

    def print_fds(self):
        fds = livefds()
        newfds = fds-self.fds
        self.fds = fds
        log.info("print_fds() new fds=%s (total=%s)", newfds, len(fds))
        return True


    def idle_add(self, *args, **kwargs):
        raise NotImplementedError()

    def timeout_add(self, *args, **kwargs):
        raise NotImplementedError()

    def source_remove(self, timer):
        raise NotImplementedError()


    def server_event(self, *args):
        for s in self._server_sources.values():
            s.send_server_event(*args)
        if self.dbus_server:
            self.dbus_server.Event(str(args[0]), [str(x) for x in args[1:]])


    def init(self, opts):
        for c in ServerBase.__bases__:
            c.init(self, opts)
        log("ServerBase.init(%s)", opts)
        self.init_options(opts)

    def init_options(self, opts):
        #from now on, use the logger for parsing errors:
        from xpra.scripts import config
        config.warn = log.warn

        if opts.mmap and os.path.isabs(opts.mmap):
            self.supports_mmap = True
            self.mmap_filename = opts.mmap
        else:
            self.supports_mmap = bool(parse_bool("mmap", opts.mmap.lower()))
        self.allowed_encodings = opts.encodings
        self.init_encoding(opts.encoding)

        self.default_quality = opts.quality
        self.default_min_quality = opts.min_quality
        self.default_speed = opts.speed
        self.default_min_speed = opts.min_speed
        self.sharing = opts.sharing
        self.lock = opts.lock
        self.bell = opts.bell
        self.cursors = opts.cursors
        self.default_dpi = int(opts.dpi)
        self.idle_timeout = opts.idle_timeout
        self.supports_dbus_proxy = opts.dbus_proxy
        self.exit_with_children = opts.exit_with_children
        self.terminate_children = opts.terminate_children
        self.start_new_commands = opts.start_new_commands
        if opts.exec_wrapper:
            import shlex
            self.exec_wrapper = shlex.split(opts.exec_wrapper)
        self.child_reaper = getChildReaper()
        def set_reaper_callback():
            self.child_reaper.set_quit_callback(self.reaper_exit)
            self.child_reaper.check()
        self.idle_add(set_reaper_callback)
        self.remote_logging = not ((opts.remote_logging or "").lower() in FALSE_OPTIONS)
        self.start_env = parse_env(opts.start_env)
        self.pings = opts.pings
        self.av_sync = opts.av_sync
        self.scaling_control = parse_bool_or_int("video-scaling", opts.video_scaling)

        #video init: default to ALL if not specified
        video_encoders = opts.video_encoders or ALL_VIDEO_ENCODER_OPTIONS
        csc_modules = opts.csc_modules or ALL_CSC_MODULE_OPTIONS
        getVideoHelper().set_modules(video_encoders=video_encoders, csc_modules=csc_modules)

    def setup(self, opts):
        log("starting component init")
        for c in ServerBase.__bases__:
            c.setup(self, opts)
        self.init_keyboard()
        self.init_dbus_helper()

        if opts.system_tray:
            self.add_system_tray()
        self.load_existing_windows()
        thread.start_new_thread(self.threaded_init, ())

    def threaded_init(self):
        log("threaded_init() start")
        #try to load video encoders in advance as this can take some time:
        sleep(0.1)
        getVideoHelper().init()
        #re-init list of encodings now that we have video initialized
        self.init_encodings()
        self.init_memcheck()
        for c in ServerBase.__bases__:
            if c!=ServerCore:
                c.threaded_setup(self)
        log("threaded_init() end")


    def server_is_ready(self):
        ServerCore.server_is_ready(self)
        self.server_event("ready")


    def run(self):
        if self.pings>0:
            self.timeout_add(1000*self.pings, self.send_ping)
        return ServerCore.run(self)

    def do_cleanup(self):
        self.server_event("exit")
        if self.terminate_children and self._upgrading!=ServerCore.EXITING_CODE:
            self.terminate_children_processes()
        for c in ServerBase.__bases__:
            if c!=ServerCore:
                c.cleanup(self)
        getVideoHelper().cleanup()
        reaper_cleanup()


    def init_memcheck(self):
        #verify we have enough memory:
        if POSIX and self.mem_bytes==0:
            try:
                self.mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')  # e.g. 4015976448
                LOW_MEM_LIMIT = 512*1024*1024
                if self.mem_bytes<=LOW_MEM_LIMIT:
                    log.warn("Warning: only %iMB total system memory available", self.mem_bytes//(1024**2))
                    log.warn(" this may not be enough to run a server")
                else:
                    log.info("%.1fGB of system memory", self.mem_bytes/(1024.0**3))
            except:
                pass


    ######################################################################
    # keyboard:
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

    def parse_hello_ui_keyboard(self, ss, c):
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s!=ss and s.ui_client]
        #parse client config:
        ss.keyboard_config = self.get_keyboard_config(c)

        if not other_ui_clients:
            #so only activate this feature afterwards:
            self.keyboard_sync = c.boolget("keyboard_sync", True)
            key_repeat = c.intpair("key_repeat")
            self.set_keyboard_repeat(key_repeat)
            #always clear modifiers before setting a new keymap
            ss.make_keymask_match(c.strlistget("modifiers", []))
        else:
            self.set_keyboard_repeat(None)
            key_repeat = (0, 0)

        self.set_keymap(ss)
        return key_repeat

    def get_keyboard_info(self):
        start = monotonic_time()
        info = {
             "sync"             : self.keyboard_sync,
             "repeat"           : {
                                   "delay"      : self.key_repeat_delay,
                                   "interval"   : self.key_repeat_interval,
                                   },
             "keys_pressed"     : tuple(self.keys_pressed.values()),
             "modifiers"        : self.xkbmap_mod_meanings,
             }
        kc = self.keyboard_config
        if kc:
            info.update(kc.get_info())
        log("ServerBase.get_keyboard_info took %ims", (monotonic_time()-start)*1000)
        return info

    def _process_layout(self, proto, packet):
        if self.readonly:
            return
        layout, variant = packet[1:3]
        if len(packet)>=4:
            options = packet[3]
        else:
            options = ""
        ss = self._server_sources.get(proto)
        if ss and ss.set_layout(layout, variant, options):
            self.set_keymap(ss, force=True)

    def _process_keymap(self, proto, packet):
        if self.readonly:
            return
        props = typedict(packet[1])
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        log("received new keymap from client")
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s!=ss and s.ui_client]
        if other_ui_clients:
            log.warn("Warning: ignoring keymap change as there are %i other clients", len(other_ui_clients))
            return
        kc = ss.keyboard_config
        if kc and kc.enabled:
            kc.parse_options(props)
            self.set_keymap(ss, True)
        modifiers = props.get("modifiers", [])
        ss.make_keymask_match(modifiers)

    def set_keyboard_layout_group(self, grp):
        #only actually implemented in X11ServerBase
        pass

    def _process_key_action(self, proto, packet):
        if self.readonly:
            return
        wid, keyname, pressed, modifiers, keyval, _, client_keycode, group = packet[1:9]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        keyname = bytestostr(keyname)
        modifiers = tuple(bytestostr(x) for x in modifiers)
        self.ui_driver = ss.uuid
        self.set_keyboard_layout_group(group)
        keycode = self.get_keycode(ss, client_keycode, keyname, modifiers)
        keylog("process_key_action(%s) server keycode=%s", packet, keycode)
        #currently unused: (group, is_modifier) = packet[8:10]
        self._focus(ss, wid, None)
        ss.make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>=0:
            try:
                self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers)
            except Exception as e:
                keylog("process_key_action%s", (proto, packet), exc_info=True)
                keylog.error("Error: failed to %s key", ["unpress", "press"][pressed])
                keylog.error(" %s", e)
                keylog.error(" for keyname=%s, keyval=%i, keycode=%i", keyname, keyval, keycode)
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
            keylog("handle keycode pressing   %3i: key '%s'", keycode, name)
            self.keys_pressed[keycode] = name
            self.fake_key(keycode, True)
        def unpress():
            keylog("handle keycode unpressing %3i: key '%s'", keycode, name)
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
            now = monotonic_time()
            self.key_repeat_timer = self.timeout_add(0, self._key_repeat_timeout, now, delay_ms, wid, keyname, keyval, keycode, modifiers)

    def _key_repeat_timeout(self, when, delay_ms, wid, keyname, keyval, keycode, modifiers):
        self.key_repeat_timer = None
        now = monotonic_time()
        keylog("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
        self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
        self.keys_timedout[keycode] = now

    def _process_key_repeat(self, proto, packet):
        if self.readonly:
            return
        wid, keyname, keyval, client_keycode, modifiers = packet[1:6]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        keyname = bytestostr(keyname)
        modifiers = tuple(bytestostr(x) for x in modifiers)
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
            now = monotonic_time()
            if when_timedout and (now-when_timedout)<30:
                #not so long ago, just re-press it now:
                keylog("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                self.fake_key(keycode, True)
        self._key_repeat(wid, True, keyname, keyval, keycode, modifiers, self.key_repeat_interval)
        ss.user_event()

    def _process_keyboard_sync_enabled_status(self, proto, packet):
        assert proto in self._server_sources
        if self.readonly:
            return
        self.keyboard_sync = bool(packet[1])
        keylog("toggled keyboard-sync to %s", self.keyboard_sync)

    def _keys_changed(self, *_args):
        if not self.keymap_changing:
            for ss in self._server_sources.values():
                ss.keys_changed()

    def _clear_keys_pressed(self):
        pass

    def get_keyboard_config(self, _props):
        return None

    def set_keyboard_repeat(self, key_repeat):
        pass

    def set_keymap(self, ss, force=False):
        pass


    ######################################################################
    # pointer:
    def _move_pointer(self, wid, pos, *args):
        raise NotImplementedError()

    def _adjust_pointer(self, proto, wid, pointer):
        #the window may not be mapped at the same location by the client:
        ss = self._server_sources.get(proto)
        window = self._id_to_window.get(wid)
        if ss and window:
            ws = ss.get_window_source(wid)
            if ws:
                mapped_at = ws.mapped_at
                pos = self.get_window_position(window)
                mouselog("client %s: server window position: %s, client window position: %s", ss, pos, mapped_at)
                if mapped_at and pos:
                    wx, wy = pos
                    cx, cy = mapped_at[:2]
                    if wx!=cx or wy!=cy:
                        px, py = pointer
                        return px+(wx-cx), py+(wy-cy)
        return pointer

    def _process_mouse_common(self, proto, wid, pointer, *args):
        pointer = self._adjust_pointer(proto, wid, pointer)
        #TODO: adjust args too
        self.do_process_mouse_common(proto, wid, pointer, *args)
        return pointer

    def do_process_mouse_common(self, proto, wid, pointer, *args):
        pass

    def _process_button_action(self, proto, packet):
        mouselog("process_button_action(%s, %s)", proto, packet)
        if self.readonly:
            return
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        ss.user_event()
        self.ui_driver = ss.uuid
        self.do_process_button_action(proto, *packet[1:])

    def do_process_button_action(self, proto, wid, button, pressed, pointer, modifiers, *args):
        pass


    def _update_modifiers(self, proto, wid, modifiers):
        pass

    def _process_pointer_position(self, proto, packet):
        if self.readonly:
            return
        wid, pointer, modifiers = packet[1:4]
        ss = self._server_sources.get(proto)
        if ss is not None:
            ss.mouse_last_position = pointer
        if self.ui_driver and self.ui_driver!=ss.uuid:
            return
        self._update_modifiers(proto, wid, modifiers)
        self._process_mouse_common(proto, wid, pointer, *packet[5:])


    ######################################################################
    # input devices:
    def _process_input_devices(self, _proto, packet):
        self.input_devices_format = packet[1]
        self.input_devices_data = packet[2]
        from xpra.util import print_nested_dict
        mouselog("client %s input devices:", self.input_devices_format)
        print_nested_dict(self.input_devices_data, print_fn=mouselog)
        self.setup_input_devices()

    def setup_input_devices(self):
        pass


    ######################################################################
    # dbus:
    def init_dbus_helper(self):
        if not self.supports_dbus_proxy:
            return
        try:
            from xpra.dbus.helper import DBusHelper
            self.dbus_helper = DBusHelper()
            self.rpc_handlers["dbus"] = self._handle_dbus_rpc
        except Exception as e:
            log("init_dbus_helper()", exc_info=True)
            log.warn("Warning: cannot load dbus helper:")
            log.warn(" %s", e)
            self.dbus_helper = None
            self.supports_dbus_proxy = False

    def make_dbus_server(self):
        from xpra.server.dbus.dbus_server import DBUS_Server
        return DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))


    def add_system_tray(self):
        pass

    def load_existing_windows(self):
        pass

    def is_shown(self, _window):
        return True


    ######################################################################
    # start commands:
    def get_child_env(self):
        #subclasses may add more items (ie: fakexinerama)
        env = os.environ.copy()
        env.update(self.start_env)
        if self.child_display:
            env["DISPLAY"] = self.child_display
        return env

    def get_full_child_command(self, cmd, use_wrapper=True):
        #make sure we have it as a list:
        if type(cmd) not in (list, tuple):
            import shlex
            cmd = shlex.split(str(cmd))
        if not use_wrapper or not self.exec_wrapper:
            return cmd
        return self.exec_wrapper + cmd

    def exec_start_commands(self):
        execlog("exec_start_commands() start=%s, start_child=%s", self.start_commands, self.start_child_commands)
        self._exec_commands(self.start_commands, self.start_child_commands)

    def exec_after_connect_commands(self):
        execlog("exec_after_connect_commands() start=%s, start_child=%s", self.start_after_connect, self.start_child_after_connect)
        self._exec_commands(self.start_after_connect, self.start_child_after_connect)

    def exec_on_connect_commands(self):
        execlog("exec_on_connect_commands() start=%s, start_child=%s", self.start_on_connect, self.start_child_on_connect)
        self._exec_commands(self.start_on_connect, self.start_child_on_connect)

    def _exec_commands(self, start_list, start_child_list):
        started = []
        if start_list:
            for x in start_list:
                if x:
                    proc = self.start_command(x, x, ignore=True)
                    if proc:
                        started.append(proc)
        if start_child_list:
            for x in start_child_list:
                if x:
                    proc = self.start_command(x, x, ignore=False)
                    if proc:
                        started.append(proc)
        procs = tuple(x for x in started if x is not None)
        if not self.session_name:
            self.guess_session_name(procs)

    def start_command(self, name, child_cmd, ignore=False, callback=None, use_wrapper=True, shell=False, **kwargs):
        execlog("start_command%s exec_wrapper=%s", (name, child_cmd, ignore, callback, use_wrapper, shell, kwargs), self.exec_wrapper)
        import subprocess
        env = self.get_child_env()
        try:
            real_cmd = self.get_full_child_command(child_cmd, use_wrapper)
            execlog("full child command(%s, %s)=%s", child_cmd, use_wrapper, real_cmd)
            proc = subprocess.Popen(real_cmd, stdin=subprocess.PIPE, env=env, shell=shell, cwd=self.exec_cwd, close_fds=True, **kwargs)
            procinfo = self.add_process(proc, name, real_cmd, ignore=ignore, callback=callback)
            execlog("pid(%s)=%s", real_cmd, proc.pid)
            if not ignore:
                execlog.info("started command '%s' with pid %s", " ".join(real_cmd), proc.pid)
            self.children_started.append(procinfo)
            return proc
        except OSError as e:
            execlog.error("Error spawning child '%s': %s\n" % (child_cmd, e))
            return None

    def _process_start_command(self, proto, packet):
        log("start new command: %s", packet)
        if not self.start_new_commands:
            log.warn("Warning: received start-command request,")
            log.warn(" but the feature is currently disabled")
            return
        name, command, ignore = packet[1:4]
        proc = self.start_command(name, command, ignore)
        if len(packet)>=5:
            shared = packet[4]
            if proc and not shared:
                ss = self._server_sources.get(proto)
                assert ss
                log("adding filter: pid=%s for %s", proc.pid, proto)
                ss.add_window_filter("window", "pid", "=", proc.pid)
        log("process_start_command: proc=%s", proc)

    def add_process(self, process, name, command, ignore=False, callback=None):
        return self.child_reaper.add_process(process, name, command, ignore, callback=callback)

    def is_child_alive(self, proc):
        return proc is not None and proc.poll() is None

    def reaper_exit(self):
        if self.exit_with_children:
            execlog.info("all children have exited and --exit-with-children was specified, exiting")
            self.idle_add(self.clean_quit)

    def terminate_children_processes(self):
        cl = tuple(self.children_started)
        self.children_started = []
        execlog("terminate_children_processes() children=%s", cl)
        if not cl:
            return
        wait_for = []
        self.child_reaper.poll()
        for procinfo in cl:
            proc = procinfo.process
            name = procinfo.name
            if self.is_child_alive(proc):
                wait_for.append(procinfo)
                execlog("child command '%s' is still alive, calling terminate on %s", name, proc)
                try:
                    proc.terminate()
                except Exception as e:
                    execlog("failed to terminate %s: %s", proc, e)
                    del e
        if not wait_for:
            return
        execlog("waiting for child commands to exit: %s", wait_for)
        start = monotonic_time()
        while monotonic_time()-start<TERMINATE_DELAY and wait_for:
            self.child_reaper.poll()
            #this is called from the UI thread, we cannot sleep
            #sleep(1)
            wait_for = [procinfo for procinfo in wait_for if self.is_child_alive(procinfo.process)]
            execlog("still not terminated: %s", wait_for)
        execlog("done waiting for child commands")

    def guess_session_name(self, procs):
        if not procs:
            return
        #use the commands to define the session name:
        self.child_reaper.poll()
        cmd_names = []
        for proc in procs:
            proc_info = self.child_reaper.get_proc_info(proc.pid)
            if not proc_info:
                continue
            cmd = proc_info.command
            bcmd = os.path.basename(cmd[0])
            if bcmd not in cmd_names:
                cmd_names.append(bcmd)
        execlog("guess_session_name() commands=%s", cmd_names)
        if cmd_names:
            self.session_name = csv(cmd_names)

    def get_commands_info(self):
        info = {
                "start"                     : self.start_commands,
                "start-child"               : self.start_child_commands,
                "start-after-connect"       : self.start_after_connect,
                "start-child-after-connect" : self.start_child_after_connect,
                "start-on-connect"          : self.start_on_connect,
                "start-child-on-connect"    : self.start_child_on_connect,
                "exit-with-children"        : self.exit_with_children,
                "start-after-connect-done"  : self.start_after_connect_done,
                "start-new"                 : self.start_new_commands,
                }
        for i,procinfo in enumerate(self.children_started):
            info[i] = procinfo.get_info()
        return info


    ######################################################################
    # shutdown / exit commands:
    def _process_exit_server(self, _proto, _packet):
        log.info("Exiting in response to client request")
        self.cleanup_all_protocols(SERVER_EXIT)
        self.timeout_add(500, self.clean_quit, ServerCore.EXITING_CODE)

    def _process_shutdown_server(self, _proto, _packet):
        if not self.client_shutdown:
            log.warn("Warning: ignoring shutdown request")
            return
        log.info("Shutting down in response to client request")
        self.cleanup_all_protocols(SERVER_SHUTDOWN)
        self.timeout_add(500, self.clean_quit)


    ######################################################################
    # handle new connections:
    def handle_sharing(self, proto, ui_client=True, detach_request=False, share=False, uuid=None):
        share_count = 0
        disconnected = 0
        existing_sources = set(ss for p,ss in self._server_sources.items() if p!=proto)
        is_existing_client = uuid and any(ss.uuid==uuid for ss in existing_sources)
        log("handle_sharing%s lock=%s, sharing=%s, existing sources=%s, is existing client=%s", (proto, ui_client, detach_request, share, uuid), self.lock, self.sharing, existing_sources, is_existing_client)
        #if other clients are connected, verify we can steal or share:
        if existing_sources and not is_existing_client:
            if self.sharing is True or (self.sharing is None and share and all(ss.share for ss in existing_sources)):
                log("handle_sharing: sharing with %s", tuple(existing_sources))
            elif self.lock is True:
                self.disconnect_client(proto, SESSION_BUSY, "this session is locked")
                return False, 0, 0
            elif self.lock is not False and any(ss.lock for ss in existing_sources):
                self.disconnect_client(proto, SESSION_BUSY, "a client has locked this session")
                return False, 0, 0
        for p,ss in tuple(self._server_sources.items()):
            if detach_request and p!=proto:
                self.disconnect_client(p, DETACH_REQUEST)
                disconnected += 1
            elif uuid and ss.uuid==uuid:
                self.disconnect_client(p, NEW_CLIENT, "new connection from the same uuid")
                disconnected += 1
            elif ui_client and ss.ui_client:
                #check if existing sessions are willing to share:
                if self.sharing is True:
                    share_count += 1
                elif self.sharing is False:
                    self.disconnect_client(p, NEW_CLIENT, "this session does not allow sharing")
                    disconnected += 1
                else:
                    assert self.sharing is None
                    if not share:
                        self.disconnect_client(p, NEW_CLIENT, "the new client does not wish to share")
                        disconnected += 1
                    elif not ss.share:
                        self.disconnect_client(p, NEW_CLIENT, "this client had not enabled sharing")
                        disconnected += 1
                    else:
                        share_count += 1

        #don't accept this connection if we're going to exit-with-client:
        accepted = True
        if disconnected>0 and share_count==0 and self.exit_with_client:
            self.disconnect_client(proto, SERVER_EXIT, "last client has exited")
            accepted = False
        return accepted, share_count, disconnected

    def hello_oked(self, proto, packet, c, auth_caps):
        if ServerCore.hello_oked(self, proto, packet, c, auth_caps):
            #has been handled
            return
        if not c.boolget("steal", True) and self._server_sources:
            self.disconnect_client(proto, SESSION_BUSY, "this session is already active")
            return
        if c.boolget("screenshot_request"):
            self.send_screenshot(proto)
            return
        #added in 2.2:
        generic_request = c.strget("request")
        def is_req(mode):
            return generic_request==mode or c.boolget("%s_request" % mode, False)
        detach_request  = is_req("detach")
        stop_request    = is_req("stop_request")
        exit_request    = is_req("exit_request")
        event_request   = is_req("event_request")
        print_request   = is_req("print_request")
        is_request = detach_request or stop_request or exit_request or event_request or print_request
        if not is_request:
            #"normal" connection, so log welcome message:
            log.info("Handshake complete; enabling connection")
        else:
            log("handling request %s", generic_request)
        self.server_event("handshake-complete")

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        # (but only if this is going to be a UI session - control sessions can co-exist)
        ui_client = c.boolget("ui_client", True)
        share = c.boolget("share")
        uuid = c.strget("uuid")
        accepted, share_count, disconnected = self.handle_sharing(proto, ui_client, detach_request, share, uuid)
        if not accepted:
            return

        if detach_request:
            self.disconnect_client(proto, DONE, "%i other clients have been disconnected" % disconnected)
            return

        if not is_request and ui_client:
            #a bit of explanation:
            #normally these things are synchronized using xsettings, which we handle already
            #but non-posix clients have no such thing,
            #and we don't want to expose that as an interface
            #(it's not very nice and it is very X11 specific)
            #also, clients may want to override what is in their xsettings..
            #so if the client specifies what it wants to use, we patch the xsettings with it
            #(the actual xsettings part is done in update_all_server_settings in the X11 specific subclasses)
            if share_count>0:
                log.info("sharing with %s other client(s)", share_count)
                self.dpi = 0
                self.xdpi = 0
                self.ydpi = 0
                self.double_click_time = -1
                self.double_click_distance = -1, -1
                self.antialias = {}
                self.cursor_size = 24
            else:
                self.dpi = c.intget("dpi", 0)
                self.xdpi = c.intget("dpi.x", 0)
                self.ydpi = c.intget("dpi.y", 0)
                self.double_click_time = c.intget("double_click.time", -1)
                self.double_click_distance = c.intpair("double_click.distance", (-1, -1))
                self.antialias = c.dictget("antialias")
                self.cursor_size = c.intget("cursor.size", 0)
            screenlog("dpi=%s, dpi.x=%s, dpi.y=%s, double_click_time=%s, double_click_distance=%s, antialias=%s, cursor_size=%s", self.dpi, self.xdpi, self.ydpi, self.double_click_time, self.double_click_distance, self.antialias, self.cursor_size)
            #if we're not sharing, reset all the settings:
            reset = share_count==0
            self.update_all_server_settings(reset)

        self.accept_client(proto, c)
        #use blocking sockets from now on:
        if not (PYTHON3 and WIN32):
            set_socket_timeout(proto._conn, None)

        def drop_client(reason="unknown", *args):
            self.disconnect_client(proto, reason, *args)
        def get_window_id(wid):
            return self._window_to_id.get(wid)
        bandwidth_limit = self.get_client_bandwidth_limit(proto)
        ServerSourceClass = self.get_server_source_class()
        ss = ServerSourceClass(proto, drop_client,
                          self.idle_add, self.timeout_add, self.source_remove, self.setting_changed,
                          self.idle_timeout, self.idle_timeout_cb, self.idle_grace_timeout_cb,
                          self._socket_dir, self.unix_socket_paths, not is_request, self.dbus_control,
                          self.get_transient_for, self.get_focus, self.get_cursor_data,
                          get_window_id,
                          self.window_filters,
                          self.file_transfer,
                          self.supports_mmap, self.mmap_filename,
                          bandwidth_limit,
                          self.av_sync,
                          self.core_encodings, self.encodings, self.default_encoding, self.scaling_control,
                          self.sound_properties,
                          self.sound_source_plugin,
                          self.supports_speaker, self.supports_microphone,
                          self.speaker_codecs, self.microphone_codecs,
                          self.default_quality, self.default_min_quality,
                          self.default_speed, self.default_min_speed)
        log("process_hello serversource=%s", ss)
        try:
            ss.parse_hello(c, self.min_mmap_size)
        except:
            #close it already
            ss.close()
            raise
        try:
            self.notify_new_user(ss)
        except Exception as e:
            notifylog("%s(%s)", self.notify_new_user, ss, exc_info=True)
            notifylog.error("Error: failed to show notification of user login:")
            notifylog.error(" %s", e)
        self._server_sources[proto] = ss
        #process ui half in ui thread:
        send_ui = ui_client and not is_request
        self.idle_add(self.parse_hello_ui, ss, c, auth_caps, send_ui, share_count)

    def notify_new_user(self, ss):
        #tell other users:
        notifylog("notify_new_user(%s) sources=%s", ss, self._server_sources)
        if not self._server_sources:
            return
        try:
            from xpra.notifications.common import XPRA_NEW_USER_ID
        except ImportError as e:
            notifylog("notify_new_user(%s) %s", ss, e)
        else:
            nid = XPRA_NEW_USER_ID
            icon = parse_image_path(get_icon_filename("user"))
            title = "User '%s' connected to the session" % (ss.name or ss.username or ss.uuid)
            body = "\n".join(ss.get_connect_info())
            for s in self._server_sources.values():
                s.notify("", nid, "Xpra", 0, "", title, body, [], {}, 10*1000, icon)
        
    def get_client_bandwidth_limit(self, proto):
        if self.bandwidth_limit is None:
            #auto-detect:
            pinfo = proto.get_info()
            socket_speed = pinfo.get("socket", {}).get("speed")
            if socket_speed:
                #auto: use 80% of socket speed if we have it:
                v = socket_speed*AUTO_BANDWIDTH_PCT//100 or 0
            else:
                v = 0
        else:
            v = self.bandwidth_limit
        bandwidthlog("get_client_bandwidth_limit(%s)=%s", proto, v)            
        return v

    def get_server_source_class(self):
        from xpra.server.source import ServerSource
        return ServerSource

    def reset_window_filters(self):
        self.window_filters = []

    def parse_hello_ui(self, ss, c, auth_caps, send_ui, share_count):
        #adds try:except around parse hello ui code:
        try:
            if self._closing:
                raise Exception("server is shutting down")
            self.do_parse_hello_ui(ss, c, auth_caps, send_ui, share_count)
            if self._closing:
                raise Exception("server is shutting down")
        except Exception as e:
            #log exception but don't disclose internal details to the client
            p = ss.protocol
            log("parse_hello_ui%s", (ss, c, auth_caps, send_ui, share_count), exc_info=True)
            log.error("Error: processing new connection from %s:", p or ss)
            log.error(" %s", e)
            if p:
                self.disconnect_client(p, SERVER_ERROR, "error accepting new connection")

    def do_parse_hello_ui(self, ss, c, auth_caps, send_ui, share_count):
        #process screen size (if needed)
        if send_ui:
            root_w, root_h = self.parse_screen_info(ss)
            self.parse_hello_ui_clipboard(ss, c)
            key_repeat = self.parse_hello_ui_keyboard(ss, c)
            self.parse_hello_ui_window_settings(ss, c)
            if self.notifications_forwarder:
                client_notification_actions = dict((s.uuid,s.send_notifications_actions) for s in self._server_sources.values())
                notifylog("client_notification_actions=%s", client_notification_actions)
                self.notifications_forwarder.support_actions = any(v for v in client_notification_actions.values())
        else:
            root_w, root_h = self.get_root_window_size()
            key_repeat = (0, 0)

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, auth_caps)

        if send_ui:
            self.send_initial_windows(ss, share_count>0)
            self.send_initial_cursors(ss, share_count>0)
        self.client_startup_complete(ss)

    def client_startup_complete(self, ss):
        ss.startup_complete()
        self.server_event("startup-complete", ss.uuid)
        if not self.start_after_connect_done:
            self.start_after_connect_done = True
            self.exec_after_connect_commands()
        self.exec_on_connect_commands()

    def sanity_checks(self, proto, c):
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid==self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display that the server it connects to is managing - this would create a loop!")
                return  False
            log.warn("This client is running within the Xpra server %s", server_uuid)
        return True


    def update_all_server_settings(self, reset=False):
        pass        #may be overriden in subclasses (ie: x11 server)


    ######################################################################
    # hello:
    def get_server_features(self, server_source=None):
        #these are flags that have been added over time with new versions
        #to expose new server features:
        f = dict((k, True) for k in (
                #all these flags are assumed enabled in 0.17 (they are present in 0.14.x onwards):
                "window_refresh_config",
                "toggle_cursors_bell_notify",
                "toggle_keyboard_sync",
                "window_unmap",
                "xsettings-tuple",
                "event_request",
                "sound_sequence",
                "notify-startup-complete",
                "suspend-resume",
                "server-events",
                "change-quality", "change-min-quality", "change-speed", "change-min-speed",
                #newer flags:
                "window.configure.skip-geometry",
                "av-sync",
                "auto-video-encoding",
                "window-filters",
                "connection-data",
                ))
        f["sound"] = {
                      "ogg-latency-fix" : True,
                      "eos-sequence"    : True,
                      }
        f["encoding"] = {
                         "generic" : True,
                         }
        f["network"] = {
                 "bandwidth-limit-change"       : True,
                 "bandwidth-limit"              : self.bandwidth_limit or 0,
                 }
        for c in ServerBase.__bases__:
            if c!=ServerCore:
                f.update(c.get_server_features(self, server_source))
        return f

    def make_hello(self, source):
        capabilities = ServerCore.make_hello(self, source)
        for c in ServerBase.__bases__:
            if c!=ServerCore:
                capabilities.update(c.get_caps(self))
        capabilities["server_type"] = "base"
        if source.wants_display:
            capabilities.update({
                 "max_desktop_size"             : self.get_max_screen_size(),
                 })
        if source.wants_features:
            capabilities.update({
                 "bell"                         : self.bell,
                 "cursors"                      : self.cursors,
                 "dbus_proxy"                   : self.supports_dbus_proxy,
                 "rpc-types"                    : tuple(self.rpc_handlers.keys()),
                 "start-new-commands"           : self.start_new_commands,
                 "exit-with-children"           : self.exit_with_children,
                 "av-sync.enabled"              : self.av_sync,
                 "input-devices"                : self.input_devices,
                 "client-shutdown"              : self.client_shutdown,
                 "window.states"                : [],   #subclasses set this as needed
                 "sharing"                      : self.sharing is not False,
                 "sharing-toggle"               : self.sharing is None,
                 "lock"                         : self.lock is not False,
                 "lock-toggle"                  : self.lock is None,
                 "server-commands-signals"      : COMMAND_SIGNALS,
                 "server-commands-info"         : not WIN32 and not OSX,
                 })
            capabilities.update(self.file_transfer.get_file_transfer_features())
            capabilities.update(flatten_dict(self.get_server_features(source)))
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
            capabilities["remote-logging"] = self.remote_logging
            capabilities["remote-logging.multi-line"] = True
        if self._reverse_aliases and server_source.wants_aliases:
            capabilities["aliases"] = self._reverse_aliases
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.send_hello(capabilities)


    def _process_logging(self, proto, packet):
        assert self.remote_logging
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        level, msg = packet[1:3]
        prefix = "client "
        if len(self._server_sources)>1:
            prefix += "%3i " % ss.counter
        if len(packet)>=4:
            dtime = packet[3]
            prefix += "@%02i.%03i " % ((dtime//1000)%60, dtime%1000)
        if isinstance(msg, (tuple, list)):
            msg = " ".join(bytestostr(x) for x in msg)
        for x in bytestostr(msg).splitlines():
            clientlog.log(level, prefix+x)


    def _process_command_signal(self, _proto, packet):
        pid = packet[1]
        signame = packet[2]
        if signame not in COMMAND_SIGNALS:
            log.warn("Warning: invalid signal received: '%s'", signame)
            return
        procinfo = self.child_reaper.get_proc_info(pid)
        if not procinfo:
            log.warn("Warning: command not found for pid %i", pid)
            return
        if procinfo.returncode is not None:
            log.warn("Warning: command for pid %i has already terminated", pid)
            return
        import signal
        sigval = getattr(signal, signame, None)
        if not sigval:
            log.error("Error: signal '%s' not found!", signame)
            return
        log.info("sending signal %s to pid %i", signame, pid)
        try:
            os.kill(pid, sigval)
        except Exception as e:
            log.error("Error sending signal '%s' to pid %i", signame, pid)
            log.error(" %s", e)
            

    ######################################################################
    # info:
    def _process_info_request(self, proto, packet):
        log("process_info_request(%s, %s)", proto, packet)
        #ignoring the list of client uuids supplied in packet[1]
        ss = self._server_sources.get(proto)
        if not ss:
            return
        window_ids, categories = [], None
        #if len(packet>=2):
        #    uuid = packet[1]
        if len(packet)>=3:
            window_ids = packet[2]
        if len(packet)>=4:
            categories = packet[3]
        def info_callback(_proto, info):
            assert proto==_proto
            if categories:
                info = dict((k,v) for k,v in info.items() if k in categories)
            ss.send_info_response(info)
        self.get_all_info(info_callback, proto, None, window_ids)

    def send_hello_info(self, proto, flatten=True):
        start = monotonic_time()
        def cb(proto, info):
            self.do_send_info(proto, info, flatten)
            end = monotonic_time()
            log.info("processed %s info request from %s in %ims", ["structured", "flat"][flatten], proto._conn, (end-start)*1000)
        self.get_all_info(cb, proto, None, self._id_to_window.keys())

    def get_ui_info(self, _proto, _client_uuids=None, wids=None, *_args):
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        info = {"server"    : {"max_desktop_size"   : self.get_max_screen_size()}}
        if self.keyboard_config:
            info["keyboard"] = {"state" : {"modifiers"          : self.keyboard_config.get_current_mask()}}
        #window info:
        self.add_windows_info(info, wids)
        return info

    def get_thread_info(self, proto):
        return get_thread_info(proto, tuple(self._server_sources.keys()))


    def get_info(self, proto=None, client_uuids=None, wids=None, *args):
        log("ServerBase.get_info%s", (proto, client_uuids, wids, args))
        start = monotonic_time()
        info = ServerCore.get_info(self, proto)
        server_info = info.setdefault("server", {})
        server_info["pings"] = self.pings
        if self.mem_bytes:
            server_info["total-memory"] = self.mem_bytes
        if client_uuids:
            sources = [ss for ss in self._server_sources.values() if ss.uuid in client_uuids]
        else:
            sources = tuple(self._server_sources.values())
        if not wids:
            wids = self._id_to_window.keys()
        log("info-request: sources=%s, wids=%s", sources, wids)
        dgi = self.do_get_info(proto, sources, wids)
        #ugly alert: merge nested dictionaries,
        #ie: do_get_info may return a dictionary for "server" and we already have one,
        # so we update it with the new values
        for k,v in dgi.items():
            cval = info.get(k)
            if cval is None:
                info[k] = v
                continue
            cval.update(v)
        info.setdefault("dpi", {}).update({
                             "default"      : self.default_dpi,
                             "value"        : self.dpi,
                             "x"            : self.xdpi,
                             "y"            : self.ydpi,
                             })
        info.setdefault("mmap", {}).update({
            "supported"     : self.supports_mmap,
            "filename"      : self.mmap_filename or "",
            })
        info.setdefault("antialias", {}).update(self.antialias)
        info.setdefault("cursor", {}).update({"size" : self.cursor_size})
        info.setdefault("commands", self.get_commands_info())
        if self.notifications_forwarder:
            info.setdefault("notifications", {}).update(self.notifications_forwarder.get_info())
        log("ServerBase.get_info took %.1fms", 1000.0*(monotonic_time()-start))
        return info

    def get_features_info(self):
        i = {
             "randr"            : self.randr,
             "cursors"          : self.cursors,
             "bell"             : self.bell,
             "notifications"    : self.notifications_forwarder is not None,
             "sharing"          : self.sharing is not False,
             "dbus_proxy"       : self.supports_dbus_proxy,
             "rpc-types"        : tuple(self.rpc_handlers.keys()),
             "idle_timeout"     : self.idle_timeout,
             }
        i.update(self.get_server_features())
        return i

    def do_get_info(self, proto, server_sources=None, window_ids=None):
        start = monotonic_time()
        info = {}
        def up(prefix, d):
            info[prefix] = d

        for c in ServerBase.__bases__:
            try:
                info.update(c.get_info(self, proto))
            except Exception as e:
                log("do_get_info%s", (proto, server_sources, window_ids), exc_info=True)
                log.error("Error collecting information from %s: %s", c, e)

        up("commands",  self.get_commands_info())
        up("features",  self.get_features_info())
        up("keyboard",  self.get_keyboard_info())
        up("encodings", self.get_encoding_info())
        up("network", {
            "sharing"                      : self.sharing is not False,
            "sharing-toggle"               : self.sharing is None,
            "lock"                         : self.lock is not False,
            "lock-toggle"                  : self.lock is None,
            })
        for k,v in codec_versions.items():
            info.setdefault("encoding", {}).setdefault(k, {})["version"] = v
        # csc and video encoders:
        up("video",     getVideoHelper().get_info())

        info.setdefault("state", {})["windows"] = len([window for window in tuple(self._id_to_window.values()) if window.is_managed()])
        # other clients:
        info["clients"] = {""                   : len([p for p in self._server_sources.keys() if p!=proto]),
                           "unauthenticated"    : len([p for p in self._potential_protocols if ((p is not proto) and (p not in self._server_sources.keys()))])}
        #find the server source to report on:
        n = len(server_sources or [])
        if n==1:
            ss = server_sources[0]
            up("client", ss.get_info())
            info.update(ss.get_window_info(window_ids))
        elif n>1:
            cinfo = {}
            for i, ss in enumerate(server_sources):
                sinfo = ss.get_info()
                sinfo["ui-driver"] = self.ui_driver==ss.uuid
                sinfo.update(ss.get_window_info(window_ids))
                cinfo[i] = sinfo
            up("client", cinfo)
        log("ServerBase.do_get_info took %ims", (monotonic_time()-start)*1000)
        return info


    ######################################################################
    # display / screen / root window:
    def set_screen_geometry_attributes(self, w, h):
        #by default, use the screen as desktop area:
        self.set_desktop_geometry_attributes(w, h)

    def set_desktop_geometry_attributes(self, w, h):
        self.calculate_desktops()
        self.calculate_workarea(w, h)
        self.set_desktop_geometry(w, h)


    def parse_screen_info(self, ss):
        return self.do_parse_screen_info(ss, ss.desktop_size)

    def do_parse_screen_info(self, ss, desktop_size):
        log("do_parse_screen_info%s", (ss, desktop_size))
        dw, dh = None, None
        if desktop_size:
            try:
                dw, dh = desktop_size
                if not ss.screen_sizes:
                    screenlog.info(" client root window size is %sx%s", dw, dh)
                else:
                    screenlog.info(" client root window size is %sx%s with %s display%s:", dw, dh, len(ss.screen_sizes), engs(ss.screen_sizes))
                    log_screen_sizes(dw, dh, ss.screen_sizes)
            except:
                dw, dh = None, None
        sw, sh = self.configure_best_screen_size()
        screenlog("configure_best_screen_size()=%s", (sw, sh))
        #we will tell the client about the size chosen in the hello we send back,
        #so record this size as the current server desktop size to avoid change notifications:
        ss.desktop_size_server = sw, sh
        #prefer desktop size, fallback to screen size:
        w = dw or sw
        h = dh or sh
        #clamp to max supported:
        maxw, maxh = self.get_max_screen_size()
        w = min(w, maxw)
        h = min(h, maxh)
        self.set_desktop_geometry_attributes(w, h)
        self.set_icc_profile()
        return w, h


    def set_icc_profile(self):
        screenlog("set_icc_profile() not implemented")

    def reset_icc_profile(self):
        screenlog("reset_icc_profile() not implemented")

    def _screen_size_changed(self, screen):
        screenlog("_screen_size_changed(%s)", screen)
        #randr has resized the screen, tell the client (if it supports it)
        w, h = screen.get_width(), screen.get_height()
        screenlog("new screen dimensions: %ix%i", w, h)
        self.set_screen_geometry_attributes(w, h)
        self.idle_add(self.send_updated_screen_size)

    def get_root_window_size(self):
        raise NotImplementedError()

    def send_updated_screen_size(self):
        max_w, max_h = self.get_max_screen_size()
        root_w, root_h = self.get_root_window_size()
        root_w = min(root_w, max_w)
        root_h = min(root_h, max_h)
        count = 0
        for ss in self._server_sources.values():
            if ss.updated_desktop_size(root_w, root_h, max_w, max_h):
                count +=1
        if count>0:
            log.info("sent updated screen size to %s client%s: %sx%s (max %sx%s)", count, engs(count), root_w, root_h, max_w, max_h)

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

    def configure_best_screen_size(self):
        root_w, root_h = self.get_root_window_size()
        return root_w, root_h

    def _process_desktop_size(self, proto, packet):
        width, height = packet[1:3]
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        ss.desktop_size = (width, height)
        if len(packet)>=10:
            #added in 0.16 for scaled client displays:
            xdpi, ydpi = packet[8:10]
            if xdpi!=self.xdpi or ydpi!=self.ydpi:
                self.xdpi, self.ydpi = xdpi, ydpi
                screenlog("new dpi: %ix%i", self.xdpi, self.ydpi)
                self.dpi = iround((self.xdpi + self.ydpi)/2.0)
                self.dpi_changed()
        if len(packet)>=8:
            #added in 0.16 for scaled client displays:
            ss.desktop_size_unscaled = packet[6:8]
        if len(packet)>=6:
            desktops, desktop_names = packet[4:6]
            ss.set_desktops(desktops, desktop_names)
            self.calculate_desktops()
        if len(packet)>=4:
            ss.set_screen_sizes(packet[3])
        screenlog("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        if len(packet)>=4:
            screenlog.info("received updated display dimensions")
            screenlog.info("client display size is %sx%s with %s screen%s:", width, height, len(ss.screen_sizes), engs(ss.screen_sizes))
            log_screen_sizes(width, height, ss.screen_sizes)
            self.calculate_workarea(width, height)
        #ensures that DPI and antialias information gets reset:
        self.update_all_server_settings()

    def dpi_changed(self):
        pass

    def calculate_desktops(self):
        count = 1
        for ss in self._server_sources.values():
            if ss.desktops:
                count = max(count, ss.desktops)
        count = max(1, min(20, count))
        names = []
        for i in range(count):
            if i==0:
                name = "Main"
            else:
                name = "Desktop %s" % (i+1)
            for ss in self._server_sources.values():
                if ss.desktops and i<len(ss.desktop_names) and ss.desktop_names[i]:
                    name = ss.desktop_names[i]
            names.append(name)
        self.set_desktops(names)

    def set_desktops(self, names):
        pass

    def calculate_workarea(self, w, h):
        raise NotImplementedError()

    def set_workarea(self, workarea):
        pass


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
            #filter out encoding properties, which are expected to be set everytime:
            ncp = {}
            for k,v in new_client_properties.items():
                if v is None:
                    log.warn("removing invalid None property for %s", k)
                    continue
                if not k.startswith(b"encoding"):
                    ncp[k] = v
            if ncp:
                log("set_client_properties updating window %s of source %s with %s", wid, ss.uuid, ncp)
                client_properties = self.client_properties.setdefault(wid, {}).setdefault(ss.uuid, {})
                client_properties.update(ncp)


    ######################################################################
    # screenshots:
    def _process_screenshot(self, proto, _packet):
        packet = self.make_screenshot_packet()
        ss = self._server_sources.get(proto)
        if packet and ss:
            ss.send(*packet)

    def make_screenshot_packet(self):
        try:
            return self.do_make_screenshot_packet()
        except:
            log.error("make_screenshot_packet()", exc_info=True)
            return None

    def do_make_screenshot_packet(self):
        raise NotImplementedError("no screenshot capability in %s" % type(self))

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


    ######################################################################
    # windows:
    def parse_hello_ui_window_settings(self, ss, c):
        pass

    def add_windows_info(self, info, window_ids):
        winfo = info.setdefault("window", {})
        for wid, window in self._id_to_window.items():
            if window_ids is not None and wid not in window_ids:
                continue
            winfo.setdefault(wid, {}).update(self.get_window_info(window))

    def get_window_info(self, window):
        from xpra.server.source import make_window_metadata
        info = {}
        for prop in window.get_property_names():
            if prop=="icon" or prop is None:
                continue
            metadata = make_window_metadata(window, prop, get_transient_for=self.get_transient_for)
            info.update(metadata)
        for prop in window.get_internal_property_names():
            metadata = make_window_metadata(window, prop)
            info.update(metadata)
        info.update({
             "override-redirect"    : window.is_OR(),
             "tray"                 : window.is_tray(),
             "size"                 : window.get_dimensions(),
             })
        wid = self._window_to_id.get(window)
        if wid:
            wprops = self.client_properties.get(wid)
            if wprops:
                info["client-properties"] = wprops
        return info

    def _update_metadata(self, window, pspec):
        metalog("updating metadata on %s: %s", window, pspec)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.window_metadata(wid, window, pspec.name)


    def _add_new_window_common(self, window):
        props = window.get_dynamic_property_names()
        metalog("add_new_window_common(%s) watching for dynamic properties: %s", window, props)
        for prop in props:
            window.managed_connect("notify::%s" % prop, self._update_metadata)
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        return wid

    def _do_send_new_window_packet(self, ptype, window, geometry):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            wprops = self.client_properties.get(wid, {}).get(ss.uuid)
            x, y, w, h = geometry
            #adjust if the transient-for window is not mapped in the same place by the client we send to:
            if "transient-for" in window.get_property_names():
                transient_for = self.get_transient_for(window)
                if transient_for>0:
                    parent = self._id_to_window.get(transient_for)
                    parent_ws = ss.get_window_source(transient_for)
                    pos = self.get_window_position(parent)
                    geomlog("transient-for=%s : %s, ws=%s, pos=%s", transient_for, parent, parent_ws, pos)
                    if parent and parent_ws and parent_ws.mapped_at and pos:
                        cx, cy = parent_ws.mapped_at[:2]
                        px, py = pos
                        x += cx-px
                        y += cy-py
            ss.new_window(ptype, wid, window, x, y, w, h, wprops)

    def _process_damage_sequence(self, proto, packet):
        packet_sequence, wid, width, height, decode_time = packet[1:6]
        if len(packet)>=7:
            message = packet[6]
        else:
            message = ""
        ss = self._server_sources.get(proto)
        if ss:
            ss.client_ack_damage(packet_sequence, wid, width, height, decode_time, message)

    def _damage(self, window, x, y, width, height, options=None):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.damage(wid, window, x, y, width, height, options)

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
            #may have been destroyed since the request was made
            log("invalid window specified for refresh: %s", wid)
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

    def refresh_windows(self, proto, wid_windows, opts={}):
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        for wid, window in wid_windows.items():
            if window is None or not window.is_managed():
                continue
            if not self.is_shown(window):
                log("window is no longer shown, ignoring buffer refresh which would fail")
                continue
            ss.refresh(wid, window, opts)

    def _idle_refresh_all_windows(self, proto):
        self.idle_add(self.refresh_windows, proto, self._id_to_window)


    def get_window_position(self, _window):
        #where the window is actually mapped on the server screen:
        return None

    def _window_mapped_at(self, proto, wid, window, coords=None):
        #record where a window is mapped by a client
        #(in order to support multiple clients and different offsets)
        ss = self._server_sources.get(proto)
        if not ss:
            return
        ws = ss.make_window_source(wid, window)
        ws.mapped_at = coords
        #log("window %i mapped at %s for client %s", wid, coords, ss)

    def get_transient_for(self, _window):
        return  None

    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)

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


    def send_initial_windows(self, ss, sharing=False):
        raise NotImplementedError()


    def send_initial_cursors(self, ss, sharing=False):
        pass


    ######################################################################
    # focus:
    def _process_focus(self, proto, packet):
        if self.readonly:
            return
        wid = packet[1]
        focuslog("process_focus: wid=%s", wid)
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self._server_sources.get(proto)
        if ss:
            self._focus(ss, wid, modifiers)
            #if the client focused one of our windows, count this as a user event:
            if wid>0:
                ss.user_event()

    def _focus(self, _server_source, wid, modifiers):
        focuslog("_focus(%s,%s)", wid, modifiers)

    def get_focus(self):
        #can be overriden by subclasses that do manage focus
        #(ie: not shadow servers which only have a single window)
        #default: no focus
        return -1


    ######################################################################
    # encodings:
    def init_encodings(self):
        load_codecs(decoders=False)
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
        enc_pillow = get_codec("enc_pillow")
        if enc_pillow:
            pil_encs = enc_pillow.get_encodings()
            add_encodings(x for x in pil_encs if x!="webp")
            #Note: webp will only be enabled if we have a Python-PIL fallback
            #(either "webp" or "png")
            if has_codec("enc_webp") and ("webp" in pil_encs or "png" in pil_encs):
                add_encodings(["webp"])
                if "webp" not in self.lossless_mode_encodings:
                    self.lossless_mode_encodings.append("webp")
        #look for video encodings with lossless mode:
        for e in ve:
            for colorspace,especs in getVideoHelper().get_encoder_specs(e).items():
                for espec in especs:
                    if espec.has_lossless_mode:
                        if e not in self.lossless_mode_encodings:
                            log("found lossless mode for encoding %s with %s and colorspace %s", e, espec, colorspace)
                            self.lossless_mode_encodings.append(e)
                            break
        #now update the variables:
        self.encodings = encs
        self.core_encodings = core_encs
        self.lossless_encodings = [x for x in self.core_encodings if (x.startswith("png") or x.startswith("rgb") or x=="webp")]
        log("allowed encodings=%s, encodings=%s, core encodings=%s, lossless encodings=%s", self.allowed_encodings, encs, core_encs, self.lossless_encodings)
        pref = [x for x in PREFERED_ENCODING_ORDER if x in self.encodings]
        if pref:
            self.default_encoding = pref[0]
        else:
            self.default_encoding = None

    def init_encoding(self, cmdline_encoding):
        if not cmdline_encoding or str(cmdline_encoding).lower() in ("auto", "none"):
            self.default_encoding = None
        elif cmdline_encoding in self.encodings:
            self.default_encoding = cmdline_encoding
        else:
            log.warn("ignored invalid default encoding option: %s", cmdline_encoding)

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

    def _process_quality(self, proto, packet):
        quality = packet[1]
        log("Setting quality to %s", quality)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_quality(quality)
            self._idle_refresh_all_windows(proto)

    def _process_min_quality(self, proto, packet):
        min_quality = packet[1]
        log("Setting min quality to %s", min_quality)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_min_quality(min_quality)
            self._idle_refresh_all_windows(proto)

    def _process_speed(self, proto, packet):
        speed = packet[1]
        log("Setting speed to ", speed)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_speed(speed)
            self._idle_refresh_all_windows(proto)

    def _process_min_speed(self, proto, packet):
        min_speed = packet[1]
        log("Setting min speed to ", min_speed)
        ss = self._server_sources.get(proto)
        if ss:
            ss.set_min_speed(min_speed)
            self._idle_refresh_all_windows(proto)

    def get_encoding_info(self):
        return  {
             ""                     : self.encodings,
             "core"                 : self.core_encodings,
             "allowed"              : self.allowed_encodings,
             "lossless"             : self.lossless_encodings,
             "problematic"          : [x for x in self.core_encodings if x in PROBLEMATIC_ENCODINGS],
             "with_speed"           : tuple(set({"rgb32" : "rgb", "rgb24" : "rgb"}.get(x, x) for x in self.core_encodings if x in ("h264", "vp8", "vp9", "rgb24", "rgb32", "png", "png/P", "png/L", "webp"))),
             "with_quality"         : [x for x in self.core_encodings if x in ("jpeg", "webp", "h264", "vp8", "vp9")],
             "with_lossless_mode"   : self.lossless_mode_encodings,
             }


    ######################################################################
    # settings toggle:
    def setting_changed(self, setting, value):
        #tell all the clients (that can) about the new value for this setting
        for ss in tuple(self._server_sources.values()):
            ss.send_setting_change(setting, value)

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

    def _process_sharing_toggle(self, proto, packet):
        assert self.sharing is None
        ss = self._server_sources.get(proto)
        if not ss:
            return
        sharing = bool(packet[1])
        ss.share = sharing
        if not sharing:
            #disconnect other users:
            for p,ss in tuple(self._server_sources.items()):
                if p!=proto:
                    self.disconnect_client(p, DETACH_REQUEST, "client %i no longer wishes to share the session" % ss.counter)

    def _process_lock_toggle(self, proto, packet):
        assert self.lock is None
        ss = self._server_sources.get(proto)
        if ss:
            ss.lock = bool(packet[1])
            log("lock set to %s for client %i", ss.lock, ss.counter)


    ######################################################################
    # rpc:
    def _process_rpc(self, proto, packet):
        if self.readonly:
            return
        ss = self._server_sources.get(proto)
        assert ss is not None
        rpc_type = packet[1]
        rpcid = packet[2]
        handler = self.rpc_handlers.get(rpc_type)
        if not handler:
            rpclog.error("Error: invalid rpc request of type '%s'", rpc_type)
            return
        rpclog("rpc handler for %s: %s", rpc_type, handler)
        try:
            handler(ss, *packet[2:])
        except Exception as e:
            rpclog.error("Error: cannot call %s handler %s:", rpc_type, handler, exc_info=True)
            ss.rpc_reply(rpc_type, rpcid, False, str(e))

    def _handle_dbus_rpc(self, ss, rpcid, _, bus_name, path, interface, function, args, *_extra):
        assert self.supports_dbus_proxy, "server does not support dbus proxy calls"
        def native(args):
            return [self.dbus_helper.dbus_to_native(x) for x in (args or [])]
        def ok_back(*args):
            log("rpc: ok_back%s", args)
            ss.rpc_reply("dbus", rpcid, True, native(args))
        def err_back(*args):
            log("rpc: err_back%s", args)
            ss.rpc_reply("dbus", rpcid, False, native(args))
        self.dbus_helper.call_function(bus_name, path, interface, function, args, ok_back, err_back)


    ######################################################################
    # connection state:
    def _process_connection_data(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.update_connection_data(packet[1])

    def _process_bandwidth_limit(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            return
        bandwidth_limit = packet[1]
        if self.bandwidth_limit:
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        ss.bandwidth_limit = bandwidth_limit
        bandwidthlog.info("bandwidth-limit changed to %sbps for client %i", std_unit(bandwidth_limit), ss.counter)

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


    ######################################################################
    # http server and http audio stream:
    def get_http_info(self):
        info = ServerCore.get_http_info(self)
        info["clients"] = len(self._server_sources)
        return info

    def get_http_scripts(self):
        scripts = ServerCore.get_http_scripts(self)
        scripts["/audio.mp3"] = self.http_audio_mp3_request
        return scripts

    def http_audio_mp3_request(self, handler):
        def err(code=500):
            handler.send_response(code)
            return None
        try:
            args_str = handler.path.split("?", 1)[1]
        except:
            return err()
        #parse args:
        args = {}
        for x in args_str.split("&"):
            v = x.split("=", 1)
            if len(v)==1:
                args[v[0]] = ""
            else:
                args[v[0]] = v[1]
        httplog("http_audio_mp3_request(%s) args(%s)=%s", handler, args_str, args)
        uuid = args.get("uuid")
        if not uuid:
            httplog.warn("Warning: http-stream audio request, missing uuid")
            return err()
        source = None
        for x in self._server_sources.values():
            if x.uuid==uuid:
                source = x
                break
        if not source:
            httplog.warn("Warning: no client matching uuid '%s'", uuid)
            return err()
        state = {}
        def new_buffer(_sound_source, data, _metadata, packet_metadata=[]):
            if not state.get("started"):
                httplog.warn("buffer received but stream is not started yet")
                err()
                source.stop_sending_sound()
                return
            count = state.get("buffers", 0)
            httplog("new_buffer [%i] for %s sound stream: %i bytes", count, state.get("codec", "?"), len(data))
            #httplog("buffer %i: %s", count, hexstr(data))
            state["buffers"] = count+1
            try:
                for x in packet_metadata:
                    handler.wfile.write(x)
                handler.wfile.write(data)
            except Exception as e:
                httplog.warn("Error: failed to send audio packet:")
                httplog.warn(" %s", e)
                source.stop_sending_sound()
                return
        def new_stream(_sound_source, codec):
            httplog("new_stream: %s", codec)
            state["started"] = True
            state["buffers"] = 0
            state["codec"] = codec
            handler.send_response(200)
            headers = {
                "Content-type"      : "audio/mpeg",
                }
            for k,v in headers.items():
                handler.send_header(k, v)
            handler.end_headers()
        def timeout_check():
            if not state.get("started"):
                err()
        if source.sound_source:
            source.stop_sending_sound()
        source.start_sending_sound("mp3", volume=1.0, new_stream=new_stream, new_buffer=new_buffer, skip_client_codec_check=True)
        self.timeout_add(1000*5, timeout_check)


    ######################################################################
    # client connections:
    def init_sockets(self, sockets):
        ServerCore.init_sockets(self, sockets)
        #verify we have a local socket for printing:
        nontcpsockets = [info for socktype, _, info in sockets if socktype=="unix-domain"]
        netlog("local sockets we can use for printing: %s", nontcpsockets)
        if not nontcpsockets and self.file_transfer.printing:
            if not WIN32:
                log.warn("Warning: no local sockets defined,")
                log.warn(" disabling printer forwarding")
            self.file_transfer.printing = False

    def force_disconnect(self, proto):
        self.cleanup_protocol(proto)
        ServerCore.force_disconnect(self, proto)

    def disconnect_protocol(self, protocol, reason, *extra):
        ServerCore.disconnect_protocol(self, protocol, reason, *extra)
        self.cleanup_protocol(protocol)

    def cleanup_protocol(self, protocol):
        netlog("cleanup_protocol(%s)", protocol)
        #this ensures that from now on we ignore any incoming packets coming
        #from this connection as these could potentially set some keys pressed, etc
        try:
            del self._potential_protocols[protocol]
        except:
            pass
        source = self._server_sources.get(protocol)
        if source:
            self.cleanup_source(source)
            try:
                del self._server_sources[protocol]
            except:
                pass
        return source

    def cleanup_source(self, source):
        had_client = len(self._server_sources)>0
        self.server_event("connection-lost", source.uuid)
        if self.ui_driver==source.uuid:
            self.ui_driver = None
        source.close()
        remaining_sources = [x for x in self._server_sources.values() if x!=source]
        netlog("cleanup_source(%s) remaining sources: %s", source, remaining_sources)
        netlog.info("xpra client %i disconnected.", source.counter)
        has_client = len(remaining_sources)>0
        if had_client and not has_client:
            self.idle_add(self.last_client_exited)

    def last_client_exited(self):
        #must run from the UI thread (modifies focus and keys)
        if self.exit_with_client:
            netlog.info("Last client has disconnected, terminating")
            self.clean_quit(False)
        else:
            self.reset_server_timeout(True)
            #so it is now safe to clear them:
            #(this may fail during shutdown - which is ok)
            try:
                self._clear_keys_pressed()
            except:
                pass
            self._focus(None, 0, [])
            self.reset_icc_profile()


    def get_all_protocols(self):
        return list(self._potential_protocols) + list(self._server_sources.keys())


    def is_timedout(self, protocol):
        v = ServerCore.is_timedout(self, protocol) and protocol not in self._server_sources
        netlog("is_timedout(%s)=%s", protocol, v)
        return v


    def idle_timeout_cb(self, source):
        timeoutlog("idle_timeout_cb(%s)", source)
        p = source.protocol
        if p:
            self.disconnect_client(p, IDLE_TIMEOUT)

    def idle_grace_timeout_cb(self, source):
        timeoutlog("idle_grace_timeout_cb(%s)", source)
        nid = XPRA_IDLE_NOTIFICATION_ID
        actions = ()
        if source.send_notifications_actions:
            actions = ("cancel", "Cancel Timeout")
        user_icon = os.path.join(get_icon_dir(), "timer.png")
        icon = parse_image_path(user_icon) or ()
        def idle_notification_action(nid, action_id):
            timeoutlog("idle_notification_action(%i, %s)", nid, action_id)
            if action_id=="cancel":
                source.user_event()
                source.no_idle()
        if self.session_name!="Xpra":
            summary = "The Xpra session %s" % self.session_name
        else:
            summary = "Xpra session"
        summary += " is about to timeout"
        body = "Unless this session sees some activity,\n" + \
               "it will be terminated soon."
        source.notify("", nid, "Xpra", 0, "", summary, body, actions, {}, source.idle_grace_duration*1000, icon, user_callback=idle_notification_action)
        source.go_idle()


    def _log_disconnect(self, proto, *args):
        #skip logging of disconnection events for server sources
        #we have tagged during hello ("info_request", "exit_request", etc..)
        ss = self._server_sources.get(proto)
        if ss and not ss.log_disconnect:
            #log at debug level only:
            netlog(*args)
            return
        ServerCore._log_disconnect(self, proto, *args)

    def _disconnect_proto_info(self, proto):
        #only log protocol info if there is more than one client:
        if len(self._server_sources)>1:
            return " %s" % proto
        return ""

    def _process_connection_lost(self, proto, packet):
        ServerCore._process_connection_lost(self, proto, packet)
        ch = self._clipboard_helper
        if ch and self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
            ch.client_reset()
        self.cleanup_protocol(proto)


    ######################################################################
    # packets:
    def init_packet_handlers(self):
        for c in ServerBase.__bases__:
            c.init_packet_handlers(self)
        self._authenticated_packet_handlers.update({
            "set-keyboard-sync-enabled":            self._process_keyboard_sync_enabled_status,
            "damage-sequence":                      self._process_damage_sequence,
            "ping":                                 self._process_ping,
            "ping_echo":                            self._process_ping_echo,
            "set-cursors":                          self._process_set_cursors,
            "set-bell":                             self._process_set_bell,
            "logging":                              self._process_logging,
            "command_request":                      self._process_command_request,
            "connection-data":                      self._process_connection_data,
            "bandwidth-limit":                      self._process_bandwidth_limit,
            "sharing-toggle":                       self._process_sharing_toggle,
            "lock-toggle":                          self._process_lock_toggle,
            "command-signal":                       self._process_command_signal,
          })
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
            #requests:
            "shutdown-server":                      self._process_shutdown_server,
            "exit-server":                          self._process_exit_server,
            "buffer-refresh":                       self._process_buffer_refresh,
            "screenshot":                           self._process_screenshot,
            "info-request":                         self._process_info_request,
            "start-command":                        self._process_start_command,
            "input-devices":                        self._process_input_devices,
            })

    def init_aliases(self):
        packet_types = list(self._default_packet_handlers.keys())
        packet_types += list(self._authenticated_packet_handlers.keys())
        packet_types += list(self._authenticated_ui_packet_handlers.keys())
        self.do_init_aliases(packet_types)

    def process_packet(self, proto, packet):
        try:
            handler = None
            packet_type = bytestostr(packet[0])
            if proto in self._server_sources:
                handler = self._authenticated_ui_packet_handlers.get(packet_type)
                if handler:
                    netlog("process ui packet %s", packet_type)
                    self.idle_add(handler, proto, packet)
                    return
                handler = self._authenticated_packet_handlers.get(packet_type)
                if handler:
                    netlog("process non-ui packet %s", packet_type)
                    handler(proto, packet)
                    return
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                netlog("process default packet %s", packet_type)
                handler(proto, packet)
                return
            def invalid_packet():
                ss = self._server_sources.get(proto)
                if not self._closing and not proto._closed and (ss is None or not ss.is_closed()):
                    netlog("invalid packet: %s", packet)
                    netlog.error("unknown or invalid packet type: %s from %s", packet_type, proto)
                if not ss:
                    proto.close()
            self.idle_add(invalid_packet)
        except KeyboardInterrupt:
            raise
        except:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
