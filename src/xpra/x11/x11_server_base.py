# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util import nonl, typedict, envbool, iround

from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()
from xpra.gtk_common.error import xswallow, xsync

from xpra.log import Logger
log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
mouselog = Logger("x11", "server", "mouse")
grablog = Logger("server", "grab")
cursorlog = Logger("server", "cursor")
screenlog = Logger("server", "screen")
xinputlog = Logger("xinput")
gllog = Logger("screen", "opengl")

from xpra.util import envint
from xpra.os_util import hexstr
from xpra.x11.x11_server_core import X11ServerCore, XTestPointerDevice

MOUSE_WHEEL_CLICK_MULTIPLIER = envint("XPRA_MOUSE_WHEEL_CLICK_MULTIPLIER", 30)
SCALED_FONT_ANTIALIAS = envbool("XPRA_SCALED_FONT_ANTIALIAS", False)


class UInputDevice(object):

    def __init__(self, device, device_path):
        self.device = device
        self.device_path = device_path
        self.wheel_delta = 0
        #the first event always goes MIA:
        #http://who-t.blogspot.co.at/2012/06/xi-21-protocol-design-issues.html
        #so synthesize a dummy one now:
        try:
            with xsync:
                from xpra.x11.bindings.xi2_bindings import X11XI2Bindings
                xi2 = X11XI2Bindings()
                v = xi2.get_xi_version()
                log("XInput version %s", ".".join(str(x) for x in v))
                if v<=(2, 2):
                    self.wheel_motion(4, 1)
        except:
            log.warn("cannot query XInput protocol version", exc_info=True)

    def click(self, button, pressed, *_args):
        import uinput
        BUTTON_STR = {
            uinput.BTN_LEFT     : "BTN_LEFT",
            uinput.BTN_RIGHT    : "BTN_RIGHT",
            uinput.BTN_MIDDLE   : "BTN_MIDDLE",
            uinput.BTN_SIDE     : "BTN_SIDE",
            uinput.BTN_EXTRA    : "BTN_EXTRA",
            uinput.REL_WHEEL    : "REL_WHEEL",
            }
        #this multiplier is based on the values defined in 71-xpra-virtual-pointer.rules as:
        #MOUSE_WHEEL_CLICK_COUNT=360
        #MOUSE_WHEEL_CLICK_ANGLE=1
        mult = MOUSE_WHEEL_CLICK_MULTIPLIER
        if button==4:
            ubutton = uinput.REL_WHEEL
            val = 1*mult
            if pressed: #only send one event
                return
        elif button==5:
            ubutton = uinput.REL_WHEEL
            val = -1*mult
            if pressed: #only send one event
                return
        else:
            ubutton = {
                1   : uinput.BTN_LEFT,
                3   : uinput.BTN_RIGHT,
                2   : uinput.BTN_MIDDLE,
                8   : uinput.BTN_SIDE,
                9   : uinput.BTN_EXTRA,
                }.get(button)
            val = bool(pressed)
        if ubutton:
            mouselog("UInput.click(%i, %s) uinput button=%s (%#x), %#x, value=%s", button, pressed, BUTTON_STR.get(ubutton), ubutton[0], ubutton[1], val)
            self.device.emit(ubutton, val)
        else:
            mouselog("UInput.click(%i, %s) uinput button not found - using XTest", button, pressed)
            X11Keyboard.xtest_fake_button(button, pressed)

    def wheel_motion(self, button, distance):
        if button in (4, 5):
            val = distance*MOUSE_WHEEL_CLICK_MULTIPLIER
        else:
            log.warn("Warning: %s", self)
            log.warn(" cannot handle wheel motion %i", button)
            log.warn(" this event has been dropped")
            return
        delta = self.wheel_delta+val
        mouselog("UInput.wheel_motion(%i, %.4f) REL_WHEEL: %s+%s=%s", button, distance, self.wheel_delta, val, delta)
        ival = int(delta)
        if ival!=0:
            import uinput
            self.device.emit(uinput.REL_WHEEL, ival)
            self.wheel_delta += val-ival

    def close(self):
        pass

    def has_precise_wheel(self):
        return True

class UInputPointerDevice(UInputDevice):

    def __repr__(self):
        return "UInput pointer device %s" % self.device_path

    def move_pointer(self, screen_no, x, y, *_args):
        mouselog("UInputPointerDevice.move_pointer(%i, %s, %s)", screen_no, x, y)
        #calculate delta:
        with xsync:
            cx, cy = X11Keyboard.query_pointer()
            mouselog("X11Keyboard.query_pointer=%s, %s", cx, cy)
            dx = x-cx
            dy = y-cy
            mouselog("delta(%s, %s)=%s, %s", cx, cy, dx, dy)
        import uinput
        #self.device.emit(uinput.ABS_X, x, syn=(dy==0))
        #self.device.emit(uinput.ABS_Y, y, syn=True)
        if dx or dy:
            if dx!=0:
                self.device.emit(uinput.REL_X, dx, syn=(dy==0))
            if dy!=0:
                self.device.emit(uinput.REL_Y, dy, syn=True)

class UInputTouchpadDevice(UInputDevice):

    def __repr__(self):
        return "UInput touchpad device %s" % self.device_path

    def move_pointer(self, screen_no, x, y, *_args):
        mouselog("UInputTouchpadDevice.move_pointer(%i, %s, %s)", screen_no, x, y)
        import uinput
        #self.device.emit(uinput.BTN_TOUCH, 1, syn=False)
        self.device.emit(uinput.ABS_X, x, syn=False)
        self.device.emit(uinput.ABS_Y, y, syn=False)
        #self.device.emit(uinput.ABS_PRESSURE, 255, syn=False)
        #self.device.emit(uinput.BTN_TOUCH, 0, syn=True)


def _get_antialias_hintstyle(antialias):
    hintstyle = antialias.strget("hintstyle", "").lower()
    if hintstyle in ("hintnone", "hintslight", "hintmedium", "hintfull"):
        #X11 clients can give us what we need directly:
        return hintstyle
    #win32 style contrast value:
    contrast = antialias.intget("contrast", -1)
    if contrast>1600:
        return "hintfull"
    elif contrast>1000:
        return "hintmedium"
    elif contrast>0:
        return "hintslight"
    return "hintnone"


class X11ServerBase(X11ServerCore):
    """
        Base class for X11 servers,
        adds uinput, icc and xsettings synchronization to the X11ServerCore class
        (see XpraServer or DesktopServer for actual implementations)
    """

    def __init__(self):
        X11ServerCore.__init__(self)
        self._default_xsettings = {}
        self._settings = {}
        self._xsettings_manager = None
        self._xsettings_enabled = False

    def do_init(self, opts):
        X11ServerCore.do_init(self, opts)
        self._xsettings_enabled = opts.xsettings
        if self._xsettings_enabled:
            from xpra.x11.xsettings import XSettingsHelper
            self._default_xsettings = XSettingsHelper().get_settings()
            log("_default_xsettings=%s", self._default_xsettings)
            self.init_all_server_settings()


    def last_client_exited(self):
        self.reset_settings()
        X11ServerCore.last_client_exited(self)

    def init_virtual_devices(self, devices):
        #(this runs in the main thread - before the main loop starts)
        #for the time being, we only use the pointer if there is one:
        pointer = devices.get("pointer")
        touchpad = devices.get("touchpad")
        mouselog("init_virtual_devices(%s) got pointer=%s, touchpad=%s", devices, pointer, touchpad)
        self.input_devices = "xtest"
        if pointer:
            uinput_device = pointer.get("uinput")
            device_path = pointer.get("device")
            if uinput_device:
                self.input_devices = "uinput"
                self.pointer_device = UInputPointerDevice(uinput_device, device_path)
                self.verify_uinput_pointer_device()
        if self.input_devices=="uinput" and touchpad:
            uinput_device = touchpad.get("uinput")
            device_path = touchpad.get("device")
            if uinput_device:
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path)
        try:
            mouselog.info("pointer device emulation using %s", str(self.pointer_device).replace("PointerDevice", ""))
        except Exception as e:
            mouselog("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def verify_uinput_pointer_device(self):
        xtest = XTestPointerDevice()
        ox, oy = 100, 100
        with xsync:
            xtest.move_pointer(0, ox, oy)
        nx, ny = 200, 200
        self.pointer_device.move_pointer(0, nx, ny)
        def verify_uinput_moved():
            pos = None  #@UnusedVariable
            with xswallow:
                pos = X11Keyboard.query_pointer()
                mouselog("X11Keyboard.query_pointer=%s", pos)
            if pos==(ox, oy):
                mouselog.warn("Warning: %s failed verification", self.pointer_device)
                mouselog.warn(" expected pointer at %s, now at %s", (nx, ny), pos)
                mouselog.warn(" usign XTest fallback")
                self.pointer_device = xtest
                self.input_devices = "xtest"
        self.timeout_add(1000, verify_uinput_moved)


    def dpi_changed(self):
        #re-apply the same settings, which will apply the new dpi override to it:
        self.update_server_settings()


    def set_icc_profile(self):
        ui_clients = [s for s in self._server_sources.values() if s.ui_client]
        if len(ui_clients)!=1:
            screenlog("%i UI clients, not setting ICC profile")
            self.reset_icc_profile()
            return
        icc = ui_clients[0].icc
        data = None
        for x in ("data", "icc-data", "icc-profile"):
            if x in icc:
                data = icc.get(x)
                break
        if not data:
            screenlog("no icc data found in %s", icc)
            self.reset_icc_profile()
            return
        screenlog("set_icc_profile() icc data for %s: %s (%i bytes)", ui_clients[0], hexstr(data or ""), len(data or ""))
        from xpra.x11.gtk_x11.prop import prop_set
        #each CARD32 contains just one 8-bit value - don't ask me why
        prop_set(self.root_window, "_ICC_PROFILE", ["u32"], [ord(x) for x in data])
        prop_set(self.root_window, "_ICC_PROFILE_IN_X_VERSION", "u32", 0*100+4) #0.4 -> 0*100+4*1

    def reset_icc_profile(self):
        screenlog("reset_icc_profile()")
        from xpra.x11.gtk_x11.prop import prop_del
        prop_del(self.root_window, "_ICC_PROFILE")
        prop_del(self.root_window, "_ICC_PROFILE_IN_X_VERSION")


    def reset_settings(self):
        if not self._xsettings_enabled:
            return
        log("resetting xsettings to: %s", self._default_xsettings)
        self.set_xsettings(self._default_xsettings or (0, ()))

    def set_xsettings(self, v):
        if not self._xsettings_enabled:
            return
        log("set_xsettings(%s)", v)
        with xsync:
            if self._xsettings_manager is None:
                from xpra.x11.xsettings import XSettingsManager
                self._xsettings_manager = XSettingsManager()
            self._xsettings_manager.set_settings(v)

    def init_all_server_settings(self):
        log("init_all_server_settings() dpi=%i, default_dpi=%i", self.dpi, self.default_dpi)
        #almost like update_all, except we use the default_dpi,
        #since this is called before the first client connects
        self.do_update_server_settings({
            "resource-manager"  : "",
            "xsettings-blob"    : (0, [])
            }, reset = True, dpi = self.default_dpi, cursor_size=24)

    def update_all_server_settings(self, reset=False):
        self.update_server_settings({
            "resource-manager"  : "",
            "xsettings-blob"    : (0, []),
            }, reset=reset)

    def update_server_settings(self, settings=None, reset=False):
        self.do_update_server_settings(settings or self._settings, reset,
                                self.dpi, self.double_click_time, self.double_click_distance, self.antialias, self.cursor_size)

    def do_update_server_settings(self, settings, reset=False,
                                  dpi=0, double_click_time=0, double_click_distance=(-1, -1), antialias={}, cursor_size=-1):
        if not self._xsettings_enabled:
            log("ignoring xsettings update: %s", settings)
            return
        if reset:
            #FIXME: preserve serial? (what happens when we change values which had the same serial?)
            self.reset_settings()
            self._settings = {}
            if self._default_xsettings:
                #try to parse default xsettings into a dict:
                try:
                    for _, prop_name, value, _ in self._default_xsettings[1]:
                        self._settings[prop_name] = value
                except Exception as e:
                    log("failed to parse %s", self._default_xsettings)
                    log.warn("Warning: failed to parse default XSettings:")
                    log.warn(" %s", e)
        old_settings = dict(self._settings)
        log("server_settings: old=%s, updating with=%s", nonl(old_settings), nonl(settings))
        log("overrides: dpi=%s, double click time=%s, double click distance=%s", dpi, double_click_time, double_click_distance)
        log("overrides: antialias=%s", antialias)
        self._settings.update(settings)
        for k, v in settings.items():
            #cook the "resource-manager" value to add the DPI and/or antialias values:
            if k=="resource-manager" and (dpi>0 or antialias or cursor_size>0):
                value = v.decode("utf-8")
                #parse the resources into a dict:
                values={}
                options = value.split("\n")
                for option in options:
                    if not option:
                        continue
                    parts = option.split(":\t", 1)
                    if len(parts)!=2:
                        log("skipped invalid option: '%s'", option)
                        continue
                    values[parts[0]] = parts[1]
                if cursor_size>0:
                    values["Xcursor.size"] = cursor_size
                if dpi>0:
                    values["Xft.dpi"] = dpi
                    values["Xft/DPI"] = dpi*1024
                    values["gnome.Xft/DPI"] = dpi*1024
                if antialias:
                    ad = typedict(antialias)
                    subpixel_order = "none"
                    sss = self._server_sources.values()
                    if len(sss)==1:
                        #only honour sub-pixel hinting if a single client is connected
                        #and only when it is not using any scaling (or overriden with SCALED_FONT_ANTIALIAS):
                        ss = sss[0]
                        if SCALED_FONT_ANTIALIAS or (not ss.desktop_size_unscaled or ss.desktop_size_unscaled==ss.desktop_size):
                            subpixel_order = ad.strget("orientation", "none").lower()
                    values.update({
                                   "Xft.antialias"  : ad.intget("enabled", -1),
                                   "Xft.hinting"    : ad.intget("hinting", -1),
                                   "Xft.rgba"       : subpixel_order,
                                   "Xft.hintstyle"  : _get_antialias_hintstyle(ad)})
                log("server_settings: resource-manager values=%s", nonl(values))
                #convert the dict back into a resource string:
                value = ''
                for vk, vv in values.items():
                    value += "%s:\t%s\n" % (vk, vv)
                #record the actual value used
                self._settings["resource-manager"] = value
                v = value.encode("utf-8")

            #cook xsettings to add various settings:
            #(as those may not be present in xsettings on some platforms.. like win32 and osx)
            if k=="xsettings-blob" and (self.double_click_time>0 or self.double_click_distance!=(-1, -1) or antialias or dpi>0):
                from xpra.x11.xsettings_prop import XSettingsTypeInteger, XSettingsTypeString
                def set_xsettings_value(name, value_type, value):
                    #remove existing one, if any:
                    serial, values = v
                    new_values = [(_t,_n,_v,_s) for (_t,_n,_v,_s) in values if _n!=name]
                    new_values.append((value_type, name, value, 0))
                    return serial, new_values
                def set_xsettings_int(name, value):
                    if value<0: #not set, return v unchanged
                        return v
                    return set_xsettings_value(name, XSettingsTypeInteger, value)
                if dpi>0:
                    v = set_xsettings_int("Xft/DPI", dpi*1024)
                if double_click_time>0:
                    v = set_xsettings_int("Net/DoubleClickTime", self.double_click_time)
                if antialias:
                    ad = typedict(antialias)
                    v = set_xsettings_int("Xft/Antialias",  ad.intget("enabled", -1))
                    v = set_xsettings_int("Xft/Hinting",    ad.intget("hinting", -1))
                    v = set_xsettings_value("Xft/RGBA",     XSettingsTypeString, ad.strget("orientation", "none").lower())
                    v = set_xsettings_value("Xft/HintStyle", XSettingsTypeString, _get_antialias_hintstyle(ad))
                if double_click_distance!=(-1, -1):
                    #some platforms give us a value for each axis,
                    #but X11 only has one, so take the average
                    try:
                        x,y = double_click_distance
                        if x>0 and y>0:
                            d = iround((x+y)/2.0)
                            d = max(1, min(128, d))     #sanitize it a bit
                            v = set_xsettings_int("Net/DoubleClickDistance", d)
                    except Exception as e:
                        log.warn("error setting double click distance from %s: %s", double_click_distance, e)

            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    from xpra.x11.gtk_x11.prop import prop_set
                    log("server_settings: setting %s to %s", nonl(p), nonl(v))
                    prop_set(self.root_window, p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self.set_xsettings(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
