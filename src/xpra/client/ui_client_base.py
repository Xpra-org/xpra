# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import time
import datetime

from xpra.log import Logger
log = Logger("client")
windowlog = Logger("client", "window")
paintlog = Logger("client", "paint")
focuslog = Logger("client", "focus")
soundlog = Logger("client", "sound")
traylog = Logger("client", "tray")
keylog = Logger("client", "keyboard")
workspacelog = Logger("client", "workspace")
dbuslog = Logger("client", "dbus")
grablog = Logger("client", "grab")

from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.deque import maxdeque
from xpra.client.client_base import XpraClientBase, EXIT_TIMEOUT, EXIT_MMAP_TOKEN_FAILURE
from xpra.client.client_tray import ClientTray
from xpra.client.keyboard_helper import KeyboardHelper
from xpra.platform import set_application_name
from xpra.platform.features import MMAP_SUPPORTED, SYSTEM_TRAY_SUPPORTED, CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY, CLIPBOARDS
from xpra.platform.gui import init as gui_init, ready as gui_ready, get_native_notifier_classes, get_native_tray_classes, get_native_system_tray_classes, get_native_tray_menu_helper_classes, ClientExtras
from xpra.codecs.codec_constants import get_PIL_decodings
from xpra.codecs.loader import codec_versions, has_codec, get_codec, PREFERED_ENCODING_ORDER, ALL_NEW_ENCODING_NAMES_TO_OLD, OLD_ENCODING_NAMES_TO_NEW
from xpra.codecs.video_helper import getVideoHelper, ALL_VIDEO_DECODER_OPTIONS, NO_GFX_CSC_OPTIONS
from xpra.simple_stats import std_unit
from xpra.net.protocol import Compressed, use_lz4
from xpra.daemon_thread import make_daemon_thread
from xpra.os_util import thread, Queue, os_info, platform_name, get_machine_id, get_user_uuid
from xpra.util import nn, nonl, std, AtomicInteger, AdHocStruct, log_screen_sizes
try:
    from xpra.clipboard.clipboard_base import ALL_CLIPBOARDS
except:
    ALL_CLIPBOARDS = []

FAKE_BROKEN_CONNECTION = os.environ.get("XPRA_FAKE_BROKEN_CONNECTION", "0")=="1"
PING_TIMEOUT = int(os.environ.get("XPRA_PING_TIMEOUT", "60"))
UNGRAB_KEY = os.environ.get("XPRA_UNGRAB_KEY", "Escape")


if sys.version > '3':
    unicode = str           #@ReservedAssignment


"""
Utility superclass for client classes which have a UI.
See gtk_client_base and its subclasses.
"""
class UIXpraClient(XpraClientBase):
    #NOTE: these signals aren't registered because this class
    #does not extend GObject.
    __gsignals__ = {
        "handshake-complete"        : no_arg_signal,
        "first-ui-received"         : no_arg_signal,

        "clipboard-toggled"         : no_arg_signal,
        "keyboard-sync-toggled"     : no_arg_signal,
        "speaker-changed"           : no_arg_signal,        #bitrate or pipeline state has changed
        "microphone-changed"        : no_arg_signal,        #bitrate or pipeline state has changed
        }

    def __init__(self):
        XpraClientBase.__init__(self)
        gui_init()
        self.start_time = time.time()
        self._window_to_id = {}
        self._id_to_window = {}
        self._ui_events = 0
        self.title = ""
        self.session_name = ""
        self.auto_refresh_delay = -1
        self.dpi = 96

        #draw thread:
        self._draw_queue = None
        self._draw_thread = None

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.pixel_counter = maxdeque(maxlen=1000)
        self.server_ping_latency = maxdeque(maxlen=1000)
        self.server_load = None
        self.client_ping_latency = maxdeque(maxlen=1000)
        self._server_ok = True
        self.last_ping_echoed_time = 0
        self.server_info_request = False
        self.server_last_info = None
        self.info_request_pending = False
        self.screen_size_change_pending = False
        self.core_encodings = None
        self.encoding = None

        #sound:
        self.speaker_allowed = False
        self.speaker_enabled = False
        self.speaker_codecs = []
        self.microphone_allowed = False
        self.microphone_enabled = False
        self.microphone_codecs = []
        try:
            from xpra.sound.gstreamer_util import has_gst, get_sound_codecs
            self.speaker_allowed = has_gst
            if self.speaker_allowed:
                self.speaker_codecs = get_sound_codecs(True, False)
                self.speaker_allowed = len(self.speaker_codecs)>0
            self.microphone_allowed = has_gst
            self.microphone_enabled = False
            self.microphone_codecs = []
            if self.microphone_allowed:
                self.microphone_codecs = get_sound_codecs(False, False)
                self.microphone_allowed = len(self.microphone_codecs)>0
            if has_gst:
                soundlog("speaker_allowed=%s, speaker_codecs=%s", self.speaker_allowed, self.speaker_codecs)
                soundlog("microphone_allowed=%s, microphone_codecs=%s", self.microphone_allowed, self.microphone_codecs)
        except Exception, e:
            soundlog("sound support unavailable: %s", e)
            has_gst = False
        #sound state:
        self.sink_restart_pending = False
        self.on_sink_ready = None
        self.sound_sink = None
        self.server_sound_sequence = False
        self.min_sound_sequence = 0
        self.sound_source = None
        self.server_pulseaudio_id = None
        self.server_pulseaudio_server = None
        self.server_sound_decoders = []
        self.server_sound_encoders = []
        self.server_sound_receive = False
        self.server_sound_send = False

        #dbus:
        self.dbus_counter = AtomicInteger()
        self.dbus_pending_requests = {}

        #mmap:
        self.mmap_enabled = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_filename = None
        self.mmap_size = 0
        self.mmap_group = None

        #features:
        self.opengl_enabled = False
        self.opengl_props = {}
        self.toggle_cursors_bell_notify = False
        self.toggle_keyboard_sync = False
        self.force_ungrab = False
        self.window_unmap = False
        self.window_refresh_config = False
        self.server_generic_encodings = False
        self.server_encodings = []
        self.server_core_encodings = []
        self.server_encodings_with_speed = ()
        self.server_encodings_with_quality = ()
        self.server_encodings_with_lossless = ()
        self.change_quality = False
        self.change_min_quality = False
        self.change_speed = False
        self.readonly = False
        self.windows_enabled = True
        self.pings = False
        self.xsettings_enabled = False
        self.server_dbus_proxy = False

        self.client_supports_opengl = False
        self.client_supports_notifications = False
        self.client_supports_system_tray = False
        self.client_supports_clipboard = False
        self.client_supports_cursors = False
        self.client_supports_bell = False
        self.client_supports_sharing = False
        self.notifications_enabled = False
        self.clipboard_enabled = False
        self.cursors_enabled = False
        self.bell_enabled = False
        self.border = None

        self.supports_mmap = MMAP_SUPPORTED

        #helpers and associated flags:
        self.client_extras = None
        self.keyboard_helper = None
        self.kh_warning = False
        self.clipboard_helper = None
        self.menu_helper = None
        self.tray = None
        self.notifier = None

        #state:
        self._focused = None
        self._window_with_grab = None
        self._last_screen_settings = None
        self._suspended_at = 0

        self.init_packet_handlers()
        self.init_aliases()


    def init(self, opts):
        """ initialize variables from configuration """
        self.encoding = opts.encoding
        self.title = opts.title
        self.session_name = opts.session_name
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.dpi = int(opts.dpi)
        self.xsettings_enabled = opts.xsettings
        self.supports_mmap = MMAP_SUPPORTED and opts.mmap
        self.mmap_group = opts.mmap_group

        try:
            from xpra.sound.gstreamer_util import has_gst, get_sound_codecs
        except:
            has_gst = False
        self.speaker_allowed = bool(opts.speaker) and has_gst
        self.microphone_allowed = bool(opts.microphone) and has_gst
        self.speaker_codecs = opts.speaker_codec
        if len(self.speaker_codecs)==0 and self.speaker_allowed:
            self.speaker_codecs = get_sound_codecs(True, False)
            self.speaker_allowed = len(self.speaker_codecs)>0
        self.microphone_codecs = opts.microphone_codec
        if len(self.microphone_codecs)==0 and self.microphone_allowed:
            self.microphone_codecs = get_sound_codecs(False, False)
            self.microphone_allowed = len(self.microphone_codecs)>0

        self.readonly = opts.readonly
        self.windows_enabled = opts.windows
        self.pings = opts.pings

        self.client_supports_notifications = opts.notifications
        self.client_supports_system_tray = opts.system_tray and SYSTEM_TRAY_SUPPORTED
        self.client_supports_clipboard = opts.clipboard
        self.client_supports_cursors = opts.cursors
        self.client_supports_bell = opts.bell
        self.client_supports_sharing = opts.sharing

        #until we add the ability to choose decoders, use all of them:
        #(and default to non grahics card csc modules if not specified)
        vh = getVideoHelper()
        vh.set_modules(video_decoders=ALL_VIDEO_DECODER_OPTIONS, csc_modules=opts.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()


    def init_ui(self, opts):
        """ initialize user interface """
        self.init_opengl(opts.opengl)

        if not self.readonly:
            self.keyboard_helper = self.make_keyboard_helper(opts.keyboard_sync, opts.key_shortcut)

        tray_icon_filename = opts.tray_icon
        if opts.tray:
            self.menu_helper = self.make_tray_menu_helper()
            self.tray = self.setup_xpra_tray(opts.tray_icon)
            if self.tray:
                tray_icon_filename = self.tray.get_tray_icon_filename(tray_icon_filename)
                if opts.delay_tray:
                    self.tray.hide()
                    def show_tray(*args):
                        traylog("first ui received, showing tray %s", self.tray)
                        self.tray.show()
                    self.connect("first-ui-received", show_tray)
                else:
                    self.tray.show()

        if self.client_supports_notifications:
            self.notifier = self.make_notifier()
            traylog("using notifier=%s", self.notifier)
            self.client_supports_notifications = self.notifier is not None

        #audio tagging:
        if tray_icon_filename and os.path.exists(tray_icon_filename):
            try:
                from xpra.sound.pulseaudio_util import add_audio_tagging_env
                add_audio_tagging_env(tray_icon_filename)
            except ImportError, e:
                log("failed to set pulseaudio audio tagging: %s", e)

        if ClientExtras is not None:
            self.client_extras = ClientExtras(self)

        if opts.border:
            self.parse_border(opts.border)

        #draw thread:
        self._draw_queue = Queue()
        self._draw_thread = make_daemon_thread(self._draw_thread_loop, "draw")

    def setup_connection(self, conn):
        XpraClientBase.setup_connection(self, conn)
        if self.supports_mmap:
            self.init_mmap(self.mmap_group, conn.filename)


    def parse_border(self, border_str):
        #not implemented here (see gtk2 client)
        pass


    def run(self):
        XpraClientBase.run(self)    #start network threads
        self._draw_thread.start()
        self.send_hello()


    def quit(self, exit_code=0):
        raise Exception("override me!")

    def cleanup(self):
        log("UIXpraClient.cleanup()")
        XpraClientBase.cleanup(self)
        for x in (self.keyboard_helper, self.clipboard_helper, self.tray, self.notifier, self.menu_helper, self.client_extras, getVideoHelper()):
            if x is None:
                continue
            log("UIXpraClient.cleanup() calling %s.cleanup()", type(x))
            try:
                x.cleanup()
            except:
                log.error("error on %s cleanup", type(x), exc_info=True)
        #the protocol has been closed, it is now safe to close all the windows:
        #(cleaner and needed when we run embedded in the client launcher)
        self.destroy_all_windows()
        self.clean_mmap()
        if self.sound_source:
            self.stop_sending_sound()
        if self.sound_sink:
            self.stop_receiving_sound()
        time.sleep(0.2)
        log("UIXpraClient.cleanup() done")

    def destroy_all_windows(self):
        for wid, window in self._id_to_window.items():
            try:
                windowlog("destroy_all_windows() destroying %s / %s", wid, window)
                self.destroy_window(wid, window)
            except:
                pass
        self._id_to_window = {}
        self._window_to_id = {}


    def suspend(self):
        log.info("system is suspending")
        self._suspended_at = time.time()
        #tell the server to slow down refresh for all the windows:
        self.control_refresh(-1, True, False)

    def resume(self):
        elapsed = 0
        if self._suspended_at>0:
            elapsed = time.time()-self._suspended_at
            self._suspended_at = 0
        delta = datetime.timedelta(seconds=int(elapsed))
        log.info("system resumed, was suspended for %s", delta)
        #this will reset the refresh rate too:
        self.send_refresh_all()


    def control_refresh(self, wid, suspend_resume, refresh, quality=100, options={}, client_properties={}):
        packet = ["buffer-refresh", wid, 0, quality]
        if self.window_refresh_config:
            options["refresh-now"] = bool(refresh)
            if suspend_resume is True:
                options["batch"] = {"reset"     : True,
                                    "delay"     : 1000,
                                    "locked"    : True,
                                    "always"    : True}
            elif suspend_resume is False:
                options["batch"] = {"reset"     : True}
            else:
                pass    #batch unchanged
            log("sending buffer refresh: options=%s, client_properties=%s", options, client_properties)
            packet.append(options)
            packet.append(client_properties)
        elif not refresh:
            #we don't really want a refresh, we want to use the "window_refresh_config" feature
            #but since the server doesn't support it, we can't do anything
            return
        self.send(*packet)

    def send_refresh(self, wid):
        packet = ["buffer-refresh", wid, 0, 100]
        if self.window_refresh_config:
            #explicit refresh (should be assumed True anyway),
            #also force a reset of batch configs:
            packet.append({
                           "refresh-now"    : True,
                           "batch"          : {"reset" : True}
                           })
            packet.append({})   #no client_properties
        self.send(*packet)

    def send_refresh_all(self):
        log("Automatic refresh for all windows ")
        self.send_refresh(-1)


    def show_session_info(self, *args):
        log.warn("show_session_info() is not implemented in %s", self)


    def get_encodings(self):
        """
            Unlike get_core_encodings(), this method returns "rgb" for both "rgb24" and "rgb32".
            That's because although we may support both, the encoding chosen is plain "rgb",
            and the actual encoding used ("rgb24" or "rgb32") depends on the window's bit depth.
            ("rgb32" if there is an alpha channel, and if the client supports it)
        """
        cenc = self.get_core_encodings()
        if ("rgb24" in cenc or "rgb32" in cenc) and "rgb" not in cenc:
            cenc.append("rgb")
        return [x for x in PREFERED_ENCODING_ORDER if x in cenc and x not in ("rgb32", "rgb24")]

    def get_core_encodings(self):
        if self.core_encodings is None:
            self.core_encodings = self.do_get_core_encodings()
        return self.core_encodings

    def do_get_core_encodings(self):
        """
            This method returns the actual encodings supported.
            ie: ["rgb24", "vp8", "webp", "png", "png/L", "png/P", "jpeg", "h264", "vpx"]
            It is often overriden in the actual client class implementations,
            where extra encodings can be added (generally just 'rgb32' for transparency),
            or removed if the toolkit implementation class is more limited.
        """
        #we always support rgb24:
        core_encodings = ["rgb24"]
        #PIL:
        core_encodings += get_PIL_decodings(get_codec("PIL"))
        if has_codec("dec_webm") and "webp" not in core_encodings:
            core_encodings.append("webp")
        #we enable all the video decoders we know about,
        #what will actually get used by the server will still depend on the csc modes supported
        video_decodings = getVideoHelper().get_decodings()
        log("video_decodings=%s", video_decodings)
        for encoding in video_decodings:
            if encoding not in core_encodings:
                core_encodings.append(encoding)
        #remove duplicates and use prefered encoding order:
        core_encodings = [x for x in PREFERED_ENCODING_ORDER if x in set(core_encodings)]
        log("do_get_core_encodings()=%s", core_encodings)
        return core_encodings


    def get_supported_window_layouts(self):
        return  []

    def make_keyboard_helper(self, keyboard_sync, key_shortcuts):
        return KeyboardHelper(self.send, keyboard_sync, key_shortcuts)

    def make_clipboard_helper(self):
        raise Exception("override me!")


    def make_notifier(self):
        nc = self.get_notifier_classes()
        traylog("make_notifier() notifier classes: %s", nc)
        return self.make_instance(nc)

    def get_notifier_classes(self):
        #subclasses will generally add their toolkit specific variants
        #by overriding this method
        #use the native ones first:
        return get_native_notifier_classes()


    def make_system_tray(self, *args):
        """ tray used for application systray forwarding """
        tc = self.get_system_tray_classes()
        traylog("make_system_tray%s system tray classes=%s", args, tc)
        return self.make_instance(tc, *args)

    def get_system_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_system_tray_classes()


    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.get_tray_classes()
        traylog("make_tray%s tray classes=%s", args, tc)
        return self.make_instance(tc, *args)

    def get_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_tray_classes()


    def make_tray_menu_helper(self):
        """ menu helper class used by our tray (make_tray / setup_xpra_tray) """
        mhc = self.get_tray_menu_helper_classes()
        traylog("make_tray_menu_helper() tray menu helper classes: %s", mhc)
        return self.make_instance(mhc, self)

    def get_tray_menu_helper_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_tray_menu_helper_classes()


    def make_instance(self, class_options, *args):
        log("make_instance%s", [class_options]+list(args))
        for c in class_options:
            try:
                v = c(*args)
                log("make_instance(..) %s()=%s", c, v)
                if v:
                    return v
            except:
                log.error("make_instance%s failed to instantiate %s", class_options+list(args), c, exc_info=True)
        return None


    def setup_xpra_tray(self, tray_icon_filename):
        tray = None
        #this is our own tray
        def xpra_tray_click(button, pressed, time=0):
            traylog("xpra_tray_click(%s, %s)", button, pressed)
            if button==1 and pressed:
                self.menu_helper.activate()
            elif button==3 and not pressed:
                self.menu_helper.popup(button, time)
        def xpra_tray_mouseover(*args):
            traylog("xpra_tray_mouseover(%s)", args)
        def xpra_tray_exit(*args):
            traylog("xpra_tray_exit(%s)", args)
            self.quit(0)
        def xpra_tray_geometry(*args):
            traylog("xpra_tray_geometry%s geometry=%s", args, tray.get_geometry())
        menu = None
        if self.menu_helper:
            menu = self.menu_helper.build()
        tray = self.make_tray(menu, self.get_tray_title(), tray_icon_filename, xpra_tray_geometry, xpra_tray_click, xpra_tray_mouseover, xpra_tray_exit)
        traylog("setup_xpra_tray(%s)=%s", tray_icon_filename, tray)
        return tray

    def get_tray_title(self):
        t = []
        if self.session_name:
            t.append(self.session_name)
        if self._protocol and self._protocol._conn:
            t.append(self._protocol._conn.target)
        if len(t)==0:
            t.insert(0, "Xpra")
        v = "\n".join(t)
        traylog("get_tray_title()=%s", nonl(v))
        return v

    def setup_system_tray(self, client, wid, w, h, title):
        tray_widget = None
        #this is a tray forwarded for a remote application
        def tray_click(button, pressed, time=0):
            tray = self._id_to_window.get(wid)
            traylog("tray_click(%s, %s, %s) tray=%s", button, pressed, time, tray)
            if tray:
                x, y = self.get_mouse_position()
                modifiers = self.get_current_modifiers()
                self.send_positional(["button-action", wid, button, pressed, (x, y), modifiers])
                tray.reconfigure()
        def tray_mouseover(x, y):
            tray = self._id_to_window.get(wid)
            traylog("tray_mouseover(%s, %s) tray=%s", x, y, tray)
            if tray:
                pointer = x, y
                modifiers = self.get_current_modifiers()
                buttons = []
                self.send_mouse_position(["pointer-position", wid, pointer, modifiers, buttons])
        def tray_geometry(*args):
            #tell the "ClientTray" where it now lives
            #which should also update the location on the server if it has changed
            tray = self._id_to_window.get(wid)
            geom = tray_widget.get_geometry()
            traylog("tray_geometry(%s) geometry=%s tray=%s", args, geom, tray)
            if tray and geom:
                tray.move_resize(*geom)
        def tray_exit(*args):
            traylog("tray_exit(%s)", args)
        tray_widget = self.make_system_tray(None, title, None, tray_geometry, tray_click, tray_mouseover, tray_exit)
        traylog("setup_system_tray%s tray_widget=%s", (client, wid, w, h, title), tray_widget)
        assert tray_widget, "could not instantiate a system tray for tray id %s" % wid
        tray_widget.show()
        return ClientTray(client, wid, w, h, tray_widget, self.mmap_enabled, self.mmap)

    def workspace_changed(self, *args):
        workspacelog("workspace_changed%s", args)
        for win in self._id_to_window.values():
            win.workspace_changed()

    def screen_size_changed(self, *args):
        log("screen_size_changed(%s) pending=%s", args, self.screen_size_change_pending)
        if self.screen_size_change_pending:
            return
        def update_screen_size():
            self.screen_size_change_pending = False
            root_w, root_h = self.get_root_size()
            ss = self.get_screen_sizes()
            log("update_screen_size() sizes=%s", ss)
            screen_settings = (root_w, root_h, ss)
            if self._last_screen_settings==screen_settings:
                log("screen size unchanged")
                return
            log.info("sending updated screen size to server: %sx%s with %s screens", root_w, root_h, len(ss))
            log_screen_sizes(root_w, root_h, ss)
            self.send("desktop_size", *screen_settings)
            self.last_screen_settings = screen_settings
            #update the max packet size (may have gone up):
            self.set_max_packet_size()
        #update via timer so the data is more likely to be final (up to date) when we query it,
        #some properties (like _NET_WORKAREA for X11 clients via xposix "ClientExtras") may
        #trigger multiple calls to screen_size_changed, delayed by some amount
        #(sometimes up to 1s..)
        self.screen_size_change_pending = True
        delay = 1000
        #if we are suspending, wait longer:
        #(better chance that the suspend-resume cycle will have completed)
        if self._suspended_at>0 and self._suspended_at-time.time()<5*1000:
            delay = 5*1000
        self.timeout_add(delay, update_screen_size)

    def get_screen_sizes(self):
        raise Exception("override me!")

    def get_root_size(self):
        raise Exception("override me!")

    def set_windows_cursor(self, client_windows, new_cursor):
        raise Exception("override me!")

    def get_mouse_position(self):
        raise Exception("override me!")

    def get_current_modifiers(self):
        raise Exception("override me!")

    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        raise Exception("override me!")


    def init_mmap(self, mmap_group, socket_filename):
        log("init_mmap(%s, %s)", mmap_group, socket_filename)
        from xpra.os_util import get_int_uuid
        from xpra.net.mmap_pipe import init_client_mmap
        self.mmap_token = get_int_uuid()
        self.mmap_enabled, self.mmap, self.mmap_size, self.mmap_tempfile, self.mmap_filename = \
            init_client_mmap(self.mmap_token, mmap_group, socket_filename)

    def clean_mmap(self):
        log("XpraClient.clean_mmap() mmap_filename=%s", self.mmap_filename)
        if self.mmap_filename and os.path.exists(self.mmap_filename):
            os.unlink(self.mmap_filename)
            self.mmap_filename = None


    def init_opengl(self, enable_opengl):
        self.opengl_enabled = False
        self.client_supports_opengl = False
        self.opengl_props = {"info" : "not supported"}


    def send_layout(self):
        keylog("send_layout()")
        self.send("layout-changed", nn(self.keyboard_helper.xkbmap_layout), nn(self.keyboard_helper.xkbmap_variant))

    def send_keymap(self):
        keylog("send_keymap()")
        self.send("keymap-changed", self.get_keymap_properties())

    def get_keymap_properties(self):
        props = self.keyboard_helper.get_keymap_properties()
        props["modifiers"] = self.get_current_modifiers()
        return  props

    def handle_key_action(self, window, key_event):
        if self.readonly or self.keyboard_helper is None:
            return
        wid = self._window_to_id[window]
        keylog("handle_key_action(%s, %s) wid=%s", window, key_event, wid)
        self.keyboard_helper.handle_key_action(window, wid, key_event)

    def mask_to_names(self, mask):
        if self.keyboard_helper is None:
            return []
        return self.keyboard_helper.mask_to_names(mask)


    def set_default_window_icon(self, window_icon):
        if not window_icon:
            window_icon = self.get_icon_filename("xpra.png")
        if window_icon and os.path.exists(window_icon):
            try:
                self.do_set_window_icon(window_icon)
            except Exception, e:
                windowlog.error("failed to set window icon %s: %s", window_icon, e)


    def send_focus(self, wid):
        focuslog("send_focus(%s)", wid)
        self.send("focus", wid, self.get_current_modifiers())

    def update_focus(self, wid, gotit):
        focuslog("update_focus(%s, %s) focused=%s, grabbed=%s", wid, gotit, self._focused, self._window_with_grab)
        if gotit and self._focused is not wid:
            if self.keyboard_helper:
                self.keyboard_helper.clear_repeat()
            self.send_focus(wid)
            self._focused = wid
        if not gotit:
            if self._window_with_grab:
                self.window_ungrab()
                self.do_force_ungrab(self._window_with_grab)
                self._window_with_grab = None
            if self._focused!=wid:
                #if this window lost focus, it must have had it!
                #(catch up - makes things like OR windows work:
                # their parent receives the focus-out event)
                focuslog("window %s lost a focus it did not have!? (simulating focus before losing it)", wid)
                self.send_focus(wid)
            if self.keyboard_helper:
                self.keyboard_helper.clear_repeat()
            self.send_focus(0)
            self._focused = None

    def do_force_ungrab(self, wid):
        grablog("do_force_ungrab(%s) server supports force ungrab: %s", wid, self.force_ungrab)
        if self.force_ungrab:
            #ungrab via dedicated server packet:
            self.send_force_ungrab(wid)
            return
        #fallback for older servers: try to find a key to press:
        kh = self.keyboard_helper
        if not kh:
            if not self.kh_warning:
                self.kh_warning = True
                grablog.warn("no keyboard support, cannot simulate keypress to lose grab!")
            return
        #xkbmap_keycodes is a list of: (keyval, name, keycode, group, level)
        ungrab_keys = [x for x in kh.xkbmap_keycodes if x[1]==UNGRAB_KEY]
        if len(ungrab_keys)==0:
            if not self.kh_warning:
                self.kh_warning = True
                grablog.warn("ungrab key %s not found, cannot simulate keypress to lose grab!", UNGRAB_KEY)
            return
        #ungrab_keys.append((65307, "Escape", 27, 0, 0))     #ugly hardcoded default value
        ungrab_key = ungrab_keys[0]
        grablog("lost focus whilst window %s has grab, simulating keypress: %s", wid, ungrab_key)
        key_event = AdHocStruct()
        key_event.keyname = ungrab_key[1]
        key_event.pressed = True
        key_event.modifiers = []
        key_event.keyval = ungrab_key[0]
        keycode = ungrab_key[2]
        try:
            key_event.string = chr(keycode)
        except:
            key_event.string = str(keycode)
        key_event.keycode = keycode
        key_event.group = 0
        #press:
        kh.send_key_action(wid, key_event)
        #unpress:
        key_event.pressed = False
        kh.send_key_action(wid, key_event)

    def _process_pointer_grab(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        grablog("grabbing %s: %s", wid, window)
        if window:
            self.window_grab(window)
            self._window_with_grab = wid

    def window_grab(self, window):
        #subclasses should implement this method
        pass

    def _process_pointer_ungrab(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        grablog("ungrabbing %s: %s", wid, window)
        self.window_ungrab()
        self._window_with_grab = None

    def window_ungrab(self):
        #subclasses should implement this method
        pass


    def make_hello(self):
        capabilities = XpraClientBase.make_hello(self)
        if self.readonly:
            #don't bother sending keyboard info, as it won't be used
            capabilities["keyboard"] = False
        else:
            for k,v in self.get_keymap_properties().items():
                capabilities[k] = v
            capabilities["xkbmap_layout"] = nn(self.keyboard_helper.xkbmap_layout)
            capabilities["xkbmap_variant"] = nn(self.keyboard_helper.xkbmap_variant)
            #show the user a summary of what we have detected:
            kb_info = {}
            xkbq = capabilities.get("xkbmap_query")
            if xkbq:
                from xpra.keyboard.layouts import parse_xkbmap_query
                d = parse_xkbmap_query(xkbq)
                for x in ["rules", "model", "layout"]:
                    v = d.get(x)
                    if v:
                        kb_info[x] = v
            if self.keyboard_helper.xkbmap_layout:
                kb_info["layout"] = self.keyboard_helper.xkbmap_layout
            if len(kb_info)==0:
                log.info("using default keyboard settings")
            else:
                log.info("detected keyboard: %s", ", ".join(["%s=%s" % (std(k), std(v)) for k,v in kb_info.items()]))

        capabilities["modifiers"] = self.get_current_modifiers()
        root_w, root_h = self.get_root_size()
        capabilities["desktop_size"] = [root_w, root_h]
        ss = self.get_screen_sizes()
        log.info("desktop size is %sx%s with %s screen(s):", root_w, root_h, len(ss))
        log_screen_sizes(root_w, root_h, ss)
        capabilities["screen_sizes"] = ss
        self._last_screen_settings = (root_w, root_h, ss)
        if self.keyboard_helper:
            key_repeat = self.keyboard_helper.keyboard.get_keyboard_repeat()
            if key_repeat:
                delay_ms,interval_ms = key_repeat
                capabilities["key_repeat"] = (delay_ms,interval_ms)
            else:
                #cannot do keyboard_sync without a key repeat value!
                #(maybe we could just choose one?)
                self.keyboard_helper.keyboard_sync = False
            capabilities["keyboard_sync"] = self.keyboard_helper.keyboard_sync
            log("keyboard capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("key")])
        if self.mmap_enabled:
            capabilities["mmap_file"] = self.mmap_filename
            capabilities["mmap_token"] = self.mmap_token
        #don't try to find the server uuid if this platform cannot run servers..
        #(doing so causes lockups on win32 and startup errors on osx)
        if MMAP_SUPPORTED:
            #we may be running inside another server!
            try:
                from xpra.server.server_uuid import get_uuid
                capabilities["server_uuid"] = get_uuid() or ""
            except:
                pass
        capabilities.update({
            "randr_notify"              : True,
            "compressible_cursors"      : True,
            "dpi"                       : self.dpi,
            "clipboard"                 : self.client_supports_clipboard,
            "clipboard.notifications"   : self.client_supports_clipboard,
            "clipboard.selections"      : CLIPBOARDS,
            #buggy osx clipboards:
            "clipboard.want_targets"    : CLIPBOARD_WANT_TARGETS,
            #buggy osx and win32 clipboards:
            "clipboard.greedy"          : CLIPBOARD_GREEDY,
            "clipboard.set_enabled"     : True,
            "notifications"             : self.client_supports_notifications,
            "cursors"                   : self.client_supports_cursors,
            "bell"                      : self.client_supports_bell,
            "sound.server_driven"       : True,
            "encoding.client_options"   : True,
            "encoding_client_options"   : True,
            "encoding.csc_atoms"        : True,
            #TODO: check for csc support (swscale only?)
            "encoding.video_subregion"  : True,
            "encoding.video_reinit"     : True,
            "encoding.video_scaling"    : True,
            #separate plane is only supported by avcodec2:
            "encoding.video_separateplane"  : get_codec("dec_avcodec") is None and get_codec("dec_avcodec2") is not None,
            "encoding.rgb_lz4"          : use_lz4 and self.compression_level==1,
            "encoding.webp_leaks"       : False,
            "encoding.transparency"     : self.has_transparency(),
            "rgb24zlib"                 : True,
            "encoding.rgb24zlib"        : True,
            "named_cursors"             : False,
            "share"                     : self.client_supports_sharing,
            "auto_refresh_delay"        : int(self.auto_refresh_delay*1000),
            "windows"                   : self.windows_enabled,
            "window.raise"              : True,
            "raw_window_icons"          : True,
            "system_tray"               : self.client_supports_system_tray,
            "xsettings-tuple"           : True,
            "generic_window_types"      : True,
            "server-window-move-resize" : True,
            "server-window-resize"      : True,
            "window.resize-counter"     : True,
            "notify-startup-complete"   : True,
            "generic-rgb-encodings"     : True,
            "encodings"                 : self.get_encodings(),
            "encodings.core"            : self.get_core_encodings(),
            })
        control_commands = ["show_session_info", "enable_bencode", "enable_zlib"]
        from xpra.net.protocol import use_bencode, use_rencode
        if use_lz4:
            control_commands.append("enable_lz4")
        if use_bencode:
            control_commands.append("enable_bencode")
        if use_rencode:
            control_commands.append("enable_rencode")
        capabilities["control_commands"] = control_commands
        for k,v in codec_versions.items():
            capabilities["encoding.%s.version" % k] = v
        if self.encoding:
            capabilities["encoding"] = self.encoding
        if self.quality>0:
            capabilities.update({
                         "jpeg"             : self.quality,
                         "quality"          : self.quality,
                         "encoding.quality" : self.quality
                         })
        if self.min_quality>0:
            capabilities["encoding.min-quality"] = self.min_quality
        if self.speed>=0:
            capabilities["speed"] = self.speed
            capabilities["encoding.speed"] = self.speed
        if self.min_speed>=0:
            capabilities["encoding.min-speed"] = self.min_speed

        #figure out the CSC modes supported:
        #these are the RGB modes we want (the ones we can paint with):
        rgb_formats = ["RGB", "RGBX"]
        if not sys.platform.startswith("win") and not sys.platform.startswith("darwin"):
            #only win32 and osx cannot handle transparency
            rgb_formats.append("RGBA")
        capabilities["encodings.rgb_formats"] = rgb_formats

        #figure out which CSC modes (usually YUV) can give us those RGB modes:
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*rgb_formats)
        log("supported full csc_modes=%s", full_csc_modes)
        capabilities["encoding.full_csc_modes"] = full_csc_modes
        #for older servers (remove per-encoding and hope for the best..):
        csc_modes = []
        for modes in full_csc_modes.values():
            csc_modes += modes
        capabilities["encoding.csc_modes"] = list(set(csc_modes))

        log("encoding capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("encoding")])
        capabilities["encoding.uses_swscale"] = True
        if "h264" in self.get_core_encodings():
            # some profile options: "baseline", "main", "high", "high10", ...
            # set the default to "high10" for I420/YUV420P
            # as the python client always supports all the profiles
            # whereas on the server side, the default is baseline to accomodate less capable clients.
            # I422/YUV422P requires high422, and
            # I444/YUV444P requires high444,
            # so we don't bother specifying anything for those two.
            for old_csc_name, csc_name, default_profile in (
                        ("I420", "YUV420P", "high10"),
                        ("I422", "YUV422P", ""),
                        ("I444", "YUV444P", "")):
                profile = default_profile
                #try with the old prefix (X264) as well as the more correct one (H264):
                for H264_NAME in ("X264", "H264"):
                    profile = os.environ.get("XPRA_%s_%s_PROFILE" % (H264_NAME, old_csc_name), profile)
                    profile = os.environ.get("XPRA_%s_%s_PROFILE" % (H264_NAME, csc_name), profile)
                if profile:
                    #send as both old and new names:
                    for h264_name in ("x264", "h264"):
                        capabilities["encoding.%s.%s.profile" % (h264_name, old_csc_name)] = profile
                        capabilities["encoding.%s.%s.profile" % (h264_name, csc_name)] = profile
            log("x264 encoding options: %s", str([(k,v) for k,v in capabilities.items() if k.startswith("encoding.x264.")]))
        iq = max(self.min_quality, self.quality)
        if iq<0:
            iq = 70
        capabilities["encoding.initial_quality"] = iq
        try:
            from xpra.sound.gstreamer_util import has_gst, add_gst_capabilities
        except:
            has_gst = False
        if has_gst:
            try:
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                add_gst_capabilities(capabilities, receive=self.speaker_allowed, send=self.microphone_allowed,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs, new_namespace=True)
                soundlog("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e, exc_info=True)
                self.speaker_allowed = False
                self.microphone_allowed = False
        #batch options:
        for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
            evalue = os.environ.get("XPRA_BATCH_%s" % bprop.upper())
            if evalue:
                try:
                    capabilities["batch.%s" % bprop] = int(evalue)
                except:
                    log.error("invalid environment value for %s: %s", bprop, evalue)
        log("batch props=%s", [("%s=%s" % (k,v)) for k,v in capabilities.items() if k.startswith("batch.")])
        return capabilities

    def has_transparency(self):
        return False


    def server_ok(self):
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
        last = self._server_ok
        self._server_ok = not FAKE_BROKEN_CONNECTION and self.last_ping_echoed_time>=ping_sent_time
        if last!=self._server_ok and not self._server_ok:
            log.info("server is not responding, drawing spinners over the windows")
            def timer_redraw():
                if self._protocol is None:
                    #no longer connected!
                    return False
                self.redraw_spinners()
                if self.server_ok():
                    log.info("server is OK again")
                    return False
                return True
            self.redraw_spinners()
            self.timeout_add(100, timer_redraw)
        return False

    def redraw_spinners(self):
        #draws spinner on top of the window, or not (plain repaint)
        #depending on whether the server is ok or not
        for w in self._id_to_window.values():
            if not w.is_tray():
                w.spinner(self.server_ok())

    def check_echo_timeout(self, ping_time):
        log("check_echo_timeout(%s) last_ping_echoed_time=%s", ping_time, self.last_ping_echoed_time)
        if self.last_ping_echoed_time<ping_time:
            self.warn_and_quit(EXIT_TIMEOUT, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self):
        now_ms = int(1000.0*time.time())
        self.send("ping", now_ms)
        self.timeout_add(PING_TIMEOUT*1000, self.check_echo_timeout, now_ms)
        wait = 2.0
        if len(self.server_ping_latency)>0:
            l = [x for _,x in list(self.server_ping_latency)]
            avg = sum(l) / len(l)
            wait = min(5, 1.0+avg*2.0)
            log("average server latency=%.1f, using max wait %.2fs", 1000.0*avg, wait)
        self.timeout_add(int(1000.0*wait), self.check_server_echo, now_ms)
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = time.time()-echoedtime/1000.0
        self.server_ping_latency.append((time.time(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((time.time(), cl/1000.0))
        log("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        l1,l2,l3 = 0,0,0
        if os.name=="posix":
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            except (OSError, AttributeError):
                pass
        sl = -1
        if len(self.server_ping_latency)>0:
            _, sl = self.server_ping_latency[-1]
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl))


    def _process_info_response(self, packet):
        self.info_request_pending = False
        self.server_last_info = packet[1]
        log("info-response: %s", packet)

    def send_info_request(self):
        assert self.server_info_request
        if not self.info_request_pending:
            self.info_request_pending = True
            self.send("info-request", [self.uuid], self._id_to_window.keys())


    def send_quality(self):
        q = self.quality
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        if self.change_quality:
            self.send("quality", q)

    def send_min_quality(self):
        q = self.min_quality
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        if self.change_min_quality:
            #v0.8 onwards: set min
            self.send("min-quality", q)

    def send_speed(self):
        assert self.change_speed
        s = self.speed
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("speed", s)

    def send_min_speed(self):
        assert self.change_speed
        s = self.min_speed
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("min-speed", s)


    def parse_server_capabilities(self, c):
        if not XpraClientBase.parse_server_capabilities(self, c):
            return
        if not self.session_name:
            self.session_name = c.strget("session_name", "")
        set_application_name(self.session_name or "Xpra")
        self.window_unmap = c.boolget("window_unmap")
        self.force_ungrab = c.boolget("force_ungrab")
        self.window_refresh_config = c.boolget("window_refresh_config")
        self.suspend_resume = c.boolget("suspend-resume")
        self.server_supports_notifications = c.boolget("notifications")
        self.notifications_enabled = self.server_supports_notifications and self.client_supports_notifications
        self.server_supports_cursors = c.boolget("cursors", True)    #added in 0.5, default to True!
        self.cursors_enabled = self.server_supports_cursors and self.client_supports_cursors
        self.server_supports_bell = c.boolget("bell")          #added in 0.5, default to True!
        self.bell_enabled = self.server_supports_bell and self.client_supports_bell
        self.server_supports_clipboard = c.boolget("clipboard")
        self.server_clipboards = c.listget("clipboards", ALL_CLIPBOARDS)
        self.clipboard_enabled = self.client_supports_clipboard and self.server_supports_clipboard
        self.server_dbus_proxy = c.boolget("dbus_proxy")
        self.mmap_enabled = self.supports_mmap and self.mmap_enabled and c.boolget("mmap_enabled")
        if self.mmap_enabled:
            mmap_token = c.intget("mmap_token")
            if mmap_token:
                from xpra.net.mmap_pipe import read_mmap_token
                token = read_mmap_token(self.mmap)
                if token!=mmap_token:
                    log.warn("mmap token verification failed!")
                    log.warn("expected '%s', found '%s'", mmap_token, token)
                    self.mmap_enabled = False
                    self.quit(EXIT_MMAP_TOKEN_FAILURE)
                    return
        server_auto_refresh_delay = c.intget("auto_refresh_delay", 0)/1000.0
        if server_auto_refresh_delay==0 and self.auto_refresh_delay>0:
            log.warn("server does not support auto-refresh!")
        def getenclist(k, default_value=[]):
            #deals with old servers and substitute old encoding names for the new ones
            v = c.strlistget(k, default_value)
            if not v:
                return v
            return [OLD_ENCODING_NAMES_TO_NEW.get(x, x) for x in v]
        self.server_generic_encodings = c.boolget("encoding.generic")
        self.server_encodings = getenclist("encodings")
        self.server_core_encodings = getenclist("encodings.core", self.server_encodings)
        self.server_encodings_with_speed = getenclist("encodings.with_speed", ("h264",)) #old servers only supported x264
        self.server_encodings_with_quality = getenclist("encodings.with_quality", ("jpeg", "webp", "h264"))
        self.server_encodings_with_lossless_mode = getenclist("encodings.with_lossless_mode", ())
        self.change_quality = c.boolget("change-quality")
        self.change_min_quality = c.boolget("change-min-quality")
        self.change_speed = c.boolget("change-speed")
        self.change_min_speed = c.boolget("change-min-speed")
        self.xsettings_tuple = c.boolget("xsettings-tuple")
        if self.mmap_enabled:
            log.info("mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), self.mmap_filename)
        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()
        self.server_start_time = c.intget("start_time", -1)
        self.server_platform = c.strget("platform")
        self.toggle_cursors_bell_notify = c.boolget("toggle_cursors_bell_notify")
        self.toggle_keyboard_sync = c.boolget("toggle_keyboard_sync")

        self.server_display = c.strget("display")
        self.server_max_desktop_size = c.intpair("max_desktop_size")
        self.server_actual_desktop_size = c.intpair("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.server_randr = c.boolget("resize_screen")
        log("server has randr: %s", self.server_randr)
        self.server_sound_sequence = c.boolget("sound_sequence")
        self.server_info_request = c.boolget("info-request")
        e = c.strget("encoding")
        if e:
            if self.encoding and e!=self.encoding:
                if self.encoding not in self.server_core_encodings:
                    log.warn("server does not support %s encoding and has switched to %s", self.encoding, e)
                else:
                    log.info("server is using %s encoding instead of %s", e, self.encoding)
            self.encoding = e
        i = " ".join(os_info(self._remote_platform, self._remote_platform_release, self._remote_platform_platform, self._remote_platform_linux_distribution))
        r = self._remote_version
        if self._remote_revision:
            r += " (r%s)" % self._remote_revision
        log.info("server: %s, Xpra version %s", i, r)
        if c.boolget("proxy"):
            proxy_hostname = c.strget("proxy.hostname")
            proxy_platform = c.strget("proxy.platform")
            proxy_release = c.strget("proxy.platform.release")
            proxy_version = c.strget("proxy.version")
            msg = "via: %s proxy version %s" % (platform_name(proxy_platform, proxy_release), std(proxy_version))
            if proxy_hostname:
                msg += " on '%s'" % std(proxy_hostname)
            log.info(msg)
        #process the rest from the UI thread:
        self.idle_add(self.process_ui_capabilities, c)

    def process_ui_capabilities(self, c):
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        if self.clipboard_enabled:
            self.clipboard_helper = self.make_clipboard_helper()
            self.clipboard_enabled = self.clipboard_helper is not None
        self.set_max_packet_size()
        self.send_deflate_level()
        server_desktop_size = c.listget("desktop_size")
        log("server desktop size=%s", server_desktop_size)
        if not c.boolget("shadow"):
            assert server_desktop_size
            avail_w, avail_h = server_desktop_size
            root_w, root_h = self.get_root_size()
            if avail_w<root_w or avail_h<root_h:
                log.warn("Server's virtual screen is too small -- "
                         "(server: %sx%s vs. client: %sx%s)\n"
                         "You may see strange behavior.\n"
                         "Please see "
                         "https://www.xpra.org/trac/ticket/10"
                         % (avail_w, avail_h, root_w, root_h))
        if self.keyboard_helper:
            modifier_keycodes = c.dictget("modifier_keycodes")
            if modifier_keycodes:
                self.keyboard_helper.set_modifier_mappings(modifier_keycodes)

        #sound:
        self.server_pulseaudio_id = c.strget("sound.pulseaudio.id")
        self.server_pulseaudio_server = c.strget("sound.pulseaudio.server")
        self.server_sound_decoders = c.strlistget("sound.decoders", [])
        self.server_sound_encoders = c.strlistget("sound.encoders", [])
        self.server_sound_receive = c.boolget("sound.receive")
        self.server_sound_send = c.boolget("sound.send")
        soundlog("pulseaudio id=%s, server=%s, sound decoders=%s, sound encoders=%s, receive=%s, send=%s",
                 self.server_pulseaudio_id, self.server_pulseaudio_server, self.server_sound_decoders,
                 self.server_sound_encoders, self.server_sound_receive, self.server_sound_send)
        if self.server_sound_send and self.speaker_allowed:
            self.start_receiving_sound()
        #dont' send sound automatically, wait for user to request it:
        #if self.server_sound_receive and self.microphone_allowed:
        #    self.start_sending_sound()

        self.key_repeat_delay, self.key_repeat_interval = c.intpair("key_repeat", (-1,-1))
        self.emit("handshake-complete")
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        if self.server_supports_clipboard:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.send_clipboard_enabled_status)
        if self.toggle_keyboard_sync:
            self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)
        self.send_ping()
        if not c.boolget("notify-startup-complete"):
            #we won't get notified, so assume it is now:
            self._startup_complete()

    def _startup_complete(self, *args):
        log("all the existing windows and system trays have been received: %s items", len(self._id_to_window))
        gui_ready()
        if self.tray:
            self.tray.ready()


    def dbus_call(self, wid, bus_name, path, interface, function, reply_handler=None, error_handler=None, *args):
        if not self.server_dbus_proxy:
            log.error("cannot use dbus_call: this server does not support dbus-proxying")
            return
        rpcid = self.dbus_counter.increase()
        self.dbus_filter_pending()
        req = (time.time(), bus_name, path, interface, function, reply_handler, error_handler)
        dbuslog("sending dbus request %s to server: %s", rpcid, req)
        self.dbus_pending_requests[rpcid] = req
        self.send("rpc", "dbus", rpcid, wid, bus_name, path, interface, function, args)
        self.timeout_add(5000, self.dbus_filter_pending)

    def dbus_filter_pending(self):
        """ removes timed out dbus requests """
        for k in list(self.dbus_pending_requests.keys()):
            v = self.dbus_pending_requests.get(k)
            if v is None:
                continue
            t, bn, p, i, fn, _, ecb = v
            if time.time()-t>=5:
                dbuslog.warn("dbus request: %s:%s (%s).%s has timed out", bn, p, i, fn)
                del self.dbus_pending_requests[k]
                if ecb is not None:
                    ecb("timeout")

    def _process_rpc_reply(self, packet):
        rpc_type, rpcid, success, args = packet[1:5]
        assert rpc_type=="dbus", "unsupported rpc reply type: %s" % rpc_type
        dbuslog("rpc_reply: %s", (rpc_type, rpcid, success, args))
        v = self.dbus_pending_requests.get(rpcid)
        assert v is not None, "pending dbus handler not found for id %s" % rpcid
        del self.dbus_pending_requests[rpcid]
        if success:
            ctype = "ok"
            rh = v[-2]      #ok callback
        else:
            ctype = "error"
            rh = v[-1]      #error callback
        if rh is None:
            dbuslog("no %s rpc callback defined, return values=%s", ctype, args)
            return
        dbuslog("calling %s callback %s(%s)", ctype, rh, args)
        try:
            rh(*args)
        except Exception, e:
            dbuslog.warn("error processing rpc reply handler %s(%s) : %s", rh, args, e)


    def _process_control(self, packet):
        command = packet[1]
        if command=="show_session_info":
            args = packet[2:]
            log("calling show_session_info%s on server request", args)
            self.show_session_info(*args)
        elif command=="enable_zlib":
            log.info("switching to zlib on server request")
            self._protocol.enable_zlib()
        elif command=="enable_lz4":
            log.info("switching to lz4 on server request")
            self._protocol.enable_lz4()
        elif command=="enable_bencode":
            log.info("switching to bencode on server request")
            self._protocol.enable_bencode()
        elif command=="enable_rencode":
            log.info("switching to rencode on server request")
            self._protocol.enable_rencode()
        elif command=="name":
            assert len(args)>=3
            self.session_name = args[2]
            log.info("session name updated from server: %s", self.session_name)
            #TODO: reset tray tooltip, session info title, etc..
        else:
            log.warn("received invalid control command from server: %s", command)


    def start_sending_sound(self):
        """ (re)start a sound source and emit client signal """
        soundlog("start_sending_sound()")
        assert self.microphone_allowed
        assert self.server_sound_receive
        from xpra.sound.gstreamer_util import ALLOW_SOUND_LOOP
        if self._remote_machine_id and self._remote_machine_id==get_machine_id() and not ALLOW_SOUND_LOOP:
            #looks like we're on the same machine, verify it's a different user:
            if self._remote_uuid==get_user_uuid():
                log.warn("cannot start sound: identical user environment as the server (loop)")
                return

        if self.sound_source:
            if self.sound_source.get_state()=="active":
                log.error("already sending sound!")
                return
            self.sound_source.start()
        if not self.start_sound_source():
            return
        self.microphone_enabled = True
        self.emit("microphone-changed")
        soundlog("start_sending_sound() done")

    def start_sound_source(self):
        soundlog("start_sound_source()")
        assert self.sound_source is None
        def sound_source_state_changed(*args):
            self.emit("microphone-changed")
        def sound_source_bitrate_changed(*args):
            self.emit("microphone-changed")
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(None, 1.0, self.server_sound_decoders, self.microphone_codecs, self.server_pulseaudio_server, self.server_pulseaudio_id)
            if not self.sound_source:
                return False
            self.sound_source.connect("new-buffer", self.new_sound_buffer)
            self.sound_source.connect("state-changed", sound_source_state_changed)
            self.sound_source.connect("bitrate-changed", sound_source_bitrate_changed)
            self.sound_source.start()
            soundlog("start_sound_source() sound source %s started", self.sound_source)
            return True
        except Exception, e:
            log.error("error setting up sound: %s", e)
            return False

    def stop_sending_sound(self):
        """ stop the sound source and emit client signal """
        soundlog("stop_sending_sound() sound source=%s", self.sound_source)
        ss = self.sound_source
        self.microphone_enabled = False
        self.sound_source = None
        def stop_sending_sound_thread():
            soundlog("UIXpraClient.stop_sending_sound_thread()")
            if ss is None:
                log.warn("stop_sending_sound: sound not started!")
                return
            ss.cleanup()
            self.emit("microphone-changed")
            soundlog("UIXpraClient.stop_sending_sound_thread() done")
        thread.start_new_thread(stop_sending_sound_thread, ())

    def start_receiving_sound(self):
        """ ask the server to start sending sound and emit the client signal """
        soundlog("start_receiving_sound() sound sink=%s", self.sound_sink)
        if self.sound_sink is not None:
            soundlog("start_receiving_sound: we already have a sound sink")
            return
        elif not self.server_sound_send:
            log.error("cannot start receiving sound: support not enabled on the server")
            return
        #choose a codec:
        from xpra.sound.gstreamer_util import CODEC_ORDER
        matching_codecs = [x for x in self.server_sound_encoders if x in self.speaker_codecs]
        ordered_codecs = [x for x in CODEC_ORDER if x in matching_codecs]
        if len(ordered_codecs)==0:
            log.error("no matching codecs between server (%s) and client (%s)", self.server_sound_encoders, self.speaker_codecs)
            return
        codec = ordered_codecs[0]
        self.speaker_enabled = True
        self.emit("speaker-changed")
        def sink_ready(*args):
            soundlog("sink_ready(%s) codec=%s", args, codec)
            self.send("sound-control", "start", codec)
            return False
        self.on_sink_ready = sink_ready
        self.start_sound_sink(codec)

    def stop_receiving_sound(self, tell_server=True):
        """ ask the server to stop sending sound, toggle flag so we ignore further packets and emit client signal """
        soundlog("stop_receiving_sound() sound sink=%s", self.sound_sink)
        ss = self.sound_sink
        self.speaker_enabled = False
        if tell_server:
            self.send("sound-control", "stop")
        if ss is None:
            return
        self.sound_sink = None
        def stop_receiving_sound_thread():
            soundlog("UIXpraClient.stop_receiving_sound_thread()")
            if ss is None:
                log("stop_receiving_sound: sound not started!")
                return
            ss.cleanup()
            self.emit("speaker-changed")
            soundlog("UIXpraClient.stop_receiving_sound_thread() done")
        thread.start_new_thread(stop_receiving_sound_thread, ())

    def bump_sound_sequence(self):
        if self.server_sound_sequence:
            #server supports the "sound-sequence" feature
            #tell it to use a new one:
            self.min_sound_sequence += 1
            soundlog("bump_sound_sequence() sequence is now %s", self.min_sound_sequence)
            #via idle add so this will wait for UI thread to catch up if needed:
            self.idle_add(self.send_new_sound_sequence)

    def send_new_sound_sequence(self):
        soundlog("send_new_sound_sequence() sequence=%s", self.min_sound_sequence)
        self.send("sound-control", "new-sequence", self.min_sound_sequence)


    def sound_sink_state_changed(self, sound_sink, state):
        soundlog("sound_sink_state_changed(%s, %s) on_sink_ready=%s", sound_sink, state, self.on_sink_ready)
        if state=="ready" and self.on_sink_ready:
            if not self.on_sink_ready():
                self.on_sink_ready = None
        self.emit("speaker-changed")
    def sound_sink_bitrate_changed(self, sound_sink, bitrate):
        soundlog("sound_sink_bitrate_changed(%s, %s)", sound_sink, bitrate)
        #not shown in the UI, so don't bother with emitting a signal:
        #self.emit("speaker-changed")
    def sound_sink_error(self, sound_sink, error):
        log.warn("stopping speaker because of error: %s", error)
        self.stop_receiving_sound()

    def sound_sink_overrun(self, *args):
        if self.sink_restart_pending:
            soundlog("overrun re-start is already pending")
            return
        log.warn("re-starting speaker because of overrun")
        codec = self.sound_sink.codec
        self.sink_restart_pending = True
        if self.server_sound_sequence:
            self.min_sound_sequence += 1
        #Note: the next sound packet will take care of starting a new pipeline
        self.stop_receiving_sound()
        def restart():
            soundlog("restart() sound_sink=%s, codec=%s, server_sound_sequence=%s", self.sound_sink, codec, self.server_sound_sequence)
            if self.server_sound_sequence:
                self.send_new_sound_sequence()
            self.start_receiving_sound()
            self.sink_restart_pending = False
            return False
        self.timeout_add(200, restart)

    def start_sound_sink(self, codec):
        soundlog("start_sound_sink(%s)", codec)
        assert self.sound_sink is None
        try:
            soundlog("starting %s sound sink", codec)
            from xpra.sound.sink import SoundSink
            self.sound_sink = SoundSink(codec=codec)
            self.sound_sink.connect("state-changed", self.sound_sink_state_changed)
            self.sound_sink.connect("bitrate-changed", self.sound_sink_bitrate_changed)
            self.sound_sink.connect("error", self.sound_sink_error)
            self.sound_sink.connect("overrun", self.sound_sink_overrun)
            self.sound_sink.start()
            soundlog("%s sound sink started", codec)
            return True
        except:
            log.error("failed to start sound sink", exc_info=True)
            return False

    def new_sound_buffer(self, sound_source, data, metadata):
        soundlog("new_sound_buffer(%s, %s, %s) sound source=%s", sound_source, len(data or []), metadata, self.sound_source)
        if self.sound_source:
            self.send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data), metadata)

    def _process_sound_data(self, packet):
        codec, data, metadata = packet[1:4]
        if not self.speaker_enabled:
            if metadata.get("start-of-stream"):
                #server is asking us to start playing sound
                if not self.speaker_allowed:
                    #no can do!
                    self.stop_receiving_sound(True)
                    return
                self.speaker_enabled = True
                self.emit("speaker-changed")
                self.on_sink_ready = None
                codec = metadata.get("codec")
                soundlog("starting speaker on server request using codec %s", codec)
                self.start_sound_sink(codec)
            else:
                soundlog("speaker is now disabled - dropping packet")
                return
        elif metadata.get("end-of-stream"):
            if self.sound_sink:
                soundlog("server sent end-of-stream, closing sound pipeline")
                self.stop_receiving_sound(False)
            return
        seq = metadata.get("sequence", -1)
        if self.min_sound_sequence>0 and seq<self.min_sound_sequence:
            soundlog("ignoring sound data with old sequence number %s", seq)
            return
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.error("sound codec change not supported! (from %s to %s)", self.sound_sink.codec, codec)
            self.sound_sink.stop()
            return
        if self.sound_sink is None:
            soundlog("no sound sink to process sound data, dropping it")
            return
        elif self.sound_sink.get_state()=="stopped":
            soundlog("sound data received, sound sink is stopped - starting it")
            self.sound_sink.start()
        #(some packets (ie: sos, eos) only contain metadata)
        if len(data)>0:
            self.sound_sink.add_data(data, metadata)


    def send_notify_enabled(self):
        assert self.client_supports_notifications, "cannot toggle notifications: the feature is disabled by the client"
        assert self.server_supports_notifications, "cannot toggle notifications: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle notifications: server lacks the feature"
        self.send("set-notify", self.notifications_enabled)

    def send_bell_enabled(self):
        assert self.client_supports_bell, "cannot toggle bell: the feature is disabled by the client"
        assert self.server_supports_bell, "cannot toggle bell: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle bell: server lacks the feature"
        self.send("set-bell", self.bell_enabled)

    def send_cursors_enabled(self):
        assert self.client_supports_cursors, "cannot toggle cursors: the feature is disabled by the client"
        assert self.server_supports_cursors, "cannot toggle cursors: the feature is disabled by the server"
        assert self.toggle_cursors_bell_notify, "cannot toggle cursors: server lacks the feature"
        self.send("set-cursors", self.cursors_enabled)

    def send_force_ungrab(self, wid):
        assert self.force_ungrab
        self.send("force-ungrab", wid)

    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        self._protocol.set_compression_level(self.compression_level)
        self.send("set_deflate", self.compression_level)


    def _process_clipboard_enabled_status(self, packet):
        clipboard_enabled, reason = packet[1:3]
        if self.clipboard_enabled!=clipboard_enabled:
            log.info("clipboard toggled to %s by the server, reason: %s", clipboard_enabled, reason)
            self.clipboard_enabled = clipboard_enabled
            self.emit("clipboard-toggled")

    def send_clipboard_enabled_status(self, *args):
        self.send("set-clipboard-enabled", self.clipboard_enabled)

    def send_keyboard_sync_enabled_status(self, *args):
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)


    def set_encoding(self, encoding):
        log("set_encoding(%s)", encoding)
        assert encoding in self.get_encodings(), "encoding %s is not supported!" % encoding
        assert encoding in self.server_encodings, "encoding %s is not supported by the server! (only: %s)" % (encoding, self.server_encodings)
        self.encoding = encoding
        if not self.server_generic_encodings:
            #translate to old name the server will understand:
            encoding = ALL_NEW_ENCODING_NAMES_TO_OLD.get(encoding, encoding)
        self.send("encoding", encoding)


    def reset_cursor(self):
        self.set_windows_cursor(self._id_to_window.values(), [])

    def _ui_event(self):
        if self._ui_events==0:
            self.emit("first-ui-received")
        self._ui_events += 1

    def _process_new_common(self, packet, override_redirect):
        self._ui_event()
        wid, x, y, w, h, metadata = packet[1:7]
        windowlog("process_new_common: %s, OR=%s", packet[1:7], override_redirect)
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        if w<=0 or h<=0:
            windowlog.error("window dimensions are wrong: %sx%s", w, h)
            w, h = 1, 1
        client_properties = {}
        if len(packet)>=8:
            client_properties = packet[7]
        self.make_new_window(wid, x, y, w, h, metadata, override_redirect, client_properties)

    def make_new_window(self, wid, x, y, w, h, metadata, override_redirect, client_properties):
        client_window_classes = self.get_client_window_classes(metadata, override_redirect)
        group_leader_window = self.get_group_leader(metadata, override_redirect)
        window = None
        windowlog("make_new_window(..) client_window_classes=%s, group_leader_window=%s", client_window_classes, group_leader_window)
        for cwc in client_window_classes:
            try:
                window = cwc(self, group_leader_window, wid, x, y, w, h, metadata, override_redirect, client_properties, self.border)
                break
            except:
                windowlog.warn("failed to instantiate %s", cwc, exc_info=True)
        if window is None:
            windowlog.warn("no more options.. this window will not be shown, sorry")
            return None
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        window.show()
        return window

    def get_group_leader(self, metadata, override_redirect):
        #subclasses that wish to implement the feature may override this method
        return None


    def get_client_window_classes(self, metadata, override_redirect):
        return [self.ClientWindowClass]

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_new_tray(self, packet):
        assert SYSTEM_TRAY_SUPPORTED
        self._ui_event()
        wid, w, h = packet[1:4]
        metadata = {}
        if len(packet)>=5:
            metadata = packet[4]
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        tray = self.setup_system_tray(self, wid, w, h, metadata.get("title", ""))
        traylog("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid

    def _process_window_move_resize(self, packet):
        (wid, x, y, w, h) = packet[1:6]
        resize_counter = -1
        if len(packet)>4:
            resize_counter = packet[4]
        window = self._id_to_window.get(wid)
        windowlog("_process_window_resized moving / resizing window %s (id=%s) to %s", window, wid, (x, y, w, h))
        if window:
            window.move_resize(x, y, w, h, resize_counter)

    def _process_window_resized(self, packet):
        (wid, w, h) = packet[1:4]
        resize_counter = -1
        if len(packet)>4:
            resize_counter = packet[4]
        window = self._id_to_window.get(wid)
        windowlog("_process_window_resized resizing window %s (id=%s) to %s", window, wid, (w,h))
        if window:
            window.resize(w, h, resize_counter)

    def _process_draw(self, packet):
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid, packet_sequence, width, height, decode_time):
        self.send_now("damage-sequence", packet_sequence, wid, width, height, decode_time)

    def _draw_thread_loop(self):
        while self.exit_code is None:
            packet = self._draw_queue.get()
            try:
                self._do_draw(packet)
                time.sleep(0)
            except KeyboardInterrupt:
                raise
            except:
                log.error("error processing draw packet", exc_info=True)

    def _do_draw(self, packet):
        """ this runs from the draw thread above """
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        #rename old encoding aliases early:
        coding = OLD_ENCODING_NAMES_TO_NEW.get(coding, coding)
        window = self._id_to_window.get(wid)
        if not window:
            #window is gone
            def draw_cleanup():
                if coding=="mmap":
                    assert self.mmap_enabled
                    from xpra.net.mmap_pipe import int_from_buffer
                    def free_mmap_area():
                        #we need to ack the data to free the space!
                        data_start = int_from_buffer(self.mmap, 0)
                        offset, length = data[-1]
                        data_start.value = offset+length
                    #clear the mmap area via idle_add so any pending draw requests
                    #will get a chance to run first (preserving the order)
                self.send_damage_sequence(wid, packet_sequence, width, height, -1)
            self.idle_add(draw_cleanup)
            return
        options = {}
        if len(packet)>10:
            options = packet[10]
        paintlog("process_draw %s bytes for window %s using %s encoding with options=%s", len(data), wid, coding, options)
        start = time.time()
        def record_decode_time(success):
            if success:
                end = time.time()
                decode_time = int(end*1000*1000-start*1000*1000)
                self.pixel_counter.append((start, end, width*height))
                dms = "%sms" % (int(decode_time/100)/10.0)
                paintlog("record_decode_time(%s) wid=%s, %s: %sx%s, %s", success, wid, coding, width, height, dms)
            else:
                decode_time = -1
                paintlog("record_decode_time(%s) decoding error on wid=%s, %s: %sx%s", success, wid, coding, width, height)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time)
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, packet_sequence, options, [record_decode_time])
        except KeyboardInterrupt:
            raise
        except:
            log.error("draw error", exc_info=True)
            self.idle_add(record_decode_time, False)
            raise

    def _process_cursor(self, packet):
        if not self.cursors_enabled:
            return
        if len(packet)==2:
            new_cursor = packet[1]
        elif len(packet)>=8:
            new_cursor = packet[1:]
        else:
            raise Exception("invalid cursor packet: %s items" % len(packet))
        self.set_windows_cursor(self._id_to_window.values(), new_cursor)

    def _process_bell(self, packet):
        if not self.bell_enabled:
            return
        (wid, device, percent, pitch, duration, bell_class, bell_id, bell_name) = packet[1:9]
        window = self._id_to_window.get(wid)
        self.window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)


    def _process_notify_show(self, packet):
        if not self.notifications_enabled:
            return
        self._ui_event()
        dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout = packet[1:9]
        log("_process_notify_show(%s)", packet)
        assert self.notifier
        #TODO: choose more appropriate tray if we have more than one shown?
        tray = self.tray
        self.notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout)

    def _process_notify_close(self, packet):
        if not self.notifications_enabled:
            return
        assert self.notifier
        nid = packet[1]
        log("_process_notify_close(%s)", nid)
        self.notifier.close_notify(nid)


    def _process_raise_window(self, packet):
        #only implemented in gtk2 for now
        pass

    def _process_window_metadata(self, packet):
        wid, metadata = packet[1:3]
        window = self._id_to_window.get(wid)
        if window:
            window.update_metadata(metadata)

    def _process_window_icon(self, packet):
        windowlog("_process_window_icon(%s,%s bytes)", packet[1:5], len(packet[5]))
        wid, w, h, pixel_format, data = packet[1:6]
        window = self._id_to_window.get(wid)
        if window:
            window.update_icon(w, h, pixel_format, data)

    def _process_configure_override_redirect(self, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window[wid]
        window.move_resize(x, y, w, h, -1)

    def _process_lost_window(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            del self._id_to_window[wid]
            del self._window_to_id[window]
            self.destroy_window(wid, window)
        if len(self._id_to_window)==0:
            windowlog("last window gone, clearing key repeat")
            if self.keyboard_helper:
                self.keyboard_helper.clear_repeat()

    def destroy_window(self, wid, window):
        windowlog("destroy_window(%s, %s)", wid, window)
        window.destroy()
        if self._window_with_grab==wid:
            log("destroying window %s which has grab, ungrabbing!", wid)
            self.window_ungrab()
            self._window_with_grab = None

    def _process_desktop_size(self, packet):
        root_w, root_h, max_w, max_h = packet[1:5]
        log("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h

    def set_max_packet_size(self):
        root_w, root_h = self.get_root_size()
        maxw, maxh = root_w, root_h
        try:
            server_w, server_h = self.server_actual_desktop_size
            maxw = max(root_w, server_w)
            maxh = max(root_h, server_h)
        except:
            pass
        assert maxw>0 and maxh>0 and maxw<32768 and maxh<32768, "problems calculating maximum desktop size: %sx%s" % (maxw, maxh)
        #full screen at 32bits times 4 for safety
        self._protocol.max_packet_size = maxw*maxh*4*4
        log("set maximum packet size to %s", self._protocol.max_packet_size)


    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        for k,v in {
            "hello":                self._process_hello,
            "startup-complete":     self._startup_complete,
            "new-window":           self._process_new_window,
            "new-override-redirect":self._process_new_override_redirect,
            "new-tray":             self._process_new_tray,
            "raise-window":         self._process_raise_window,
            "window-move-resize":   self._process_window_move_resize,
            "window-resized":       self._process_window_resized,
            "cursor":               self._process_cursor,
            "bell":                 self._process_bell,
            "notify_show":          self._process_notify_show,
            "notify_close":         self._process_notify_close,
            "set-clipboard-enabled":self._process_clipboard_enabled_status,
            "window-metadata":      self._process_window_metadata,
            "configure-override-redirect":  self._process_configure_override_redirect,
            "lost-window":          self._process_lost_window,
            "desktop_size":         self._process_desktop_size,
            "window-icon":          self._process_window_icon,
            "rpc-reply":            self._process_rpc_reply,
            "control" :             self._process_control,
            "draw":                 self._process_draw,
            # "clipboard-*" packets are handled by a special case below.
            }.items():
            self._ui_packet_handlers[k] = v
        #these handlers can run directly from the network thread:
        for k,v in {
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "info-response":        self._process_info_response,
            "sound-data":           self._process_sound_data,
            }.items():
            self._packet_handlers[k] = v

    def process_clipboard_packet(self, packet):
        self.idle_add(self.clipboard_helper.process_clipboard_packet, packet)

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        self.check_server_echo(0)
        if type(packet_type) in (unicode, str) and packet_type.startswith("clipboard-"):
            if self.clipboard_enabled and self.clipboard_helper:
                self.process_clipboard_packet(packet)
        else:
            XpraClientBase.process_packet(self, proto, packet)
