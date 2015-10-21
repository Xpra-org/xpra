# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk

#ensure that we use gtk as display source:
from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source

from xpra.x11.bindings.randr_bindings import RandRBindings  #@UnresolvedImport
RandR = RandRBindings()
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()
from xpra.x11.bindings.core_bindings import X11CoreBindings #@UnresolvedImport
X11Core = X11CoreBindings()
from xpra.gtk_common.error import XError, xswallow, xsync
from xpra.server.server_uuid import save_uuid, get_uuid
from xpra.x11.fakeXinerama import find_libfakeXinerama, save_fakeXinerama_config, cleanup_fakeXinerama

from xpra.log import Logger
log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
mouselog = Logger("x11", "server", "mouse")
grablog = Logger("server", "grab")
cursorlog = Logger("server", "cursor")
screenlog = Logger("server", "screen")

from xpra.server.gtk_server_base import GTKServerBase
from xpra.x11.xkbhelper import clean_keyboard_state
from xpra.x11.server_keyboard_config import KeyboardConfig

MAX_CONCURRENT_CONNECTIONS = 20


def window_name(window):
    from xpra.x11.gtk_x11.prop import prop_get
    return prop_get(window, "_NET_WM_NAME", "utf8", True) or "unknown"

def window_info(window):
    from xpra.x11.gtk_x11.prop import prop_get
    net_wm_name = prop_get(window, "_NET_WM_NAME", "utf8", True)
    return "%s %s (%s / %s)" % (net_wm_name, window, window.get_geometry(), window.is_visible())


from xpra.x11.gtk2.gdk_bindings import get_children #@UnresolvedImport
def dump_windows():
    root = gtk.gdk.get_default_root_window()
    log("root window: %s" % root)
    children = get_children(root)
    log("%s windows" % len(children))
    for window in get_children(root):
        log("found window: %s", window_info(window))


class X11ServerBase(GTKServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to GTKServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def __init__(self, clobber):
        self.clobber = clobber
        self.screen_number = gtk.gdk.display_get_default().get_default_screen().get_number()
        self.root_window = gtk.gdk.get_default_root_window()
        GTKServerBase.__init__(self)

    def init(self, opts):
        self.fake_xinerama = opts.fake_xinerama
        self.current_xinerama_config = None
        self.x11_init()
        GTKServerBase.init(self, opts)

    def x11_init(self):
        if not X11Keyboard.hasXFixes():
            log.error("Error: cursor forwarding support disabled") 
        if not X11Keyboard.hasXTest():
            log.error("Error: keyboard and mouse disabled")
        elif not X11Keyboard.hasXkb():
            log.error("Error: limited keyboard support")
        self.init_x11_atoms()
        self.randr = RandR.has_randr()
        if self.randr and len(RandR.get_screen_sizes())<=1:
            log.info("no RandR support")
            #disable randr when we are dealing with a Xvfb
            #with only one resolution available
            #since we don't support adding them on the fly yet
            self.randr = False
        if self.randr:
            display = gtk.gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        log("randr enabled: %s", self.randr)

    def init_x11_atoms(self):
        #some applications (like openoffice), do not work properly
        #if some x11 atoms aren't defined, so we define them in advance:
        for wtype in ["",
                      "_NORMAL",
                      "_DESKTOP",
                      "_DOCK",
                      "_TOOLBAR",
                      "_MENU",
                      "_UTILITY",
                      "_SPLASH",
                      "_DIALOG",
                      "_DROPDOWN_MENU",
                      "_POPUP_MENU",
                      "_TOOLTIP",
                      "_NOTIFICATION",
                      "_COMBO",
                      "_DND",
                      "_NORMAL"
                      ]:
            X11Core.get_xatom("_NET_WM_WINDOW_TYPE"+wtype)

    def init_keyboard(self):
        GTKServerBase.init_keyboard(self)
        #clear all modifiers
        clean_keyboard_state()


    def init_packet_handlers(self):
        GTKServerBase.init_packet_handlers(self)
        self._authenticated_ui_packet_handlers["force-ungrab"] = self._process_force_ungrab


    def get_server_source_class(self):
        from xpra.x11.x11_source import X11ServerSource
        return X11ServerSource


    def get_child_env(self):
        #adds fakeXinerama:
        env = GTKServerBase.get_child_env(self)
        if self.fake_xinerama:
            libfakeXinerama_so = find_libfakeXinerama()
            if libfakeXinerama_so:
                env["LD_PRELOAD"] = libfakeXinerama_so
        return env


    def get_uuid(self):
        return get_uuid()

    def save_uuid(self):
        save_uuid(self.uuid)

    def set_keyboard_repeat(self, key_repeat):
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                X11Keyboard.set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                log.info("setting key repeat rate from client: %sms delay / %sms interval", self.key_repeat_delay, self.key_repeat_interval)
        else:
            #dont do any jitter compensation:
            self.key_repeat_delay = -1
            self.key_repeat_interval = -1
            #but do set a default repeat rate:
            X11Keyboard.set_key_repeat_rate(500, 30)
            keylog("keyboard repeat disabled")

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["server_type"] = "Python/gtk/x11"
        if source.wants_features:
            capabilities["resize_screen"] = self.randr
            capabilities["force_ungrab"] = True
        return capabilities

    def do_get_info(self, proto, server_sources, window_ids):
        info = GTKServerBase.do_get_info(self, proto, server_sources, window_ids)
        info["server.type"] = "Python/gtk/x11"
        try:
            from xpra.x11.gtk2.composite import CompositeHelper
            info["server.XShm"] = CompositeHelper.XShmEnabled
        except:
            pass
        #randr:
        try:
            sizes = RandR.get_screen_sizes()
            if self.randr and len(sizes)>=0:
                info["server.randr.options"] = list(reversed(sorted(sizes)))
        except:
            pass
        try:
            fx = find_libfakeXinerama()
        except:
            fx = None
        info["server.fakeXinerama"] = self.fake_xinerama and bool(fx)
        info["server.libfakeXinerama"] = fx or ""
        #this is added here because the server keyboard config doesn't know about "keys_pressed"..
        info["keyboard.state.keys_pressed"] = list(self.keys_pressed.keys())
        return info

    def get_window_info(self, window):
        info = GTKServerBase.get_window_info(self, window)
        info["XShm"] = window.uses_XShm()
        return info


    def get_keyboard_config(self, props):
        keyboard_config = KeyboardConfig()
        keyboard_config.enabled = props.boolget("keyboard", True)
        keyboard_config.parse_options(props)
        keyboard_config.xkbmap_layout = props.strget("xkbmap_layout")
        keyboard_config.xkbmap_variant = props.strget("xkbmap_variant")
        keylog("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config


    def set_keymap(self, server_source, force=False):
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True

            self.keyboard_config = server_source.set_keymap(self.keyboard_config, self.keys_pressed, force)
        finally:
            # re-enable via idle_add to give all the pending
            # events a chance to run first (and get ignored)
            def reenable_keymap_changes(*args):
                keylog("reenable_keymap_changes(%s)", args)
                self.keymap_changing = False
                self._keys_changed()
            self.idle_add(reenable_keymap_changes)


    def _clear_keys_pressed(self):
        keylog("_clear_keys_pressed()")
        #make sure the timer doesn't fire and interfere:
        self.cancel_key_repeat_timer()
        #clear all the keys we know about:
        if len(self.keys_pressed)>0:
            log("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                X11Keyboard.xtest_fake_key(keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        X11Keyboard.unpress_all_keys()


    def get_cursor_data(self):
        #must be called from the UI thread!
        try:
            with xsync:
                cursor_data = X11Keyboard.get_cursor_image()
        except Exception as e:
            cursorlog.error("Error getting cursor data:")
            cursorlog.error(" %s", e)
            return None, []
        if cursor_data is None:
            cursorlog("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_cursor_data = cursor_data
        pixels = self.last_cursor_data[7]
        cursorlog("get_cursor_data() cursor=%s", cursor_data[:7]+["%s bytes" % len(pixels)]+cursor_data[8:])
        if self.default_cursor_data is not None and str(pixels)==str(self.default_cursor_data[7]):
            cursorlog("get_cursor_data(): default cursor - clearing it")
            cursor_data = None
        display = gtk.gdk.display_get_default()
        cursor_sizes = display.get_default_cursor_size(), display.get_maximal_cursor_size()
        return (cursor_data, cursor_sizes)


    def get_max_screen_size(self):
        from xpra.x11.gtk2.window import MAX_WINDOW_SIZE
        max_w, max_h = self.root_window.get_size()
        sizes = RandR.get_screen_sizes()
        if self.randr and len(sizes)>=1:
            for w,h in sizes:
                max_w = max(max_w, w)
                max_h = max(max_h, h)
        if max_w>MAX_WINDOW_SIZE or max_h>MAX_WINDOW_SIZE:
            screenlog.warn("maximum size is very large: %sx%s, you may encounter window sizing problems", max_w, max_h)
        screenlog("get_max_screen_size()=%s", (max_w, max_h))
        return max_w, max_h


    def set_best_screen_size(self):
        #return ServerBase.set_best_screen_size(self)
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = self.root_window.get_size()
        if not self.randr:
            return root_w, root_h
        max_w, max_h = 0, 0
        sss = self._server_sources.values()
        for ss in sss:
            client_size = ss.desktop_size
            if not client_size:
                continue
            if ss.screen_sizes and len(sss)>1:
                log.info("* %s:", ss.uuid)
            w, h = client_size
            max_w = max(max_w, w)
            max_h = max(max_h, h)
        log("maximum client resolution is %sx%s (current server resolution is %sx%s)", max_w, max_h, root_w, root_h)
        if max_w>0 and max_h>0:
            return self.set_screen_size(max_w, max_h)
        return  root_w, root_h

    def set_screen_size(self, desired_w, desired_h):
        root_w, root_h = self.root_window.get_size()
        if desired_w==root_w and desired_h==root_h and not self.fake_xinerama:
            return    root_w,root_h    #unlikely: perfect match already!
        #clients may supply "xdpi" and "ydpi" (v0.15 onwards), or just "dpi", or nothing...
        xdpi = self.xdpi or self.dpi
        ydpi = self.ydpi or self.dpi
        log("set_screen_size(%s, %s) xdpi=%s, ydpi=%s", desired_w, desired_h, xdpi, ydpi)
        if xdpi<=0 or ydpi<=0:
            #use some sane defaults: either the command line option, or fallback to 96
            #(96 is better than nothing, because we do want to set the dpi
            # to avoid Xdummy setting a crazy dpi from the virtual screen dimensions)
            xdpi = self.default_dpi or 96
            ydpi = self.default_dpi or 96
            #find the "physical" screen dimensions, so we can calculate the required dpi
            #(and do this before changing the resolution)
            wmm, hmm = 0, 0
            client_w, client_h = 0, 0
            sss = self._server_sources.values()
            for ss in sss:
                for s in ss.screen_sizes:
                    if len(s)>=10:
                        #display_name, width, height, width_mm, height_mm, monitors, work_x, work_y, work_width, work_height
                        client_w = max(client_w, s[1])
                        client_h = max(client_h, s[2])
                        wmm = max(wmm, s[3])
                        hmm = max(hmm, s[4])
            if wmm>0 and hmm>0 and client_w>0 and client_h>0:
                #calculate "real" dpi:
                xdpi = int(client_w * 25.4 / wmm + 0.5)
                ydpi = int(client_h * 25.4 / hmm + 0.5)
                log("calculated DPI: %s x %s (from w: %s / %s, h: %s / %s)", xdpi, ydpi, client_w, wmm, client_h, hmm)
        self.set_dpi(xdpi, ydpi)

        #try to find the best screen size to resize to:
        new_size = None
        closest = {}
        for w,h in RandR.get_screen_sizes():
            if w<desired_w or h<desired_h:
                distance = abs(w-desired_w)*abs(h-desired_h)
                closest[distance] = (w, h)
                continue            #size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue        #we found a better (smaller) candidate already
            new_size = w,h
        if not new_size:
            log.warn("Warning: no matching resolution found for %sx%s", desired_w, desired_h)
            if len(closest)>0:
                new_size = sorted(closest.items())[0]
                log.warn(" using %sx%s instead", *new_size)
            else:
                return  root_w, root_h
        log("best resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        #now actually apply the new settings:
        w, h = new_size
        #fakeXinerama:
        ui_clients = [s for s in self._server_sources.values() if s.ui_client]
        source = None
        screen_sizes = []
        if len(ui_clients)==1:
            source = ui_clients[0]
            screen_sizes = source.screen_sizes
        else:
            log("fakeXinerama can only be enabled for a single client (found %s)" % len(ui_clients))
        xinerama_changed = save_fakeXinerama_config(self.fake_xinerama and len(ui_clients)==1, source, screen_sizes)
        #we can only keep things unchanged if xinerama was also unchanged
        #(many apps will only query xinerama again if they get a randr notification)
        if (w==root_w and h==root_h) and not xinerama_changed:
            log.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return  root_w, root_h
        try:
            if (w==root_w and h==root_h) and xinerama_changed:
                #xinerama was changed, but the RandR resolution will not be...
                #and we need a RandR change to force applications to re-query it
                #so we temporarily switch to another resolution to force
                #the change! (ugly! but this works)
                temp = {}
                for tw,th in RandR.get_screen_sizes():
                    if tw!=w or th!=h:
                        #use the number of extra pixels as key:
                        #(so we can choose the closest resolution)
                        temp[abs((tw*th) - (w*h))] = (tw, th)
                if len(temp)==0:
                    log.warn("cannot find a temporary resolution for Xinerama workaround!")
                else:
                    k = sorted(temp.keys())[0]
                    tw, th = temp[k]
                    log.info("temporarily switching to %sx%s as a Xinerama workaround", tw, th)
                    RandR.set_screen_size(tw, th)
            log("calling RandR.set_screen_size(%s, %s)", w, h)
            with xsync:
                RandR.set_screen_size(w, h)
            log("calling RandR.get_screen_size()")
            root_w, root_h = RandR.get_screen_size()
            log("RandR.get_screen_size()=%s,%s", root_w, root_h)
            log("RandR.get_vrefresh()=%s", RandR.get_vrefresh())
            if root_w!=w or root_h!=h:
                log.error("odd, failed to set the new resolution, "
                          "tried to set it to %sx%s and ended up with %sx%s", w, h, root_w, root_h)
            else:
                msg = "server virtual display now set to %sx%s" % (root_w, root_h)
                if desired_w!=root_w or desired_h!=root_h:
                    msg += " (best match for %sx%s)" % (desired_w, desired_h)
                log.info(msg)
            def show_dpi():
                wmm, hmm = RandR.get_screen_size_mm()      #ie: (1280, 1024)
                actual_xdpi = int(root_w * 25.4 / wmm + 0.5)
                actual_ydpi = int(root_h * 25.4 / hmm + 0.5)
                if actual_xdpi==xdpi and actual_ydpi==ydpi:
                    log.info("DPI set to %s x %s", xdpi, ydpi)
                else:
                    #should this be a warning:
                    l = log.info
                    maxdelta = max(abs(actual_xdpi-xdpi), abs(actual_ydpi-ydpi))
                    if maxdelta>=10:
                        l = log.warn
                    l("DPI set to %s x %s (wanted %s x %s)", actual_xdpi, actual_ydpi, xdpi, ydpi)
                    if maxdelta>=10:
                        l(" you may experience scaling problems, such as huge or small fonts, etc")
                        l(" to fix this issue, try the dpi switch, or use a patched Xorg dummy driver")
            #show dpi via idle_add so server has time to change the screen size (mm)
            self.idle_add(show_dpi)
        except Exception as e:
            log.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        return  root_w, root_h


    def do_cleanup(self, *args):
        GTKServerBase.do_cleanup(self)
        cleanup_fakeXinerama()


    def _process_server_settings(self, proto, packet):
        settings = packet[1]
        log.info("process_server_settings: %s", settings)
        self.update_server_settings(settings)

    def update_server_settings(self, settings, reset=False):
        #implemented in the X11 xpra server only for now
        #(does not make sense to update a shadow server)
        log("ignoring server settings update in %s", self)


    def _process_force_ungrab(self, proto, packet):
        #ignore the window id: wid = packet[1]
        grablog("force ungrab from %s", proto)
        self.X11_ungrab()

    def X11_ungrab(self):
        grablog("X11_ungrab")
        with xsync:
            X11Core.UngrabKeyboard()
            X11Core.UngrabPointer()


    def fake_key(self, keycode, press):
        keylog("fake_key(%s, %s)", keycode, press)
        with xsync:
            X11Keyboard.xtest_fake_key(keycode, press)


    def _move_pointer(self, wid, pos):
        #(this is called within an xswallow context)
        mouselog("move_pointer(%s, %s)", wid, pos)
        x, y = pos
        X11Keyboard.xtest_fake_motion(self.screen_number, x, y)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        pos = self.root_window.get_pointer()[:2]
        if pos!=pointer:
            with xswallow:
                self._move_pointer(wid, pointer)
        ss = self._server_sources.get(proto)
        if ss:
            ss.make_keymask_match(modifiers)
            if wid==self.get_focus():
                ss.user_event()

    def _process_button_action(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        wid, button, pressed, pointer, modifiers = packet[1:6]
        self._process_mouse_common(proto, wid, pointer, modifiers)
        ss.user_event()
        mouselog("xtest_fake_button(%s, %s) at %s", button, pressed, pointer)
        try:
            with xsync:
                X11Keyboard.xtest_fake_button(button, pressed)
        except XError:
            err = "Failed to pass on (un)press of mouse button %s" % button
            if button>=4:
                err += " (perhaps your Xvfb does not support mousewheels?)"
            log.warn(err)
