# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import signal
import datetime
from collections import deque
from time import sleep

from xpra.log import Logger
log = Logger("window")
geomlog = Logger("geometry")
paintlog = Logger("paint")
drawlog = Logger("draw")
focuslog = Logger("focus")
grablog = Logger("grab")
iconlog = Logger("icon")
mouselog = Logger("mouse")
cursorlog = Logger("cursor")
metalog = Logger("metadata")
traylog = Logger("client", "tray")


from xpra.gtk_common.gobject_compat import import_glib
from xpra.platform.gui import get_vrefresh, get_double_click_time, get_double_click_distance, get_native_system_tray_classes
from xpra.platform.features import SYSTEM_TRAY_SUPPORTED
from xpra.platform.paths import get_icon_filename
from xpra.scripts.config import FALSE_OPTIONS
from xpra.make_thread import make_thread
from xpra.os_util import BytesIOClass, Queue, bytestostr, monotonic_time, memoryview_to_bytes, OSX, POSIX, is_Ubuntu
from xpra.util import iround, envint, envbool, typedict, make_instance, updict
from xpra.client.mixins.stub_client_mixin import StubClientMixin


glib = import_glib()

MOUSE_SHOW = envbool("XPRA_MOUSE_SHOW", True)

PAINT_FAULT_RATE = envint("XPRA_PAINT_FAULT_INJECTION_RATE")
PAINT_FAULT_TELL = envbool("XPRA_PAINT_FAULT_INJECTION_TELL", True)

WM_CLASS_CLOSEEXIT = os.environ.get("XPRA_WM_CLASS_CLOSEEXIT", "Xephyr").split(",")
TITLE_CLOSEEXIT = os.environ.get("XPRA_TITLE_CLOSEEXIT", "Xnest").split(",")

SKIP_DUPLICATE_BUTTON_EVENTS = envbool("XPRA_SKIP_DUPLICATE_BUTTON_EVENTS", True)
REVERSE_HORIZONTAL_SCROLLING = envbool("XPRA_REVERSE_HORIZONTAL_SCROLLING", OSX)

DYNAMIC_TRAY_ICON = envbool("XPRA_DYNAMIC_TRAY_ICON", not OSX and not is_Ubuntu())
ICON_OVERLAY = envint("XPRA_ICON_OVERLAY", 50)
ICON_SHRINKAGE = envint("XPRA_ICON_SHRINKAGE", 75)
SAVE_WINDOW_ICONS = envbool("XPRA_SAVE_WINDOW_ICONS", False)
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)


DRAW_TYPES = {bytes : "bytes", str : "bytes", tuple : "arrays", list : "arrays"}


"""
Utility superclass for clients that handle windows:
create, resize, paint, grabs, cursors, etc
"""
class WindowClient(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        self._window_to_id = {}
        self._id_to_window = {}

        self.auto_refresh_delay = -1
        self.max_window_size = 0, 0

        #draw thread:
        self._draw_queue = None
        self._draw_thread = None
        self._draw_counter = 0

        #statistics and server info:
        self.pixel_counter = deque(maxlen=1000)

        self.readonly = False
        self.windows_enabled = True
        self.pixel_depth = 0

        self.server_window_decorations = False
        self.server_window_frame_extents = False
        self.server_is_desktop = False
        self.server_window_states = []
        self.server_window_signals = ()

        self.server_input_devices = None
        self.server_precise_wheel = False
        self.input_devices = "auto"

        self.overlay_image = None

        self.client_supports_system_tray = False
        self.client_supports_cursors = False
        self.client_supports_bell = False
        self.cursors_enabled = False
        self.default_cursor_data = None
        self.bell_enabled = False

        self.border = None
        self.window_close_action = "forward"

        self._pid_to_signalwatcher = {}
        self._signalwatcher_to_wids = {}

        self.wheel_map = {}
        self.wheel_deltax = 0
        self.wheel_deltay = 0

        #state:
        self.lost_focus_timer = None
        self._focused = None
        self._window_with_grab = None
        self._suspended_at = 0
        self._button_state = {}
        self._on_handshake = []

    def init(self, opts):
        if opts.system_tray and SYSTEM_TRAY_SUPPORTED:
            try:
                from xpra.client import client_tray
                assert client_tray
            except ImportError:
                log.warn("Warning: the tray forwarding module is missing")
            else:
                self.client_supports_system_tray = True
        self.client_supports_cursors = opts.cursors
        self.client_supports_bell = opts.bell
        self.input_devices = opts.input_devices
        self.auto_refresh_delay = opts.auto_refresh_delay
        if opts.max_size:
            try:
                self.max_window_size = [int(x.strip()) for x in opts.max_size.split("x", 1)]
                assert len(self.max_window_size)==2
            except:
                #the main script does some checking, but we could be called from a config file launch
                log.warn("Warning: invalid window max-size specified: %s", opts.max_size)
                self.max_window_size = 0, 0
        self.pixel_depth = int(opts.pixel_depth)
        if self.pixel_depth not in (0, 16, 24, 30) and self.pixel_depth<32:
            log.warn("Warning: invalid pixel depth %i", self.pixel_depth)
            self.pixel_depth = 0

        self.windows_enabled = opts.windows

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


    def init_ui(self, opts, extra_args=[]):
        if opts.border:
            self.parse_border(opts.border, extra_args)
        if opts.window_close not in ("forward", "ignore", "disconnect", "shutdown", "auto"):
            self.window_close_action = "forward"
            log.warn("Warning: invalid 'window-close' option: '%s'", opts.window_close)
            log.warn(" using '%s'", self.window_close_action)
        else:
            self.window_close_action = opts.window_close

        if ICON_OVERLAY>0 and ICON_OVERLAY<=100:
            icon_filename = get_icon_filename("xpra")
            if icon_filename:
                try:
                    from PIL import Image   #@UnresolvedImport
                    self.overlay_image = Image.open(icon_filename)
                except Exception as e:
                    log.error("Error: failed to load overlay icon '%s':", icon_filename, exc_info=True)
                    log.error(" %s", e)

        self._draw_queue = Queue()
        self._draw_thread = make_thread(self._draw_thread_loop, "draw")


    def parse_border(self, border_str, extra_args):
        #not implemented here (see gtk2 client)
        pass


    def run(self):
        #we decode pixel data in this thread
        self._draw_thread.start()


    def cleanup(self):
        log("WindowClient.cleanup()")
        #tell the draw thread to exit:
        dq = self._draw_queue
        if dq:
            dq.put(None)
        #the protocol has been closed, it is now safe to close all the windows:
        #(cleaner and needed when we run embedded in the client launcher)
        self.destroy_all_windows()
        self.cancel_lost_focus_timer()
        log("WindowClient.cleanup() done")


    def set_windows_cursor(self, client_windows, new_cursor):
        raise NotImplementedError()

    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        raise NotImplementedError()


    ######################################################################
    # hello:
    def get_caps(self):
        #FIXME: the messy bits without proper namespace:
        caps = {
            #generic server flags:
            #mouse and cursors:
            "mouse.show"                : MOUSE_SHOW,
            "mouse.initial-position"    : self.get_mouse_position(),
            "named_cursors"             : False,
            "cursors"                   : self.client_supports_cursors,
            "double_click.time"         : get_double_click_time(),
            "double_click.distance"     : get_double_click_distance(),
            #features:
            "bell"                      : self.client_supports_bell,
            "vrefresh"                  : get_vrefresh(),
            "windows"                   : self.windows_enabled,
            "auto_refresh_delay"        : int(self.auto_refresh_delay*1000),
            #system tray forwarding:
            "system_tray"               : self.client_supports_system_tray,
            #window meta data and handling:
            "generic_window_types"      : True,
            "server-window-move-resize" : True,
            "server-window-resize"      : True,
            }
        for x in (
            #generic feature flags:
            "wants_default_cursor",
            #window meta data and handling:
            "generic_window_types", "server-window-move-resize", "server-window-resize",
            #legacy (not needed in 1.0 - can be dropped soon):
            "raw_window_icons",
            ):
            caps[x] = True
        updict(caps, "window", self.get_window_caps())
        updict(caps, "encoding", {
            "eos"                       : True,
            })
        return caps

    def get_window_caps(self):
        return {
            "raise"                     : True,
            #implemented in the gtk client:
            "initiate-moveresize"       : False,
            "resize-counter"            : True,
            }


    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.window_configure_pointer = c.boolget("window.configure.pointer")
        self.server_window_decorations = c.boolget("window.decorations")
        self.server_window_frame_extents = c.boolget("window.frame-extents")
        self.server_cursors = c.boolget("cursors", True)    #added in 0.5, default to True!
        self.cursors_enabled = self.server_cursors and self.client_supports_cursors
        self.default_cursor_data = c.listget("cursor.default", None)
        self.server_bell = c.boolget("bell")          #added in 0.5, default to True!
        self.bell_enabled = self.server_bell and self.client_supports_bell
        if c.boolget("windows", True):
            if self.windows_enabled:
                server_auto_refresh_delay = c.intget("auto_refresh_delay", 0)/1000.0
                if server_auto_refresh_delay==0 and self.auto_refresh_delay>0:
                    log.warn("Warning: server does not support auto-refresh!")
        else:
            log.warn("Warning: window forwarding is not enabled on this server")
        self.server_window_signals = c.strlistget("window.signals")
        self.server_window_states = c.strlistget("window.states", ["iconified", "fullscreen", "above", "below", "sticky", "iconified", "maximized"])
        self.server_window_filters = c.boolget("window-filters")
        self.server_is_desktop = c.boolget("shadow") or c.boolget("desktop")
        #input devices:
        self.server_input_devices = c.strget("input-devices")
        self.server_precise_wheel = c.boolget("wheel.precise", False)
        return True


    ######################################################################
    # pointer:
    def _process_pointer_position(self, packet):
        wid, x, y = packet[1:4]
        if len(packet)>=6:
            rx, ry = packet[4:6]
        else:
            rx, ry = -1, -1
        cx, cy = self.get_mouse_position()
        start_time = monotonic_time()
        mouselog("process_pointer_position: %i,%i (%i,%i relative to wid %i) - current position is %i,%i", x, y, rx, ry, wid, cx, cy)
        size = 10
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
                mouselog("send_wheel_delta(..) %s", packet)
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
        if REVERSE_HORIZONTAL_SCROLLING:
            deltax = -deltax
        self.wheel_deltax += deltax
        self.wheel_deltay += deltay
        button = self.wheel_map.get(6+int(self.wheel_deltax>0))            #RIGHT=7, LEFT=6
        if button>0:
            self.wheel_deltax = self.send_wheel_delta(wid, button, self.wheel_deltax, deviceid)
        button = self.wheel_map.get(5-int(self.wheel_deltay>0))            #UP=4, DOWN=5
        if button>0:
            self.wheel_deltay = self.send_wheel_delta(wid, button, self.wheel_deltay, deviceid)
        mouselog("wheel_event%s new deltas=%s,%s", (wid, deltax, deltay, deviceid), self.wheel_deltax, self.wheel_deltay)

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

    def scale_pointer(self, pointer):
        #subclass may scale this:
        #return int(pointer[0]/self.xscale), int(pointer[1]/self.yscale)
        return int(pointer[0]), int(pointer[1])

    def send_input_devices(self, fmt, input_devices):
        assert self.server_input_devices
        self.send("input-devices", fmt, input_devices)


    ######################################################################
    # cursor:
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
                if SAVE_CURSORS:
                    serial = new_cursor[7]
                    with open("raw-cursor-%#x.png" % serial, 'wb') as f:
                        f.write(pixels)
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

    def reset_cursor(self):
        self.set_windows_cursor(self._id_to_window.values(), [])


    def cook_metadata(self, _new_window, metadata):
        #subclasses can apply tweaks here:
        return typedict(metadata)


    ######################################################################
    # system tray
    def _process_new_tray(self, packet):
        assert self.client_supports_system_tray
        self._ui_event()
        wid, w, h = packet[1:4]
        w = max(1, self.sx(w))
        h = max(1, self.sy(h))
        metadata = typedict()
        if len(packet)>=5:
            metadata = typedict(packet[4])
        traylog("tray %i metadata=%s", wid, metadata)
        assert wid not in self._id_to_window, "we already have a window %s: %s" % (wid, self._id_to_window.get(wid))
        app_id = wid
        tray = self.setup_system_tray(self, app_id, wid, w, h, metadata)
        traylog("process_new_tray(%s) tray=%s", packet, tray)
        self._id_to_window[wid] = tray
        self._window_to_id[tray] = wid


    def make_system_tray(self, *args):
        """ tray used for application systray forwarding """
        tc = self.get_system_tray_classes()
        traylog("make_system_tray%s system tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    def get_system_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_system_tray_classes()

    def setup_system_tray(self, client, app_id, wid, w, h, metadata):
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
        title = metadata.strget("title", "")
        tray_widget = self.make_system_tray(app_id, None, title, None, tray_geometry, tray_click, tray_mouseover, tray_exit)
        traylog("setup_system_tray%s tray_widget=%s", (client, app_id, wid, w, h, title), tray_widget)
        assert tray_widget, "could not instantiate a system tray for tray id %s" % wid
        tray_widget.show()
        from xpra.client.client_tray import ClientTray
        return ClientTray(client, wid, w, h, metadata, tray_widget, self.mmap_enabled, self.mmap)


    def get_tray_window(self, app_name, hints):
        #try to identify the application tray that generated this notification,
        #so we can show it as coming from the correct systray icon
        #on platforms that support it (ie: win32)
        trays = tuple(w for w in self._id_to_window.values() if w.is_tray())
        if trays:
            try:
                pid = int(hints.get("pid") or 0)
            except (TypeError, ValueError):
                pass
            else:
                if pid:
                    for tray in trays:
                        metadata = getattr(tray, "_metadata", typedict())
                        if metadata.intget("pid")==pid:
                            traylog("tray window: matched pid=%i", pid)
                            return tray.tray_widget
            if app_name and app_name.lower()!="xpra":
                #exact match:
                for tray in trays:
                    #traylog("window %s: is_tray=%s, title=%s", window, window.is_tray(), getattr(window, "title", None))
                    if tray.title==app_name:
                        return tray.tray_widget
                for tray in trays:
                    if tray.title.find(app_name)>=0:
                        return tray.tray_widget
        return self.tray


    def set_tray_icon(self):
        #find all the window icons,
        #and if they are all using the same one, then use it as tray icon
        #otherwise use the default icon
        traylog("set_tray_icon() DYNAMIC_TRAY_ICON=%s, tray=%s", DYNAMIC_TRAY_ICON, self.tray)
        if not self.tray:
            return
        if not DYNAMIC_TRAY_ICON:
            #the icon ends up looking garbled on win32,
            #and we somehow also lose the settings that can keep us in the visible systray list
            #so don't bother
            return
        windows = tuple(w for w in self._window_to_id.keys() if not w.is_tray())
        #get all the icons:
        icons = tuple(getattr(w, "_current_icon", None) for w in windows)
        missing = sum(1 for icon in icons if icon is None)
        traylog("set_tray_icon() %i windows, %i icons, %i missing", len(windows), len(icons), missing)
        if icons and not missing:
            icon = icons[0]
            for i in icons[1:]:
                if i!=icon:
                    #found a different icon
                    icon = None
                    break
            if icon:
                has_alpha = icon.mode=="RGBA"
                width, height = icon.size
                traylog("set_tray_icon() using unique %s icon: %ix%i (has-alpha=%s)", icon.mode, width, height, has_alpha)
                rowstride = width * (3+int(has_alpha))
                rgb_data = icon.tobytes("raw", icon.mode)
                self.tray.set_icon_from_data(rgb_data, has_alpha, width, height, rowstride)
                return
        #this sets the default icon (badly named function!)
        traylog("set_tray_icon() using default icon")
        self.tray.set_icon()


    ######################################################################
    # combine the window icon with our own icon
    def _window_icon_image(self, wid, width, height, coding, data):
        #convert the data into a pillow image,
        #adding the icon overlay (if enabled)
        from PIL import Image
        coding = bytestostr(coding)
        iconlog("%s.update_icon(%s, %s, %s, %s bytes) ICON_SHRINKAGE=%s, ICON_OVERLAY=%s", self, width, height, coding, len(data), ICON_SHRINKAGE, ICON_OVERLAY)
        if coding=="default":
            img = self.overlay_image
        elif coding == "premult_argb32":            #we usually cannot do in-place and this is not performance critical
            from xpra.codecs.argb.argb import unpremultiply_argb    #@UnresolvedImport
            data = unpremultiply_argb(data)
            rowstride = width*4
            img = Image.frombytes("RGBA", (width,height), memoryview_to_bytes(data), "raw", "BGRA", rowstride, 1)
            has_alpha = True
        else:
            buf = BytesIOClass(data)
            img = Image.open(buf)
            assert img.mode in ("RGB", "RGBA"), "invalid image mode: %s" % img.mode
            has_alpha = img.mode=="RGBA"
            rowstride = width * (3+int(has_alpha))
        icon = img
        if self.overlay_image and self.overlay_image!=img:
            if ICON_SHRINKAGE>0 and ICON_SHRINKAGE<100:
                #paste the application icon in the top-left corner,
                #shrunk by ICON_SHRINKAGE pct
                shrunk_width = max(1, width*ICON_SHRINKAGE//100)
                shrunk_height = max(1, height*ICON_SHRINKAGE//100)
                icon_resized = icon.resize((shrunk_width, shrunk_height), Image.ANTIALIAS)
                icon = Image.new("RGBA", (width, height))
                icon.paste(icon_resized, (0, 0, shrunk_width, shrunk_height))
            assert ICON_OVERLAY>0 and ICON_OVERLAY<=100
            overlay_width = max(1, width*ICON_OVERLAY//100)
            overlay_height = max(1, height*ICON_OVERLAY//100)
            xpra_resized = self.overlay_image.resize((overlay_width, overlay_height), Image.ANTIALIAS)
            xpra_corner = Image.new("RGBA", (width, height))
            xpra_corner.paste(xpra_resized, (width-overlay_width, height-overlay_height, width, height))
            composite = Image.alpha_composite(icon, xpra_corner)
            icon = composite
        if SAVE_WINDOW_ICONS:
            filename = "client-window-%i-icon-%i.png" % (wid, int(time.time()))
            icon.save(filename, "png")
            iconlog("client window icon saved to %s", filename)
        return icon


    ######################################################################
    # regular windows:
    def _process_new_common(self, packet, override_redirect):
        self._ui_event()
        wid, x, y, w, h = packet[1:6]
        assert w>=0 and h>=0 and w<32768 and h<32768
        metadata = self.cook_metadata(True, packet[6])
        metalog("process_new_common: %s, metadata=%s, OR=%s", packet[1:7], metadata, override_redirect)
        assert wid not in self._id_to_window, "we already have a window %s: %s" % (wid, self._id_to_window.get(wid))
        if w<1 or h<1:
            log.error("window dimensions are wrong: %sx%s", w, h)
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

    def make_new_window(self, wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties):
        client_window_classes = self.get_client_window_classes(ww, wh, metadata, override_redirect)
        group_leader_window = self.get_group_leader(wid, metadata, override_redirect)
        #workaround for "popup" OR windows without a transient-for (like: google chrome popups):
        #prevents them from being pushed under other windows on OSX
        #find a "transient-for" value using the pid to find a suitable window
        #if possible, choosing the currently focused window (if there is one..)
        pid = metadata.intget("pid", 0)
        watcher_pid = self.assign_signal_watcher_pid(wid, pid)
        if override_redirect and pid>0 and metadata.intget("transient-for", 0)>0 is None and metadata.get("role")=="popup":
            tfor = None
            for twid, twin in self._id_to_window.items():
                if not twin._override_redirect and twin._metadata.intget("pid", -1)==pid:
                    tfor = twin
                    if twid==self._focused:
                        break
            if tfor:
                log("forcing transient for=%s for new window %s", twid, wid)
                metadata["transient-for"] = twid
        border = None
        if self.border:
            border = self.border.clone()
        window = None
        log("make_new_window(..) client_window_classes=%s, group_leader_window=%s", client_window_classes, group_leader_window)
        for cwc in client_window_classes:
            try:
                window = cwc(self, group_leader_window, watcher_pid, wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties, border, self.max_window_size, self.default_cursor_data, self.pixel_depth)
                break
            except:
                log.warn("failed to instantiate %s", cwc, exc_info=True)
        if window is None:
            log.warn("no more options.. this window will not be shown, sorry")
            return None
        log("make_new_window(..) window(%i)=%s", wid, window)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        window.show()
        return window

    ######################################################################
    # listen for process signals using a watcher process:
    def assign_signal_watcher_pid(self, wid, pid):
        if not POSIX or OSX or not pid:
            return 0
        proc = self._pid_to_signalwatcher.get(pid)
        if proc is None or proc.poll():
            from xpra.child_reaper import getChildReaper
            import subprocess
            try:
                proc = subprocess.Popen("xpra_signal_listener", stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, preexec_fn=os.setsid)
            except OSError as e:
                log("assign_signal_watcher_pid(%s, %s)", wid, pid, exc_info=True)
                log.error("Error: cannot execute signal listener")
                log.error(" %s", e)
                proc = None
            if proc and proc.poll() is None:
                #def add_process(self, process, name, command, ignore=False, forget=False, callback=None):
                proc.stdout_io_watch = None
                def watcher_terminated(*args):
                    #watcher process terminated, remove io watch:
                    #this may be redundant since we also return False from signal_watcher_event
                    log("watcher_terminated%s", args)
                    source = proc.stdout_io_watch
                    if source:
                        proc.stdout_io_watch = None
                        self.source_remove(source)
                getChildReaper().add_process(proc, "signal listener for remote process %s" % pid, command="xpra_signal_listener", ignore=True, forget=True, callback=watcher_terminated)
                log("using watcher pid=%i for server pid=%i", proc.pid, pid)
                self._pid_to_signalwatcher[pid] = proc
                proc.stdout_io_watch = glib.io_add_watch(proc.stdout, glib.IO_IN, self.signal_watcher_event, proc, pid, wid, priority=glib.PRIORITY_DEFAULT)
        if proc:
            self._signalwatcher_to_wids.setdefault(proc, []).append(wid)
            return proc.pid
        return 0

    def signal_watcher_event(self, fd, cb_condition, proc, pid, wid):
        log("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid))
        if cb_condition==glib.IO_HUP:
            proc.stdout_io_watch = None
            return False
        if cb_condition==glib.IO_IN:
            try:
                signame = proc.stdout.readline().strip("\n\r")
                log("signal_watcher_event: %s", signame)
                if not signame:
                    pass
                elif signame not in self.server_window_signals:
                    log("Warning: signal %s cannot be forwarded to this server", signame)
                else:
                    self.send("window-signal", wid, signame)
            except Exception as e:
                log("signal_watcher_event%s", (fd, cb_condition, proc, pid, wid), exc_info=True)
                log.error("Error: processing signal watcher output for pid %i of window %i", pid, wid)
                log.error(" %s", e)
        if proc.poll():
            #watcher ended, stop watching its stdout
            proc.stdout_io_watch = None
            return False
        return True


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
        iconlog("reinit_window_icons()")
        for window in self._id_to_window.values():
            reset_icon = getattr(window, "reset_icon", None)
            if reset_icon:
                reset_icon()

    def reinit_windows(self, new_size_fn=None):
        def fake_send(*args):
            log("fake_send%s", args)
        #now replace all the windows with new ones:
        for wid, window in self._id_to_window.items():
            if window:
                self.reinit_window(wid, window, new_size_fn)
        self.send_refresh_all()

    def reinit_window(self, wid, window, new_size_fn=None):
        geomlog("reinit_window%s", (wid, window, new_size_fn))
        def fake_send(*args):
            log("fake_send%s", args)
        if window.is_tray():
            #trays are never GL enabled, so don't bother re-creating them
            #might cause problems anyway if we did
            #just send a configure event in case they are moved / scaled
            window.send_configure()
            return
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
                    log("reinit_windows() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                    backing._video_decoder = None
                    backing._csc_decoder = None
                    backing._decoder_lock = None
                    backing.close()

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
                window.update_icon(current_icon)
        finally:
            if decoder_lock:
                decoder_lock.release()


    def get_group_leader(self, _wid, _metadata, _override_redirect):
        #subclasses that wish to implement the feature may override this method
        return None


    def get_client_window_classes(self, _w, _h, _metadata, _override_redirect):
        return [self.ClientWindowClass]


    def _process_new_window(self, packet):
        self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet):
        self._process_new_common(packet, True)


    def _process_initiate_moveresize(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            x_root, y_root, direction, button, source_indication = packet[2:7]
            window.initiate_moveresize(self.sx(x_root), self.sy(y_root), direction, button, source_indication)

    def _process_window_metadata(self, packet):
        wid, metadata = packet[1:3]
        metalog("metadata update for window %i: %s", wid, metadata)
        window = self._id_to_window.get(wid)
        if window:
            metadata = self.cook_metadata(False, metadata)
            window.update_metadata(metadata)

    def _process_window_icon(self, packet):
        wid, w, h, coding, data = packet[1:6]
        img = self._window_icon_image(wid, w, h, coding, data)
        window = self._id_to_window.get(wid)
        iconlog("_process_window_icon(%s, %s, %s, %s, %s bytes) image=%s, window=%s", wid, w, h, coding, len(data), img, window)
        if window and img:
            window.update_icon(img)
            self.set_tray_icon()

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

    def _process_raise_window(self, packet):
        #only implemented in gtk2 for now
        pass


    def _process_configure_override_redirect(self, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window[wid]
        ax = self.sx(x)
        ay = self.sy(y)
        aw = max(1, self.sx(w))
        ah = max(1, self.sy(h))
        geomlog("_process_configure_override_redirect%s move resize window %s (id=%s) to %s", packet[1:], window, wid, (ax,ay,aw,ah))
        window.move_resize(ax, ay, aw, ah, -1)


    def window_close_event(self, wid):
        log("window_close_event(%s) close window action=%s", wid, self.window_close_action)
        if self.window_close_action=="forward":
            self.send("close-window", wid)
        elif self.window_close_action=="ignore":
            log("close event for window %i ignored", wid)
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
                close = None
                if matching_title_close:
                    close = "window-close event on %s window" % title
                elif class_instance and class_instance[1] in WM_CLASS_CLOSEEXIT:
                    close = "window-close event on %s window" % class_instance[0]
                if close:
                    #honour this close request if there are no other windows:
                    if len(self._id_to_window)==1:
                        log.info("%s, disconnecting", close)
                        self.quit(0)
                        return True
                    else:
                        log("there are %i windows, so forwarding %s", len(self._id_to_window), close)
            #default to forward:
            self.send("close-window", wid)
        else:
            log.warn("unknown close-window action: %s", self.window_close_action)
        return True


    def _process_lost_window(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if window:
            del self._id_to_window[wid]
            del self._window_to_id[window]
            self.destroy_window(wid, window)
        if len(self._id_to_window)==0:
            log("last window gone, clearing key repeat")
        self.set_tray_icon()

    def destroy_window(self, wid, window):
        log("destroy_window(%s, %s)", wid, window)
        window.destroy()
        if self._window_with_grab==wid:
            log("destroying window %s which has grab, ungrabbing!", wid)
            self.window_ungrab()
            self._window_with_grab = None
        #deal with signal watchers:
        log("looking for window %i in %s", wid, self._signalwatcher_to_wids)
        for signalwatcher, wids in tuple(self._signalwatcher_to_wids.items()):
            if wid in wids:
                log("removing %i from %s for signalwatcher %s", wid, wids, signalwatcher)
                wids.remove(wid)
                if not wids:
                    log("last window, removing watcher %s", signalwatcher)
                    try:
                        del self._signalwatcher_to_wids[signalwatcher]
                        if signalwatcher.poll() is None:
                            os.kill(signalwatcher.pid, signal.SIGKILL)
                    except:
                        log("destroy_window(%i, %s) error killing signal watcher %s", wid, window, signalwatcher, exc_info=True)
                    #now remove any pids that use this watcher:
                    for pid, w in tuple(self._pid_to_signalwatcher.items()):
                        if w==signalwatcher:
                            del self._pid_to_signalwatcher[pid]

    def destroy_all_windows(self):
        for wid, window in self._id_to_window.items():
            try:
                log("destroy_all_windows() destroying %s / %s", wid, window)
                self.destroy_window(wid, window)
            except:
                pass
        self._id_to_window = {}
        self._window_to_id = {}
        #signal watchers should have been killed in destroy_window(),
        #make sure we don't leave any behind:
        for signalwatcher in tuple(self._signalwatcher_to_wids.keys()):
            try:
                if signalwatcher.poll() is None:
                    os.kill(signalwatcher.pid, signal.SIGKILL)
            except:
                log("destroy_all_windows() error killing signal watcher %s", signalwatcher, exc_info=True)


    ######################################################################
    # bell
    def _process_bell(self, packet):
        if not self.bell_enabled:
            return
        (wid, device, percent, pitch, duration, bell_class, bell_id, bell_name) = packet[1:9]
        window = self._id_to_window.get(wid)
        self.window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)


    ######################################################################
    # focus:
    def send_focus(self, wid):
        focuslog("send_focus(%s)", wid)
        self.send("focus", wid, self.get_current_modifiers())

    def update_focus(self, wid, gotit):
        focuslog("update_focus(%s, %s) focused=%s, grabbed=%s", wid, gotit, self._focused, self._window_with_grab)
        if gotit:
            if self._focused is not wid:
                self.send_focus(wid)
                self._focused = wid
            self.cancel_lost_focus_timer()
        else:
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
            if self._focused and not self.lost_focus_timer:
                #send the lost-focus via a timer and re-check it
                #(this allows a new window to gain focus without having to do a reset_focus)
                self.lost_focus_timer = self.timeout_add(20, self.send_lost_focus)
                self._focused = None

    def send_lost_focus(self):
        self.lost_focus_timer = None
        #check that a new window has not gained focus since:
        if self._focused is None:
            self.send_focus(0)

    def cancel_lost_focus_timer(self):
        lft = self.lost_focus_timer
        if lft:
            self.lost_focus_timer = None
            self.source_remove(lft)


    ######################################################################
    # grabs:
    def window_grab(self, _window):
        grablog.warn("Warning: window grab not implemented in %s", self.client_type())

    def window_ungrab(self):
        grablog.warn("Warning: window ungrab not implemented in %s", self.client_type())

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

    def _process_pointer_ungrab(self, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        grablog("ungrabbing %s: %s", wid, window)
        self.window_ungrab()
        self._window_with_grab = None


    ######################################################################
    # window refresh:
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


    ######################################################################
    # painting windows:
    def _process_draw(self, packet):
        self._draw_queue.put(packet)

    def _process_eos(self, packet):
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid, packet_sequence, width, height, decode_time, message=""):
        packet = "damage-sequence", packet_sequence, wid, width, height, decode_time, message
        drawlog("sending ack: %s", packet)
        self.send_now(*packet)

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
            except Exception as e:
                log.error("Error '%s' processing %s packet", e, packet[0], exc_info=True)
        log("draw thread ended")

    def _do_draw(self, packet):
        """ this runs from the draw thread above """
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if packet[0]==b"eos":
            if window:
                window.eos()
            return
        x, y, width, height, coding, data, packet_sequence, rowstride = packet[2:10]
        if not window:
            #window is gone
            def draw_cleanup():
                if coding==b"mmap":
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
        #rename old encoding aliases early:
        options = {}
        if len(packet)>10:
            options = packet[10]
        options = typedict(options)
        dtype = DRAW_TYPES.get(type(data), type(data))
        drawlog("process_draw: %7i %8s for window %3i, sequence %8i, %4ix%-4i at %4i,%-4i using %6s encoding with options=%s", len(data), dtype, wid, packet_sequence, width, height, x, y, bytestostr(coding), options)
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


    ######################################################################
    # screen scaling:
    def sx(self, v):
        """ convert X coordinate from server to client """
        return iround(v)
    def sy(self, v):
        """ convert Y coordinate from server to client """
        return iround(v)
    def srect(self, x, y, w, h):
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)
    def sp(self, x, y):
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    def cx(self, v):
        """ convert X coordinate from client to server """
        return iround(v)
    def cy(self, v):
        """ convert Y coordinate from client to server """
        return iround(v)
    def crect(self, x, y, w, h):
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)
    def cp(self, x, y):
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)


    def redraw_spinners(self):
        #draws spinner on top of the window, or not (plain repaint)
        #depending on whether the server is ok or not
        ok = self.server_ok()
        log("redraw_spinners() ok=%s", ok)
        for w in self._id_to_window.values():
            if not w.is_tray():
                w.spinner(ok)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._ui_packet_handlers, {
            "new-window":           self._process_new_window,
            "new-override-redirect":self._process_new_override_redirect,
            "new-tray":             self._process_new_tray,
            "raise-window":         self._process_raise_window,
            "initiate-moveresize":  self._process_initiate_moveresize,
            "window-move-resize":   self._process_window_move_resize,
            "window-resized":       self._process_window_resized,
            "window-metadata":      self._process_window_metadata,
            "configure-override-redirect":  self._process_configure_override_redirect,
            "lost-window":          self._process_lost_window,
            "window-icon":          self._process_window_icon,
            "draw":                 self._process_draw,
            "eos":                  self._process_eos,
            "cursor":               self._process_cursor,
            "bell":                 self._process_bell,
            "pointer-position":     self._process_pointer_position,
            "pointer-grab":         self._process_pointer_grab,
            "pointer-ungrab":       self._process_pointer_ungrab,
            })
