# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
from collections import deque

from xpra.log import Logger
log = Logger("client")
traylog = Logger("client", "tray")
keylog = Logger("client", "keyboard")
workspacelog = Logger("client", "workspace")
iconlog = Logger("client", "icon")
screenlog = Logger("client", "screen")
netlog = Logger("network")
bandwidthlog = Logger("bandwidth")


from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.client.client_base import XpraClientBase
from xpra.exit_codes import EXIT_TIMEOUT
from xpra.client.keyboard_helper import KeyboardHelper
from xpra.platform import set_name
from xpra.platform.features import MMAP_SUPPORTED
from xpra.platform.gui import (ready as gui_ready,
                               get_native_tray_classes, get_session_type,
                               get_native_tray_menu_helper_class, ClientExtras)
from xpra.codecs.loader import load_codecs, codec_versions, has_codec, get_codec, PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS
from xpra.version_util import full_version_str
from xpra.scripts.config import parse_bool_or_int, parse_bool
from xpra.net import compression, packet_encoding
from xpra.child_reaper import reaper_cleanup
from xpra.os_util import platform_name, bytestostr, monotonic_time, strtobytes, POSIX, BITS
from xpra.util import nonl, std, envint, envbool, typedict, updict, csv, make_instance, CLIENT_EXIT, XPRA_APP_ID
from xpra.version_util import get_version_info_full, get_platform_info
#client mixins:
from xpra.client.mixins.webcam_forwarder import WebcamForwarder
from xpra.client.mixins.audio_client import AudioClient
from xpra.client.mixins.rpc_client import RPCClient
from xpra.client.mixins.clipboard_client import ClipboardClient
from xpra.client.mixins.notification_client import NotificationClient
from xpra.client.mixins.window_client import WindowClient
from xpra.client.mixins.mmap_client import MmapClient
from xpra.client.mixins.remote_logging import RemoteLogging
from xpra.client.mixins.display_client import DisplayClient


FAKE_BROKEN_CONNECTION = envint("XPRA_FAKE_BROKEN_CONNECTION")
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)

#LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")


MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)

TRAY_DELAY = envint("XPRA_TRAY_DELAY", 0)


"""
Utility superclass for client classes which have a UI.
See gtk_client_base and its subclasses.
"""
class UIXpraClient(XpraClientBase, DisplayClient, WindowClient, WebcamForwarder, AudioClient, ClipboardClient, NotificationClient, RPCClient, MmapClient, RemoteLogging):
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
        DisplayClient.__init__(self)
        WindowClient.__init__(self)
        WebcamForwarder.__init__(self)
        AudioClient.__init__(self)
        ClipboardClient.__init__(self)
        NotificationClient.__init__(self)
        RPCClient.__init__(self)
        MmapClient.__init__(self)
        RemoteLogging.__init__(self)
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

        #statistics and server info:
        self.server_start_time = -1
        self.server_platform = ""

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

        self.init_aliases()


    def init(self, opts):
        """ initialize variables from configuration """
        XpraClientBase.init(self, opts)
        DisplayClient.init(self, opts)
        WindowClient.init(self, opts)
        WebcamForwarder.init(self, opts)
        AudioClient.init(self, opts)
        ClipboardClient.init(self, opts)
        NotificationClient.init(self, opts)
        RPCClient.init(self, opts)
        MmapClient.init(self, opts)
        RemoteLogging.init(self, opts)
        self.allowed_encodings = opts.encodings
        self.encoding = opts.encoding
        self.video_scaling = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.title = opts.title
        self.session_name = bytestostr(opts.session_name)

        self.xsettings_enabled = opts.xsettings

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
        for x in (XpraClientBase, DisplayClient, WindowClient, WebcamForwarder, AudioClient, ClipboardClient, NotificationClient, RPCClient, MmapClient, RemoteLogging):
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


    def get_mouse_position(self):
        raise NotImplementedError()

    def get_current_modifiers(self):
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
            "setting-change", "info-namespace",
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
        caps.update(DisplayClient.get_caps(self))
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
        mmap_caps = MmapClient.get_caps(self)
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
        MmapClient.setup_connection(self, conn)

    def server_connection_established(self):
        if not XpraClientBase.server_connection_established(self):
            return False
        #process the rest from the UI thread:
        self.idle_add(self.process_ui_capabilities)
        return True


    def parse_server_capabilities(self):
        if not XpraClientBase.parse_server_capabilities(self):
            return  False
        RemoteLogging.parse_server_capabilities(self)
        DisplayClient.parse_server_capabilities(self)
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
        DisplayClient.parse_ui_capabilities(self)
        WindowClient.parse_ui_capabilities(self)
        WebcamForwarder.process_capabilities(self)
        AudioClient.process_capabilities(self)
        RPCClient.parse_capabilities(self)
        ClipboardClient.parse_capabilities(self)
        NotificationClient.parse_server_capabilities(self)
        #figure out the maximum actual desktop size and use it to
        #calculate the maximum size of a packet (a full screen update packet)
        self.send_deflate_level()
        c = self.server_capabilities
        if self.keyboard_helper:
            modifier_keycodes = c.dictget("modifier_keycodes")
            if modifier_keycodes:
                self.keyboard_helper.set_modifier_mappings(modifier_keycodes)

        self.key_repeat_delay, self.key_repeat_interval = c.intpair("key_repeat", (-1,-1))
        self.handshake_complete()

        #FIXME: merge this with parse?
        ClipboardClient.process_ui_capabilities(self)

        self.connect("keyboard-sync-toggled", self.send_keyboard_sync_enabled_status)
        self.send_ping()
        if self.pings>0:
            self.timeout_add(1000*self.pings, self.send_ping)


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
    # packets:
    def init_authenticated_packet_handlers(self):
        log("init_authenticated_packet_handlers()")
        XpraClientBase.init_authenticated_packet_handlers(self)
        DisplayClient.init_authenticated_packet_handlers(self)
        WindowClient.init_authenticated_packet_handlers(self)
        WebcamForwarder.init_authenticated_packet_handlers(self)
        AudioClient.init_authenticated_packet_handlers(self)
        RPCClient.init_authenticated_packet_handlers(self)
        ClipboardClient.init_authenticated_packet_handlers(self)
        NotificationClient.init_authenticated_packet_handlers(self)
        self.set_packet_handlers(self._ui_packet_handlers, {
            "startup-complete":     self._process_startup_complete,
            "setting-change":       self._process_setting_change,
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
