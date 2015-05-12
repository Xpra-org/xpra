# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.gtk_common.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()


from xpra.log import Logger
log = Logger("gtk", "main")
opengllog = Logger("gtk", "opengl")
cursorlog = Logger("gtk", "client", "cursor")
screenlog = Logger("gtk", "client", "screen")

from xpra.gtk_common.quit import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from xpra.util import bytestostr, DEFAULT_METADATA_SUPPORTED
from xpra.gtk_common.cursor_names import cursor_names
from xpra.gtk_common.gtk_util import get_gtk_version_info, scaled_image, default_Cursor, \
            new_Cursor_for_display, new_Cursor_from_pixbuf, icon_theme_get_default, \
            pixbuf_new_from_file, display_get_default, screen_get_default, get_pixbuf_from_data, INTERP_BILINEAR
from xpra.client.ui_client_base import UIXpraClient
from xpra.client.gobject_client_base import GObjectXpraClient
from xpra.client.gtk_base.gtk_keyboard_helper import GTKKeyboardHelper
from xpra.client.gtk_base.session_info import SessionInfo
from xpra.platform.paths import get_icon_filename
from xpra.platform.gui import system_bell, get_workarea, get_workareas, get_fixed_cursor_size

missing_cursor_names = set()

METADATA_SUPPORTED = os.environ.get("XPRA_METADATA_SUPPORTED")


class GTKXpraClient(UIXpraClient, GObjectXpraClient):
    __gsignals__ = UIXpraClient.__gsignals__

    ClientWindowClass = None
    GLClientWindowClass = None

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.session_info = None
        self.bug_report = None
        self.start_new_command = None
        #opengl bits:
        self.client_supports_opengl = False
        self.opengl_enabled = False
        self.opengl_props = {}

    def init(self, opts):
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)

    def run(self):
        UIXpraClient.run(self)
        gtk_main_quit_on_fatal_exceptions_enable()
        self.gtk_main()
        log("GTKXpraClient.run_main_loop() main loop ended, returning exit_code=%s", self.exit_code)
        return  self.exit_code

    def gtk_main(self):
        raise NotImplementedError()

    def quit(self, exit_code=0):
        log("GTKXpraClient.quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        if gtk.main_level()>0:
            #if for some reason cleanup() hangs, maybe this will fire...
            gobject.timeout_add(4*1000, gtk_main_quit_really)
            #try harder!:
            def force_quit():
                from xpra import os_util
                os_util.force_quit()
            gobject.timeout_add(5*1000, force_quit)
        self.cleanup()
        log("GTKXpraClient.quit(%s) cleanup done, main_level=%s", exit_code, gtk.main_level())
        if gtk.main_level()>0:
            log("GTKXpraClient.quit(%s) main loop at level %s, calling gtk quit via timeout", exit_code, gtk.main_level())
            gobject.timeout_add(500, gtk_main_quit_really)

    def cleanup(self):
        if self.session_info:
            self.session_info.destroy()
            self.session_info = None
        if self.bug_report:
            self.bug_report.destroy()
            self.bug_report = None
        if self.start_new_command:
            self.start_new_command.destroy()
            self.start_new_command = None
        UIXpraClient.cleanup(self)


    def show_start_new_command(self, *args):
        log("show_start_new_command%s current start_new_command=%s, flag=%s", args, self.start_new_command, self.start_new_commands)
        if self.start_new_command is None:
            from xpra.client.gtk_base.start_new_command import getStartNewCommand
            def run_command_cb(command):
                self.send_start_command(command, command, False)
            self.start_new_command = getStartNewCommand(run_command_cb)
        self.start_new_command.show()
        return self.start_new_command


    def show_session_info(self, *args):
        if self.session_info and not self.session_info.is_closed:
            #exists already: just raise its window:
            self.session_info.set_args(*args)
            self.session_info.present()
            return
        pixbuf = self.get_pixbuf("statistics.png")
        if not pixbuf:
            pixbuf = self.get_pixbuf("xpra.png")
        self.session_info = SessionInfo(self, self.session_name, pixbuf, self._protocol._conn, self.get_pixbuf)
        self.session_info.set_args(*args)
        self.session_info.show_all()

    def show_bug_report(self, *args):
        if self.bug_report:
            self.bug_report.show()
            return
        self.send_info_request()
        from xpra.client.gtk_base.bug_report import BugReport
        self.bug_report = BugReport()
        def init_bug_report():
            #skip things we aren't using:
            includes ={
                       "keyboard"       : bool(self.keyboard_helper),
                       "opengl"         : self.opengl_enabled,
                       }
            def get_server_info():
                return self.server_last_info
            self.bug_report.init(show_about=False, get_server_info=get_server_info, opengl_info=self.opengl_props, includes=includes)
            self.bug_report.show()
        #gives the server time to send an info response..
        #(by the time the user clicks on copy, it should have arrived, we hope!)
        self.timeout_add(200, init_bug_report)


    def get_pixbuf(self, icon_name):
        try:
            if not icon_name:
                log("get_pixbuf(%s)=None", icon_name)
                return None
            icon_filename = get_icon_filename(icon_name)
            log("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
            if icon_filename:
                return pixbuf_new_from_file(icon_filename)
        except:
            log.error("get_pixbuf(%s)", icon_name, exc_info=True)
        return  None


    def get_image(self, icon_name, size=None):
        try:
            pixbuf = self.get_pixbuf(icon_name)
            log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None


    def make_keyboard_helper(self, keyboard_sync, key_shortcuts):
        return GTKKeyboardHelper(self.send, keyboard_sync, key_shortcuts)


    def _add_statusicon_tray(self, tray_list):
        #add gtk.StatusIcon tray:
        try:
            from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
            tray_list.append(GTKStatusIconTray)
        except Exception as e:
            log.warn("failed to load StatusIcon tray: %s" % e)
        return tray_list

    def get_tray_classes(self):
        return self._add_statusicon_tray(UIXpraClient.get_tray_classes(self))

    def get_system_tray_classes(self):
        return self._add_statusicon_tray(UIXpraClient.get_system_tray_classes(self))


    def supports_system_tray(self):
        #always True: we can always use gtk.StatusIcon as fallback
        return True


    def get_root_window(self):
        raise Exception("override me!")

    def get_root_size(self):
        raise Exception("override me!")

    def get_mouse_position(self):
        return self.get_root_window().get_pointer()[:2]

    def get_current_modifiers(self):
        modifiers_mask = self.get_root_window().get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)


    def make_hello(self):
        capabilities = UIXpraClient.make_hello(self)
        capabilities["named_cursors"] = len(cursor_names)>0
        capabilities.update(get_gtk_version_info())
        #tell the server which icons GTK can use
        #so it knows when it should supply one as fallback
        it = icon_theme_get_default()
        #this would add our bundled icon directory
        #to the search path, but I don't think we have
        #any extra icons that matter in there:
        #from xpra.platform.paths import get_icon_dir
        #d = get_icon_dir()
        #if d not in it.get_search_path():
        #    it.append_search_path(d)
        #    it.rescan_if_needed()
        log("default icon theme: %s", it)
        log("icon search path: %s", it.get_search_path())
        log("contexts: %s", it.list_contexts())
        icons = []
        for context in it.list_contexts():
            icons += it.list_icons(context)
        log("icons: %s", icons)
        capabilities["theme.default.icons"] = list(set(icons))
        if METADATA_SUPPORTED:
            ms = [x.strip() for x in METADATA_SUPPORTED.split(",")]
        else:
            #this is currently unused, and slightly redundant because of metadata.supported below:
            capabilities["window.states"] = ["fullscreen", "maximized", "sticky", "above", "below", "shaded", "iconified", "skip-taskbar", "skip-pager"]
            ms = list(DEFAULT_METADATA_SUPPORTED)
            #added in 0.15:
            ms += ["command", "workspace", "above", "below", "sticky"]
        if os.name=="posix":
            #this is only really supported on X11, but posix is easier to check for..
            #"strut" and maybe even "fullscreen-monitors" could also be supported on other platforms I guess
            ms += ["shaded", "bypass-compositor", "strut", "fullscreen-monitors"]
        log("metadata.supported: %s", ms)
        capabilities["metadata.supported"] = ms
        #we need the bindings to support initiate-moveresize (posix only for now):
        from xpra.client.gtk_base.gtk_client_window_base import HAS_X11_BINDINGS
        capabilities["window.initiate-moveresize"] = HAS_X11_BINDINGS
        #window icon bits
        capabilities["encoding.icons.greedy"] = True            #we don't set a default window icon any more
        capabilities["encoding.icons.size"] = 64, 64            #size we want
        capabilities["encoding.icons.max_size"] = 128, 128      #limit
        from xpra.client.window_backing_base import DELTA_BUCKETS
        capabilities["encoding.delta_buckets"] = DELTA_BUCKETS
        return capabilities


    def has_transparency(self):
        return screen_get_default().get_rgba_visual() is not None


    def get_screen_sizes(self):
        display = display_get_default()
        i=0
        screen_sizes = []
        n_screens = display.get_n_screens()
        screenlog("get_screen_sizes() found %s screens", n_screens)
        while i<n_screens:
            screen = display.get_screen(i)
            j = 0
            monitors = []
            workareas = []
            #native "get_workareas()" is only valid for a single screen (but describes all the monitors)
            #and it is only implemented on win32 right now
            #other platforms only implement "get_workarea()" instead, which is reported against the screen
            n_monitors = screen.get_n_monitors()
            screenlog("get_screen_sizes() screen %s has %s monitors", i, n_monitors)
            if n_screens==1:
                workareas = get_workareas()
                if len(workareas)!=n_monitors:
                    screenlog("number of monitors does not match number of workareas!")
                    workareas = []
            while j<screen.get_n_monitors():
                geom = screen.get_monitor_geometry(j)
                plug_name = ""
                if hasattr(screen, "get_monitor_plug_name"):
                    plug_name = screen.get_monitor_plug_name(j) or ""
                wmm = -1
                if hasattr(screen, "get_monitor_width_mm"):
                    wmm = screen.get_monitor_width_mm(j)
                hmm = -1
                if hasattr(screen, "get_monitor_height_mm"):
                    hmm = screen.get_monitor_height_mm(j)
                monitor = [plug_name, geom.x, geom.y, geom.width, geom.height, wmm, hmm]
                screenlog("get_screen_sizes() monitor %s: %s", j, monitor)
                if workareas:
                    w = workareas[j]
                    monitor += list(w)
                monitors.append(tuple(monitor))
                j += 1
            work_x, work_y = 0, 0
            work_width, work_height = screen.get_width(), screen.get_height()
            workarea = get_workarea()
            if workarea:
                work_x, work_y, work_width, work_height = workarea
            screenlog("get_screen_sizes() workarea=%s", workarea)
            item = (screen.make_display_name(), screen.get_width(), screen.get_height(),
                        screen.get_width_mm(), screen.get_height_mm(),
                        monitors,
                        work_x, work_y, work_width, work_height)
            screenlog("get_screen_sizes() screen %s: %s", i, item)
            screen_sizes.append(item)
            i += 1
        return screen_sizes

    def set_windows_cursor(self, windows, cursor_data):
        cursorlog("set_windows_cursor(%s, ..)", windows)
        cursor = None
        if cursor_data:
            try:
                cursor = self.make_cursor(cursor_data)
                cursorlog("make_cursor(..)=%s", cursor)
            except Exception as e:
                log.warn("error creating cursor: %s (using default)", e, exc_info=True)
            if cursor is None:
                #use default:
                cursor = default_Cursor
        for w in windows:
            gdkwin = w.get_window()
            #trays don't have a gdk window
            if gdkwin:
                gdkwin.set_cursor(cursor)

    def make_cursor(self, cursor_data):
        #if present, try cursor ny name:
        display = display_get_default()
        if len(cursor_data)>=9 and cursor_names:
            cursor_name = bytestostr(cursor_data[8])
            if cursor_name:
                gdk_cursor = cursor_names.get(cursor_name.upper())
                if gdk_cursor is not None:
                    cursorlog("setting new cursor by name: %s=%s", cursor_name, gdk_cursor)
                    return new_Cursor_for_display(display, gdk_cursor)
                else:
                    global missing_cursor_names
                    if cursor_name not in missing_cursor_names:
                        cursorlog("cursor name '%s' not found", cursor_name)
                        missing_cursor_names.add(cursor_name)
        #create cursor from the pixel data:
        w, h, xhot, yhot, serial, pixels = cursor_data[2:8]
        if len(pixels)<w*h*4:
            import binascii
            cursorlog.warn("not enough pixels provided in cursor data: %s needed and only %s bytes found (%s)", w*h*4, len(pixels), binascii.hexlify(pixels)[:100])
            return
        pixbuf = get_pixbuf_from_data(pixels, True, w, h, w*4)
        x = max(0, min(xhot, w-1))
        y = max(0, min(yhot, h-1))
        csize = display.get_default_cursor_size()
        cmaxw, cmaxh = display.get_maximal_cursor_size()
        if len(cursor_data)>=11:
            ssize = cursor_data[9]
            smax = cursor_data[10]
            cursorlog("server cursor sizes: default=%s, max=%s", ssize, smax)
        cursorlog("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s, default cursor size is %s, maximum=%s", xhot,yhot, serial, w,h, len(pixels), csize, (cmaxw, cmaxh))
        fw, fh = get_fixed_cursor_size()
        if fw>0 and fh>0 and (w!=fw or h!=fh):
            #OS wants a fixed cursor size! (win32 does, and GTK doesn't do this for us)
            if w<=fw and h<=fh:
                cursorlog("pasting cursor of size %ix%i onto clear pixbuf of size %ix%i", w, h, fw, fh)
                cursor_pixbuf = get_pixbuf_from_data("\0"*fw*fh*4, True, fw, fh, fw*4)
                pixbuf.copy_area(0, 0, w, h, cursor_pixbuf, 0, 0)
            else:
                cursorlog("scaling cursor from %ix%i to fixed OS size %ix%i", w, h, fw, fh)
                cursor_pixbuf = pixbuf.scale_simple(fw, fh, INTERP_BILINEAR)
                xratio, yratio = float(w)/fw, float(h)/fh
                x, y = int(x/xratio), int(y/yratio)
        elif w>cmaxw or h>cmaxh or (csize>0 and (csize<w or csize<h)):
            ratio = max(float(w)/cmaxw, float(h)/cmaxh, float(max(w,h))/csize)
            x, y, w, h = int(x/ratio), int(y/ratio), int(w/ratio), int(h/ratio)
            cursorlog("downscaling cursor %s by %.2f: %sx%s", pixbuf, ratio, w, h)
            cursor_pixbuf = pixbuf.scale_simple(w, h, INTERP_BILINEAR)
        else:
            cursor_pixbuf = pixbuf
        return new_Cursor_from_pixbuf(display, cursor_pixbuf, x, y)


    def process_ui_capabilities(self):
        UIXpraClient.process_ui_capabilities(self)
        if self.server_randr:
            display = display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self.screen_size_changed)
                i += 1


    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = self.get_root_window()
        log("window_bell(..) gdkwindow=%s", gdkwindow)
        if not system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name):
            #fallback to simple beep:
            gdk.beep()


    #OpenGL bits:
    def init_opengl(self, enable_opengl):
        opengllog("init_opengl(%s)", enable_opengl)
        #enable_opengl can be True, False or None (auto-detect)
        if enable_opengl is False:
            self.opengl_props["info"] = "disabled by configuration"
            return
        from xpra.scripts.config import OpenGL_safety_check
        warning = OpenGL_safety_check()
        if warning:
            if enable_opengl is True:
                opengllog.warn("OpenGL safety warning (enabled at your own risk): %s", warning)
                self.opengl_props["info"] = "forced enabled despite: %s" % warning
            else:
                opengllog.warn("OpenGL disabled: %s", warning)
                self.opengl_props["info"] = "disabled: %s" % warning
                return
        self.opengl_props["info"] = ""
        try:
            opengllog("init_opengl: going to import xpra.client.gl")
            __import__("xpra.client.gl", {}, {}, [])
            __import__("xpra.client.gl.gtk_compat", {}, {}, [])
            gl_check = __import__("xpra.client.gl.gl_check", {}, {}, ["check_support"])
            opengllog("init_opengl: gl_check=%s", gl_check)
            w, h = self.get_root_size()
            min_texture_size = max(w, h)
            self.opengl_props = gl_check.check_support(min_texture_size, force_enable=(enable_opengl is True))
            opengllog("init_opengl: found props %s", self.opengl_props)
            GTK_GL_CLIENT_WINDOW_MODULE = "xpra.client.gl.gtk%s.gl_client_window" % (2+int(is_gtk3()))
            opengllog("init_opengl: trying to load GL client window module '%s'", GTK_GL_CLIENT_WINDOW_MODULE)
            gl_client_window = __import__(GTK_GL_CLIENT_WINDOW_MODULE, {}, {}, ["GLClientWindow"])
            self.GLClientWindowClass = gl_client_window.GLClientWindow
            self.client_supports_opengl = True
            #only enable opengl by default if force-enabled or if safe to do so:
            self.opengl_enabled = (enable_opengl is True) or self.opengl_props.get("safe", False)
        except ImportError as e:
            opengllog.warn("OpenGL support could not be enabled:")
            opengllog.warn(" %s", e)
            self.opengl_props["info"] = str(e)
        except Exception as e:
            opengllog.error("Error loading OpenGL support:")
            opengllog.error(" %s", e, exc_info=True)
            self.opengl_props["info"] = str(e)

    def get_client_window_classes(self, metadata, override_redirect):
        log("get_client_window_class(%s, %s) GLClientWindowClass=%s, opengl_enabled=%s, mmap_enabled=%s, encoding=%s", metadata, override_redirect, self.GLClientWindowClass, self.opengl_enabled, self.mmap_enabled, self.encoding)
        if self.GLClientWindowClass is None or not self.opengl_enabled:
            return [self.ClientWindowClass]
        return [self.GLClientWindowClass, self.ClientWindowClass]

    def toggle_opengl(self, *args):
        assert self.window_unmap, "server support for 'window_unmap' is required for toggling opengl at runtime"
        self.opengl_enabled = not self.opengl_enabled
        opengllog("opengl_toggled: %s", self.opengl_enabled)
        def fake_send(*args):
            opengllog("fake_send(%s)", args)
        #now replace all the windows with new ones:
        for wid, window in self._id_to_window.items():
            if window.is_tray():
                #trays are never GL enabled, so don't bother re-creating them
                #(might cause problems anyway if we did)
                continue
            #ignore packets from old window:
            window.send = fake_send
            #copy attributes:
            x, y = window._pos
            w, h = window._size
            client_properties = window._client_properties
            metadata = window._metadata
            override_redirect = window._override_redirect
            backing = window._backing
            video_decoder = None
            csc_decoder = None
            decoder_lock = None
            try:
                if backing:
                    video_decoder = backing._video_decoder
                    csc_decoder = backing._csc_decoder
                    decoder_lock = backing._decoder_lock
                    if decoder_lock:
                        decoder_lock.acquire()
                        opengllog("toggle_opengl() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                        backing._video_decoder = None
                        backing._csc_decoder = None
                        backing._decoder_lock = None

                #now we can unmap it:
                self.destroy_window(wid, window)
                #explicitly tell the server we have unmapped it:
                #(so it will reset the video encoders, etc)
                self.send("unmap-window", wid)
                try:
                    del self._id_to_window[wid]
                except:
                    pass
                try:
                    del self._window_to_id[window]
                except:
                    pass
                #create the new window, which should honour the new state of the opengl_enabled flag:
                window = self.make_new_window(wid, x, y, w, h, metadata, override_redirect, client_properties)
                if video_decoder or csc_decoder:
                    backing = window._backing
                    backing._video_decoder = video_decoder
                    backing._csc_decoder = csc_decoder
                    backing._decoder_lock = decoder_lock
            finally:
                if decoder_lock:
                    decoder_lock.release()
        opengllog("replaced all the windows with opengl=%s: %s", self.opengl_enabled, self._id_to_window)
