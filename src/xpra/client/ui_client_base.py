# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import traceback
import logging
from collections import deque

from xpra.log import Logger, set_global_logging_handler
log = Logger("client")
traylog = Logger("client", "tray")
keylog = Logger("client", "keyboard")
workspacelog = Logger("client", "workspace")
iconlog = Logger("client", "icon")
screenlog = Logger("client", "screen")
scalinglog = Logger("scaling")
netlog = Logger("network")
bandwidthlog = Logger("bandwidth")


from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.client.client_base import XpraClientBase
from xpra.exit_codes import (EXIT_TIMEOUT, EXIT_MMAP_TOKEN_FAILURE, EXIT_INTERNAL_ERROR)
from xpra.client.keyboard_helper import KeyboardHelper
from xpra.platform import set_name
from xpra.platform.features import MMAP_SUPPORTED, REINIT_WINDOWS
from xpra.platform.gui import (ready as gui_ready, get_antialias_info, get_icc_info, get_display_icc_info, show_desktop, get_cursor_size,
                               get_native_tray_classes, get_session_type,
                               get_native_tray_menu_helper_class, get_xdpi, get_ydpi, get_number_of_desktops, get_desktop_names, get_wm_name, ClientExtras)
from xpra.codecs.loader import load_codecs, codec_versions, has_codec, get_codec, PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS
from xpra.version_util import full_version_str
from xpra.scripts.config import parse_bool_or_int, parse_bool, FALSE_OPTIONS, TRUE_OPTIONS
from xpra.simple_stats import std_unit
from xpra.net import compression, packet_encoding
from xpra.child_reaper import reaper_cleanup
from xpra.os_util import platform_name, bytestostr, monotonic_time, strtobytes, POSIX, BITS
from xpra.util import nonl, std, iround, envint, envfloat, envbool, log_screen_sizes, typedict, updict, csv, engs, make_instance, CLIENT_EXIT, XPRA_APP_ID
from xpra.version_util import get_version_info_full, get_platform_info
from xpra.client.webcam_forwarder import WebcamForwarder
from xpra.client.audio_client import AudioClient
from xpra.client.rpc_client import RPCClient
from xpra.client.clipboard_client import ClipboardClient
from xpra.client.notification_client import NotificationClient
from xpra.client.window_client import WindowClient


FAKE_BROKEN_CONNECTION = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
UNGRAB_KEY = os.environ.get("XPRA_UNGRAB_KEY", "Escape")

MONITOR_CHANGE_REINIT = envint("XPRA_MONITOR_CHANGE_REINIT")

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)

#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")


MIN_SCALING = envfloat("XPRA_MIN_SCALING", "0.1")
MAX_SCALING = envfloat("XPRA_MAX_SCALING", "8")
SCALING_OPTIONS = [float(x) for x in os.environ.get("XPRA_TRAY_SCALING_OPTIONS", "0.25,0.5,0.666,1,1.25,1.5,2.0,3.0,4.0,5.0").split(",") if float(x)>=MIN_SCALING and float(x)<=MAX_SCALING]
SCALING_EMBARGO_TIME = int(os.environ.get("XPRA_SCALING_EMBARGO_TIME", "1000"))/1000.0
MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)

TRAY_DELAY = envint("XPRA_TRAY_DELAY", 0)


def r4cmp(v, rounding=1000.0):    #ignore small differences in floats for scale values
    return iround(v*rounding)
def fequ(v1, v2):
    return r4cmp(v1)==r4cmp(v2)


"""
Utility superclass for client classes which have a UI.
See gtk_client_base and its subclasses.
"""
class UIXpraClient(XpraClientBase, WindowClient, WebcamForwarder, AudioClient, ClipboardClient, NotificationClient, RPCClient):
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
        log.info("Xpra %s client version %s %i-bit", self.client_toolkit(), full_version_str(), BITS)
        XpraClientBase.__init__(self)
        WindowClient.__init__(self)
        WebcamForwarder.__init__(self)
        AudioClient.__init__(self)
        ClipboardClient.__init__(self)
        NotificationClient.__init__(self)
        RPCClient.__init__(self)
        try:
            pinfo = get_platform_info()
            osinfo = "%s" % platform_name(sys.platform, pinfo.get("linux_distribution") or pinfo.get("sysrelease", ""))
            log.info(" running on %s", osinfo)
        except:
            log("platform name error:", exc_info=True)
        self.start_time = monotonic_time()

        self._ui_events = 0
        self.title = ""
        self.session_name = u""

        self.dpi = 0
        self.initial_scaling = 1, 1
        self.xscale, self.yscale = self.initial_scaling
        self.scale_change_embargo = 0
        self.desktop_fullscreen = False
        self.screen_size_change_pending = False

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.server_bandwidth_limit_change = False
        self.server_bandwidth_limit = 0
        self.server_session_name = None

        self.server_last_info = None
        self.info_request_pending = False

        self.allowed_encodings = []
        self.core_encodings = None
        self.encoding = None

        #network state:
        self.server_ping_latency = deque(maxlen=1000)
        self.server_load = None
        self.client_ping_latency = deque(maxlen=1000)
        self._server_ok = True
        self.last_ping_echoed_time = 0

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
        self.readonly = False
        self.pings = False
        self.xsettings_enabled = False
        self.server_start_new_commands = False

        #in WindowClient - should it be?
        #self.server_is_desktop = False
        self.server_sharing = False
        self.server_sharing_toggle = False
        self.server_lock = False
        self.server_lock_toggle = False
        self.server_window_filters = False
        #what we told the server about our encoding defaults:
        self.encoding_defaults = {}

        self.client_supports_opengl = False
        self.client_supports_sharing = False
        self.client_supports_remote_logging = False
        self.client_lock = False
        self.log_both = False

        self.supports_mmap = MMAP_SUPPORTED

        #helpers and associated flags:
        self.client_extras = None
        self.keyboard_helper_class = KeyboardHelper
        self.keyboard_helper = None
        self.keyboard_grabbed = False
        self.pointer_grabbed = False
        self.kh_warning = False
        self.menu_helper = None
        self.tray = None
        self.in_remote_logging = False
        self.local_logging = None

        #state:
        self._on_handshake = []
        self._on_server_setting_changed = {}
        self._current_screen_sizes = None

        self.init_aliases()


    def init(self, opts):
        """ initialize variables from configuration """
        WindowClient.init(self, opts)
        WebcamForwarder.init(self, opts)
        AudioClient.init(self, opts)
        ClipboardClient.init(self, opts)
        NotificationClient.init(self, opts)
        self.allowed_encodings = opts.encodings
        self.encoding = opts.encoding
        self.video_scaling = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.title = opts.title
        self.session_name = bytestostr(opts.session_name)
        self.desktop_scaling = opts.desktop_scaling
        self.can_scale = opts.desktop_scaling not in FALSE_OPTIONS
        if self.can_scale:
            root_w, root_h = self.get_root_size()
            from xpra.client.scaling_parser import parse_scaling
            self.initial_scaling = parse_scaling(opts.desktop_scaling, root_w, root_h, MIN_SCALING, MAX_SCALING)
            self.xscale, self.yscale = self.initial_scaling

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

        self.readonly = opts.readonly
        self.pings = opts.pings

        self.client_supports_sharing = opts.sharing is True
        self.client_lock = opts.lock is True
        self.log_both = (opts.remote_logging or "").lower()=="both"
        self.client_supports_remote_logging = self.log_both or parse_bool("remote-logging", opts.remote_logging)

        #until we add the ability to choose decoders, use all of them:
        #(and default to non grahics card csc modules if not specified)
        load_codecs(encoders=False)
        vh = getVideoHelper()
        vh.set_modules(video_decoders=opts.video_decoders, csc_modules=opts.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()


    def init_ui(self, opts, extra_args=[]):
        """ initialize user interface """
        if not self.readonly:
            def noauto(v):
                if not v:
                    return None
                if str(v).lower()=="auto":
                    return None
                return v
            overrides = [noauto(getattr(opts, "keyboard_%s" % x)) for x in ("layout", "layouts", "variant", "variants", "options")]
            self.keyboard_helper = self.keyboard_helper_class(self.send, opts.keyboard_sync, opts.shortcut_modifiers, opts.key_shortcut, opts.keyboard_raw, *overrides)

        if opts.tray:
            self.menu_helper = self.make_tray_menu_helper()
            def setup_xpra_tray(*args):
                traylog("setup_xpra_tray%s", args)
                self.tray = self.setup_xpra_tray(opts.tray_icon or "xpra")
                if self.tray:
                    self.tray.show()
                #re-set the icon after a short delay,
                #seems to help with buggy tray geometries:
                self.timeout_add(1000, self.tray.set_icon)
            if opts.delay_tray:
                self.connect("first-ui-received", setup_xpra_tray)
            else:
                #show shortly after the main loop starts running:
                self.timeout_add(TRAY_DELAY, setup_xpra_tray)

        NotificationClient.init_ui(self)

        self.init_opengl(opts.opengl)

        #audio tagging:
        AudioClient.init_audio_tagging(self, opts.tray_icon)

        if ClientExtras is not None:
            self.client_extras = ClientExtras(self, opts)

        WindowClient.init_ui(self, opts, extra_args)


    def run(self):
        if self.client_extras:
            self.idle_add(self.client_extras.ready)
        WindowClient.run(self)      #start decoding thread
        XpraClientBase.run(self)    #start network threads
        self.send_hello()


    def quit(self, exit_code=0):
        raise Exception("override me!")

    def cleanup(self):
        log("UIXpraClient.cleanup()")
        for x in (XpraClientBase, WindowClient, WebcamForwarder, AudioClient, ClipboardClient, NotificationClient):
            x.cleanup(self)
        for x in (self.keyboard_helper, self.tray, self.menu_helper, self.client_extras, getVideoHelper()):
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


    def signal_cleanup(self):
        log("UIXpraClient.signal_cleanup()")
        XpraClientBase.signal_cleanup(self)
        reaper_cleanup()
        log("UIXpraClient.signal_cleanup() done")


    def show_about(self, *_args):
        log.warn("show_about() is not implemented in %s", self)

    def show_session_info(self, *_args):
        log.warn("show_session_info() is not implemented in %s", self)

    def show_bug_report(self, *_args):
        log.warn("show_bug_report() is not implemented in %s", self)


    def init_opengl(self, _enable_opengl):
        self.opengl_enabled = False
        self.client_supports_opengl = False
        self.opengl_props = {"info" : "not supported"}


    def _ui_event(self):
        if self._ui_events==0:
            self.emit("first-ui-received")
        self._ui_events += 1


    def webcam_state_changed(self):
        self.idle_add(self.emit, "webcam-changed")


    def get_screen_sizes(self, xscale=1, yscale=1):
        raise NotImplementedError()

    def get_root_size(self):
        raise NotImplementedError()

    def set_windows_cursor(self, client_windows, new_cursor):
        raise NotImplementedError()

    def get_mouse_position(self):
        raise NotImplementedError()

    def get_current_modifiers(self):
        raise NotImplementedError()

    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        raise NotImplementedError()


    def send_start_command(self, name, command, ignore, sharing=True):
        log("send_start_command(%s, %s, %s, %s)", name, command, ignore, sharing)
        self.send("start-command", name, command, ignore, sharing)


    def get_version_info(self):
        return get_version_info_full()


    ######################################################################
    # hello:
    def make_hello(self):
        caps = XpraClientBase.make_hello(self)
        caps["session-type"] = get_session_type()

        #don't try to find the server uuid if this platform cannot run servers..
        #(doing so causes lockups on win32 and startup errors on osx)
        if MMAP_SUPPORTED:
            #we may be running inside another server!
            try:
                from xpra.server.server_uuid import get_uuid
                caps["server_uuid"] = get_uuid() or ""
            except:
                pass
        for x in (
            #generic feature flags:
            "notify-startup-complete", "wants_events",
            "setting-change", "randr_notify", "show-desktop", "info-namespace",
            #legacy (not needed in 1.0 - can be dropped soon):
            "generic-rgb-encodings",
            ):
            caps[x] = True
        #FIXME: the messy bits without proper namespace:
        caps.update({
            #generic server flags:
            "share"                     : self.client_supports_sharing,
            "lock"                      : self.client_lock,
            "system_tray"               : self.client_supports_system_tray,
            #window meta data and handling:
            "generic_window_types"      : True,
            "server-window-move-resize" : True,
            "server-window-resize"      : True,
            "encodings"                 : self.get_encodings(),
            "encodings.core"            : self.get_core_encodings(),
            "encodings.window-icon"     : self.get_window_icon_encodings(),
            "encodings.cursor"          : self.get_cursor_encodings(),
            })
        #messy unprefixed:
        caps.update(WindowClient.get_caps(self))
        caps.update(self.get_keyboard_caps())
        caps.update(self.get_desktop_caps())
        #nicely prefixed:
        def u(prefix, c):
            updict(caps, prefix, c, flatten_dicts=False)
        u("sound",              AudioClient.get_audio_capabilities(self))
        u("window",             self.get_window_caps())
        u("notifications",      self.get_notifications_caps())
        u("clipboard",          self.get_clipboard_caps())
        u("encoding",           self.get_encodings_caps())
        u("control_commands",   self.get_control_commands_caps())
        u("platform",           get_platform_info())
        u("batch",              self.get_batch_caps())
        mmap_caps = self.get_mmap_caps()
        u("mmap",               mmap_caps)
        #pre 2.3 servers only use underscore instead of "." prefix for mmap caps:
        for k,v in mmap_caps.items():
            caps["mmap_%s" % k] = v
        return caps


    def get_batch_caps(self):
        #batch options:
        caps = {}
        for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
            evalue = os.environ.get("XPRA_BATCH_%s" % bprop.upper())
            if evalue:
                try:
                    caps["batch.%s" % bprop] = int(evalue)
                except:
                    log.error("Error: invalid environment value for %s: %s", bprop, evalue)
        log("get_batch_caps()=%s", caps)
        return caps


    ######################################################################
    # connection setup:
    def setup_connection(self, conn):
        XpraClientBase.setup_connection(self, conn)
        if self.supports_mmap:
            self.init_mmap(self.mmap_filename, self.mmap_group, conn.filename)

    def server_connection_established(self):
        if not XpraClientBase.server_connection_established(self):
            return False
        #process the rest from the UI thread:
        self.idle_add(self.process_ui_capabilities)
        return True


    def parse_server_capabilities(self):
        if not XpraClientBase.parse_server_capabilities(self):
            return  False
        c = self.server_capabilities
        self.server_session_name = strtobytes(c.rawget("session_name", b"")).decode("utf-8")
        set_name("Xpra", self.session_name or self.server_session_name or "Xpra")
        self.server_sharing = c.boolget("sharing")
        self.server_sharing_toggle = c.boolget("sharing-toggle")
        self.server_lock = c.boolget("lock")
        self.server_lock_toggle = c.boolget("lock-toggle")

        self.server_compressors = c.strlistget("compressors", ["zlib"])
        self.server_start_new_commands = c.boolget("start-new-commands")
        self.server_commands_info = c.boolget("server-commands-info")
        self.server_commands_signals = c.strlistget("server-commands-signals")
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
        self.server_encodings = c.strlistget("encodings")
        self.server_core_encodings = c.strlistget("encodings.core", self.server_encodings)
        self.server_encodings_problematic = c.strlistget("encodings.problematic", PROBLEMATIC_ENCODINGS)  #server is telling us to try to avoid those
        self.server_encodings_with_speed = c.strlistget("encodings.with_speed", ("h264",)) #old servers only supported x264
        self.server_encodings_with_quality = c.strlistget("encodings.with_quality", ("jpeg", "webp", "h264"))
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
        self.server_bandwidth_limit_change = c.boolget("network.bandwidth-limit-change")
        self.server_bandwidth_limit = c.intget("network.bandwidth-limit")
        bandwidthlog("server_bandwidth_limit_change=%s, server_bandwidth_limit=%s", self.server_bandwidth_limit_change, self.server_bandwidth_limit)
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
        WindowClient.parse_ui_capabilities(self)
        WebcamForwarder.process_capabilities(self)
        AudioClient.process_capabilities(self)
        RPCClient.parse_capabilities(self)
        ClipboardClient.parse_capabilities(self)
        NotificationClient.parse_server_capabilities(self)
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        self.set_max_packet_size()
        self.send_deflate_level()
        c = self.server_capabilities
        server_desktop_size = c.intlistget("desktop_size")
        log("server desktop size=%s", server_desktop_size)
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

        self.key_repeat_delay, self.key_repeat_interval = c.intpair("key_repeat", (-1,-1))
        self.handshake_complete()

        ClipboardClient.process_ui_capabilities(self)

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
            dtime = int(1000*(monotonic_time() - self.start_time))
            data = self.compressed_wrapper("text", strtobytes(msg % args), level=1)
            self.send("logging", level, data, dtime)
            exc_info = kwargs.get("exc_info")
            if exc_info is True:
                exc_info = sys.exc_info()
            if exc_info:
                for x in traceback.format_tb(exc_info[2]):
                    self.send("logging", level, strtobytes(x), dtime)
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


    ######################################################################
    # info:
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

    def send_info_request(self, *categories):
        if not self.info_request_pending:
            self.info_request_pending = True
            self.send("info-request", [self.uuid], tuple(self._id_to_window.keys()), categories)


    ######################################################################
    # server messages:
    def _process_server_event(self, packet):
        log(u": ".join((str(x) for x in packet[1:])))

    def on_server_setting_changed(self, setting, cb):
        self._on_server_setting_changed.setdefault(setting, []).append(cb)

    def _process_setting_change(self, packet):
        setting, value = packet[1:3]
        setting = bytestostr(setting)
        #convert "hello" / "setting" variable names to client variables:
        if setting in (
            "bell", "randr", "cursors", "notifications", "dbus-proxy", "clipboard",
            "clipboard-direction", "session_name",
            "sharing", "sharing-toggle", "lock", "lock-toggle",
            "start-new-commands", "client-shutdown", "webcam",
            "bandwidth-limit",
            ):
            setattr(self, "server_%s" % setting.replace("-", "_"), value)
        else:
            log.info("unknown server setting changed: %s=%s", setting, value)
            return
        log.info("server setting changed: %s=%s", setting, value)
        self.server_setting_changed(setting, value)

    def server_setting_changed(self, setting, value):
        log("setting_changed(%s, %s)", setting, value)
        cbs = self._on_server_setting_changed.get(setting)
        if cbs:
            for cb in cbs:
                log("setting_changed(%s, %s) calling %s", setting, value, cb)
                cb(setting, value)


    def get_control_commands_caps(self):
        caps = ["show_session_info", "show_bug_report", "debug"]
        for x in compression.get_enabled_compressors():
            caps.append("enable_"+x)
        for x in packet_encoding.get_enabled_encoders():
            caps.append("enable_"+x)
        log("get_control_commands_caps()=%s", caps)
        return {"" : caps}

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
            self.server_session_name = args[2]
            log.info("session name updated from server: %s", self.server_session_name)
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


    def may_notify_audio(self, summary, body):
        try:
            from xpra.notifications.common import XPRA_AUDIO_NOTIFICATION_ID
        except ImportError:
            log("no notifications")
        else:
            self.may_notify(XPRA_AUDIO_NOTIFICATION_ID, summary, body, icon_name="audio")


    ######################################################################
    # encodings:
    def get_encodings_caps(self):
        if B_FRAMES:
            video_b_frames = ["h264"]   #only tested with dec_avcodec2
        else:
            video_b_frames = []
        caps = {
            "flush"                     : PAINT_FLUSH,
            "scaling.control"           : self.video_scaling,
            "client_options"            : True,
            "csc_atoms"                 : True,
            #TODO: check for csc support (swscale only?)
            "video_reinit"              : True,
            "video_scaling"             : True,
            "video_b_frames"            : video_b_frames,
            "webp_leaks"                : False,
            "transparency"              : self.has_transparency(),
            "rgb24zlib"                 : True,
            "max-soft-expired"          : MAX_SOFT_EXPIRED,
            "send-timestamps"           : SEND_TIMESTAMPS,
            "supports_delta"            : tuple(x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()),
            }
        if self.encoding:
            caps[""] = self.encoding
        for k,v in codec_versions.items():
            caps["%s.version" % k] = v
        if self.quality>0:
            caps["quality"] = self.quality
        if self.min_quality>0:
            caps["min-quality"] = self.min_quality
        if self.speed>=0:
            caps["speed"] = self.speed
        if self.min_speed>=0:
            caps["min-speed"] = self.min_speed

        #generic rgb compression flags:
        for x in compression.ALL_COMPRESSORS:
            caps["rgb_%s" % x] = x in compression.get_enabled_compressors()
        #these are the defaults - when we instantiate a window,
        #we can send different values as part of the map event
        #these are the RGB modes we want (the ones we are expected to be able to paint with):
        rgb_formats = ["RGB", "RGBX", "RGBA"]
        caps["rgb_formats"] = rgb_formats
        #figure out which CSC modes (usually YUV) can give us those RGB modes:
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*rgb_formats)
        if has_codec("dec_webp"):
            if self.opengl_enabled:
                full_csc_modes["webp"] = ("BGRX", "BGRA", "RGBX", "RGBA")
            else:
                full_csc_modes["webp"] = ("BGRX", "BGRA", )
        log("supported full csc_modes=%s", full_csc_modes)
        caps["full_csc_modes"] = full_csc_modes

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
                        caps["%s.%s.profile" % (h264_name, old_csc_name)] = profile
                        caps["%s.%s.profile" % (h264_name, csc_name)] = profile
            log("x264 encoding options: %s", str([(k,v) for k,v in caps.items() if k.startswith("x264.")]))
        iq = max(self.min_quality, self.quality)
        if iq<0:
            iq = 70
        caps["initial_quality"] = iq
        log("encoding capabilities: %s", caps)
        return caps

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
        e = ["premult_argb32", "default"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def do_get_core_encodings(self):
        """
            This method returns the actual encodings supported.
            ie: ["rgb24", "vp8", "webp", "png", "png/L", "png/P", "jpeg", "jpeg2000", "h264", "vpx"]
            It is often overriden in the actual client class implementations,
            where extra encodings can be added (generally just 'rgb32' for transparency),
            or removed if the toolkit implementation class is more limited.
        """
        #we always support rgb:
        core_encodings = ["rgb24", "rgb32"]
        for codec in ("dec_pillow", "dec_webp"):
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
        return core_encodings

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


    ######################################################################
    # features:
    def send_bandwidth_limit(self):
        bandwidthlog("send_bandwidth_limit() bandwidth-limit=%i", self.bandwidth_limit)
        assert self.server_bandwidth_limit_change
        self.send("bandwidth-limit", self.bandwidth_limit)

    def send_sharing_enabled(self):
        assert self.server_sharing and self.server_sharing_toggle
        self.send("sharing-toggle", self.client_supports_sharing)

    def send_lock_enabled(self):
        assert self.server_lock_toggle
        self.send("lock-toggle", self.client_lock)

    def send_notify_enabled(self):
        assert self.client_supports_notifications, "cannot toggle notifications: the feature is disabled by the client"
        self.send("set-notify", self.notifications_enabled)

    def send_bell_enabled(self):
        assert self.client_supports_bell, "cannot toggle bell: the feature is disabled by the client"
        assert self.server_bell, "cannot toggle bell: the feature is disabled by the server"
        self.send("set-bell", self.bell_enabled)

    def send_cursors_enabled(self):
        assert self.client_supports_cursors, "cannot toggle cursors: the feature is disabled by the client"
        assert self.server_cursors, "cannot toggle cursors: the feature is disabled by the server"
        self.send("set-cursors", self.cursors_enabled)

    def send_force_ungrab(self, wid):
        self.send("force-ungrab", wid)

    def send_keyboard_sync_enabled_status(self, *_args):
        self.send("set-keyboard-sync-enabled", self.keyboard_sync)

    def set_deflate_level(self, level):
        self.compression_level = level
        self.send_deflate_level()

    def send_deflate_level(self):
        self._protocol.set_compression_level(self.compression_level)
        self.send("set_deflate", self.compression_level)


    ######################################################################
    # keyboard:
    def get_keyboard_caps(self):
        caps = {}
        if self.readonly:
            #don't bother sending keyboard info, as it won't be used
            caps["keyboard"] = False
        else:
            caps.update(self.get_keymap_properties())
            #show the user a summary of what we have detected:
            self.keyboard_helper.log_keyboard_info()

        caps["modifiers"] = self.get_current_modifiers()
        if self.keyboard_helper:
            delay_ms, interval_ms = self.keyboard_helper.key_repeat_delay, self.keyboard_helper.key_repeat_interval
            if delay_ms>0 and interval_ms>0:
                caps["key_repeat"] = (delay_ms,interval_ms)
            else:
                #cannot do keyboard_sync without a key repeat value!
                #(maybe we could just choose one?)
                self.keyboard_helper.keyboard_sync = False
            caps["keyboard_sync"] = self.keyboard_helper.keyboard_sync
        log("keyboard capabilities: %s", caps)
        return caps

    def window_keyboard_layout_changed(self, window):
        #win32 can change the keyboard mapping per window...
        keylog("window_keyboard_layout_changed(%s)", window)
        if self.keyboard_helper:
            self.keyboard_helper.keymap_changed()

    def get_keymap_properties(self):
        props = self.keyboard_helper.get_keymap_properties()
        props["modifiers"] = self.get_current_modifiers()
        return props

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
        

    ######################################################################
    # windows overrides
    def cook_metadata(self, _new_window, metadata):
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

    ######################################################################
    # xpra's tray:
    def get_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_tray_classes()

    def make_tray_menu_helper(self):
        """ menu helper class used by our tray (make_tray / setup_xpra_tray) """
        mhc = (get_native_tray_menu_helper_class(), self.get_tray_menu_helper_class())
        traylog("make_tray_menu_helper() tray menu helper classes: %s", mhc)
        return make_instance(mhc, self)

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
        if tray:
            def reset_tray_title():
                tray.set_tooltip(self.get_tray_title())
            self.after_handshake(reset_tray_title)
        return tray

    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.get_tray_classes()
        traylog("make_tray%s tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    def get_tray_title(self):
        t = []
        if self.session_name or self.server_session_name:
            t.append(self.session_name or self.server_session_name)
        if self._protocol and self._protocol._conn:
            t.append(bytestostr(self._protocol._conn.target))
        if len(t)==0:
            t.insert(0, u"Xpra")
        v = u"\n".join(t)
        traylog("get_tray_title()=%s (items=%s)", nonl(v), tuple(strtobytes(x) for x in t))
        return v


    ######################################################################
    # desktop and screen:
    def has_transparency(self):
        return False

    def get_icc_info(self):
        return get_icc_info()

    def get_display_icc_info(self):
        return get_display_icc_info()

    def _process_show_desktop(self, packet):
        show = packet[1]
        log("calling %s(%s)", show_desktop, show)
        show_desktop(show)

    def _process_desktop_size(self, packet):
        root_w, root_h, max_w, max_h = packet[1:5]
        screenlog("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h
        if self.can_scale:
            self.may_adjust_scaling()


    def may_adjust_scaling(self):
        log("may_adjust_scaling() server_is_desktop=%s, desktop_fullscreen=%s", self.server_is_desktop, self.desktop_fullscreen)
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
            #prefer int over float,
            #and even tolerate a 0.1% difference to get it:
            if iround(v)*1000==iround(v*1000):
                return int(v)
            return v
        self.xscale = mint(x)
        self.yscale = mint(y)
        #to use the same scale for both axes:
        #self.xscale = mint(max(x, y))
        #self.yscale = self.xscale
        summary = "Desktop scaling adjusted to accomodate the server"
        xstr = ("%.3f" % self.xscale).rstrip("0")
        ystr = ("%.3f" % self.yscale).rstrip("0")
        messages = [
            "server desktop size is %ix%i" % (max_w, max_h),
            "using scaling factor %s x %s" % (xstr, ystr),
            ]
        try:
            from xpra.notifications.common import XPRA_SCALING_NOTIFICATION_ID
        except:
            pass
        else:
            self.may_notify(XPRA_SCALING_NOTIFICATION_ID, summary, "\n".join(messages), icon_name="scaling")
        scalinglog.warn("Warning: %s", summary)
        for m in messages:
            scalinglog.warn(" %s", m)
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
        if maxw<=0 or maxh<=0 or maxw>=32768 or maxh>=32768:
            message = "invalid maximum desktop size: %ix%i" % (maxw, maxh)
            log(message)
            self.quit(EXIT_INTERNAL_ERROR)
            raise SystemExit(message)
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


    ######################################################################
    # screen scaling:
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


    ######################################################################
    # desktop, screen and scaling:
    def get_desktop_caps(self):
        caps = {}
        wm_name = get_wm_name()
        if wm_name:
            caps["wm_name"] = wm_name

        self._last_screen_settings = self.get_screen_settings()
        root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi = self._last_screen_settings
        caps["desktop_size"] = self.cp(u_root_w, u_root_h)
        caps["desktops"] = ndesktops
        caps["desktop.names"] = desktop_names

        ss = self.get_screen_sizes()
        self._current_screen_sizes = ss

        log.info(" desktop size is %sx%s with %s screen%s:", u_root_w, u_root_h, len(ss), engs(ss))
        log_screen_sizes(u_root_w, u_root_h, ss)
        if self.xscale!=1 or self.yscale!=1:
            caps["screen_sizes.unscaled"] = ss
            caps["desktop_size.unscaled"] = u_root_w, u_root_h
            root_w, root_h = self.cp(u_root_w, u_root_h)
            if fequ(self.xscale, self.yscale):
                sinfo = "%i%%" % iround(self.xscale*100)
            else:
                sinfo = "%i%% x %i%%" % (iround(self.xscale*100), iround(self.yscale*100))
            log.info(" %sscaled by %s, virtual screen size: %ix%i", ["down", "up"][int(u_root_w>root_w or u_root_h>root_h)], sinfo, root_w, root_h)
            log_screen_sizes(root_w, root_h, sss)
        else:
            root_w, root_h = u_root_w, u_root_h
            sss = ss
        caps["screen_sizes"] = sss

        caps["screen-scaling"] = True
        caps["screen-scaling.enabled"] = self.xscale!=1 or self.yscale!=1
        caps["screen-scaling.values"] = (int(1000*self.xscale), int(1000*self.yscale))

        #command line (or config file) override supplied:
        dpi = 0
        if self.dpi>0:
            #scale it:
            xdpi = ydpi = dpi = self.cx(self.cy(self.dpi))
        else:
            #not supplied, use platform detection code:
            #platforms may also provide per-axis dpi (later win32 versions do)
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
            screenlog("xdpi=%i, ydpi=%i", xdpi, ydpi)
            if xdpi>0 and ydpi>0:
                xdpi = self.cx(xdpi)
                ydpi = self.cy(ydpi)
                dpi = iround((xdpi+ydpi)/2.0)
                caps.update({
                    "dpi.x"    : xdpi,
                    "dpi.y"    : ydpi,
                    })
        if dpi:
            caps["dpi"] = dpi
        screenlog("dpi: %i", dpi)
        caps.update({
            "antialias"    : get_antialias_info(),
            "icc"          : self.get_icc_info(),
            "display-icc"  : self.get_display_icc_info(),
            "cursor.size"  : int(2*get_cursor_size()/(self.xscale+self.yscale)),
            })
        return caps
    
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


    def get_screen_settings(self):
        u_root_w, u_root_h = self.get_root_size()
        root_w, root_h = self.cp(u_root_w, u_root_h)
        self._current_screen_sizes = self.get_screen_sizes()
        sss = self.get_screen_sizes(self.xscale, self.yscale)
        ndesktops = get_number_of_desktops()
        desktop_names = get_desktop_names()
        screenlog("update_screen_size() sizes=%s, %s desktops: %s", sss, ndesktops, desktop_names)
        if self.dpi>0:
            #use command line value supplied, but scale it:
            xdpi = ydpi = self.dpi
        else:
            #not supplied, use platform detection code:
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
        xdpi = self.cx(xdpi)
        ydpi = self.cy(ydpi)
        screenlog("dpi: %s -> %s", (get_xdpi(), get_ydpi()), (xdpi, ydpi))
        return (root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi)
        
    def update_screen_size(self):
        self.screen_size_change_pending = False
        screen_settings = self.get_screen_settings()
        screenlog("update_screen_size()     new settings=%s", screen_settings)
        screenlog("update_screen_size() current settings=%s", self._last_screen_settings)
        if self._last_screen_settings==screen_settings:
            log("screen size unchanged")
            return
        root_w, root_h, sss = screen_settings[:3]
        screenlog.info("sending updated screen size to server: %sx%s with %s screens", root_w, root_h, len(sss))
        log_screen_sizes(root_w, root_h, sss)
        self.send("desktop_size", *screen_settings)
        self._last_screen_settings = screen_settings
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_xdpi(self):
        return get_xdpi()

    def get_ydpi(self):
        return get_ydpi()


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
            summary = "Invalid Scale Factor"
            messages = [
                "cannot scale by %i%% x %i%% or lower" % ((100*xscale), (100*yscale)),
                "the scaled client screen %i x %i -> %i x %i" % (root_w, root_h, sw, sh),
                " would overflow the server's screen: %i x %i" % (maxw, maxh),
                ]    
            try:
                from xpra.notifications.common import XPRA_SCALING_NOTIFICATION_ID
            except ImportError:
                pass
            else:
                self.may_notify(XPRA_SCALING_NOTIFICATION_ID, summary, "\n".join(messages), "scaling")
            scalinglog.warn("Warning: %s", summary)
            for m in messages:
                scalinglog.warn(" %s", m)
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


    ######################################################################
    # network and status:
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
            l = [x for _,x in tuple(self.server_ping_latency)]
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


    ######################################################################
    # mmap:
    def get_mmap_caps(self):
        if self.mmap_enabled:
            return {
                "file"          : self.mmap_filename,
                "size"          : self.mmap_size,
                "token"         : self.mmap_token,
                "token_index"   : self.mmap_token_index,
                "token_bytes"   : self.mmap_token_bytes,
                }
        return {}
    
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


    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self):
        log("init_authenticated_packet_handlers()")
        XpraClientBase.init_authenticated_packet_handlers(self)
        WindowClient.init_authenticated_packet_handlers(self)
        WebcamForwarder.init_authenticated_packet_handlers(self)
        AudioClient.init_authenticated_packet_handlers(self)
        RPCClient.init_authenticated_packet_handlers(self)
        ClipboardClient.init_authenticated_packet_handlers(self)
        NotificationClient.init_authenticated_packet_handlers(self)
        self.set_packet_handlers(self._ui_packet_handlers, {
            "startup-complete":     self._process_startup_complete,
            "setting-change":       self._process_setting_change,
            "show-desktop":         self._process_show_desktop,
            "desktop_size":         self._process_desktop_size,
            "control" :             self._process_control,
            })
        #these handlers can run directly from the network thread:
        self.set_packet_handlers(self._packet_handlers, {
            "ping":                 self._process_ping,
            "ping_echo":            self._process_ping_echo,
            "info-response":        self._process_info_response,
            "server-event":         self._process_server_event,
            })


    def process_packet(self, proto, packet):
        self.check_server_echo(0)
        XpraClientBase.process_packet(self, proto, packet)
