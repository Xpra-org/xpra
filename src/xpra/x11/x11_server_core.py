# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

try:
    from gtk import gdk
except Exception as e:
    from xpra.scripts.main import InitException
    raise InitException(e)

#ensure that we use gtk as display source:
from xpra.gtk_common.gobject_compat import want_gtk3
want_gtk3(False)
from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source

from xpra.x11.bindings.randr_bindings import RandRBindings  #@UnresolvedImport
RandR = RandRBindings()
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()
from xpra.x11.bindings.core_bindings import X11CoreBindings     #@UnresolvedImport
X11Core = X11CoreBindings()
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()
from xpra.gtk_common.error import XError, xswallow, xsync, trap
from xpra.gtk_common.gtk_util import get_xwindow
from xpra.server.server_uuid import save_uuid, get_uuid
from xpra.x11.fakeXinerama import find_libfakeXinerama, save_fakeXinerama_config, cleanup_fakeXinerama
from xpra.os_util import StringIOClass, monotonic_time
from xpra.net.compression import Compressed


from xpra.log import Logger
log = Logger("x11", "server")
keylog = Logger("x11", "server", "keyboard")
mouselog = Logger("x11", "server", "mouse")
grablog = Logger("server", "grab")
cursorlog = Logger("server", "cursor")
screenlog = Logger("server", "screen")
xinputlog = Logger("xinput")
gllog = Logger("screen", "opengl")

from xpra.util import iround, envbool
from xpra.server.gtk_server_base import GTKServerBase
from xpra.x11.xkbhelper import clean_keyboard_state
from xpra.x11.server_keyboard_config import KeyboardConfig

ALWAYS_NOTIFY_MOTION = envbool("XPRA_ALWAYS_NOTIFY_MOTION", False)


class XTestPointerDevice(object):

    def __repr__(self):
        return "XTestPointerDevice"

    def move_pointer(self, screen_no, x, y, *_args):
        mouselog("xtest_fake_motion(%i, %s, %s)", screen_no, x, y)
        X11Keyboard.xtest_fake_motion(screen_no, x, y)

    def click(self, button, pressed, *_args):
        mouselog("xtest_fake_button(%i, %s)", button, pressed)
        X11Keyboard.xtest_fake_button(button, pressed)

    def close(self):
        pass

    def has_precise_wheel(self):
        return False


class X11ServerCore(GTKServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to GTKServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def __init__(self):
        self.screen_number = gdk.display_get_default().get_default_screen().get_number()
        self.root_window = gdk.get_default_root_window()
        self.pointer_device = XTestPointerDevice()
        self.last_mouse_user = None
        GTKServerBase.__init__(self)

    def init(self, opts):
        self.do_init(opts)
        GTKServerBase.init(self, opts)

    def do_init(self, opts):
        self.randr = opts.resize_display
        self.randr_initial_sizes = []
        self.randr_added_sizes = []
        self.fake_xinerama = opts.fake_xinerama
        self.current_xinerama_config = None
        self.x11_init()

    def x11_init(self):
        if self.fake_xinerama:
            self.libfakeXinerama_so = find_libfakeXinerama()
        else:
            self.libfakeXinerama_so = None
        if not X11Keyboard.hasXFixes() and self.cursors:
            log.error("Error: cursor forwarding support disabled")
        if not X11Keyboard.hasXTest():
            log.error("Error: keyboard and mouse disabled")
        elif not X11Keyboard.hasXkb():
            log.error("Error: limited keyboard support")
        self.init_x11_atoms()
        if self.randr:
            self.init_randr()
        self.init_cursor()
        self.query_opengl()

    def init_randr(self):
        self.randr = RandR.has_randr()
        log("randr=%s", self.randr)
        self.randr_initial_sizes = RandR.get_screen_sizes()
        log("initial screen sizes=%s", self.randr_initial_sizes)
        if self.randr:
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
            log("randr enabled: %s", self.randr)
        else:
            log.warn("Warning: no X11 RandR support on %s", os.environ.get("DISPLAY"))

    def init_cursor(self):
        #cursor:
        self.default_cursor_data = None
        self.last_cursor_serial = None
        self.last_cursor_data = None
        self.send_cursor_pending = False
        def get_default_cursor():
            self.default_cursor_data = X11Keyboard.get_cursor_image()
            cursorlog("get_default_cursor=%s", self.default_cursor_data)
        trap.swallow_synced(get_default_cursor)
        X11Keyboard.selectCursorChange(True)

    def get_display_bit_depth(self):
        with xswallow:
            return X11Window.get_depth(X11Window.getDefaultRootWindow())
        return 0

    def query_opengl(self):
        self.opengl_props = {}
        try:
            import subprocess
            from xpra.platform.paths import get_xpra_command
            cmd = self.get_full_child_command(get_xpra_command()+["opengl"])
            env = self.get_child_env()
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, shell=False, close_fds=True)
            out,err = proc.communicate()
            gllog("out(xpra opengl)=%s", out)
            gllog("err(xpra opengl)=%s", err)
            if proc.returncode==0:
                #parse output:
                for line in out.splitlines():
                    parts = line.split("=")
                    if len(parts)!=2:
                        continue
                    k = parts[0].strip()
                    v = parts[1].strip()
                    self.opengl_props[k] = v
            else:
                self.opengl_props["error"] = str(err).strip("\n\r")
        except Exception as e:
            gllog.warn("Warning: failed to query OpenGL properties")
            gllog.warn(" %s", e)
            self.opengl_props["error"] = str(e)
        gllog("OpenGL: %s", self.opengl_props)

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
        self.current_keyboard_group = None
        #clear all modifiers
        clean_keyboard_state()

    def set_keyboard_layout_group(self, grp):
        if self.current_keyboard_group!=grp and X11Keyboard.hasXkb():
            try:
                with xsync:
                    self.current_keyboard_group = X11Keyboard.set_layout_group(grp)
            except Exception as e:
                keylog("set_keyboard_layout_group(%s)", grp, exc_info=True)
                keylog.error("Error: failed to set keyboard layout group '%s'", grp)
                keylog.error(" %s", e)

    def init_packet_handlers(self):
        GTKServerBase.init_packet_handlers(self)
        self._authenticated_ui_packet_handlers["force-ungrab"] = self._process_force_ungrab
        self._authenticated_ui_packet_handlers["wheel-motion"] = self._process_wheel_motion


    def init_virtual_devices(self, _devices):
        self.input_devices = "xtest"


    def get_server_source_class(self):
        from xpra.x11.x11_source import X11ServerSource
        return X11ServerSource


    def get_child_env(self):
        #adds fakeXinerama:
        env = GTKServerBase.get_child_env(self)
        if self.fake_xinerama and self.libfakeXinerama_so:
            env["LD_PRELOAD"] = self.libfakeXinerama_so
        return env

    def do_cleanup(self):
        GTKServerBase.do_cleanup(self)
        if self.fake_xinerama:
            cleanup_fakeXinerama()


    def get_uuid(self):
        return get_uuid()

    def save_uuid(self):
        save_uuid(unicode(self.uuid))

    def set_keyboard_repeat(self, key_repeat):
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                X11Keyboard.set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                keylog.info("setting key repeat rate from client: %sms delay / %sms interval", self.key_repeat_delay, self.key_repeat_interval)
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
            capabilities.update({
                    "resize_screen"             : self.randr,
                    "force_ungrab"              : True,
                    "keyboard.fast-switching"   : True,
                    "wheel.precise"             : self.pointer_device.has_precise_wheel(),
                    })
            if self.randr and len(RandR.get_screen_sizes())>1:
                capabilities["screen-sizes"] = RandR.get_screen_sizes()
            if self.default_cursor_data and source.wants_default_cursor:
                capabilities["cursor.default"] = self.default_cursor_data
        return capabilities

    def do_get_info(self, proto, server_sources, window_ids):
        start = monotonic_time()
        info = GTKServerBase.do_get_info(self, proto, server_sources, window_ids)
        if self.opengl_props:
            info["opengl"] = self.opengl_props
        sinfo = info.setdefault("server", {})
        sinfo.update({
            "type"                  : "Python/gtk/x11",
            "fakeXinerama"          : self.fake_xinerama and bool(self.libfakeXinerama_so),
            "libfakeXinerama"       : self.libfakeXinerama_so or "",
            })
        log("X11ServerBase.do_get_info took %ims", (monotonic_time()-start)*1000)
        return info

    def get_ui_info(self, proto, wids=None, *args):
        import threading
        log("do_get_info thread=%s", threading.current_thread())
        info = GTKServerBase.get_ui_info(self, proto, wids, *args)
        #this is added here because the server keyboard config doesn't know about "keys_pressed"..
        with xsync:
            info.setdefault("keyboard", {}).update({
                                                    "state"             : {
                                                                           "keys_pressed"   : list(self.keys_pressed.keys())
                                                                           },
                                                    "fast-switching"    : True,
                                                    "layout-group"      : X11Keyboard.get_layout_group(),
                                                    })
        sinfo = info.setdefault("server", {})
        try:
            from xpra.x11.gtk2.composite import CompositeHelper
            sinfo["XShm"] = CompositeHelper.XShmEnabled
        except:
            pass
        #cursor:
        log("do_get_info: adding cursor=%s", self.last_cursor_data)
        info.setdefault("cursor", {}).update(self.get_cursor_info())
        with xswallow:
            sinfo.update({
                "Xkb"                   : X11Keyboard.hasXkb(),
                "XTest"                 : X11Keyboard.hasXTest(),
                })
        #randr:
        try:
            with xsync:
                sizes = RandR.get_screen_sizes()
                if self.randr and len(sizes)>=0:
                    sinfo["randr"] = {
                        ""          : True,
                        "options"   : list(reversed(sorted(sizes))),
                        "initial"   : self.randr_initial_sizes,
                        "added"     : self.randr_added_sizes,
                        }
        except:
            pass
        return info


    def get_cursor_info(self):
        #(NOT from UI thread)
        #copy to prevent race:
        cd = self.last_cursor_data
        if cd is None:
            return {"" : "None"}
        cinfo = {"is_default"   : bool(self.default_cursor_data and len(self.default_cursor_data)>=8 and len(cd)>=8 and cd[7]==cd[7])}
        #all but pixels:
        for i, x in enumerate(("x", "y", "width", "height", "xhot", "yhot", "serial", None, "name")):
            if x:
                v = cd[i] or ""
                cinfo[x] = v
        return cinfo

    def get_window_info(self, window):
        info = GTKServerBase.get_window_info(self, window)
        info["XShm"] = window.uses_XShm()
        info["geometry"] = window.get_geometry()
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
        if self.readonly:
            return
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True

            #if sharing, don't set the keymap, translate the existing one:
            other_ui_clients = [s.uuid for s in self._server_sources.values() if s!=server_source and s.ui_client]
            translate_only = len(other_ui_clients)>0
            self.keyboard_config = server_source.set_keymap(self.keyboard_config, self.keys_pressed, force, translate_only)
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
            keylog("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                X11Keyboard.xtest_fake_key(keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        X11Keyboard.unpress_all_keys()


    def get_cursor_sizes(self):
        display = gdk.display_get_default()
        return display.get_default_cursor_size(), display.get_maximal_cursor_size()

    def do_get_cursor_data(self):
        #must be called from the UI thread!
        try:
            with xsync:
                return X11Keyboard.get_cursor_image()
        except Exception as e:
            cursorlog.error("Error getting cursor data:")
            cursorlog.error(" %s", e)
            return None

    def get_cursor_data(self):
        #must be called from the UI thread!
        cursor_data = self.do_get_cursor_data()
        if cursor_data is None:
            cursorlog("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_cursor_data = cursor_data
        pixels = self.last_cursor_data[7]
        cursorlog("get_cursor_data() cursor=%s", cursor_data[:7]+["%s bytes" % len(pixels)]+cursor_data[8:])
        if self.default_cursor_data is not None and str(pixels)==str(self.default_cursor_data[7]):
            cursorlog("get_cursor_data(): default cursor - clearing it")
            cursor_data = None
        cursor_sizes = self.get_cursor_sizes()
        return (cursor_data, cursor_sizes)


    def get_max_screen_size(self):
        from xpra.x11.gtk2.models import MAX_WINDOW_SIZE
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


    def configure_best_screen_size(self):
        #return ServerBase.set_best_screen_size(self)
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = self.root_window.get_size()
        if not self.randr:
            return root_w, root_h
        max_w, max_h = 0, 0
        sss = self._server_sources.values()
        if len(sss)>1:
            screenlog.info("screen used by %i clients:", len(sss))
        for ss in sss:
            client_size = ss.desktop_size
            if not client_size:
                size = "unknown"
            else:
                w, h = client_size
                size = "%ix%i" % (w, h)
                max_w = max(max_w, w)
                max_h = max(max_h, h)
            if len(sss)>1:
                screenlog.info("* %s: %s", ss.uuid, size)
        screenlog("maximum client resolution is %sx%s (current server resolution is %sx%s)", max_w, max_h, root_w, root_h)
        if max_w<=0 or max_h<=0:
            #invalid - use fallback
            return  root_w, root_h
        return self.set_screen_size(max_w, max_h)

    def get_best_screen_size(self, desired_w, desired_h, bigger=True):
        return self.do_get_best_screen_size(desired_w, desired_h, bigger)

    def do_get_best_screen_size(self, desired_w, desired_h, bigger=True):
        #ugly hackish way of detecting Xvfb with randr,
        #assume that it has only one resolution pre-defined:
        if len(self.randr_initial_sizes)==1:
            try:
                with xsync:
                    v = RandR.add_screen_size(desired_w, desired_h)
                    if v:
                        self.randr_added_sizes.append(v)
                        #we have to wait a little bit
                        #to make sure that everything sees the new resolution
                        #(ideally this method would be split in two and this would be a callback)
                        import time
                        time.sleep(0.5)
                        return v
            except Exception as e:
                screenlog.warn("Warning: failed to add resolution %ix%i:", desired_w, desired_h)
                screenlog.warn(" %s", e)
        #try to find the best screen size to resize to:
        new_size = None
        closest = {}
        for w,h in RandR.get_screen_sizes():
            if (w<desired_w)==bigger or (h<desired_h)==bigger:
                distance = abs(w-desired_w)*abs(h-desired_h)
                closest[distance] = (w, h)
                continue            #size is too small/big for client
            if new_size:
                ew,eh = new_size
                if (ew*eh<w*h)==bigger:
                    continue        #we found a better (smaller/bigger) candidate already
            new_size = w,h
        if not new_size:
            screenlog.warn("Warning: no matching resolution found for %sx%s", desired_w, desired_h)
            if len(closest)>0:
                new_size = sorted(closest.items())[0]
                screenlog.warn(" using %sx%s instead", *new_size)
            else:
                root_w, root_h = self.root_window.get_size()
                return  root_w, root_h
        screenlog("best %s resolution for client(%sx%s) is: %s", ["smaller", "bigger"][bigger], desired_w, desired_h, new_size)
        w, h = new_size
        return w, h

    def set_screen_size(self, desired_w, desired_h):
        screenlog("set_screen_size%s", (desired_w, desired_h))
        root_w, root_h = self.root_window.get_size()
        if not self.randr:
            return root_w,root_h
        if desired_w==root_w and desired_h==root_h and not self.fake_xinerama:
            return root_w,root_h    #unlikely: perfect match already!
        #clients may supply "xdpi" and "ydpi" (v0.15 onwards), or just "dpi", or nothing...
        xdpi = self.xdpi or self.dpi
        ydpi = self.ydpi or self.dpi
        screenlog("set_screen_size(%s, %s) xdpi=%s, ydpi=%s", desired_w, desired_h, xdpi, ydpi)
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
                xdpi = iround(client_w * 25.4 / wmm)
                ydpi = iround(client_h * 25.4 / hmm)
                screenlog("calculated DPI: %s x %s (from w: %s / %s, h: %s / %s)", xdpi, ydpi, client_w, wmm, client_h, hmm)
        self.set_dpi(xdpi, ydpi)

        #try to find the best screen size to resize to:
        w, h = self.get_best_screen_size(desired_w, desired_h)

        #fakeXinerama:
        ui_clients = [s for s in self._server_sources.values() if s.ui_client]
        source = None
        screen_sizes = []
        if len(ui_clients)==1:
            source = ui_clients[0]
            screen_sizes = source.screen_sizes
        else:
            screenlog("fakeXinerama can only be enabled for a single client (found %s)" % len(ui_clients))
        xinerama_changed = save_fakeXinerama_config(self.fake_xinerama and len(ui_clients)==1, source, screen_sizes)
        #we can only keep things unchanged if xinerama was also unchanged
        #(many apps will only query xinerama again if they get a randr notification)
        if (w==root_w and h==root_h) and not xinerama_changed:
            screenlog.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
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
                    screenlog.warn("cannot find a temporary resolution for Xinerama workaround!")
                else:
                    k = sorted(temp.keys())[0]
                    tw, th = temp[k]
                    screenlog.info("temporarily switching to %sx%s as a Xinerama workaround", tw, th)
                    RandR.set_screen_size(tw, th)
            screenlog("randr_added_sizes=%s", self.randr_added_sizes)
            with xsync:
                RandR.get_screen_size()
            #Xdummy with randr 1.2:
            screenlog("using XRRSetScreenConfigAndRate with %ix%i", w, h)
            with xsync:
                RandR.set_screen_size(w, h)
            if (w, h) in self.randr_added_sizes:
                #Xvfb with randr > 1.2: the resolution has been added
                #we can use XRRSetScreenSize:
                try:
                    with xsync:
                        RandR.xrr_set_screen_size(w, h, self.xdpi or self.dpi, self.ydpi or self.dpi)
                except Exception:
                    screenlog("XRRSetScreenSize failed", exc_info=True)
            screenlog("calling RandR.get_screen_size()")
            root_w, root_h = RandR.get_screen_size()
            screenlog("RandR.get_screen_size()=%s,%s", root_w, root_h)
            screenlog("RandR.get_vrefresh()=%s", RandR.get_vrefresh())
            if root_w!=w or root_h!=h:
                screenlog.warn("Warning: tried to set resolution to %ix%i", w, h)
                screenlog.warn(" and ended up with %ix%i", root_w, root_h)
            else:
                msg = "server virtual display now set to %sx%s" % (root_w, root_h)
                if desired_w!=root_w or desired_h!=root_h:
                    msg += " (best match for %sx%s)" % (desired_w, desired_h)
                screenlog.info(msg)
            def show_dpi():
                wmm, hmm = RandR.get_screen_size_mm()      #ie: (1280, 1024)
                screenlog("RandR.get_screen_size_mm=%s,%s", wmm, hmm)
                actual_xdpi = iround(root_w * 25.4 / wmm)
                actual_ydpi = iround(root_h * 25.4 / hmm)
                if abs(actual_xdpi-xdpi)<=1 and abs(actual_ydpi-ydpi)<=1:
                    screenlog.info("DPI set to %s x %s", xdpi, ydpi)
                else:
                    #should this be a warning:
                    l = screenlog.info
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
            screenlog.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        return  root_w, root_h


    def _process_server_settings(self, _proto, packet):
        settings = packet[1]
        log("process_server_settings: %s", settings)
        self.update_server_settings(settings)

    def update_server_settings(self, _settings, _reset=False):
        #implemented in the X11 xpra server only for now
        #(does not make sense to update a shadow server)
        log("ignoring server settings update in %s", self)


    def _process_force_ungrab(self, proto, _packet):
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


    def do_xpra_cursor_event(self, event):
        if not self.cursors:
            return
        if self.last_cursor_serial==event.cursor_serial:
            cursorlog("ignoring cursor event %s with the same serial number %s", event, self.last_cursor_serial)
            return
        cursorlog("cursor_event: %s", event)
        self.last_cursor_serial = event.cursor_serial
        for ss in self._server_sources.values():
            ss.send_cursor()
        return False


    def _motion_signaled(self, model, event):
        mouselog("motion_signaled(%s, %s) last mouse user=%s", model, event, self.last_mouse_user)
        #find the window model for this gdk window:
        wid = self._window_to_id.get(model)
        if not wid:
            return
        for ss in self._server_sources.values():
            if ALWAYS_NOTIFY_MOTION or self.last_mouse_user is None or self.last_mouse_user!=ss.uuid:
                ss.update_mouse(wid, event.x_root, event.y_root, event.x, event.y)


    def do_xpra_xkb_event(self, event):
        #X11: XKBNotify
        log("WindowModel.do_xpra_xkb_event(%r)" % event)
        if event.subtype!="bell":
            log.error("do_xpra_xkb_event(%r) unknown event type: %s" % (event, event.type))
            return
        #bell events on our windows will come through the bell signal,
        #this method is a catch-all for events on windows we don't manage,
        #so we use wid=0 for that:
        wid = 0
        for ss in self._server_sources.values():
            ss.bell(wid, event.device, event.percent, event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name or "")


    def _bell_signaled(self, wm, event):
        log("bell signaled on window %#x", get_xwindow(event.window))
        if not self.bell:
            return
        wid = 0
        if event.window!=gdk.get_default_root_window() and event.window_model is not None:
            try:
                wid = self._window_to_id[event.window_model]
            except:
                pass
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        for ss in self._server_sources.values():
            ss.bell(wid, event.device, event.percent, event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name or "")


    def get_screen_number(self, _wid):
        #maybe this should be in all cases (it is in desktop_server):
        #model = self._id_to_window.get(wid)
        #return model.client_window.get_screen().get_number()
        #return gdk.display_get_default().get_default_screen().get_number()
        #-1 uses the current screen
        return -1


    def cleanup_input_devices(self):
        pass


    def setup_input_devices(self):
        xinputlog("setup_input_devices() format=%s, input_devices=%s", self.input_devices_format, self.input_devices)


    def _process_wheel_motion(self, proto, packet):
        assert self.pointer_device.has_precise_wheel()
        wid, button, distance, pointer, modifiers, _buttons = packet[1:7]
        with xsync:
            self._update_modifiers(proto, wid, modifiers)
            self.do_process_mouse_common(proto, wid, pointer)
            self.pointer_device.wheel_motion(button, distance/1000.0)

    def _move_pointer(self, wid, pos, deviceid=-1, *args):
        #(this is called within an xswallow context)
        screen_no = self.get_screen_number(wid)
        device = self.pointer_device
        mouselog("move_pointer(%s, %s, %s) screen_no=%i, device=%s", wid, pos, deviceid, screen_no, device)
        x, y = pos
        try:
            device.move_pointer(screen_no, x, y, *args)
        except Exception as e:
            mouselog.error("Error: failed to move the pointer to %sx%s using %s", x, y, device)
            mouselog.error(" %s", e)

    def do_process_mouse_common(self, proto, wid, pointer, deviceid=-1, *args):
        log("do_process_mouse_common%s", tuple([proto, wid, pointer, deviceid]+list(args)))
        if self.readonly:
            return
        if self.input_devices_data:
            device_data = self.input_devices_data.get(deviceid)
            if device_data:
                mouselog("process_mouse_common from device=%s", device_data.get("name"))
        pos = self.root_window.get_pointer()[:2]
        uuid = None
        if proto:
            ss = self._server_sources.get(proto)
            if ss:
                uuid = ss.uuid
        if pos!=pointer or self.input_devices=="xi":
            self.last_mouse_user = uuid
            with xswallow:
                self._move_pointer(wid, pointer, deviceid, *args)

    def _update_modifiers(self, proto, wid, modifiers):
        if self.readonly:
            return
        ss = self._server_sources.get(proto)
        if ss:
            if self.ui_driver and self.ui_driver!=ss.uuid:
                return
            ss.make_keymask_match(modifiers)
            if wid==self.get_focus():
                ss.user_event()

    def do_process_button_action(self, proto, wid, button, pressed, pointer, modifiers, _buttons=[], deviceid=-1, *_args):
        self._update_modifiers(proto, wid, modifiers)
        #TODO: pass extra args
        self._process_mouse_common(proto, wid, pointer, deviceid)
        self.button_action(pointer, button, pressed, deviceid)

    def button_action(self, pointer, button, pressed, deviceid=-1, *args):
        device = self.pointer_device
        assert device, "pointer device %s not found" % deviceid
        try:
            with xsync:
                device.click(button, pressed, *args)
        except XError:
            log.error("Error: failed (un)press mouse button %s", button)
            if button>=4:
                log.error(" (perhaps your Xvfb does not support mousewheels?)")


    def make_screenshot_packet_from_regions(self, regions):
        #regions = array of (wid, x, y, PIL.Image)
        if len(regions)==0:
            log("screenshot: no regions found, returning empty 0x0 image!")
            return ["screenshot", 0, 0, "png", -1, ""]
        #in theory, we could run the rest in a non-UI thread since we're done with GTK..
        minx = min([x for (_,x,_,_) in regions])
        miny = min([y for (_,_,y,_) in regions])
        maxx = max([(x+img.get_width()) for (_,x,_,img) in regions])
        maxy = max([(y+img.get_height()) for (_,_,y,img) in regions])
        width = maxx-minx
        height = maxy-miny
        log("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
        from PIL import Image                           #@UnresolvedImport
        screenshot = Image.new("RGBA", (width, height))
        for wid, x, y, img in reversed(regions):
            pixel_format = img.get_pixel_format()
            target_format = {
                     "XRGB"   : "RGB",
                     "BGRX"   : "RGB",
                     "BGRA"   : "RGBA"}.get(pixel_format, pixel_format)
            pixels = img.get_pixels()
            w = img.get_width()
            h = img.get_height()
            #PIL cannot use the memoryview directly:
            if isinstance(pixels, memoryview):
                pixels = pixels.tobytes()
            try:
                window_image = Image.frombuffer(target_format, (w, h), pixels, "raw", pixel_format, img.get_rowstride())
            except:
                log.error("Error parsing window pixels in %s format for window %i", pixel_format, wid, exc_info=True)
                continue
            tx = x-minx
            ty = y-miny
            screenshot.paste(window_image, (tx, ty))
        buf = StringIOClass()
        screenshot.save(buf, "png")
        data = buf.getvalue()
        buf.close()
        packet = ["screenshot", width, height, "png", width*4, Compressed("png", data)]
        log("screenshot: %sx%s %s", packet[1], packet[2], packet[-1])
        return packet
