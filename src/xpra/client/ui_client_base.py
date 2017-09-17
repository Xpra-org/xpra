# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import time
import datetime
import traceback
import logging
from collections import deque
from threading import RLock
from time import sleep

from xpra.log import Logger, set_global_logging_handler
log = Logger("client")
windowlog = Logger("client", "window")
geomlog = Logger("client", "geometry")
paintlog = Logger("client", "paint")
drawlog = Logger("client", "draw")
focuslog = Logger("client", "focus")
soundlog = Logger("client", "sound")
filelog = Logger("client", "file")
traylog = Logger("client", "tray")
keylog = Logger("client", "keyboard")
workspacelog = Logger("client", "workspace")
rpclog = Logger("client", "rpc")
grablog = Logger("client", "grab")
iconlog = Logger("client", "icon")
screenlog = Logger("client", "screen")
mouselog = Logger("mouse")
avsynclog = Logger("av-sync")
clipboardlog = Logger("clipboard")
scalinglog = Logger("scaling")
webcamlog = Logger("webcam")
notifylog = Logger("notify")
cursorlog = Logger("cursor")
netlog = Logger("network")


from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.client.client_base import XpraClientBase
from xpra.exit_codes import (EXIT_TIMEOUT, EXIT_MMAP_TOKEN_FAILURE)
from xpra.client.client_tray import ClientTray
from xpra.client.keyboard_helper import KeyboardHelper
from xpra.platform.paths import get_icon_filename
from xpra.platform.features import MMAP_SUPPORTED, SYSTEM_TRAY_SUPPORTED, CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY, CLIPBOARDS, REINIT_WINDOWS
from xpra.platform.gui import (ready as gui_ready, get_vrefresh, get_antialias_info, get_icc_info, get_display_icc_info, get_double_click_time, show_desktop, get_cursor_size,
                               get_double_click_distance, get_native_notifier_classes, get_native_tray_classes, get_native_system_tray_classes, get_session_type,
                               get_native_tray_menu_helper_classes, get_xdpi, get_ydpi, get_number_of_desktops, get_desktop_names, get_wm_name, ClientExtras)
from xpra.codecs.loader import load_codecs, codec_versions, has_codec, get_codec, PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS
from xpra.scripts.main import sound_option, full_version_str
from xpra.scripts.config import parse_bool_or_int, parse_bool, FALSE_OPTIONS, TRUE_OPTIONS
from xpra.simple_stats import std_unit
from xpra.net import compression, packet_encoding
from xpra.net.compression import Compressed
from xpra.child_reaper import reaper_cleanup
from xpra.make_thread import make_thread
from xpra.os_util import BytesIOClass, Queue, platform_name, get_machine_id, get_user_uuid, bytestostr, monotonic_time, strtobytes, OSX, POSIX
from xpra.util import nonl, std, iround, envint, envbool, AtomicInteger, log_screen_sizes, typedict, updict, csv, engs, CLIENT_EXIT, XPRA_APP_ID
from xpra.version_util import get_version_info_full, get_platform_info
try:
    from xpra.clipboard.clipboard_base import ALL_CLIPBOARDS
except:
    ALL_CLIPBOARDS = []
try:
    from xpra.sound.common import LEGACY_CODEC_NAMES, NEW_CODEC_NAMES, add_legacy_names
except:
    LEGACY_CODEC_NAMES, NEW_CODEC_NAMES = {}, {}
    def add_legacy_names(codecs):
        return codecs


FAKE_BROKEN_CONNECTION = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
UNGRAB_KEY = os.environ.get("XPRA_UNGRAB_KEY", "Escape")

MONITOR_CHANGE_REINIT = envint("XPRA_MONITOR_CHANGE_REINIT")

AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA")
MOUSE_SHOW = envbool("XPRA_MOUSE_SHOW", True)

PAINT_FAULT_RATE = envint("XPRA_PAINT_FAULT_INJECTION_RATE")
PAINT_FAULT_TELL = envbool("XPRA_PAINT_FAULT_INJECTION_TELL", True)

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)

#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")


MIN_SCALING = float(os.environ.get("XPRA_MIN_SCALING", "0.1"))
MAX_SCALING = float(os.environ.get("XPRA_MAX_SCALING", "8"))
SCALING_OPTIONS = [float(x) for x in os.environ.get("XPRA_TRAY_SCALING_OPTIONS", "0.25,0.5,0.666,1,1.25,1.5,2.0,3.0,4.0,5.0").split(",") if float(x)>=MIN_SCALING and float(x)<=MAX_SCALING]
SCALING_EMBARGO_TIME = int(os.environ.get("XPRA_SCALING_EMBARGO_TIME", "1000"))/1000.0
MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)

RPC_TIMEOUT = envint("XPRA_RPC_TIMEOUT", 5000)

WEBCAM_ALLOW_VIRTUAL = envbool("XPRA_WEBCAM_ALLOW_VIRTUAL", False)
WEBCAM_TARGET_FPS = max(1, min(50, envint("XPRA_WEBCAM_FPS", 20)))

WM_CLASS_CLOSEEXIT = os.environ.get("XPRA_WM_CLASS_CLOSEEXIT", "Xephyr").split(",")
TITLE_CLOSEEXIT = os.environ.get("XPRA_TITLE_CLOSEEXIT", "Xnest").split(",")

SKIP_DUPLICATE_BUTTON_EVENTS = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)


DRAW_TYPES = {bytes : "bytes", str : "bytes", tuple : "arrays", list : "arrays"}

def r4cmp(v, rounding=1000.0):    #ignore small differences in floats for scale values
    return iround(v*rounding)
def fequ(v1, v2):
    return r4cmp(v1)==r4cmp(v2)


"""
Utility superclass for client classes which have a UI.
See gtk_client_base and its subclasses.
"""
class UIXpraClient(XpraClientBase):
    #NOTE: these signals aren't registered because this class
    #does not extend GObject.
    __gsignals__ = {
        "first-ui-received"         : no_arg_signal,

        "clipboard-toggled"         : no_arg_signal,
        "scaling-changed"           : no_arg_signal,
        "keyboard-sync-toggled"     : no_arg_signal,
        "speaker-changed"           : no_arg_signal,        #bitrate or pipeline state has changed
        "microphone-changed"        : no_arg_signal,        #bitrate or pipeline state has changed
        "webcam-changed"            : no_arg_signal,
        }

    def __init__(self):
        XpraClientBase.__init__(self)
        import struct
        bits = struct.calcsize("P") * 8
        log.info("Xpra %s client version %s %i-bit", self.client_toolkit(), full_version_str(), bits)
        try:
            pinfo = get_platform_info()
            osinfo = "%s" % platform_name(sys.platform, pinfo.get("linux_distribution") or pinfo.get("sysrelease", ""))
            log.info(" running on %s", osinfo)
        except:
            log("platform name error:", exc_info=True)
        self.start_time = monotonic_time()
        self._window_to_id = {}
        self._id_to_window = {}
        self._ui_events = 0
        self.title = ""
        self.session_name = ""
        self.auto_refresh_delay = -1
        self.max_window_size = 0, 0
        self.dpi = 0
        self.pixel_depth = 0
        self.initial_scaling = 1, 1
        self.xscale, self.yscale = self.initial_scaling
        self.scale_change_embargo = 0
        self.desktop_fullscreen = False

        #draw thread:
        self._draw_queue = None
        self._draw_thread = None
        self._draw_counter = 0

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.pixel_counter = deque(maxlen=1000)
        self.server_ping_latency = deque(maxlen=1000)
        self.server_load = None
        self.client_ping_latency = deque(maxlen=1000)
        self._server_ok = True
        self.last_ping_echoed_time = 0
        self.server_last_info = None
        self.info_request_pending = False
        self.screen_size_change_pending = False
        self.allowed_encodings = []
        self.core_encodings = None
        self.encoding = None

        #webcam:
        self.webcam_option = ""
        self.webcam_forwarding = False
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_last_ack = -1
        self.webcam_ack_check_timer = None
        self.webcam_send_timer = None
        self.webcam_lock = RLock()
        self.server_supports_webcam = False
        self.server_virtual_video_devices = 0

        #sound:
        self.sound_source_plugin = None
        self.speaker_allowed = False
        self.speaker_enabled = False
        self.speaker_codecs = []
        self.microphone_allowed = False
        self.microphone_enabled = False
        self.microphone_codecs = []
        self.microphone_device = None
        self.av_sync = False
        #sound state:
        self.on_sink_ready = None
        self.sound_sink = None
        self.min_sound_sequence = 0
        self.server_sound_eos_sequence = False
        self.sound_source = None
        self.sound_in_bytecount = 0
        self.sound_out_bytecount = 0
        self.server_pulseaudio_id = None
        self.server_pulseaudio_server = None
        self.server_sound_decoders = []
        self.server_sound_encoders = []
        self.server_sound_receive = False
        self.server_sound_send = False
        self.server_sound_bundle_metadata = False
        self.server_ogg_latency_fix = False
        self.server_codec_full_names = False
        self.queue_used_sent = None

        #rpc / dbus:
        self.rpc_counter = AtomicInteger()
        self.rpc_pending_requests = {}

        #mmap:
        self.mmap_enabled = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_token_index = 0
        self.mmap_token_bytes = 0
        self.mmap_filename = None
        self.mmap_size = 0
        self.mmap_group = None
        self.mmap_tempfile = None
        self.mmap_delete = False

        #features:
        self.opengl_enabled = False
        self.opengl_props = {}
        self.server_encodings = []
        self.server_core_encodings = []
        self.server_encodings_problematic = PROBLEMATIC_ENCODINGS
        self.server_encodings_with_speed = ()
        self.server_encodings_with_quality = ()
        self.server_encodings_with_lossless_mode = ()
        self.server_auto_video_encoding = False
        self.server_clipboard_direction = "both"
        self.readonly = False
        self.windows_enabled = True
        self.pings = False
        self.xsettings_enabled = False
        self.server_dbus_proxy = False
        self.server_rpc_types = []
        self.start_new_commands = False
        self.server_window_decorations = False
        self.server_window_frame_extents = False
        self.server_is_desktop = False
        self.server_supports_sharing = False
        self.server_supports_window_filters = False
        self.server_input_devices = None
        self.server_window_states = []
        #what we told the server about our encoding defaults:
        self.encoding_defaults = {}

        self.client_supports_opengl = False
        self.client_supports_notifications = False
        self.client_supports_system_tray = False
        self.client_supports_clipboard = False
        self.client_supports_cursors = False
        self.client_supports_bell = False
        self.client_supports_sharing = False
        self.client_supports_remote_logging = False
        self.log_both = False
        self.notifications_enabled = False
        self.client_clipboard_direction = "both"
        self.clipboard_enabled = False
        self.cursors_enabled = False
        self.default_cursor_data = None
        self.bell_enabled = False
        self.border = None
        self.window_close_action = "forward"
        self.wheel_map = {}
        self.wheel_deltax = 0
        self.wheel_deltay = 0

        self.supports_mmap = MMAP_SUPPORTED

        #helpers and associated flags:
        self.client_extras = None
        self.keyboard_helper_class = KeyboardHelper
        self.keyboard_helper = None
        self.keyboard_grabbed = False
        self.pointer_grabbed = False
        self.kh_warning = False
        self.clipboard_helper = None
        self.menu_helper = None
        self.tray = None
        self.notifier = None
        self.in_remote_logging = False
        self.local_logging = None

        #state:
        self._focused = None
        self._window_with_grab = None
        self._last_screen_settings = None
        self._suspended_at = 0
        self._button_state = {}
        self._on_handshake = []
        self._current_screen_sizes = None

        self.init_aliases()


    def init(self, opts):
        """ initialize variables from configuration """
        self.allowed_encodings = opts.encodings
        self.encoding = opts.encoding
        self.video_scaling = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.title = opts.title
        self.session_name = opts.session_name
        self.auto_refresh_delay = opts.auto_refresh_delay
        if opts.max_size:
            try:
                self.max_window_size = [int(x.strip()) for x in opts.max_size.split("x", 1)]
                assert len(self.max_window_size)==2
            except:
                #the main script does some checking, but we could be called from a config file launch
                log.warn("Warning: invalid window max-size specified: %s", opts.max_size)
                self.max_window_size = 0, 0
        self.desktop_scaling = opts.desktop_scaling
        self.can_scale = opts.desktop_scaling not in FALSE_OPTIONS
        if self.can_scale:
            self.initial_scaling = self.parse_scaling(opts.desktop_scaling)
            self.xscale, self.yscale = self.initial_scaling

        self.pixel_depth = int(opts.pixel_depth)
        if self.pixel_depth not in (0, 16, 24, 30) and self.pixel_depth<32:
            log.warn("Warning: invalid pixel depth %i", self.pixel_depth)
            self.pixel_depth = 0
        self.dpi = int(opts.dpi)
        self.xsettings_enabled = opts.xsettings
        if MMAP_SUPPORTED:
            self.mmap_group = opts.mmap_group
            if os.path.isabs(opts.mmap):
                self.mmap_filename = opts.mmap
                self.supports_mmap = True
            else:
                self.supports_mmap = opts.mmap.lower() in TRUE_OPTIONS
        self.desktop_fullscreen = opts.desktop_fullscreen

        self.webcam_option = opts.webcam
        self.webcam_forwarding = self.webcam_option.lower() not in FALSE_OPTIONS
        self.server_supports_webcam = False
        self.server_virtual_video_devices = 0
        if self.webcam_forwarding:
            try:
                import cv2
                from PIL import Image
                assert cv2 and Image
            except ImportError as e:
                webcamlog("init webcam failure", exc_info=True)
                webcamlog.warn("Warning: failed to import opencv:")
                webcamlog.warn(" %s", e)
                webcamlog.warn(" webcam forwarding is disabled")
                self.webcam_forwarding = False
        webcamlog("webcam forwarding: %s", self.webcam_forwarding)

        self.sound_properties = typedict()
        self.speaker_allowed = sound_option(opts.speaker) in ("on", "off")
        #ie: "on", "off", "on:Some Device", "off:Some Device"
        mic = [x.strip() for x in opts.microphone.split(":", 1)]
        self.microphone_allowed = sound_option(mic[0]) in ("on", "off")
        self.microphone_device = None
        if self.microphone_allowed and len(mic)==2:
            self.microphone_device = mic[1]
        self.sound_source_plugin = opts.sound_source
        def sound_option_or_all(*_args):
            return []
        if self.speaker_allowed or self.microphone_allowed:
            try:
                from xpra.sound.common import sound_option_or_all
                from xpra.sound.wrapper import query_sound
                self.sound_properties = query_sound()
                assert self.sound_properties, "query did not return any data"
                def vinfo(k):
                    val = self.sound_properties.get(k)
                    assert val, "%s not found in sound properties" % k
                    return ".".join(bytestostr(x) for x in val[:3])
                bits = self.sound_properties.intget(b"python.bits", 32)
                log.info("GStreamer version %s for Python %s %s-bit", vinfo(b"gst.version"), vinfo(b"python.version"), bits)
            except Exception as e:
                soundlog("failed to query sound", exc_info=True)
                soundlog.error("Error: failed to query sound subsystem:")
                soundlog.error(" %s", e)
                self.speaker_allowed = False
                self.microphone_allowed = False
        encoders = self.sound_properties.strlistget("encoders", [])
        decoders = self.sound_properties.strlistget("decoders", [])
        self.speaker_codecs = sound_option_or_all("speaker-codec", opts.speaker_codec, decoders)
        self.microphone_codecs = sound_option_or_all("microphone-codec", opts.microphone_codec, encoders)
        if not self.speaker_codecs:
            self.speaker_allowed = False
        if not self.microphone_codecs:
            self.microphone_allowed = False
        self.speaker_enabled = self.speaker_allowed and sound_option(opts.speaker)=="on"
        self.microphone_enabled = self.microphone_allowed and opts.microphone.lower()=="on"
        self.av_sync = opts.av_sync
        soundlog("speaker: codecs=%s, allowed=%s, enabled=%s", encoders, self.speaker_allowed, csv(self.speaker_codecs))
        soundlog("microphone: codecs=%s, allowed=%s, enabled=%s, default device=%s", decoders, self.microphone_allowed, csv(self.microphone_codecs), self.microphone_device)
        soundlog("av-sync=%s", self.av_sync)

        self.readonly = opts.readonly
        self.windows_enabled = opts.windows
        self.pings = opts.pings

        self.client_supports_notifications = opts.notifications
        self.client_supports_system_tray = opts.system_tray and SYSTEM_TRAY_SUPPORTED
        self.client_clipboard_type = opts.clipboard
        self.client_clipboard_direction = opts.clipboard_direction
        self.client_supports_clipboard = not ((opts.clipboard or "").lower() in FALSE_OPTIONS)
        self.client_supports_cursors = opts.cursors
        self.client_supports_bell = opts.bell
        self.client_supports_sharing = opts.sharing
        self.log_both = (opts.remote_logging or "").lower()=="both"
        self.client_supports_remote_logging = self.log_both or parse_bool("remote-logging", opts.remote_logging)
        self.input_devices = opts.input_devices
        #mouse wheel:
        mw = (opts.mousewheel or "").lower().replace("-", "")
        if mw not in FALSE_OPTIONS:
            UP = 4
            LEFT = 6
            Z1 = 8
            for i in range(20):
                btn = 4+i*2
                invert = mw=="invert" or (btn==UP and mw=="inverty") or (btn==LEFT and mw=="invertx") or (btn==Z1 and mw=="invertz")
                if not invert:
                    self.wheel_map[btn] = btn
                    self.wheel_map[btn+1] = btn+1
                else:
                    self.wheel_map[btn+1] = btn
                    self.wheel_map[btn] = btn+1
        #until we add the ability to choose decoders, use all of them:
        #(and default to non grahics card csc modules if not specified)
        load_codecs(encoders=False)
        vh = getVideoHelper()
        vh.set_modules(video_decoders=opts.video_decoders, csc_modules=opts.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()


    def init_ui(self, opts, extra_args=[]):
        """ initialize user interface """
        self.init_opengl(opts.opengl)

        if not self.readonly:
            def noauto(v):
                if not v:
                    return None
                if str(v).lower()=="auto":
                    return None
                return v
            overrides = [noauto(getattr(opts, "keyboard_%s" % x)) for x in ("layout", "layouts", "variant", "variants", "options")]
            self.keyboard_helper = self.keyboard_helper_class(self.send, opts.keyboard_sync, opts.key_shortcut, opts.keyboard_raw, *overrides)

        if opts.tray:
            self.menu_helper = self.make_tray_menu_helper()
            def setup_xpra_tray():
                self.tray = self.setup_xpra_tray(opts.tray_icon or "xpra")
                self.tray.show()
            if opts.delay_tray:
                self.connect("first-ui-received", setup_xpra_tray)
            else:
                #show when the main loop is running:
                self.idle_add(setup_xpra_tray)

        notifylog("client_supports_notifications=%s", self.client_supports_notifications)
        if self.client_supports_notifications:
            self.notifier = self.make_notifier()
            notifylog("using notifier=%s", self.notifier)
            self.client_supports_notifications = self.notifier is not None

        #audio tagging:
        if POSIX:
            try:
                from xpra import sound
                assert sound
            except ImportError as e:
                log("no sound module, skipping pulseaudio tagging setup")
            else:
                try:
                    from xpra.sound.pulseaudio.pulseaudio_util import set_icon_path
                    tray_icon_filename = get_icon_filename(opts.tray_icon or "xpra")
                    set_icon_path(tray_icon_filename)
                except ImportError as e:
                    if not OSX:
                        log.warn("Warning: failed to set pulseaudio tagging icon:")
                        log.warn(" %s", e)

        if ClientExtras is not None:
            self.client_extras = ClientExtras(self, opts)

        if opts.border:
            self.parse_border(opts.border, extra_args)
        if opts.window_close not in ("forward", "ignore", "disconnect", "shutdown", "auto"):
            self.window_close_action = "forward"
            log.warn("Warning: invalid 'window-close' option: '%s'", opts.window_close)
            log.warn(" using '%s'", self.window_close_action)
        else:
            self.window_close_action = opts.window_close

        #draw thread:
        self._draw_queue = Queue()
        self._draw_thread = make_thread(self._draw_thread_loop, "draw")

    def setup_connection(self, conn):
        XpraClientBase.setup_connection(self, conn)
        if self.supports_mmap:
            self.init_mmap(self.mmap_filename, self.mmap_group, conn.filename)


    def parse_border(self, border_str, extra_args):
        #not implemented here (see gtk2 client)
        pass

    def parse_scaling(self, desktop_scaling):
        scalinglog("parse_scaling(%s)", desktop_scaling)
        if desktop_scaling in TRUE_OPTIONS:
            return 1, 1
        root_w, root_h = self.get_root_size()
        if desktop_scaling.startswith("auto"):
            #figure out if the command line includes settings to use for auto mode:
            #here are our defaults:
            limits = ((3960, 2160, 1, 1),           #100% no auto scaling up to 4k
                      (7680, 4320, 1.25, 1.25),     #125%
                      (8192, 8192, 1.5, 1.5),       #150%
                      (16384, 16384, 5.0/3, 5.0/3), #166%
                      (32768, 32768, 2, 2),
                      (65536, 65536, 4, 4),
                      )         #200% if higher (who has this anyway?)
            if desktop_scaling=="auto":
                pass
            elif desktop_scaling.startswith("auto:"):
                limstr = desktop_scaling[5:]    #ie: '1920x1080:1,2560x1600:1.5,...
                limp = limstr.split(",")
                limits = []
                for l in limp:
                    try:
                        ldef = l.split(":")
                        assert len(ldef)==2, "could not find 2 parts separated by ':' in '%s'" % ldef
                        dims = ldef[0].split("x")
                        assert len(dims)==2, "could not find 2 dimensions separated by 'x' in '%s'" % ldef[0]
                        x, y = int(dims[0]), int(dims[1])
                        scaleparts = ldef[1].replace("*", "x").replace("/", "x").split("x")
                        assert len(scaleparts)<=2, "found more than 2 scaling dimensions!"
                        if len(scaleparts)==1:
                            sx = sy = float(scaleparts[0])
                        else:
                            sx = float(scaleparts[0])
                            sy = float(scaleparts[1])
                        limits.append((x, y, sx, sy))
                        scalinglog("parsed desktop-scaling auto limits: %s", limits)
                    except Exception as e:
                        log.warn("Warning: failed to parse limit string '%s':", l)
                        log.warn(" %s", e)
                        log.warn(" should use the format WIDTHxHEIGTH:SCALINGVALUE")
            else:
                scalinglog.warn("Warning: invalid auto attributes '%s'", desktop_scaling[5:])
            sx, sy = 1, 1
            matched = False
            for mx, my, tsx, tsy in limits:
                if root_w*root_h<=mx*my:
                    sx, sy = tsx, tsy
                    matched = True
                    break
            scalinglog("matched=%s : %sx%s with limits %s: %sx%s", matched, root_w, root_h, limits, sx, sy)
            return sx,sy
        def parse_item(v):
            div = 1
            try:
                if v.endswith("%"):
                    div = 100
                    v = v[:-1]
            except:
                pass
            if div==1:
                try:
                    return int(v)       #ie: desktop-scaling=2
                except:
                    pass
            try:
                return float(v)/div     #ie: desktop-scaling=1.5
            except:
                pass
            #ie: desktop-scaling=3/2, or desktop-scaling=3:2
            pair = v.replace(":", "/").split("/", 1)
            try:
                return float(pair[0])/float(pair[1])
            except:
                pass
            scalinglog.warn("Warning: failed to parse scaling value '%s'", v)
            return None
        if desktop_scaling.find("x")>0 and desktop_scaling.find(":")>0:
            scalinglog.warn("Warning: found both 'x' and ':' in desktop-scaling fixed value")
            scalinglog.warn(" maybe the 'auto:' prefix is missing?")
            return 1, 1
        #split if we have two dimensions: "1600x1200" -> ["1600", "1200"], if not: "2" -> ["2"]
        values = desktop_scaling.replace(",", "x").split("x", 1)
        x = parse_item(values[0])
        if x is None:
            return 1, 1
        if len(values)==1:
            #just one value: use the same for X and Y
            y = x
        else:
            y = parse_item(values[1])
            if y is None:
                return 1, 1
        scalinglog("parse_scaling(%s) parsed items=%s", desktop_scaling, (x, y))
        #normalize absolute values into floats:
        if x>MAX_SCALING or y>MAX_SCALING:
            scalinglog(" normalizing dimensions to a ratio of %ix%i", root_w, root_h)
            x = float(x / root_w)
            y = float(y / root_h)
        if x<MIN_SCALING or y<MIN_SCALING or x>MAX_SCALING or y>MAX_SCALING:
            scalinglog.warn("Warning: scaling values %sx%s are out of range", x, y)
            return 1, 1
        scalinglog("parse_scaling(%s)=%s", desktop_scaling, (x, y))
        return x, y


    def run(self):
        if self.client_extras:
            self.idle_add(self.client_extras.ready)
        XpraClientBase.run(self)    #start network threads
        self._draw_thread.start()
        self.send_hello()


    def quit(self, exit_code=0):
        raise Exception("override me!")

    def cleanup(self):
        log("UIXpraClient.cleanup()")
        self.stop_sending_webcam()
        XpraClientBase.cleanup(self)
        #tell the draw thread to exit:
        dq = self._draw_queue
        if dq:
            dq.put(None)
        self.stop_all_sound()
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
        reaper_cleanup()
        log("UIXpraClient.cleanup() done")

    def stop_all_sound(self):
        if self.sound_source:
            self.stop_sending_sound()
        if self.sound_sink:
            self.stop_receiving_sound()

    def signal_cleanup(self):
        log("UIXpraClient.signal_cleanup()")
        XpraClientBase.signal_cleanup(self)
        reaper_cleanup()
        log("UIXpraClient.signal_cleanup() done")


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
            elapsed = max(0, time.time()-self._suspended_at)
            self._suspended_at = 0
        delta = datetime.timedelta(seconds=int(elapsed))
        log.info("system resumed, was suspended for %s", delta)
        #this will reset the refresh rate too:
        self.send_refresh_all()
        if self.opengl_enabled:
            #with opengl, the buffers sometimes contain garbage after resuming,
            #this should create new backing buffers:
            self.reinit_windows()
        self.reinit_window_icons()


    def control_refresh(self, wid, suspend_resume, refresh, quality=100, options={}, client_properties={}):
        packet = ["buffer-refresh", wid, 0, quality]
        options["refresh-now"] = bool(refresh)
        if suspend_resume is True:
            options["batch"] = {
                "reset"     : True,
                "delay"     : 1000,
                "locked"    : True,
                "always"    : True,
                }
        elif suspend_resume is False:
            options["batch"] = {"reset"     : True}
        else:
            pass    #batch unchanged
        log("sending buffer refresh: options=%s, client_properties=%s", options, client_properties)
        packet.append(options)
        packet.append(client_properties)
        self.send(*packet)

    def send_refresh(self, wid):
        packet = ["buffer-refresh", wid, 0, 100,
        #explicit refresh (should be assumed True anyway),
        #also force a reset of batch configs:
                       {
                       "refresh-now"    : True,
                       "batch"          : {"reset" : True}
                       },
                       {}   #no client_properties
                 ]
        self.send(*packet)

    def send_refresh_all(self):
        log("Automatic refresh for all windows ")
        self.send_refresh(-1)


    def show_about(self, *_args):
        log.warn("show_about() is not implemented in %s", self)

    def show_session_info(self, *_args):
        log.warn("show_session_info() is not implemented in %s", self)

    def show_bug_report(self, *_args):
        log.warn("show_bug_report() is not implemented in %s", self)


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

    def get_cursor_encodings(self):
        e = ["raw"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def get_window_icon_encodings(self):
        e = ["premult_argb32"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def do_get_core_encodings(self):
        """
            This method returns the actual encodings supported.
            ie: ["rgb24", "vp8", "png", "png/L", "png/P", "jpeg", "h264", "vpx"]
            It is often overriden in the actual client class implementations,
            where extra encodings can be added (generally just 'rgb32' for transparency),
            or removed if the toolkit implementation class is more limited.
        """
        #we always support rgb24:
        core_encodings = ["rgb24"]
        for codec in ("dec_pillow", ):
            if has_codec(codec):
                c = get_codec(codec)
                for e in c.get_encodings():
                    if e not in core_encodings:
                        core_encodings.append(e)
        #we enable all the video decoders we know about,
        #what will actually get used by the server will still depend on the csc modes supported
        video_decodings = getVideoHelper().get_decodings()
        log("video_decodings=%s", video_decodings)
        for encoding in video_decodings:
            if encoding not in core_encodings:
                core_encodings.append(encoding)
        #remove duplicates and use prefered encoding order:
        core_encodings = [x for x in PREFERED_ENCODING_ORDER if x in set(core_encodings) and x in self.allowed_encodings]
        log("do_get_core_encodings()=%s", core_encodings)
        return core_encodings


    def get_clipboard_helper_classes(self):
        return []

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


    def make_notifier(self):
        nc = self.get_notifier_classes()
        notifylog("make_notifier() notifier classes: %s", nc)
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
        return self.make_instance(tc, self, *args)

    def get_system_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_system_tray_classes()


    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.get_tray_classes()
        traylog("make_tray%s tray classes=%s", args, tc)
        return self.make_instance(tc, self, *args)

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
                log("make_instance(%s, %s)", class_options, args, exc_info=True)
                log.error("Error: cannot instantiate %s:", c)
                log.error(" with arguments %s", list(args))
        return None


    def show_menu(self, *_args):
        if self.menu_helper:
            self.menu_helper.activate()

    def setup_xpra_tray(self, tray_icon_filename):
        tray = None
        #this is our own tray
        def xpra_tray_click(button, pressed, time=0):
            traylog("xpra_tray_click(%s, %s, %s)", button, pressed, time)
            if button==1 and pressed:
                self.idle_add(self.menu_helper.activate, button, time)
            elif button==3 and not pressed:
                self.idle_add(self.menu_helper.popup, button, time)
        def xpra_tray_mouseover(*args):
            traylog("xpra_tray_mouseover(%s)", args)
        def xpra_tray_exit(*args):
            traylog("xpra_tray_exit(%s)", args)
            self.disconnect_and_quit(0, CLIENT_EXIT)
        def xpra_tray_geometry(*args):
            if tray:
                traylog("xpra_tray_geometry%s geometry=%s", args, tray.get_geometry())
        menu = None
        if self.menu_helper:
            menu = self.menu_helper.build()
        tray = self.make_tray(XPRA_APP_ID, menu, self.get_tray_title(), tray_icon_filename, xpra_tray_geometry, xpra_tray_click, xpra_tray_mouseover, xpra_tray_exit)
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
                button_packet = ["button-action", wid, button, pressed, (x, y), modifiers]
                traylog("button_packet=%s", button_packet)
                self.send_positional(button_packet)
                tray.reconfigure()
        def tray_mouseover(x, y):
            tray = self._id_to_window.get(wid)
            traylog("tray_mouseover(%s, %s) tray=%s", x, y, tray)
            if tray:
                modifiers = self.get_current_modifiers()
                buttons = []
                pointer_packet = ["pointer-position", wid, self.cp(x, y), modifiers, buttons]
                traylog("pointer_packet=%s", pointer_packet)
                self.send_mouse_position(pointer_packet)
        def do_tray_geometry(*args):
            #tell the "ClientTray" where it now lives
            #which should also update the location on the server if it has changed
            tray = self._id_to_window.get(wid)
            if tray_widget:
                geom = tray_widget.get_geometry()
            else:
                geom = None
            traylog("tray_geometry(%s) widget=%s, geometry=%s tray=%s", args, tray_widget, geom, tray)
            if tray and geom:
                tray.move_resize(*geom)
        def tray_geometry(*args):
            #the tray widget may still be None if we haven't returned from make_system_tray yet,
            #in which case we will check the geometry a little bit later:
            if tray_widget:
                do_tray_geometry(*args)
            else:
                self.idle_add(do_tray_geometry, *args)
        def tray_exit(*args):
            traylog("tray_exit(%s)", args)
        #TODO: use the pid instead?
        app_id = wid
        tray_widget = self.make_system_tray(app_id, None, title, None, tray_geometry, tray_click, tray_mouseover, tray_exit)
        traylog("setup_system_tray%s tray_widget=%s", (client, wid, w, h, title), tray_widget)
        assert tray_widget, "could not instantiate a system tray for tray id %s" % wid
        tray_widget.show()
        return ClientTray(client, wid, w, h, tray_widget, self.mmap_enabled, self.mmap)


    def desktops_changed(self, *args):
        workspacelog("desktops_changed%s", args)
        self.screen_size_changed(*args)

    def workspace_changed(self, *args):
        workspacelog("workspace_changed%s", args)
        for win in self._id_to_window.values():
            win.workspace_changed()

    def screen_size_changed(self, *args):
        screenlog("screen_size_changed(%s) pending=%s", args, self.screen_size_change_pending)
        if self.screen_size_change_pending:
            return
        #update via timer so the data is more likely to be final (up to date) when we query it,
        #some properties (like _NET_WORKAREA for X11 clients via xposix "ClientExtras") may
        #trigger multiple calls to screen_size_changed, delayed by some amount
        #(sometimes up to 1s..)
        self.screen_size_change_pending = True
        delay = 1000
        #if we are suspending, wait longer:
        #(better chance that the suspend-resume cycle will have completed)
        if self._suspended_at>0 and self._suspended_at-monotonic_time()<5*1000:
            delay = 5*1000
        self.timeout_add(delay, self.do_process_screen_size_change)

    def do_process_screen_size_change(self):
        self.update_screen_size()
        screenlog("do_process_screen_size_change() MONITOR_CHANGE_REINIT=%s, REINIT_WINDOWS=%s", MONITOR_CHANGE_REINIT, REINIT_WINDOWS)
        if MONITOR_CHANGE_REINIT and MONITOR_CHANGE_REINIT=="0":
            return
        if MONITOR_CHANGE_REINIT or REINIT_WINDOWS:
            screenlog.info("screen size change: will reinit the windows")
            self.reinit_windows()
            self.reinit_window_icons()


    def update_screen_size(self):
        self.screen_size_change_pending = False
        u_root_w, u_root_h = self.get_root_size()
        root_w, root_h = self.cp(u_root_w, u_root_h)
        self._current_screen_sizes = self.get_screen_sizes()
        sss = self.get_screen_sizes(self.xscale, self.yscale)
        ndesktops = get_number_of_desktops()
        desktop_names = get_desktop_names()
        screenlog("update_screen_size() sizes=%s, %s desktops: %s", sss, ndesktops, desktop_names)
        if self.dpi>0:
            #use command line value supplied, but scale it:
            xdpi = self.cx(self.dpi)
            ydpi = self.cy(self.dpi)
        else:
            #not supplied, use platform detection code:
            xdpi = self.cx(get_xdpi())
            ydpi = self.cy(get_ydpi())
            screenlog("dpi: %s -> %s", (get_xdpi(), get_ydpi()), (xdpi, ydpi))
        screen_settings = (root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi)
        screenlog("update_screen_size()     new settings=%s", screen_settings)
        screenlog("update_screen_size() current settings=%s", self._last_screen_settings)
        if self._last_screen_settings==screen_settings:
            log("screen size unchanged")
            return
        screenlog.info("sending updated screen size to server: %sx%s with %s screens", root_w, root_h, len(sss))
        log_screen_sizes(root_w, root_h, sss)
        self.send("desktop_size", *screen_settings)
        self._last_screen_settings = screen_settings
        #update the max packet size (may have gone up):
        self.set_max_packet_size()


    def scaleup(self):
        scaling = max(self.xscale, self.yscale)
        options = [v for v in SCALING_OPTIONS if r4cmp(v, 10)>r4cmp(scaling, 10)]
        scalinglog("scaleup() options>%s : %s", r4cmp(scaling, 1000)/1000.0, options)
        if options:
            self._scaleto(min(options))

    def scaledown(self):
        scaling = max(self.xscale, self.yscale)
        options = [v for v in SCALING_OPTIONS if r4cmp(v, 10)<r4cmp(scaling, 10)]
        scalinglog("scaledown() options<%s : %s", r4cmp(scaling, 1000)/1000.0, options)
        if options:
            self._scaleto(max(options))

    def _scaleto(self, new_scaling):
        scaling = max(self.xscale, self.yscale)
        scalinglog("_scaleto(%s) current value=%s", r4cmp(new_scaling, 1000)/1000.0, r4cmp(scaling, 1000)/1000.0)
        if new_scaling>0:
            self.scale_change(new_scaling/scaling, new_scaling/scaling)

    def scalingoff(self):
        self.scaleset(1, 1)

    def scalereset(self):
        self.scaleset(*self.initial_scaling)

    def scaleset(self, xscale=1, yscale=1):
        scalinglog("scaleset(%s, %s) current scaling: %s, %s", xscale, yscale, self.xscale, self.yscale)
        self.scale_change(float(xscale)/self.xscale, float(yscale)/self.yscale)

    def scale_change(self, xchange=1, ychange=1):
        scalinglog("scale_change(%s, %s)", xchange, ychange)
        if self.server_is_desktop and self.desktop_fullscreen:
            scalinglog("scale_change(%s, %s) ignored, fullscreen shadow mode is active", xchange, ychange)
            return
        if not self.can_scale:
            scalinglog("scale_change(%s, %s) ignored, scaling is disabled", xchange, ychange)
            return
        if self.screen_size_change_pending:
            scalinglog("scale_change(%s, %s) screen size change is already pending", xchange, ychange)
            return
        if monotonic_time()<self.scale_change_embargo:
            scalinglog("scale_change(%s, %s) screen size change not permitted during embargo time - try again", xchange, ychange)
            return
        def clamp(v):
            return max(MIN_SCALING, min(MAX_SCALING, v))
        xscale = clamp(self.xscale*xchange)
        yscale = clamp(self.yscale*ychange)
        scalinglog("scale_change xscale: clamp(%s*%s)=%s", self.xscale, xchange, xscale)
        scalinglog("scale_change yscale: clamp(%s*%s)=%s", self.yscale, ychange, yscale)
        if fequ(xscale, self.xscale) and fequ(yscale, self.yscale):
            scalinglog("scaling unchanged: %sx%s", self.xscale, self.yscale)
            return
        #re-calculate change values against clamped scale:
        xchange = xscale / self.xscale
        ychange = yscale / self.yscale
        #check against maximum server supported size:
        maxw, maxh = self.server_max_desktop_size
        root_w, root_h = self.get_root_size()
        sw = int(root_w / xscale)
        sh = int(root_h / yscale)
        scalinglog("scale_change root size=%s x %s, scaled to %s x %s", root_w, root_h, sw, sh)
        scalinglog("scale_change max server desktop size=%s x %s", maxw, maxh)
        if not self.server_is_desktop and (sw>(maxw+1) or sh>(maxh+1)):
            #would overflow..
            scalinglog.warn("Warning: cannot scale by %i%% x %i%% or lower", (100*xscale), (100*yscale))
            scalinglog.warn(" the scaled client screen %i x %i -> %i x %i", root_w, root_h, sw, sh)
            scalinglog.warn(" would overflow the server's screen: %i x %i", maxw, maxh)
            return
        self.xscale = xscale
        self.yscale = yscale
        scalinglog("scale_change new scaling: %sx%s, change: %sx%s", self.xscale, self.yscale, xchange, ychange)
        self.scale_reinit(xchange, ychange)

    def scale_reinit(self, xchange=1.0, ychange=1.0):
        #wait at least one second before changing again:
        self.scale_change_embargo = monotonic_time()+SCALING_EMBARGO_TIME
        if fequ(self.xscale, self.yscale):
            scalinglog.info("setting scaling to %i%%:", iround(100*self.xscale))
        else:
            scalinglog.info("setting scaling to %i%% x %i%%:", iround(100*self.xscale), iround(100*self.yscale))
        self.update_screen_size()
        #re-initialize all the windows with their new size
        def new_size_fn(w, h):
            minx, miny = 16384, 16384
            if self.max_window_size!=(0, 0):
                minx, miny = self.max_window_size
            return max(1, min(minx, int(w*xchange))), max(1, min(miny, int(h*ychange)))
        self.reinit_windows(new_size_fn)
        self.reinit_window_icons()
        self.emit("scaling-changed")


    def get_screen_sizes(self, xscale=1, yscale=1):
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


    def init_mmap(self, mmap_filename, mmap_group, socket_filename):
        log("init_mmap(%s, %s, %s)", mmap_filename, mmap_group, socket_filename)
        from xpra.os_util import get_int_uuid
        from xpra.net.mmap_pipe import init_client_mmap, write_mmap_token, DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES
        #calculate size:
        root_w, root_h = self.cp(*self.get_root_size())
        #at least 256MB, or 8 fullscreen RGBX frames:
        mmap_size = max(256*1024*1024, root_w*root_h*4*8)
        mmap_size = min(1024*1024*1024, mmap_size)
        self.mmap_enabled, self.mmap_delete, self.mmap, self.mmap_size, self.mmap_tempfile, self.mmap_filename = \
            init_client_mmap(mmap_group, socket_filename, mmap_size, self.mmap_filename)
        if self.mmap_enabled:
            self.mmap_token = get_int_uuid()
            self.mmap_token_bytes = DEFAULT_TOKEN_BYTES
            self.mmap_token_index = self.mmap_size - DEFAULT_TOKEN_BYTES
            #self.mmap_token_index = DEFAULT_TOKEN_INDEX*2
            #write the token twice:
            # once at the old default offset for older servers,
            # and at the offset we want to use with new servers
            for index in (DEFAULT_TOKEN_INDEX, self.mmap_token_index):
                write_mmap_token(self.mmap, self.mmap_token, index, self.mmap_token_bytes)

    def clean_mmap(self):
        log("XpraClient.clean_mmap() mmap_filename=%s", self.mmap_filename)
        if self.mmap_tempfile:
            try:
                self.mmap_tempfile.close()
            except Exception as e:
                log("clean_mmap error closing file %s: %s", self.mmap_tempfile, e)
            self.mmap_tempfile = None
        if self.mmap_delete:
            #this should be redundant: closing the tempfile should get it deleted
            if self.mmap_filename and os.path.exists(self.mmap_filename):
                from xpra.net.mmap_pipe import clean_mmap
                clean_mmap(self.mmap_filename)
                self.mmap_filename = None


    def init_opengl(self, _enable_opengl):
        self.opengl_enabled = False
        self.client_supports_opengl = False
        self.opengl_props = {"info" : "not supported"}


    def scale_pointer(self, pointer):
        return int(pointer[0]/self.xscale), int(pointer[1]/self.yscale)


    def send_wheel_delta(self, wid, button, distance, *args):
        modifiers = self.get_current_modifiers()
        pointer = self.get_mouse_position()
        buttons = []
        mouselog("send_wheel_delta(%i, %i, %.4f, %s) precise wheel=%s, modifiers=%s, pointer=%s", wid, button, distance, args, self.server_precise_wheel, modifiers, pointer)
        if self.server_precise_wheel:
            #send the exact value multiplied by 1000 (as an int)
            idist = int(distance*1000)
            if abs(idist)>0:
                packet =  ["wheel-motion", wid,
                           button, idist,
                           pointer, modifiers, buttons] + list(args)
                mouselog.info("%s", packet)
                self.send_positional(packet)
            return 0
        else:
            #server cannot handle precise wheel,
            #so we have to use discrete events,
            #and send a click for each step:
            steps = abs(int(distance))
            for _ in range(steps):
                self.send_button(wid, button, True, pointer, modifiers, buttons)
                self.send_button(wid, button, False, pointer, modifiers, buttons)
            #return remainder:
            return float(distance) - int(distance)

    def wheel_event(self, wid, deltax=0, deltay=0, deviceid=0):
        #this is a different entry point for mouse wheel events,
        #which provides finer grained deltas (if supported by the server)
        #accumulate deltas:
        self.wheel_deltax += deltax
        self.wheel_deltay += deltay
        button = self.wheel_map.get(6+int(self.wheel_deltax>0))            #RIGHT=7, LEFT=6
        if button>0:
            self.wheel_deltax = self.send_wheel_delta(wid, button, self.wheel_deltax, deviceid)
        button = self.wheel_map.get(5-int(self.wheel_deltay>0))            #UP=4, DOWN=5
        if button>0:
            self.wheel_deltay = self.send_wheel_delta(wid, button, self.wheel_deltay, deviceid)
        log.info("wheel_delta%s new deltas=%s,%s", (wid, deltax, deltay, deviceid), self.wheel_deltax, self.wheel_deltay)

    def send_button(self, wid, button, pressed, pointer, modifiers, buttons, *args):
        pressed_state = self._button_state.get(button, False)
        if SKIP_DUPLICATE_BUTTON_EVENTS and pressed_state==pressed:
            mouselog("button action: unchanged state, ignoring event")
            return
        self._button_state[button] = pressed
        packet =  ["button-action", wid,
                   button, pressed,
                   pointer, modifiers, buttons] + list(args)
        mouselog("button packet: %s", packet)
        self.send_positional(packet)


    def window_keyboard_layout_changed(self, window):
        #win32 can change the keyboard mapping per window...
        keylog("window_keyboard_layout_changed(%s)", window)
        if self.keyboard_helper:
            self.keyboard_helper.keymap_changed()

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


    def send_start_command(self, name, command, ignore, sharing=True):
        log("send_start_command(%s, %s, %s, %s)", name, command, ignore, sharing)
        self.send("start-command", name, command, ignore, sharing)


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
            if wid and self._focused and self._focused!=wid:
                #if this window lost focus, it must have had it!
                #(catch up - makes things like OR windows work:
                # their parent receives the focus-out event)
                focuslog("window %s lost a focus it did not have!? (simulating focus before losing it)", wid)
                self.send_focus(wid)
            if self.keyboard_helper:
                self.keyboard_helper.clear_repeat()
            if self._focused:
                #send the lost-focus via a timer and re-check it
                #(this allows a new window to gain focus without having to do a reset_focus)
                def send_lost_focus():
                    #check that a new window has not gained focus since:
                    if self._focused is None:
                        self.send_focus(0)
                self.timeout_add(20, send_lost_focus)
                self._focused = None

    def do_force_ungrab(self, wid):
        grablog("do_force_ungrab(%s)", wid)
        #ungrab via dedicated server packet:
        self.send_force_ungrab(wid)

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

    def window_close_event(self, wid):
        windowlog("window_close_event(%s) close window action=%s", wid, self.window_close_action)
        if self.window_close_action=="forward":
            self.send("close-window", wid)
        elif self.window_close_action=="ignore":
            windowlog("close event for window %i ignored", wid)
        elif self.window_close_action=="disconnect":
            log.info("window-close set to disconnect, exiting (window %i)", wid)
            self.quit(0)
        elif self.window_close_action=="shutdown":
            self.send("shutdown-server", "shutdown on window close")
        elif self.window_close_action=="auto":
            #forward unless this looks like a desktop
            #this allows us behave more like VNC:
            window = self._id_to_window.get(wid)
            log("window_close_event(%i) window=%s", wid, window)
            if self.server_is_desktop:
                log.info("window-close event on desktop or shadow window, disconnecting")
                self.quit(0)
                return True
            if window:
                metadata = getattr(window, "_metadata", {})
                log("window_close_event(%i) metadata=%s", wid, metadata)
                class_instance = metadata.get("class-instance")
                title = metadata.get("title", "")
                log("window_close_event(%i) title=%s, class-instance=%s", wid, title, class_instance)
                matching_title_close = [x for x in TITLE_CLOSEEXIT if x and title.startswith(x)]
                if matching_title_close:
                    log.info("window-close event on %s window, disconnecting", title)
                    self.quit(0)
                    return True
                if class_instance and class_instance[1] in WM_CLASS_CLOSEEXIT:
                    log.info("window-close event on %s window, disconnecting", class_instance[0])
                    self.quit(0)
                    return True
            #default to forward:
            self.send("close-window", wid)
        else:
            log.warn("unknown close-window action: %s", self.window_close_action)
        return True


    def get_version_info(self):
        return get_version_info_full()

    def make_hello(self):
        capabilities = XpraClientBase.make_hello(self)
        updict(capabilities, "platform",  get_platform_info())
        capabilities["session-type"] = get_session_type()
        if self.readonly:
            #don't bother sending keyboard info, as it won't be used
            capabilities["keyboard"] = False
        else:
            capabilities.update(self.get_keymap_properties())
            #show the user a summary of what we have detected:
            self.keyboard_helper.log_keyboard_info()

        capabilities["modifiers"] = self.get_current_modifiers()
        u_root_w, u_root_h = self.get_root_size()
        wm_name = get_wm_name()
        if wm_name:
            capabilities["wm_name"] = wm_name
        capabilities["desktop_size"] = self.cp(u_root_w, u_root_h)
        ndesktops = get_number_of_desktops()
        capabilities["desktops"] = ndesktops
        desktop_names = get_desktop_names()
        capabilities["desktop.names"] = desktop_names
        ss = self.get_screen_sizes()
        self._current_screen_sizes = ss
        log.info(" desktop size is %sx%s with %s screen%s:", u_root_w, u_root_h, len(ss), engs(ss))
        log_screen_sizes(u_root_w, u_root_h, ss)
        if self.xscale!=1 or self.yscale!=1:
            capabilities["screen_sizes.unscaled"] = ss
            capabilities["desktop_size.unscaled"] = u_root_w, u_root_h
            root_w, root_h = self.cp(u_root_w, u_root_h)
            if fequ(self.xscale, self.yscale):
                sinfo = "%i%%" % iround(self.xscale*100)
            else:
                sinfo = "%i%% x %i%%" % (iround(self.xscale*100), iround(self.yscale*100))
            log.info(" %sscaled by %s, virtual screen size: %ix%i", ["down", "up"][int(u_root_w>root_w or u_root_h>root_h)], sinfo, root_w, root_h)
            sss = self.get_screen_sizes(self.xscale, self.yscale)
            log_screen_sizes(root_w, root_h, sss)
        else:
            root_w, root_h = u_root_w, u_root_h
            sss = ss
        capabilities["screen_sizes"] = sss
        #command line (or config file) override supplied:
        dpi = 0
        if self.dpi>0:
            #scale it:
            xdpi = ydpi = dpi = self.cx(self.cy(self.dpi))
        else:
            #not supplied, use platform detection code:
            #platforms may also provide per-axis dpi (later win32 versions do)
            xdpi = get_xdpi()
            ydpi = get_ydpi()
            screenlog("xdpi=%i, ydpi=%i", xdpi, ydpi)
            if xdpi>0 and ydpi>0:
                xdpi = self.cx(xdpi)
                ydpi = self.cy(ydpi)
                dpi = iround((xdpi+ydpi)/2.0)
                capabilities.update({
                                     "dpi.x"    : xdpi,
                                     "dpi.y"    : ydpi,
                                     })
        if dpi:
            capabilities["dpi"] = dpi
        screenlog("dpi: %i", dpi)
        self._last_screen_settings = (root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi)

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
            capabilities.update({
                "mmap_file"         : self.mmap_filename,
                "mmap_size"         : self.mmap_size,
                "mmap_token"        : self.mmap_token,
                "mmap_token_index"  : self.mmap_token_index,
                "mmap_token_bytes"  : self.mmap_token_bytes,
                })
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
            #generic server flags:
            "notify-startup-complete"   : True,
            "wants_events"              : True,
            "wants_default_cursor"      : True,
            "randr_notify"              : True,
            "screen-scaling"            : True,
            "screen-scaling.enabled"    : (self.xscale!=1 or self.yscale!=1),
            "screen-scaling.values"     : (int(1000*self.xscale), int(1000*self.yscale)),
            #mouse and cursors:
            "mouse.show"                : MOUSE_SHOW,
            "mouse.initial-position"    : self.get_mouse_position(),
            "named_cursors"             : False,
            "cursors"                   : self.client_supports_cursors,
            "double_click.time"         : get_double_click_time(),
            "double_click.distance"     : get_double_click_distance(),
            #features:
            "notifications"             : self.client_supports_notifications,
            "bell"                      : self.client_supports_bell,
            "vrefresh"                  : get_vrefresh(),
            "share"                     : self.client_supports_sharing,
            "windows"                   : self.windows_enabled,
            "show-desktop"              : True,
            "system_tray"               : self.client_supports_system_tray,
            "info-namespace"            : True,
            #window meta data and handling:
            "generic_window_types"      : True,
            "server-window-move-resize" : True,
            "server-window-resize"      : True,
            #encoding related:
            "raw_window_icons"          : True,
            "generic-rgb-encodings"     : True,
            "auto_refresh_delay"        : int(self.auto_refresh_delay*1000),
            "encodings"                 : self.get_encodings(),
            "encodings.core"            : self.get_core_encodings(),
            "encodings.window-icon"     : self.get_window_icon_encodings(),
            "encodings.cursor"          : self.get_cursor_encodings(),
            #sound:
            "sound.server_driven"       : True,
            "sound.ogg-latency-fix"     : True,
            "av-sync"                   : self.av_sync,
            "av-sync.delay.default"     : 0,    #start at 0 and rely on sound-control packets to set the correct value
            })
        updict(capabilities, "window", {
            "raise"                     : True,
            #only implemented on posix with the gtk client:
            "initiate-moveresize"       : False,
            "resize-counter"            : True,
            })
        updict(capabilities, "clipboard", {
            ""                          : self.client_supports_clipboard,
            "notifications"             : self.client_supports_clipboard,
            "selections"                : CLIPBOARDS,
            #buggy osx clipboards:
            "want_targets"              : CLIPBOARD_WANT_TARGETS,
            #buggy osx and win32 clipboards:
            "greedy"                    : CLIPBOARD_GREEDY,
            "set_enabled"               : True,
            })
        if B_FRAMES:
            video_b_frames = ["h264"]   #only tested with dec_avcodec2
        else:
            video_b_frames = []
        updict(capabilities, "encoding", {
            "flush"                     : PAINT_FLUSH,
            "scaling.control"           : self.video_scaling,
            "client_options"            : True,
            "csc_atoms"                 : True,
            #TODO: check for csc support (swscale only?)
            "video_reinit"              : True,
            "video_scaling"             : True,
            "video_b_frames"            : video_b_frames,
            "transparency"              : self.has_transparency(),
            "rgb24zlib"                 : True,
            "max-soft-expired"          : MAX_SOFT_EXPIRED,
            "send-timestamps"           : SEND_TIMESTAMPS,
            })
        capabilities.update({
                             "antialias"    : get_antialias_info(),
                             "icc"          : self.get_icc_info(),
                             "display-icc"  : self.get_display_icc_info(),
                             "cursor.size"  : int(2*get_cursor_size()/(self.xscale+self.yscale)),
                             })
        #generic rgb compression flags:
        for x in compression.ALL_COMPRESSORS:
            capabilities["encoding.rgb_%s" % x] = x in compression.get_enabled_compressors()

        control_commands = ["show_session_info", "show_bug_report", "debug"]
        for x in compression.get_enabled_compressors():
            control_commands.append("enable_"+x)
        for x in packet_encoding.get_enabled_encoders():
            control_commands.append("enable_"+x)
        capabilities["control_commands"] = control_commands
        log("control_commands=%s", control_commands)

        encoding_caps = {}
        if self.encoding:
            encoding_caps[""] = self.encoding
        for k,v in codec_versions.items():
            encoding_caps["%s.version" % k] = v
        if self.quality>0:
            encoding_caps["quality"] = self.quality
        if self.min_quality>0:
            encoding_caps["min-quality"] = self.min_quality
        if self.speed>=0:
            encoding_caps["speed"] = self.speed
        if self.min_speed>=0:
            encoding_caps["min-speed"] = self.min_speed

        #these are the defaults - when we instantiate a window,
        #we can send different values as part of the map event
        #these are the RGB modes we want (the ones we are expected to be able to paint with):
        rgb_formats = ["RGB", "RGBX", "RGBA"]
        encoding_caps["rgb_formats"] = rgb_formats
        #figure out which CSC modes (usually YUV) can give us those RGB modes:
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*rgb_formats)
        log("supported full csc_modes=%s", full_csc_modes)
        encoding_caps["full_csc_modes"] = full_csc_modes

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
                        encoding_caps["%s.%s.profile" % (h264_name, old_csc_name)] = profile
                        encoding_caps["%s.%s.profile" % (h264_name, csc_name)] = profile
            log("x264 encoding options: %s", str([(k,v) for k,v in encoding_caps.items() if k.startswith("x264.")]))
        iq = max(self.min_quality, self.quality)
        if iq<0:
            iq = 70
        encoding_caps["initial_quality"] = iq
        log("encoding capabilities: %s", encoding_caps)
        updict(capabilities, "encoding", encoding_caps)
        self.encoding_defaults = encoding_caps
        #hack: workaround namespace issue ("encodings" vs "encoding"..)
        capabilities["encodings.rgb_formats"] = rgb_formats

        if self.sound_properties:
            sound_caps = self.sound_properties.copy()
            #we don't know if the server supports new codec names,
            #so always add legacy names in hello:
            sound_caps.update({
                               "codec-full-names"  : True,
                               "decoders"   : add_legacy_names(self.speaker_codecs),
                               "encoders"   : add_legacy_names(self.microphone_codecs),
                               "send"       : self.microphone_allowed,
                               "receive"    : self.speaker_allowed,
                               })
            try:
                from xpra.sound.pulseaudio.pulseaudio_util import get_info as get_pa_info
                sound_caps.update(get_pa_info())
            except Exception:
                pass
            updict(capabilities, "sound", sound_caps)
            soundlog("sound capabilities: %s", sound_caps)
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

    def get_icc_info(self):
        return get_icc_info()

    def get_display_icc_info(self):
        return get_display_icc_info()


    def server_ok(self):
        return self._server_ok

    def check_server_echo(self, ping_sent_time):
        if self._protocol is None:
            #no longer connected!
            return False
        last = self._server_ok
        if FAKE_BROKEN_CONNECTION>0:
            self._server_ok = (int(monotonic_time()) % FAKE_BROKEN_CONNECTION) <= (FAKE_BROKEN_CONNECTION//2)
        else:
            self._server_ok = self.last_ping_echoed_time>=ping_sent_time
        log("check_server_echo(%s) last=%s, server_ok=%s (last_ping_echoed_time=%s)", ping_sent_time, last, self._server_ok, self.last_ping_echoed_time)
        if last!=self._server_ok and not self._server_ok:
            log.info("server is not responding, drawing spinners over the windows")
            def timer_redraw():
                if self._protocol is None:
                    #no longer connected!
                    return False
                ok = self.server_ok()
                self.redraw_spinners()
                if ok:
                    log.info("server is OK again")
                return not ok           #repaint again until ok
            self.idle_add(self.redraw_spinners)
            self.timeout_add(250, timer_redraw)
        return False

    def redraw_spinners(self):
        #draws spinner on top of the window, or not (plain repaint)
        #depending on whether the server is ok or not
        ok = self.server_ok()
        log("redraw_spinners() ok=%s", ok)
        for w in self._id_to_window.values():
            if not w.is_tray():
                w.spinner(ok)

    def check_echo_timeout(self, ping_time):
        netlog("check_echo_timeout(%s) last_ping_echoed_time=%s", ping_time, self.last_ping_echoed_time)
        if self.last_ping_echoed_time<ping_time:
            #no point trying to use disconnect_and_quit() to tell the server here..
            self.warn_and_quit(EXIT_TIMEOUT, "server ping timeout - waited %s seconds without a response" % PING_TIMEOUT)

    def send_ping(self):
        now_ms = int(1000.0*monotonic_time())
        self.send("ping", now_ms)
        self.timeout_add(PING_TIMEOUT*1000, self.check_echo_timeout, now_ms)
        wait = 2.0
        if len(self.server_ping_latency)>0:
            l = [x for _,x in list(self.server_ping_latency)]
            avg = sum(l) / len(l)
            wait = min(5, 1.0+avg*2.0)
            netlog("send_ping() timestamp=%s, average server latency=%.1f, using max wait %.2fs", now_ms, 1000.0*avg, wait)
        self.timeout_add(int(1000.0*wait), self.check_server_echo, now_ms)
        return True

    def _process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, cl = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        self.check_server_echo(0)
        server_ping_latency = monotonic_time()-echoedtime/1000.0
        self.server_ping_latency.append((monotonic_time(), server_ping_latency))
        self.server_load = l1, l2, l3
        if cl>=0:
            self.client_ping_latency.append((monotonic_time(), cl/1000.0))
        netlog("ping echo server load=%s, measured client latency=%sms", self.server_load, cl)

    def _process_ping(self, packet):
        echotime = packet[1]
        l1,l2,l3 = 0,0,0
        if POSIX:
            try:
                (fl1, fl2, fl3) = os.getloadavg()
                l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
            except (OSError, AttributeError):
                pass
        sl = -1
        if len(self.server_ping_latency)>0:
            _, sl = self.server_ping_latency[-1]
        self.send("ping_echo", echotime, l1, l2, l3, int(1000.0*sl))


    def _process_server_event(self, packet):
        log(u": ".join((str(x) for x in packet[1:])))


    def _process_info_response(self, packet):
        self.info_request_pending = False
        self.server_last_info = packet[1]
        log("info-response: %s", self.server_last_info)
        if LOG_INFO_RESPONSE:
            items = LOG_INFO_RESPONSE.split(",")
            logres = [re.compile(v) for v in items]
            log.info("info-response debug for %s:", csv(["'%s'" % x for x in items]))
            for k in sorted(self.server_last_info.keys()):
                if any(lr.match(k) for lr in logres):
                    log.info(" %s=%s", k, self.server_last_info[k])

    def send_info_request(self):
        if not self.info_request_pending:
            self.info_request_pending = True
            self.send("info-request", [self.uuid], list(self._id_to_window.keys()))


    def send_quality(self):
        q = self.quality
        log("send_quality() quality=%s", q)
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        self.send("quality", q)

    def send_min_quality(self):
        q = self.min_quality
        log("send_min_quality() min-quality=%s", q)
        assert q==-1 or (q>=0 and q<=100), "invalid min-quality: %s" % q
        self.send("min-quality", q)

    def send_speed(self):
        s = self.speed
        log("send_speed() min-speed=%s", s)
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("speed", s)

    def send_min_speed(self):
        s = self.min_speed
        log("send_min_speed() min-speed=%s", s)
        assert s==-1 or (s>=0 and s<=100), "invalid min-speed: %s" % s
        self.send("min-speed", s)


    def server_connection_established(self):
        if XpraClientBase.server_connection_established(self):
            #process the rest from the UI thread:
            self.idle_add(self.process_ui_capabilities)


    def parse_server_capabilities(self):
        if not XpraClientBase.parse_server_capabilities(self):
            return  False
        c = self.server_capabilities
        if not self.session_name:
            self.session_name = c.strget("session_name", "")
        from xpra.platform import set_name
        set_name("Xpra", self.session_name or "Xpra")
        self.window_configure_pointer = c.boolget("window.configure.pointer")
        self.server_window_decorations = c.boolget("window.decorations")
        self.server_window_frame_extents = c.boolget("window.frame-extents")
        self.server_supports_notifications = c.boolget("notifications")
        self.notifications_enabled = self.client_supports_notifications
        self.server_supports_cursors = c.boolget("cursors", True)    #added in 0.5, default to True!
        self.cursors_enabled = self.server_supports_cursors and self.client_supports_cursors
        self.default_cursor_data = c.listget("cursor.default", None)
        self.server_supports_bell = c.boolget("bell")          #added in 0.5, default to True!
        self.bell_enabled = self.server_supports_bell and self.client_supports_bell
        self.server_supports_clipboard = c.boolget("clipboard")
        self.server_clipboard_direction = c.strget("clipboard-direction", "both")
        if self.server_clipboard_direction!=self.client_clipboard_direction and self.server_clipboard_direction!="both":
            if self.client_clipboard_direction=="disabled":
                pass
            elif self.server_clipboard_direction=="disabled":
                clipboardlog.warn("Warning: server clipboard synchronization is currently disabled")
                self.client_clipboard_direction = "disabled"
            elif self.client_clipboard_direction=="both":
                clipboardlog.warn("Warning: server only supports '%s' clipboard transfers", self.server_clipboard_direction)
                self.client_clipboard_direction = self.server_clipboard_direction
            else:
                clipboardlog.warn("Warning: incompatible clipboard direction settings")
                clipboardlog.warn(" server setting: %s, client setting: %s", self.server_clipboard_direction, self.client_clipboard_direction)
        self.server_supports_clipboard_enable_selections = c.boolget("clipboard.enable-selections")
        self.server_clipboards = c.strlistget("clipboards", ALL_CLIPBOARDS)
        clipboardlog("server clipboard: supported=%s, direction=%s, supports enable selection=%s",
                     self.server_supports_clipboard, self.server_clipboard_direction, self.server_supports_clipboard_enable_selections)
        clipboardlog("client clipboard: supported=%s, direction=%s",
                     self.client_supports_clipboard, self.client_clipboard_direction)

        self.server_compressors = c.strlistget("compressors", ["zlib"])
        self.clipboard_enabled = self.client_supports_clipboard and self.server_supports_clipboard
        self.server_dbus_proxy = c.boolget("dbus_proxy")
        #default for pre-0.16 servers:
        if self.server_dbus_proxy:
            default_rpc_types = ["dbus"]
        else:
            default_rpc_types = []
        self.server_rpc_types = c.strlistget("rpc-types", default_rpc_types)
        self.start_new_commands = c.boolget("start-new-commands")
        self.mmap_enabled = self.supports_mmap and self.mmap_enabled and c.boolget("mmap_enabled")
        if self.mmap_enabled:
            from xpra.net.mmap_pipe import read_mmap_token, DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES
            mmap_token = c.intget("mmap_token")
            mmap_token_index = c.intget("mmap_token_index", DEFAULT_TOKEN_INDEX)
            mmap_token_bytes = c.intget("mmap_token_bytes", DEFAULT_TOKEN_BYTES)
            token = read_mmap_token(self.mmap, mmap_token_index, mmap_token_bytes)
            if token!=mmap_token:
                log.error("Error: mmap token verification failed!")
                log.error(" expected '%#x'", mmap_token)
                log.error(" found '%#x'", token)
                self.mmap_enabled = False
                self.quit(EXIT_MMAP_TOKEN_FAILURE)
                return
            log.info("enabled fast mmap transfers using %sB shared memory area", std_unit(self.mmap_size, unit=1024))
        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()
        self.server_readonly = c.boolget("readonly")
        if self.server_readonly and not self.readonly:
            log.info("server is read only")
            self.readonly = True
        if self.windows_enabled:
            server_auto_refresh_delay = c.intget("auto_refresh_delay", 0)/1000.0
            if server_auto_refresh_delay==0 and self.auto_refresh_delay>0:
                log.warn("Warning: server does not support auto-refresh!")
        self.server_encodings = c.strlistget("encodings")
        self.server_core_encodings = c.strlistget("encodings.core", self.server_encodings)
        self.server_encodings_problematic = c.strlistget("encodings.problematic", PROBLEMATIC_ENCODINGS)  #server is telling us to try to avoid those
        self.server_encodings_with_speed = c.strlistget("encodings.with_speed", ("h264",)) #old servers only supported x264
        self.server_encodings_with_quality = c.strlistget("encodings.with_quality", ("jpeg", "h264"))
        self.server_encodings_with_lossless_mode = c.strlistget("encodings.with_lossless_mode", ())
        self.server_auto_video_encoding = c.boolget("auto-video-encoding")
        self.server_start_time = c.intget("start_time", -1)
        self.server_platform = c.strget("platform")

        self.server_display = c.strget("display")
        self.server_max_desktop_size = c.intpair("max_desktop_size")
        self.server_actual_desktop_size = c.intpair("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.server_randr = c.boolget("resize_screen")
        log("server has randr: %s", self.server_randr)
        self.server_av_sync = c.boolget("av-sync.enabled")
        avsynclog("av-sync: server=%s, client=%s", self.server_av_sync, self.av_sync)
        e = c.strget("encoding")
        if e:
            if self.encoding and e!=self.encoding:
                if self.encoding not in self.server_core_encodings:
                    log.warn("server does not support %s encoding and has switched to %s", self.encoding, e)
                else:
                    log.info("server is using %s encoding instead of %s", e, self.encoding)
            self.encoding = e
        i = platform_name(self._remote_platform, c.strlistget("platform.linux_distribution") or c.strget("platform.release", ""))
        r = self._remote_version
        if self._remote_revision:
            r += "-r%s" % self._remote_revision
        mode = c.strget("server.mode", "server")
        bits = c.intget("python.bits", 32)
        log.info("Xpra %s server version %s %i-bit", mode, std(r), bits)
        if i:
            log.info(" running on %s", std(i))
        if c.boolget("proxy"):
            proxy_hostname = c.strget("proxy.hostname")
            proxy_platform = c.strget("proxy.platform")
            proxy_release = c.strget("proxy.platform.release")
            proxy_version = c.strget("proxy.version")
            proxy_version = c.strget("proxy.build.version", proxy_version)
            proxy_distro = c.strget("linux_distribution")
            msg = "via: %s proxy version %s" % (platform_name(proxy_platform, proxy_distro or proxy_release), std(proxy_version or "unknown"))
            if proxy_hostname:
                msg += " on '%s'" % std(proxy_hostname)
            log.info(msg)
        return True

    def process_ui_capabilities(self):
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        if self.clipboard_enabled:
            self.clipboard_helper = self.make_clipboard_helper()
            self.clipboard_enabled = self.clipboard_helper is not None
            clipboardlog("clipboard helper=%s", self.clipboard_helper)
            if self.clipboard_enabled and self.server_supports_clipboard_enable_selections:
                #tell the server about which selections we really want to sync with
                #(could have been translated, or limited if the client only has one, etc)
                clipboardlog("clipboard enabled clipboard helper=%s", self.clipboard_helper)
                self.send_clipboard_selections(self.clipboard_helper.remote_clipboards)
        self.set_max_packet_size()
        self.send_deflate_level()
        c = self.server_capabilities
        server_desktop_size = c.intlistget("desktop_size")
        log("server desktop size=%s", server_desktop_size)
        self.server_window_states = c.strlistget("window.states", ["iconified", "fullscreen", "above", "below", "sticky", "iconified", "maximized"])
        self.server_supports_sharing = c.boolget("sharing")
        self.server_supports_window_filters = c.boolget("window-filters")
        self.server_is_desktop = c.boolget("shadow") or c.boolget("desktop")
        skip_vfb_size_check = False           #if we decide not to use scaling, skip warnings
        if not fequ(self.xscale, 1.0) or not fequ(self.yscale, 1.0):
            #scaling is used, make sure that we need it and that the server can support it
            #(without rounding support, size-hints can cause resize loops)
            if self.server_is_desktop and not self.desktop_fullscreen:
                #don't honour auto mode in this case
                if self.desktop_scaling=="auto":
                    log.info(" not scaling a shadow server")
                    skip_vfb_size_check = self.xscale>1 or self.yscale>1
                    self.scalingoff()
            elif self.mmap_enabled:
                if self.desktop_scaling=="auto":
                    log.info(" no need for scaling with mmap")
                    skip_vfb_size_check = self.xscale>1 or self.yscale>1
                    self.scalingoff()
                    self.can_scale = False
        if self.can_scale:
            self.may_adjust_scaling()
        if not self.server_is_desktop and not skip_vfb_size_check:
            avail_w, avail_h = server_desktop_size
            root_w, root_h = self.get_root_size()
            if self.cx(root_w)>(avail_w+1) or self.cy(root_h)>(avail_h+1):
                log.warn("Server's virtual screen is too small")
                log.warn(" server: %sx%s vs client: %sx%s", avail_w, avail_h, self.cx(root_w), self.cy(root_h))
                log.warn(" you may see strange behavior,")
                log.warn(" please see http://xpra.org/trac/wiki/Xdummy#Configuration")
        if self.keyboard_helper:
            modifier_keycodes = c.dictget("modifier_keycodes")
            if modifier_keycodes:
                self.keyboard_helper.set_modifier_mappings(modifier_keycodes)

        #webcam
        self.server_supports_webcam = c.boolget("webcam")
        self.server_webcam_encodings = c.strlistget("webcam.encodings", ("png", "jpeg"))
        self.server_virtual_video_devices = c.intget("virtual-video-devices")
        webcamlog("webcam server support: %s (%i devices, encodings: %s)", self.server_supports_webcam, self.server_virtual_video_devices, csv(self.server_webcam_encodings))
        if self.webcam_forwarding and self.server_supports_webcam and self.server_virtual_video_devices>0:
            if self.webcam_option=="on" or self.webcam_option.find("/dev/video")>=0:
                self.start_sending_webcam()

        #input devices:
        self.server_input_devices = c.strget("input-devices")
        self.server_precise_wheel = c.boolget("wheel.precise", False)

        #sound:
        self.server_pulseaudio_id = c.strget("sound.pulseaudio.id")
        self.server_pulseaudio_server = c.strget("sound.pulseaudio.server")
        self.server_codec_full_names = c.boolget("sound.codec-full-names")
        try:
            if not self.server_codec_full_names:
                from xpra.sound.common import legacy_to_new as conv
            else:
                def conv(v):
                    return v
            self.server_sound_decoders = conv(c.strlistget("sound.decoders", []))
            self.server_sound_encoders = conv(c.strlistget("sound.encoders", []))
        except:
            soundlog("Error: cannot parse server sound codec data", exc_info=True)
        self.server_sound_receive = c.boolget("sound.receive")
        self.server_sound_send = c.boolget("sound.send")
        self.server_sound_bundle_metadata = c.boolget("sound.bundle-metadata")
        self.server_ogg_latency_fix = c.boolget("sound.ogg-latency-fix", False)
        soundlog("pulseaudio id=%s, server=%s, sound decoders=%s, sound encoders=%s, receive=%s, send=%s",
                 self.server_pulseaudio_id, self.server_pulseaudio_server,
                 csv(self.server_sound_decoders), csv(self.server_sound_encoders),
                 self.server_sound_receive, self.server_sound_send)
        if self.server_sound_send and self.speaker_enabled:
            self.start_receiving_sound()
        if self.server_sound_receive and self.microphone_enabled:
            self.start_sending_sound()

        self.key_repeat_delay, self.key_repeat_interval = c.intpair("key_repeat", (-1,-1))
        self.handshake_complete()
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        if self.server_supports_clipboard:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.clipboard_toggled)
            self.clipboard_toggled()
        self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)
        self.send_ping()
        if self.pings>0:
            self.timeout_add(1000*self.pings, self.send_ping)

    def parse_logging_capabilities(self):
        c = self.server_capabilities
        if self.client_supports_remote_logging and c.boolget("remote-logging"):
            #check for debug:
            from xpra.log import is_debug_enabled
            for x in ("network", "crypto", "udp"):
                if is_debug_enabled(x):
                    log.warn("Warning: cannot enable remote logging")
                    log.warn(" because '%s' debug logging is enabled", x)
                    return
            log.info("enabled remote logging")
            if not self.log_both:
                log.info(" see server log file for further output")
            self.local_logging = set_global_logging_handler(self.remote_logging_handler)


    def _process_startup_complete(self, packet):
        log("all the existing windows and system trays have been received: %s items", len(self._id_to_window))
        XpraClientBase._process_startup_complete(self, packet)
        gui_ready()
        if self.tray:
            self.tray.ready()
        self.send_info_request()

    def handshake_complete(self):
        oh = self._on_handshake
        self._on_handshake = None
        for cb, args in oh:
            try:
                cb(*args)
            except:
                log.error("Error processing handshake callback %s", cb, exc_info=True)

    def after_handshake(self, cb, *args):
        log("after_handshake(%s, %s) on_handshake=%s", cb, args, self._on_handshake)
        if self._on_handshake is None:
            #handshake has already occurred, just call it:
            self.idle_add(cb, *args)
        else:
            self._on_handshake.append((cb, args))


    def remote_logging_handler(self, log, level, msg, *args, **kwargs):
        #prevent loops (if our send call ends up firing another logging call):
        if self.in_remote_logging:
            return
        self.in_remote_logging = True
        try:
            data = self.compressed_wrapper("text", strtobytes(msg % args), level=1)
            self.send("logging", level, data)
            exc_info = kwargs.get("exc_info")
            if exc_info:
                for x in traceback.format_tb(exc_info[2]):
                    self.send("logging", level, strtobytes(x))
            if self.log_both:
                self.local_logging(log, level, msg, *args, **kwargs)
        except Exception as e:
            if self.exit_code is not None:
                #errors can happen during exit, don't care
                return
            self.local_logging(log, logging.WARNING, "Warning: failed to send logging packet:")
            self.local_logging(log, logging.WARNING, " %s" % e)
            self.local_logging(log, logging.WARNING, " original unformatted message: %s", msg)
            try:
                self.local_logging(log, level, msg, *args, **kwargs)
            except:
                pass
            try:
                exc_info = sys.exc_info()
                for x in traceback.format_tb(exc_info[2]):
                    for v in x.splitlines():
                        self.local_logging(log, logging.WARNING, v)
            except:
                pass
        finally:
            self.in_remote_logging = False

    def rpc_call(self, rpc_type, rpc_args, reply_handler=None, error_handler=None):
        assert rpc_type in self.server_rpc_types, "server does not support %s rpc" % rpc_type
        rpcid = self.rpc_counter.increase()
        self.rpc_filter_pending()
        #keep track of this request (for timeout / error and reply callbacks):
        req = monotonic_time(), rpc_type, rpc_args, reply_handler, error_handler
        self.rpc_pending_requests[rpcid] = req
        rpclog("sending %s rpc request %s to server: %s", rpc_type, rpcid, req)
        packet = ["rpc", rpc_type, rpcid] + rpc_args
        self.send(*packet)
        self.timeout_add(RPC_TIMEOUT, self.rpc_filter_pending)

    def rpc_filter_pending(self):
        """ removes timed out dbus requests """
        for k in list(self.rpc_pending_requests.keys()):
            v = self.rpc_pending_requests.get(k)
            if v is None:
                continue
            t, rpc_type, _rpc_args, _reply_handler, ecb = v
            if 1000*(monotonic_time()-t)>=RPC_TIMEOUT:
                rpclog.warn("%s rpc request: %s has timed out", rpc_type, _rpc_args)
                try:
                    del self.rpc_pending_requests[k]
                    if ecb is not None:
                        ecb("timeout")
                except Exception as e:
                    rpclog.error("Error during timeout handler for %s rpc callback:", rpc_type)
                    rpclog.error(" %s", e)

    def _process_rpc_reply(self, packet):
        rpc_type, rpcid, success, args = packet[1:5]
        rpclog("rpc_reply: %s", (rpc_type, rpcid, success, args))
        v = self.rpc_pending_requests.get(rpcid)
        assert v is not None, "pending dbus handler not found for id %s" % rpcid
        assert rpc_type==v[1], "rpc reply type does not match: expected %s got %s" % (v[1], rpc_type)
        del self.rpc_pending_requests[rpcid]
        if success:
            ctype = "ok"
            rh = v[-2]      #ok callback
        else:
            ctype = "error"
            rh = v[-1]      #error callback
        if rh is None:
            rpclog("no %s rpc callback defined, return values=%s", ctype, args)
            return
        rpclog("calling %s callback %s(%s)", ctype, rh, args)
        try:
            rh(*args)
        except Exception as e:
            rpclog.error("Error processing rpc reply handler %s(%s) :", rh, args)
            rpclog.error(" %s", e)


    def _process_control(self, packet):
        command = packet[1]
        if command=="show_session_info":
            args = packet[2:]
            log("calling show_session_info%s on server request", args)
            self.show_session_info(*args)
        elif command=="show_bug_report":
            self.show_bug_report()
        elif command in ("enable_%s" % x for x in compression.get_enabled_compressors()):
            compressor = command.split("_")[1]
            log.info("switching to %s on server request", compressor)
            self._protocol.enable_compressor(compressor)
        elif command in ("enable_%s" % x for x in packet_encoding.get_enabled_encoders()):
            pe = command.split("_")[1]
            log.info("switching to %s on server request", pe)
            self._protocol.enable_encoder(pe)
        elif command=="name":
            assert len(args)>=3
            self.session_name = args[2]
            log.info("session name updated from server: %s", self.session_name)
            #TODO: reset tray tooltip, session info title, etc..
        elif command=="debug":
            args = packet[2:]
            if len(args)<2:
                log.warn("not enough arguments for debug control command")
                return
            log_cmd = args[0]
            if log_cmd not in ("enable", "disable"):
                log.warn("invalid debug control mode: '%s' (must be 'enable' or 'disable')", log_cmd)
                return
            categories = args[1:]
            from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
            if log_cmd=="enable":
                add_debug_category(*categories)
                loggers = enable_debug_for(*categories)
            else:
                assert log_cmd=="disable"
                add_disabled_category(*categories)
                loggers = disable_debug_for(*categories)
            log.info("%sd debugging for: %s", log_cmd, loggers)
            return
        else:
            log.warn("received invalid control command from server: %s", command)


    def send_input_devices(self, fmt, input_devices):
        assert self.server_input_devices
        self.send("input-devices", fmt, input_devices)


    def start_sending_webcam(self):
        with self.webcam_lock:
            self.do_start_sending_webcam(self.webcam_option)

    def do_start_sending_webcam(self, device_str):
        assert self.server_supports_webcam
        device = 0
        virt_devices, all_video_devices, non_virtual = {}, {}, {}
        try:
            from xpra.platform.webcam import get_virtual_video_devices, get_all_video_devices
            virt_devices = get_virtual_video_devices()
            all_video_devices = get_all_video_devices()
            non_virtual = dict([(k,v) for k,v in all_video_devices.items() if k not in virt_devices])
            webcamlog("virtual video devices=%s", virt_devices)
            webcamlog("all_video_devices=%s", all_video_devices)
            webcamlog("found %s known non-virtual video devices: %s", len(non_virtual), non_virtual)
        except ImportError as e:
            webcamlog("no webcam_util: %s", e)
        webcamlog("do_start_sending_webcam(%s)", device_str)
        if device_str in ("auto", "on", "yes", "off", "false", "true"):
            if len(non_virtual)>0:
                device = non_virtual.keys()[0]
        else:
            webcamlog("device_str: %s", device_str)
            try:
                device = int(device_str)
            except:
                p = device_str.find("video")
                if p>=0:
                    try:
                        webcamlog("device_str: %s", device_str[p:])
                        device = int(device_str[p+len("video"):])
                    except:
                        device = 0
        if device in virt_devices:
            webcamlog.warn("Warning: video device %s is a virtual device", virt_devices.get(device, device))
            if WEBCAM_ALLOW_VIRTUAL:
                webcamlog.warn(" environment override - this may hang..")
            else:
                webcamlog.warn(" corwardly refusing to use it")
                webcamlog.warn(" set WEBCAM_ALLOW_VIRTUAL=1 to force enable it")
                return
        import cv2
        webcamlog("do_start_sending_webcam(%s) device=%i", device_str, device)
        self.webcam_frame_no = 0
        try:
            #test capture:
            webcam_device = cv2.VideoCapture(device)        #0 -> /dev/video0
            ret, frame = webcam_device.read()
            webcamlog("test capture using %s: %s, %s", webcam_device, ret, frame is not None)
            assert ret, "no device or permission"
            assert frame is not None, "no data"
            assert frame.ndim==3, "unexpected  number of dimensions: %s" % frame.ndim
            w, h, Bpp = frame.shape
            assert Bpp==3, "unexpected number of bytes per pixel: %s" % Bpp
            assert frame.size==w*h*Bpp
            self.webcam_device_no = device
            self.webcam_device = webcam_device
            self.send("webcam-start", device, w, h)
            self.idle_add(self.emit, "webcam-changed")
            webcamlog("webcam started")
            if self.send_webcam_frame():
                delay = 1000//WEBCAM_TARGET_FPS
                webcamlog("webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                self.cancel_webcam_send_timer()
                self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)
        except Exception as e:
            webcamlog.warn("webcam test capture failed: %s", e)

    def cancel_webcam_send_timer(self):
        wst = self.webcam_send_timer
        if wst:
            self.webcam_send_timer = None
            self.source_remove(wst)

    def cancel_webcam_check_ack_timer(self):
        wact = self.webcam_ack_check_timer
        if wact:
            self.webcam_ack_check_timer = None
            self.source_remove(wact)

    def webcam_check_acks(self, ack=0):
        self.webcam_ack_check_timer = None
        webcamlog("check_acks: webcam_last_ack=%s", self.webcam_last_ack)
        if self.webcam_last_ack<ack:
            webcamlog.warn("Warning: no acknowledgements received from the server for frame %i, stopping webcam", ack)
            self.stop_sending_webcam()

    def stop_sending_webcam(self):
        webcamlog("stop_sending_webcam()")
        with self.webcam_lock:
            self.do_stop_sending_webcam()

    def do_stop_sending_webcam(self):
        self.cancel_webcam_send_timer()
        self.cancel_webcam_check_ack_timer()
        wd = self.webcam_device
        webcamlog("do_stop_sending_webcam() device=%s", wd)
        if not wd:
            return
        self.send("webcam-stop", self.webcam_device_no)
        assert self.server_supports_webcam
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_frame_no = 0
        self.webcam_last_ack = -1
        try:
            wd.release()
        except Exception as e:
            webcamlog.error("Error closing webcam device %s: %s", wd, e)
        self.idle_add(self.emit, "webcam-changed")

    def _process_webcam_stop(self, packet):
        device_no = packet[1]
        if device_no!=self.webcam_device_no:
            return
        self.stop_sending_webcam()

    def _process_webcam_ack(self, packet):
        webcamlog("process_webcam_ack: %s", packet)
        with self.webcam_lock:
            if self.webcam_device:
                frame_no = packet[2]
                self.webcam_last_ack = frame_no
                if self.may_send_webcam_frame():
                    self.cancel_webcam_send_timer()
                    delay = 1000//WEBCAM_TARGET_FPS
                    webcamlog("new webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                    self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)

    def may_send_webcam_frame(self):
        self.webcam_send_timer = None
        if self.webcam_device_no<0 or not self.webcam_device:
            return False
        not_acked = self.webcam_frame_no-1-self.webcam_last_ack
        #not all frames have been acked
        latency = 100
        if len(self.server_ping_latency)>0:
            l = [x for _,x in list(self.server_ping_latency)]
            latency = int(1000 * sum(l) / len(l))
        #how many frames should be in flight
        n = max(1, latency // (1000//WEBCAM_TARGET_FPS))    #20fps -> 50ms target between frames
        if not_acked>0 and not_acked>n:
            webcamlog("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - will wait for next ack", latency, not_acked, n)
            return False
        webcamlog("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - trying to send now", latency, not_acked, n)
        return self.send_webcam_frame()

    def send_webcam_frame(self):
        if not self.webcam_lock.acquire(False):
            return False
        webcamlog("send_webcam_frame() webcam_device=%s", self.webcam_device)
        try:
            assert self.webcam_device_no>=0, "device number is not set"
            assert self.webcam_device, "no webcam device to capture from"
            from xpra.codecs.pillow.encode import get_encodings
            client_webcam_encodings = get_encodings()
            common_encodings = list(set(self.server_webcam_encodings).intersection(client_webcam_encodings))
            webcamlog("common encodings (server=%s, client=%s): %s", csv(self.server_encodings), csv(client_webcam_encodings), csv(common_encodings))
            if not common_encodings:
                webcamlog.error("Error: cannot send webcam image, no common formats")
                webcamlog.error(" the server supports: %s", csv(self.server_webcam_encodings))
                webcamlog.error(" the client supports: %s", csv(client_webcam_encodings))
                self.stop_sending_webcam()
                return False
            preferred_order = ["jpeg", "png", "png/L", "png/P"]
            formats = [x for x in preferred_order if x in common_encodings] + common_encodings
            encoding = formats[0]
            start = monotonic_time()
            import cv2
            ret, frame = self.webcam_device.read()
            assert ret and frame.ndim==3
            h, w, Bpp = frame.shape
            assert Bpp==3 and frame.size==w*h*Bpp
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            end = monotonic_time()
            webcamlog("webcam frame capture took %ims", (end-start)*1000)
            start = monotonic_time()
            from PIL import Image
            image = Image.fromarray(rgb)
            buf = BytesIOClass()
            image.save(buf, format=encoding)
            data = buf.getvalue()
            buf.close()
            end = monotonic_time()
            webcamlog("webcam frame compression to %s took %ims", encoding, (end-start)*1000)
            frame_no = self.webcam_frame_no
            self.webcam_frame_no += 1
            self.send("webcam-frame", self.webcam_device_no, frame_no, encoding, w, h, compression.Compressed(encoding, data))
            self.cancel_webcam_check_ack_timer()
            self.webcam_ack_check_timer = self.timeout_add(10*1000, self.webcam_check_acks)
            return True
        except Exception as e:
            webcamlog.error("webcam frame %i failed", self.webcam_frame_no, exc_info=True)
            webcamlog.error("Error sending webcam frame: %s", e)
            self.stop_sending_webcam()
            return False
        finally:
            self.webcam_lock.release()


    def get_matching_codecs(self, local_codecs, server_codecs):
        matching_codecs = [x for x in local_codecs if x in server_codecs]
        soundlog("get_matching_codecs(%s, %s)=%s", local_codecs, server_codecs, matching_codecs)
        return matching_codecs

    def start_sending_sound(self, device=None):
        """ (re)start a sound source and emit client signal """
        soundlog("start_sending_sound(%s)", device)
        enabled = False
        try:
            assert self.microphone_allowed, "microphone forwarding is disabled"
            assert self.server_sound_receive, "client support for receiving sound is disabled"
            from xpra.sound.gstreamer_util import ALLOW_SOUND_LOOP, loop_warning
            if self._remote_machine_id and self._remote_machine_id==get_machine_id() and not ALLOW_SOUND_LOOP:
                #looks like we're on the same machine, verify it's a different user:
                if self._remote_uuid==get_user_uuid():
                    loop_warning("microphone", self._remote_uuid)
                    return
            ss = self.sound_source
            if ss:
                if ss.get_state()=="active":
                    soundlog.error("Error: microphone forwarding is already active")
                    enabled = True
                    return
                ss.start()
            else:
                enabled = self.start_sound_source(device)
        finally:
            if enabled!=self.microphone_enabled:
                self.microphone_enabled = enabled
                self.emit("microphone-changed")
            soundlog("start_sending_sound(%s) done, microphone_enabled=%s", device, enabled)

    def start_sound_source(self, device=None):
        soundlog("start_sound_source(%s)", device)
        assert self.sound_source is None
        def sound_source_state_changed(*_args):
            self.emit("microphone-changed")
        #find the matching codecs:
        matching_codecs = self.get_matching_codecs(self.microphone_codecs, self.server_sound_decoders)
        soundlog("start_sound_source(%s) matching codecs: %s", device, csv(matching_codecs))
        if len(matching_codecs)==0:
            log.error("Error: no matching codecs between client and server")
            log.error(" server supports: %s", csv(self.server_sound_decoders))
            log.error(" client supports: %s", csv(self.microphone_codecs))
            return False
        try:
            from xpra.sound.wrapper import start_sending_sound
            plugins = self.sound_properties.get("plugins")
            ss = start_sending_sound(plugins, self.sound_source_plugin, device or self.microphone_device, None, 1.0, False, matching_codecs, self.server_pulseaudio_server, self.server_pulseaudio_id)
            if not ss:
                return False
            self.sound_source = ss
            ss.connect("new-buffer", self.new_sound_buffer)
            ss.connect("state-changed", sound_source_state_changed)
            ss.connect("new-stream", self.new_stream)
            ss.start()
            soundlog("start_sound_source(%s) sound source %s started", device, ss)
            return True
        except Exception as e:
            log.error("Error setting up sound:")
            log.error(" %s", e)
            return False

    def new_stream(self, sound_source, codec):
        soundlog("new_stream(%s)", codec)
        if self.sound_source!=sound_source:
            soundlog("dropping new-stream signal (current source=%s, signal source=%s)", self.sound_source, sound_source)
            return
        codec = codec or sound_source.codec
        if not self.server_codec_full_names:
            codec = LEGACY_CODEC_NAMES.get(codec, codec)
        sound_source.codec = codec
        #tell the server this is the start:
        self.send("sound-data", codec, "",
                  {
                   "start-of-stream"    : True,
                   "codec"              : codec,
                   })

    def stop_sending_sound(self):
        """ stop the sound source and emit client signal """
        soundlog("stop_sending_sound() sound source=%s", self.sound_source)
        ss = self.sound_source
        if self.microphone_enabled:
            self.microphone_enabled = False
            self.emit("microphone-changed")
        self.sound_source = None
        if ss is None:
            log.warn("Warning: cannot stop sound source which has not been started")
            return
        #tell the server to stop:
        self.send("sound-data", ss.codec or "", "", {"end-of-stream" : True})
        ss.cleanup()

    def start_receiving_sound(self):
        """ ask the server to start sending sound and emit the client signal """
        soundlog("start_receiving_sound() sound sink=%s", self.sound_sink)
        enabled = False
        try:
            if self.sound_sink is not None:
                soundlog("start_receiving_sound: we already have a sound sink")
                enabled = True
                return
            elif not self.server_sound_send:
                log.error("Error receiving sound: support not enabled on the server")
                return
            #choose a codec:
            matching_codecs = self.get_matching_codecs(self.speaker_codecs, self.server_sound_encoders)
            soundlog("start_receiving_sound() matching codecs: %s", csv(matching_codecs))
            if len(matching_codecs)==0:
                log.error("Error: no matching codecs between client and server")
                log.error(" server supports: %s", csv(self.server_sound_encoders))
                log.error(" client supports: %s", csv(self.speaker_codecs))
                return
            codec = matching_codecs[0]
            if not self.server_ogg_latency_fix and codec in ("flac", "opus", "speex"):
                log.warn("Warning: this server's sound support is out of date")
                log.warn(" the sound latency with the %s codec will be high", codec)
            def sink_ready(*args):
                scodec = codec
                if not self.server_codec_full_names:
                    scodec = LEGACY_CODEC_NAMES.get(codec, codec)
                soundlog("sink_ready(%s) codec=%s (server codec name=%s)", args, codec, scodec)
                self.send("sound-control", "start", scodec)
                return False
            self.on_sink_ready = sink_ready
            enabled = self.start_sound_sink(codec)
        finally:
            if self.speaker_enabled!=enabled:
                self.speaker_enabled = enabled
                self.emit("speaker-changed")
            soundlog("start_receiving_sound() done, speaker_enabled=%s", enabled)

    def stop_receiving_sound(self, tell_server=True):
        """ ask the server to stop sending sound, toggle flag so we ignore further packets and emit client signal """
        soundlog("stop_receiving_sound(%s) sound sink=%s", tell_server, self.sound_sink)
        ss = self.sound_sink
        if self.speaker_enabled:
            self.speaker_enabled = False
            self.emit("speaker-changed")
        if tell_server:
            self.send("sound-control", "stop", self.min_sound_sequence)
        self.min_sound_sequence += 1
        self.send("sound-control", "new-sequence", self.min_sound_sequence)
        if ss is None:
            return
        self.sound_sink = None
        soundlog("stop_receiving_sound(%s) calling %s", tell_server, ss.cleanup)
        ss.cleanup()
        soundlog("stop_receiving_sound(%s) done", tell_server)

    def sound_sink_state_changed(self, sound_sink, state):
        if sound_sink!=self.sound_sink:
            soundlog("sound_sink_state_changed(%s, %s) not the current sink, ignoring it", sound_sink, state)
            return
        soundlog("sound_sink_state_changed(%s, %s) on_sink_ready=%s", sound_sink, state, self.on_sink_ready)
        if state==b"ready" and self.on_sink_ready:
            if not self.on_sink_ready():
                self.on_sink_ready = None
        self.emit("speaker-changed")
    def sound_sink_bitrate_changed(self, sound_sink, bitrate):
        if sound_sink!=self.sound_sink:
            soundlog("sound_sink_bitrate_changed(%s, %s) not the current sink, ignoring it", sound_sink, bitrate)
            return
        soundlog("sound_sink_bitrate_changed(%s, %s)", sound_sink, bitrate)
        #not shown in the UI, so don't bother with emitting a signal:
        #self.emit("speaker-changed")
    def sound_sink_error(self, sound_sink, error):
        if sound_sink!=self.sound_sink:
            soundlog("sound_sink_error(%s, %s) not the current sink, ignoring it", sound_sink, error)
            return
        soundlog.warn("Error: stopping speaker:")
        soundlog.warn(" %s", str(error).replace("gst-resource-error-quark: ", ""))
        self.stop_receiving_sound()
    def sound_process_stopped(self, sound_sink, *args):
        if sound_sink!=self.sound_sink:
            soundlog("sound_process_stopped(%s, %s) not the current sink, ignoring it", sound_sink, args)
            return
        soundlog.warn("Warning: the sound process has stopped")
        self.stop_receiving_sound()

    def sound_sink_exit(self, sound_sink, *args):
        log("sound_sink_exit(%s, %s) sound_sink=%s", sound_sink, args, self.sound_sink)
        ss = self.sound_sink
        if sound_sink!=ss:
            soundlog("sound_sink_exit() not the current sink, ignoring it")
            return
        if ss and ss.codec:
            #the mandatory "I've been naughty warning":
            #we use the "codec" field as guard to ensure we only print this warning once..
            soundlog.warn("Warning: the %s sound sink has stopped", ss.codec)
            ss.codec = ""
        self.stop_receiving_sound()

    def start_sound_sink(self, codec):
        soundlog("start_sound_sink(%s)", codec)
        assert self.sound_sink is None, "sound sink already exists!"
        try:
            soundlog("starting %s sound sink", codec)
            from xpra.sound.wrapper import start_receiving_sound
            ss = start_receiving_sound(codec)
            if not ss:
                return False
            self.sound_sink = ss
            ss.connect("state-changed", self.sound_sink_state_changed)
            ss.connect("error", self.sound_sink_error)
            ss.connect("exit", self.sound_sink_exit)
            from xpra.net.protocol import Protocol
            ss.connect(Protocol.CONNECTION_LOST, self.sound_process_stopped)
            ss.start()
            soundlog("%s sound sink started", codec)
            return True
        except Exception as e:
            soundlog.error("Error: failed to start sound sink", exc_info=True)
            self.sound_sink_error(self.sound_sink, e)
            return False

    def new_sound_buffer(self, sound_source, data, metadata, packet_metadata=[]):
        soundlog("new_sound_buffer(%s, %s, %s, %s)", sound_source, len(data or []), metadata, packet_metadata)
        if not self.sound_source:
            return
        self.sound_out_bytecount += len(data)
        for x in packet_metadata:
            self.sound_out_bytecount += len(x)
        if packet_metadata:
            if not self.server_sound_bundle_metadata:
                #server does not support bundling, send packet metadata as individual packets before the main packet:
                for x in packet_metadata:
                    self.send_sound_data(sound_source, x)
                packet_metadata = ()
            else:
                #the packet metadata is compressed already:
                packet_metadata = Compressed("packet metadata", packet_metadata, can_inline=True)
        self.send_sound_data(sound_source, data, metadata, packet_metadata)

    def send_sound_data(self, sound_source, data, metadata={}, packet_metadata=()):
        codec = sound_source.codec
        if not self.server_codec_full_names:
            codec = LEGACY_CODEC_NAMES.get(codec, codec)
        packet_data = [codec, Compressed(codec, data), metadata]
        if packet_metadata:
            assert self.server_sound_bundle_metadata
            packet_data.append(packet_metadata)
        self.send("sound-data", *packet_data)

    def _process_sound_data(self, packet):
        codec, data, metadata = packet[1:4]
        codec = bytestostr(codec)
        if not self.server_codec_full_names:
            codec = NEW_CODEC_NAMES.get(codec, codec)
        metadata = typedict(metadata)
        if data:
            self.sound_in_bytecount += len(data)
        #verify sequence number if present:
        seq = metadata.intget("sequence", -1)
        if self.min_sound_sequence>0 and seq>=0 and seq<self.min_sound_sequence:
            soundlog("ignoring sound data with old sequence number %s (now on %s)", seq, self.min_sound_sequence)
            return

        if not self.speaker_enabled:
            if metadata.boolget("start-of-stream"):
                #server is asking us to start playing sound
                if not self.speaker_allowed:
                    #no can do!
                    soundlog.warn("Warning: cannot honour the request to start the speaker")
                    soundlog.warn(" speaker forwarding is disabled")
                    self.stop_receiving_sound(True)
                    return
                self.speaker_enabled = True
                self.emit("speaker-changed")
                self.on_sink_ready = None
                codec = metadata.strget("codec")
                soundlog("starting speaker on server request using codec %s", codec)
                self.start_sound_sink(codec)
            else:
                soundlog("speaker is now disabled - dropping packet")
                return
        ss = self.sound_sink
        if ss is None:
            soundlog("no sound sink to process sound data, dropping it")
            return
        if metadata.boolget("end-of-stream"):
            soundlog("server sent end-of-stream for sequence %s, closing sound pipeline", seq)
            self.stop_receiving_sound(False)
            return
        if codec!=ss.codec:
            soundlog.error("Error: sound codec change is not supported!")
            soundlog.error(" stream tried to switch from %s to %s", ss.codec, codec)
            self.stop_receiving_sound()
            return
        elif ss.get_state()=="stopped":
            soundlog("sound data received, sound sink is stopped - telling server to stop")
            self.stop_receiving_sound()
            return
        #the server may send packet_metadata, which is pushed before the actual sound data:
        packet_metadata = ()
        if len(packet)>4:
            packet_metadata = packet[4]
            if not self.sound_properties.get("bundle-metadata"):
                #we don't handle bundling, so push individually:
                for x in packet_metadata:
                    ss.add_data(x)
                packet_metadata = ()
        #(some packets (ie: sos, eos) only contain metadata)
        if len(data)>0 or packet_metadata:
            ss.add_data(data, metadata, packet_metadata)
        if self.av_sync and self.server_av_sync:
            info = ss.get_info()
            queue_used = info.get("queue.cur") or info.get("queue", {}).get("cur")
            if queue_used is None:
                return
            delta = (self.queue_used_sent or 0)-queue_used
            #avsynclog("server sound sync: queue info=%s, last sent=%s, delta=%s", dict((k,v) for (k,v) in info.items() if k.startswith("queue")), self.queue_used_sent, delta)
            if self.queue_used_sent is None or abs(delta)>=80:
                avsynclog("server sound sync: sending updated queue.used=%i (was %s)", queue_used, (self.queue_used_sent or "unset"))
                self.queue_used_sent = queue_used
                v = queue_used + AV_SYNC_DELTA
                if AV_SYNC_DELTA:
                    avsynclog(" adjusted value=%i with sync delta=%i", v, AV_SYNC_DELTA)
                self.send("sound-control", "sync", v)


    def send_notify_enabled(self):
        assert self.client_supports_notifications, "cannot toggle notifications: the feature is disabled by the client"
        self.send("set-notify", self.notifications_enabled)

    def send_bell_enabled(self):
        assert self.client_supports_bell, "cannot toggle bell: the feature is disabled by the client"
        assert self.server_supports_bell, "cannot toggle bell: the feature is disabled by the server"
        self.send("set-bell", self.bell_enabled)

    def send_cursors_enabled(self):
        assert self.client_supports_cursors, "cannot toggle cursors: the feature is disabled by the client"
        assert self.server_supports_cursors, "cannot toggle cursors: the feature is disabled by the server"
        self.send("set-cursors", self.cursors_enabled)

    def send_force_ungrab(self, wid):
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
            clipboardlog.info("clipboard toggled to %s by the server, reason given:", ["off", "on"][int(clipboard_enabled)])
            clipboardlog.info(" %s", reason)
            self.clipboard_enabled = bool(clipboard_enabled)
            self.emit("clipboard-toggled")

    def clipboard_toggled(self, *args):
        clipboardlog("clipboard_toggled%s clipboard_enabled=%s, server_supports_clipboard=%s", args, self.clipboard_enabled, self.server_supports_clipboard)
        if self.server_supports_clipboard:
            self.send("set-clipboard-enabled", self.clipboard_enabled)
            if self.clipboard_enabled:
                ch = self.clipboard_helper
                assert ch is not None
                self.send_clipboard_selections(ch.remote_clipboards)
                ch.send_all_tokens()
            else:
                pass    #FIXME: todo!

    def send_clipboard_selections(self, selections):
        clipboardlog("send_clipboard_selections(%s) server_supports_clipboard_enable_selections=%s", selections, self.server_supports_clipboard_enable_selections)
        if self.server_supports_clipboard_enable_selections:
            self.send("clipboard-enable-selections", selections)

    def send_keyboard_sync_enabled_status(self, *_args):
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)


    def set_encoding(self, encoding):
        log("set_encoding(%s)", encoding)
        if encoding=="auto":
            assert self.server_auto_video_encoding
            self.encoding = ""
        else:
            assert encoding in self.get_encodings(), "encoding %s is not supported!" % encoding
            assert encoding in self.server_encodings, "encoding %s is not supported by the server! (only: %s)" % (encoding, self.server_encodings)
        self.encoding = encoding
        self.send("encoding", self.encoding)


    def reset_cursor(self):
        self.set_windows_cursor(self._id_to_window.values(), [])

    def _ui_event(self):
        if self._ui_events==0:
            self.emit("first-ui-received")
        self._ui_events += 1


    def sx(self, v):
        """ convert X coordinate from server to client """
        return iround(v*self.xscale)
    def sy(self, v):
        """ convert Y coordinate from server to client """
        return iround(v*self.yscale)
    def srect(self, x, y, w, h):
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)
    def sp(self, x, y):
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    def cx(self, v):
        """ convert X coordinate from client to server """
        return iround(v/self.xscale)
    def cy(self, v):
        """ convert Y coordinate from client to server """
        return iround(v/self.yscale)
    def crect(self, x, y, w, h):
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)
    def cp(self, x, y):
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)


    def _process_new_common(self, packet, override_redirect):
        self._ui_event()
        wid, x, y, w, h = packet[1:6]
        metadata = self.cook_metadata(True, packet[6])
        windowlog("process_new_common: %s, metadata=%s, OR=%s", packet[1:7], metadata, override_redirect)
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        if w<1 or h<1:
            windowlog.error("window dimensions are wrong: %sx%s", w, h)
            w, h = 1, 1
        x = self.sx(x)
        y = self.sy(y)
        bw, bh = w, h
        ww = max(1, self.sx(w))
        wh = max(1, self.sy(h))
        client_properties = {}
        if len(packet)>=8:
            client_properties = packet[7]
        geomlog("process_new_common: wid=%i, OR=%s, geometry(%s)=%s", wid, override_redirect, packet[2:6], (x, y, ww, wh, bw, bh))
        self.make_new_window(wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties)

    def cook_metadata(self, new_window, metadata):
        #convert to a typedict and apply client-side overrides:
        metadata = typedict(metadata)
        if self.server_is_desktop and self.desktop_fullscreen:
            #force it fullscreen:
            try:
                del metadata["size-constraints"]
            except:
                pass
            metadata["fullscreen"] = True
            #FIXME: try to figure out the monitors we go fullscreen on for X11:
            #if POSIX:
            #    metadata["fullscreen-monitors"] = [0, 1, 0, 1]
        return metadata

    def make_new_window(self, wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties):
        client_window_classes = self.get_client_window_classes(ww, wh, metadata, override_redirect)
        group_leader_window = self.get_group_leader(wid, metadata, override_redirect)
        #workaround for "popup" OR windows without a transient-for (like: google chrome popups):
        #prevents them from being pushed under other windows on OSX
        #find a "transient-for" value using the pid to find a suitable window
        #if possible, choosing the currently focused window (if there is one..)
        pid = metadata.intget("pid", 0)
        if override_redirect and pid>0 and metadata.intget("transient-for", 0)>0 is None and metadata.get("role")=="popup":
            tfor = None
            for twid, twin in self._id_to_window.items():
                if not twin._override_redirect and twin._metadata.intget("pid", -1)==pid:
                    tfor = twin
                    if twid==self._focused:
                        break
            if tfor:
                windowlog("forcing transient for=%s for new window %s", twid, wid)
                metadata["transient-for"] = twid
        border = None
        if self.border:
            border = self.border.clone()
        window = None
        windowlog("make_new_window(..) client_window_classes=%s, group_leader_window=%s", client_window_classes, group_leader_window)
        for cwc in client_window_classes:
            try:
                window = cwc(self, group_leader_window, wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties, border, self.max_window_size, self.default_cursor_data, self.pixel_depth)
                break
            except:
                windowlog.warn("failed to instantiate %s", cwc, exc_info=True)
        if window is None:
            windowlog.warn("no more options.. this window will not be shown, sorry")
            return None
        windowlog("make_new_window(..) window(%i)=%s", wid, window)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        window.show()
        return window


    def freeze(self):
        log("freeze()")
        for window in self._id_to_window.values():
            window.freeze()

    def unfreeze(self):
        log("unfreeze()")
        for window in self._id_to_window.values():
            window.unfreeze()

    def deiconify_windows(self):
        log("deiconify_windows()")
        for window in self._id_to_window.values():
            window.deiconify()


    def reinit_window_icons(self):
        #make sure the window icons are the ones we want:
        for window in self._id_to_window.values():
            reset_icon = getattr(window, "reset_icon", None)
            if reset_icon:
                reset_icon()

    def reinit_windows(self, new_size_fn=None):
        def fake_send(*args):
            log("fake_send%s", args)
        #now replace all the windows with new ones:
        for wid, window in self._id_to_window.items():
            if not window:
                continue
            if window.is_tray():
                #trays are never GL enabled, so don't bother re-creating them
                #might cause problems anyway if we did
                #just send a configure event in case they are moved / scaled
                window.send_configure()
                continue
            #ignore packets from old window:
            window.send = fake_send
            #copy attributes:
            x, y = window._pos
            ww, wh = window._size
            if new_size_fn:
                ww, wh = new_size_fn(ww, wh)
            try:
                bw, bh = window._backing.size
            except:
                bw, bh = ww, wh
            client_properties = window._client_properties
            resize_counter = window._resize_counter
            metadata = window._metadata
            override_redirect = window._override_redirect
            backing = window._backing
            current_icon = window._current_icon
            delta_pixel_data, video_decoder, csc_decoder, decoder_lock = None, None, None, None
            try:
                if backing:
                    delta_pixel_data = backing._delta_pixel_data
                    video_decoder = backing._video_decoder
                    csc_decoder = backing._csc_decoder
                    decoder_lock = backing._decoder_lock
                    if decoder_lock:
                        decoder_lock.acquire()
                        windowlog("reinit_windows() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                        backing._video_decoder = None
                        backing._csc_decoder = None
                        backing._decoder_lock = None

                #now we can unmap it:
                self.destroy_window(wid, window)
                #explicitly tell the server we have unmapped it:
                #(so it will reset the video encoders, etc)
                if not window.is_OR():
                    self.send("unmap-window", wid)
                try:
                    del self._id_to_window[wid]
                except:
                    pass
                try:
                    del self._window_to_id[window]
                except:
                    pass
                #create the new window,
                #which should honour the new state of the opengl_enabled flag if that's what we changed,
                #or the new dimensions, etc
                window = self.make_new_window(wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties)
                window._resize_counter = resize_counter
                #if we had a backing already,
                #restore the attributes we had saved from it
                if backing:
                    backing = window._backing
                    backing._delta_pixel_data = delta_pixel_data
                    backing._video_decoder = video_decoder
                    backing._csc_decoder = csc_decoder
                    backing._decoder_lock = decoder_lock
                if current_icon:
                    window.update_icon(*current_icon)
            finally:
                if decoder_lock:
                    decoder_lock.release()
        self.send_refresh_all()


    def get_group_leader(self, wid, metadata, override_redirect):
        #subclasses that wish to implement the feature may override this method
        return None


    def get_client_window_classes(self, w, h, metadata, override_redirect):
        return [self.ClientWindowClass]

    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)

    def _process_new_tray(self, packet):
        assert SYSTEM_TRAY_SUPPORTED
        self._ui_event()
        wid, w, h = packet[1:4]
        w = max(1, self.sx(w))
        h = max(1, self.sy(h))
        metadata = typedict()
        if len(packet)>=5:
            metadata = self.cook_metadata(True, packet[4])
        assert wid not in self._id_to_window, "we already have a window %s" % wid
        tray = self.setup_system_tray(self, wid, w, h, metadata.get("title", ""))
        traylog("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid

    def _process_window_move_resize(self, packet):
        wid, x, y, w, h = packet[1:6]
        ax = self.sx(x)
        ay = self.sy(y)
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        resize_counter = -1
        if len(packet)>4:
            resize_counter = packet[4]
        window = self._id_to_window.get(wid)
        geomlog("_process_window_move_resize%s moving / resizing window %s (id=%s) to %s", packet[1:], window, wid, (ax, ay, aw, ah))
        if window:
            window.move_resize(ax, ay, aw, ah, resize_counter)

    def _process_window_resized(self, packet):
        wid, w, h = packet[1:4]
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        resize_counter = -1
        if len(packet)>4:
            resize_counter = packet[4]
        window = self._id_to_window.get(wid)
        geomlog("_process_window_resized%s resizing window %s (id=%s) to %s", packet[1:], window, wid, (aw,ah))
        if window:
            window.resize(aw, ah, resize_counter)

    def _process_draw(self, packet):
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid, packet_sequence, width, height, decode_time, message=""):
        self.send_now("damage-sequence", packet_sequence, wid, width, height, decode_time, message)

    def _draw_thread_loop(self):
        while self.exit_code is None:
            packet = self._draw_queue.get()
            if packet is None:
                break
            try:
                self._do_draw(packet)
                sleep(0)
            except KeyboardInterrupt:
                raise
            except:
                log.error("error processing draw packet", exc_info=True)
        log("draw thread ended")

    def _do_draw(self, packet):
        """ this runs from the draw thread above """
        wid, x, y, width, height, coding, data, packet_sequence, rowstride = packet[1:10]
        #rename old encoding aliases early:
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
        options = typedict(options)
        dtype = DRAW_TYPES.get(type(data), type(data))
        drawlog("process_draw: %7i %8s for window %3i, %4ix%4i at %4i,%4i using %6s encoding with options=%s", len(data), dtype, wid, width, height, x, y, coding, options)
        start = monotonic_time()
        def record_decode_time(success, message=""):
            if success>0:
                end = monotonic_time()
                decode_time = int(end*1000*1000-start*1000*1000)
                self.pixel_counter.append((start, end, width*height))
                dms = "%sms" % (int(decode_time/100)/10.0)
                paintlog("record_decode_time(%s, %s) wid=%s, %s: %sx%s, %s", success, message, wid, coding, width, height, dms)
            elif success==0:
                decode_time = -1
                paintlog("record_decode_time(%s, %s) decoding error on wid=%s, %s: %sx%s", success, message, wid, coding, width, height)
            else:
                assert success<0
                decode_time = 0
                paintlog("record_decode_time(%s, %s) decoding or painting skipped on wid=%s, %s: %sx%s", success, message, wid, coding, width, height)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time, str(message))
        self._draw_counter += 1
        if PAINT_FAULT_RATE>0 and (self._draw_counter % PAINT_FAULT_RATE)==0:
            drawlog.warn("injecting paint fault for %s draw packet %i, sequence number=%i", coding, self._draw_counter, packet_sequence)
            if PAINT_FAULT_TELL:
                self.idle_add(record_decode_time, False, "fault injection for %s draw packet %i, sequence number=%i" % (coding, self._draw_counter, packet_sequence))
            return
        #we could expose this to the csc step? (not sure how this could be used)
        #if self.xscale!=1 or self.yscale!=1:
        #    options["client-scaling"] = self.xscale, self.yscale
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, packet_sequence, options, [record_decode_time])
        except KeyboardInterrupt:
            raise
        except Exception as e:
            drawlog.error("Error drawing on window %i", wid, exc_info=True)
            self.idle_add(record_decode_time, False, str(e))
            raise

    def _process_cursor(self, packet):
        if not self.cursors_enabled:
            return
        #trim packet type:
        packet = packet[1:]
        if len(packet)==1:
            #marker telling us to use the default cursor:
            new_cursor = packet[0]
        else:
            if len(packet)<7:
                raise Exception("invalid cursor packet: %s items" % len(packet))
            #newer versions include the cursor encoding as first argument,
            #we know this is it because it will be a string rather than an int:
            if type(packet[0]) in (str, bytes):
                #we have the encoding in the packet already
                new_cursor = packet
            else:
                #prepend "raw" which is the default
                new_cursor = [b"raw"] + packet
            encoding = new_cursor[0]
            pixels = new_cursor[8]
            if encoding==b"png":
                from PIL import Image
                buf = BytesIOClass(pixels)
                img = Image.open(buf)
                new_cursor[8] = img.tobytes("raw", "BGRA")
                cursorlog("used PIL to convert png cursor to raw")
                new_cursor[0] = b"raw"
            elif encoding!=b"raw":
                cursorlog.warn("Warning: invalid cursor encoding: %s", encoding)
                return
        self.set_windows_cursor(self._id_to_window.values(), new_cursor)

    def _process_bell(self, packet):
        if not self.bell_enabled:
            return
        (wid, device, percent, pitch, duration, bell_class, bell_id, bell_name) = packet[1:9]
        window = self._id_to_window.get(wid)
        self.window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)


    def _process_notify_show(self, packet):
        if not self.notifications_enabled:
            notifylog("process_notify_show: ignoring packet, notifications are disabled")
            return
        self._ui_event()
        dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout = packet[1:9]
        #note: if the server doesn't support notification forwarding,
        #it can still send us the messages (via xpra control or the dbus interface)
        notifylog("_process_notify_show(%s) notifier=%s, server_supports_notifications=%s", packet, self.notifier, self.server_supports_notifications)
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

    def _process_show_desktop(self, packet):
        show = packet[1]
        log("calling %s(%s)", show_desktop, show)
        show_desktop(show)


    def _process_pointer_position(self, packet):
        wid, x, y = packet[1:4]
        if len(packet)>=6:
            rx, ry = packet[4:6]
        else:
            rx, ry = -1, -1
        cx, cy = self.get_mouse_position()
        size = 10
        start_time = monotonic_time()
        mouselog("process_pointer_position: %i,%i (%i,%i relative to wid %i) - current position is %i,%i", x, y, rx, ry, wid, cx, cy)
        for i,w in self._id_to_window.items():
            #not all window implementations have this method:
            #(but GLClientWindow does)
            show_pointer_overlay = getattr(w, "show_pointer_overlay", None)
            if show_pointer_overlay:
                if i==wid:
                    value = rx, ry, size, start_time
                else:
                    value = None
                show_pointer_overlay(value)


    def _process_initiate_moveresize(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            x_root, y_root, direction, button, source_indication = packet[2:7]
            window.initiate_moveresize(self.sx(x_root), self.sy(y_root), direction, button, source_indication)

    def _process_window_metadata(self, packet):
        wid, metadata = packet[1:3]
        window = self._id_to_window.get(wid)
        if window:
            metadata = self.cook_metadata(False, metadata)
            window.update_metadata(metadata)

    def _process_window_icon(self, packet):
        wid, w, h, pixel_format, data = packet[1:6]
        window = self._id_to_window.get(wid)
        iconlog("_process_window_icon(%s, %s, %s, %s, %s bytes) window=%s", wid, w, h, pixel_format, len(data), window)
        if window:
            window.update_icon(w, h, pixel_format, data)

    def _process_configure_override_redirect(self, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window[wid]
        ax = self.sx(x)
        ay = self.sy(y)
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        geomlog("_process_configure_override_redirect%s move resize window %s (id=%s) to %s", packet[1:], window, wid, (ax,ay,aw,ah))
        window.move_resize(ax, ay, aw, ah, -1)

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
        screenlog("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h
        if self.can_scale:
            self.may_adjust_scaling()


    def may_adjust_scaling(self):
        if self.server_is_desktop and not self.desktop_fullscreen:
            #don't try to make it fit
            return
        assert self.can_scale
        max_w, max_h = self.server_max_desktop_size             #ie: server limited to 8192x4096?
        w, h = self.get_root_size()                             #ie: 5760, 2160
        sw, sh = self.cp(w, h)                                  #ie: upscaled to: 11520x4320
        scalinglog("may_adjust_scaling() server desktop size=%s, client root size=%s", self.server_actual_desktop_size, self.get_root_size())
        scalinglog(" scaled client root size using %sx%s: %s", self.xscale, self.yscale, (sw, sh))
        if sw<(max_w+1) and sh<(max_h+1):
            #no change needed
            return
        #server size is too small for the client screen size with the current scaling value,
        #calculate the minimum scaling to fit it:
        def clamp(v):
            return max(MIN_SCALING, min(MAX_SCALING, v))
        x = clamp(float(w)/max_w)
        y = clamp(float(h)/max_h)
        def mint(v):
            #prefer int over float:
            try:
                return int(str(v).rstrip("0").rstrip("."))
            except:
                return v
        if self.server_is_desktop:
            self.xscale = mint(x)
            self.yscale = mint(y)
        else:
            #use the same scale for both axis:
            self.xscale = mint(max(x, y))
            self.yscale = self.xscale
        scalinglog.warn("Warning: adjusting scaling to accomodate server")
        scalinglog.warn(" server desktop size is %ix%i", max_w, max_h)
        scalinglog.warn(" using scaling factor %s x %s", self.xscale, self.yscale)
        self.emit("scaling-changed")


    def set_max_packet_size(self):
        root_w, root_h = self.cp(*self.get_root_size())
        maxw, maxh = root_w, root_h
        try:
            server_w, server_h = self.server_actual_desktop_size
            maxw = max(root_w, server_w)
            maxh = max(root_h, server_h)
        except:
            pass
        assert maxw>0 and maxh>0 and maxw<32768 and maxh<32768, "invalid maximum desktop size: %ix%i" % (maxw, maxh)
        if maxw>=16384 or maxh>=16384:
            log.warn("Warning: the desktop size is extremely large: %ix%i", maxw, maxh)
        #max packet size to accomodate:
        # * full screen RGBX (32 bits) uncompressed
        # * file-size-limit
        # both with enough headroom for some metadata (4k)
        p = self._protocol
        if p:
            p.max_packet_size = max(maxw*maxh*4, self.file_size_limit*1024*1024) + 4*1024
            p.abs_max_packet_size = max(maxw*maxh*4 * 4, self.file_size_limit*1024*1024) + 4*1024
            log("maximum packet size set to %i", p.max_packet_size)


    def init_authenticated_packet_handlers(self):
        log("init_authenticated_packet_handlers()")
        XpraClientBase.init_authenticated_packet_handlers(self)
        self.set_packet_handlers(self._ui_packet_handlers, {
            "startup-complete":     self._process_startup_complete,
            "new-window":           self._process_new_window,
            "new-override-redirect":self._process_new_override_redirect,
            "new-tray":             self._process_new_tray,
            "raise-window":         self._process_raise_window,
            "initiate-moveresize":  self._process_initiate_moveresize,
            "show-desktop":         self._process_show_desktop,
            "window-move-resize":   self._process_window_move_resize,
            "window-resized":       self._process_window_resized,
            "pointer-position":     self._process_pointer_position,
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
            "webcam-stop":          self._process_webcam_stop,
            "webcam-ack":           self._process_webcam_ack,
            "clipboard-token":              self.process_clipboard_packet,
            "clipboard-request":            self.process_clipboard_packet,
            "clipboard-contents":           self.process_clipboard_packet,
            "clipboard-contents-none":      self.process_clipboard_packet,
            "clipboard-pending-requests":   self.process_clipboard_packet,
            "clipboard-enable-selections":  self.process_clipboard_packet,
            })
        #these handlers can run directly from the network thread:
        self.set_packet_handlers(self._packet_handlers, {
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "info-response":        self._process_info_response,
            "sound-data":           self._process_sound_data,
            "server-event":         self._process_server_event,
            })


    def process_clipboard_packet(self, packet):
        ch = self.clipboard_helper
        clipboardlog("process_clipboard_packet: %s, helper=%s", packet[0], ch)
        if ch:
            ch.process_clipboard_packet(packet)

    def process_packet(self, proto, packet):
        self.check_server_echo(0)
        XpraClientBase.process_packet(self, proto, packet)
