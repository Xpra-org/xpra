# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import weakref
from xpra.gtk_common.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
from xpra.client.gtk_base.gtk_client_window_base import HAS_X11_BINDINGS, XSHAPE
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()


from xpra.log import Logger
log = Logger("gtk", "client")
opengllog = Logger("gtk", "opengl")
cursorlog = Logger("gtk", "client", "cursor")
screenlog = Logger("gtk", "client", "screen")
framelog = Logger("gtk", "client", "frame")
menulog = Logger("gtk", "client", "menu")
filelog = Logger("gtk", "client", "file")

from xpra.gtk_common.quit import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from xpra.util import updict, pver, iround, flatten_dict, envbool, DEFAULT_METADATA_SUPPORTED
from xpra.os_util import bytestostr, WIN32, OSX
from xpra.simple_stats import std_unit
from xpra.gtk_common.cursor_names import cursor_types
from xpra.gtk_common.gtk_util import get_gtk_version_info, scaled_image, get_default_cursor, \
            new_Cursor_for_display, new_Cursor_from_pixbuf, icon_theme_get_default, \
            pixbuf_new_from_file, display_get_default, screen_get_default, get_pixbuf_from_data, \
            get_default_root_window, get_root_size, get_xwindow, \
            INTERP_BILINEAR, WINDOW_TOPLEVEL, DIALOG_DESTROY_WITH_PARENT, MESSAGE_INFO, BUTTONS_CLOSE
from xpra.client.ui_client_base import UIXpraClient
from xpra.client.gobject_client_base import GObjectXpraClient
from xpra.client.gtk_base.gtk_keyboard_helper import GTKKeyboardHelper
from xpra.client.gtk_base.session_info import SessionInfo
from xpra.platform.paths import get_icon_filename
from xpra.platform.gui import get_window_frame_sizes, get_window_frame_size, system_bell, get_fixed_cursor_size, get_menu_support_function, get_wm_name

missing_cursor_names = set()

METADATA_SUPPORTED = os.environ.get("XPRA_METADATA_SUPPORTED")
USE_LOCAL_CURSORS = envbool("XPRA_USE_LOCAL_CURSORS", True)


class GTKXpraClient(UIXpraClient, GObjectXpraClient):
    __gsignals__ = UIXpraClient.__gsignals__

    ClientWindowClass = None
    GLClientWindowClass = None

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.session_info = None
        self.bug_report = None
        self.file_size_dialog = None
        self.file_dialog = None
        self.start_new_command = None
        self.keyboard_helper_class = GTKKeyboardHelper
        #opengl bits:
        self.client_supports_opengl = False
        self.opengl_enabled = False
        self.opengl_props = {}
        self.gl_max_viewport_dims = 0, 0
        self.gl_texture_size_limit = 0
        self._cursors = weakref.WeakKeyDictionary()
        #frame request hidden window:
        self.frame_request_window = None
        #group leader bits:
        self._ref_to_group_leader = {}
        self._group_leader_wids = {}
        self._set_window_menu = get_menu_support_function()
        self.connect("scaling-changed", self.reset_windows_cursors)


    def init(self, opts):
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)


    def setup_frame_request_windows(self):
        #query the window manager to get the frame size:
        from xpra.gtk_common.error import xsync
        from xpra.x11.gtk_x11.send_wm import send_wm_request_frame_extents
        self.frame_request_window = gtk.Window(WINDOW_TOPLEVEL)
        self.frame_request_window.set_title("Xpra-FRAME_EXTENTS")
        root = self.get_root_window()
        self.frame_request_window.realize()
        with xsync:
            win = self.frame_request_window.get_window()
            framelog("setup_frame_request_windows() window=%#x", get_xwindow(win))
            send_wm_request_frame_extents(root, win)

    def run(self):
        log("run() HAS_X11_BINDINGS=%s", HAS_X11_BINDINGS)
        if HAS_X11_BINDINGS:
            self.setup_frame_request_windows()
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
            self.timeout_add(4*1000, self.exit)
            #try harder!:
            def force_quit():
                from xpra import os_util
                os_util.force_quit()
            self.timeout_add(5*1000, force_quit)
        self.cleanup()
        log("GTKXpraClient.quit(%s) cleanup done, main_level=%s", exit_code, gtk.main_level())
        if gtk.main_level()>0:
            log("GTKXpraClient.quit(%s) main loop at level %s, calling gtk quit via timeout", exit_code, gtk.main_level())
            self.timeout_add(500, self.exit)

    def exit(self):
        log("GTKXpraClient.exit() calling %s", gtk_main_quit_really)
        gtk_main_quit_really()

    def cleanup(self):
        if self.session_info:
            self.session_info.destroy()
            self.session_info = None
        if self.bug_report:
            self.bug_report.destroy()
            self.bug_report = None
        self.close_file_size_warning()
        self.close_file_upload_dialog()
        if self.start_new_command:
            self.start_new_command.destroy()
            self.start_new_command = None
        UIXpraClient.cleanup(self)


    def show_start_new_command(self, *args):
        log("show_start_new_command%s current start_new_command=%s, flag=%s", args, self.start_new_command, self.start_new_commands)
        if self.start_new_command is None:
            from xpra.client.gtk_base.start_new_command import getStartNewCommand
            def run_command_cb(command, sharing=True):
                self.send_start_command(command, command, False, sharing)
            self.start_new_command = getStartNewCommand(run_command_cb, self.server_supports_sharing and self.server_supports_window_filters)
        self.start_new_command.show()
        return self.start_new_command


    def file_size_warning(self, action, location, basefilename, filesize, limit):
        if self.file_size_dialog:
            #close previous warning
            self.file_size_dialog.destroy()
            self.file_size_dialog = None
        parent = None
        msgs = (
                "Warning: cannot %s the file '%s'" % (action, basefilename),
                "this file is too large: %sB" % std_unit(filesize, unit=1024),
                "the %s file size limit is %iMB" % (location, limit),
                )
        self.file_size_dialog = gtk.MessageDialog(parent, DIALOG_DESTROY_WITH_PARENT, MESSAGE_INFO,
                                                  BUTTONS_CLOSE, "\n".join(msgs))
        try:
            image = gtk.image_new_from_stock(gtk.STOCK_DIALOG_WARNING, 64)
            self.file_size_dialog.set_image(image)
        except Exception as e:
            log.warn("failed to set dialog image: %s", e)
        self.file_size_dialog.connect("response", self.close_file_size_warning)
        self.file_size_dialog.show()

    def close_file_size_warning(self, *args):
        fsd = self.file_size_dialog
        if fsd:
            self.file_size_dialog = None
            fsd.destroy()

    def show_file_upload(self, *args):
        if self.file_dialog:
            self.file_dialog.present()
            return
        filelog("show_file_upload%s can open=%s", args, self.remote_open_files)
        buttons = [gtk.STOCK_CANCEL,    gtk.RESPONSE_CANCEL]
        if self.remote_open_files:
            buttons += [gtk.STOCK_OPEN,      gtk.RESPONSE_ACCEPT]
        buttons += [gtk.STOCK_OK,        gtk.RESPONSE_OK]
        self.file_dialog = gtk.FileChooserDialog("File to upload", parent=None, action=gtk.FILE_CHOOSER_ACTION_OPEN, buttons=tuple(buttons))
        self.file_dialog.set_default_response(gtk.RESPONSE_OK)
        self.file_dialog.connect("response", self.file_upload_dialog_response)
        self.file_dialog.show()

    def close_file_upload_dialog(self):
        fd = self.file_dialog
        if fd:
            fd.destroy()
            self.file_dialog = None

    def file_upload_dialog_response(self, dialog, v):
        if v not in (gtk.RESPONSE_OK, gtk.RESPONSE_ACCEPT):
            filelog("dialog response code %s", v)
            self.close_file_upload_dialog()
            return
        filename = dialog.get_filename()
        filelog("file_upload_dialog_response: filename=%s", filename)
        try:
            filesize = os.stat(filename).st_size
        except:
            pass
        else:
            if not self.check_file_size("upload", filename, filesize):
                self.close_file_upload_dialog()
                return
        gfile = dialog.get_file()
        self.close_file_upload_dialog()
        filelog("load_contents: filename=%s, response=%s", filename, v)
        gfile.load_contents_async(self.file_upload_ready, user_data=(filename, v==gtk.RESPONSE_ACCEPT))

    def file_upload_ready(self, gfile, result, user_data):
        filelog("file_upload_ready%s", (gfile, result, user_data))
        filename, openit = user_data
        data, filesize, entity = gfile.load_contents_finish(result)
        filelog("load_contents_finish(%s)=%s", result, (type(data), filesize, entity))
        if not data:
            log.warn("Warning: failed to load file '%s'", filename)
            return
        filelog("load_contents: filename=%s, %i bytes, entity=%s, openit=%s", filename, filesize, entity, openit)
        self.send_file(filename, "", data, filesize=filesize, openit=openit)


    def show_about(self, *args):
        from xpra.gtk_common.about import about
        about()

    def show_session_info(self, *args):
        if self.session_info and not self.session_info.is_closed:
            #exists already: just raise its window:
            self.session_info.set_args(*args)
            self.session_info.present()
            return
        pixbuf = self.get_pixbuf("statistics.png")
        if not pixbuf:
            pixbuf = self.get_pixbuf("xpra.png")
        conn = None
        p = self._protocol
        if p:
            conn = p._conn
        self.session_info = SessionInfo(self, self.session_name, pixbuf, conn, self.get_pixbuf)
        self.session_info.set_args(*args)
        self.session_info.show_all()

    def show_bug_report(self, *args):
        self.send_info_request()
        if self.bug_report:
            self.bug_report.show()
            return
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


    def request_frame_extents(self, window):
        from xpra.x11.gtk_x11.send_wm import send_wm_request_frame_extents
        from xpra.gtk_common.error import xsync
        root = self.get_root_window()
        with xsync:
            win = window.get_window()
            framelog("request_frame_extents(%s) xid=%#x", window, get_xwindow(win))
            send_wm_request_frame_extents(root, win)

    def get_frame_extents(self, window):
        #try native platform code first:
        x, y = window.get_position()
        w, h = window.get_size()
        v = get_window_frame_size(x, y, w, h)
        framelog("get_window_frame_size%s=%s", (x, y, w, h), v)
        if v:
            #(OSX does give us these values via Quartz API)
            return v
        if not HAS_X11_BINDINGS:
            #nothing more we can do!
            return None
        from xpra.x11.gtk_x11.prop import prop_get
        gdkwin = window.get_window()
        assert gdkwin
        v = prop_get(gdkwin, "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        framelog("get_frame_extents(%s)=%s", window.get_title(), v)
        return v

    def get_window_frame_sizes(self):
        wfs = get_window_frame_sizes()
        if self.frame_request_window:
            v = self.get_frame_extents(self.frame_request_window)
            if v:
                try:
                    wm_name = get_wm_name()
                except:
                    wm_name = None
                try:
                    if len(v)==8:
                        framelog.warn("Warning: invalid frame extents value '%s'", v)
                        if wm_name:
                            framelog.warn(" this is probably a bug in '%s'", wm_name)
                        v = v[4:]
                        framelog.warn(" using '%s' instead", v)
                    l, r, t, b = v
                    wfs["frame"] = (l, r, t, b)
                    wfs["offset"] = (l, t)
                except Exception as e:
                    framelog.warn("Warning: invalid frame extents value '%s'", v)
                    framelog.warn(" %s", e)
                    framelog.warn(" this is probably a bug in '%s'", wm_name)
        framelog("get_window_frame_sizes()=%s", wfs)
        return wfs


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


    def cook_metadata(self, new_window, metadata):
        metadata = UIXpraClient.cook_metadata(self, new_window, metadata)
        #ensures we will call set_window_menu for this window when we create it:
        if new_window and b"menu" not in metadata and self._set_window_menu:
            metadata[b"menu"] = {}
        return metadata


    def set_window_menu(self, add, wid, menus, application_action_callback=None, window_action_callback=None):
        assert self._set_window_menu
        model = self._id_to_window.get(wid)
        window = None
        if model:
            window = model.get_window()
        self._set_window_menu(add, wid, window, menus, application_action_callback, window_action_callback)


    def get_root_window(self):
        return get_default_root_window()

    def get_root_size(self):
        return get_root_size()


    def get_mouse_position(self):
        p = self.get_root_window().get_pointer()
        return self.cp(p[0], p[1])

    def get_current_modifiers(self):
        modifiers_mask = self.get_root_window().get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)


    def make_hello(self):
        capabilities = UIXpraClient.make_hello(self)
        capabilities["named_cursors"] = len(cursor_types)>0
        capabilities.update(flatten_dict(get_gtk_version_info()))
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
            ms += ["command", "workspace", "above", "below", "sticky",
                   "set-initial-position"]  #0.17
        if os.name=="posix":
            #this is only really supported on X11, but posix is easier to check for..
            #"strut" and maybe even "fullscreen-monitors" could also be supported on other platforms I guess
            ms += ["shaded", "bypass-compositor", "strut", "fullscreen-monitors"]
        if HAS_X11_BINDINGS and XSHAPE:
            ms += ["shape"]
        if self._set_window_menu:
            ms += ["menu"]
        #figure out if we can handle the "global menu" stuff:
        if os.name=="posix" and not OSX:
            try:
                from xpra.dbus.helper import DBusHelper
                assert DBusHelper
            except:
                pass
        log("metadata.supported: %s", ms)
        capabilities["metadata.supported"] = ms
        #we need the bindings to support initiate-moveresize (posix only for now):
        updict(capabilities, "window", {
               "initiate-moveresize"    : True,
               "configure.pointer"      : True,
               "frame_sizes"            : self.get_window_frame_sizes()
               })
        from xpra.client.window_backing_base import DELTA_BUCKETS
        updict(capabilities, "encoding", {
                    "icons.greedy"      : True,         #we don't set a default window icon any more
                    "icons.size"        : (64, 64),     #size we want
                    "icons.max_size"    : (128, 128),   #limit
                    "delta_buckets"     : DELTA_BUCKETS,
                    })
        return capabilities


    def has_transparency(self):
        return screen_get_default().get_rgba_visual() is not None


    def get_screen_sizes(self, xscale=1, yscale=1):
        from xpra.gtk_common.gtk_util import get_screen_sizes
        return get_screen_sizes(xscale, yscale)


    def reset_windows_cursors(self, *args):
        cursorlog("reset_windows_cursors() resetting cursors for: %s", self._cursors.keys())
        for w,cursor_data in list(self._cursors.items()):
            self.set_windows_cursor([w], cursor_data)


    def set_windows_cursor(self, windows, cursor_data):
        cursorlog("set_windows_cursor(%s, args[%i])", windows, len(cursor_data))
        cursor = None
        if cursor_data:
            try:
                cursor = self.make_cursor(cursor_data)
                cursorlog("make_cursor(..)=%s", cursor)
            except Exception as e:
                log.warn("error creating cursor: %s (using default)", e, exc_info=True)
            if cursor is None:
                #use default:
                cursor = get_default_cursor()
        for w in windows:
            gdkwin = w.get_window()
            #trays don't have a gdk window
            if gdkwin:
                self._cursors[w] = cursor_data
                gdkwin.set_cursor(cursor)

    def make_cursor(self, cursor_data):
        #if present, try cursor ny name:
        display = display_get_default()
        cursorlog("make_cursor: has-name=%s, has-cursor-types=%s, xscale=%s, yscale=%s, USE_LOCAL_CURSORS=%s", len(cursor_data)>=10, bool(cursor_types), self.xscale, self.yscale, USE_LOCAL_CURSORS)
        #named cursors cannot be scaled (round to 10 to compare so 0.95 and 1.05 are considered the same as 1.0, no scaling):
        if len(cursor_data)>=10 and cursor_types and iround(self.xscale*10)==10 and iround(self.yscale*10)==10:
            cursor_name = bytestostr(cursor_data[9])
            if cursor_name and USE_LOCAL_CURSORS:
                gdk_cursor = cursor_types.get(cursor_name.upper())
                if gdk_cursor is not None:
                    cursorlog("setting new cursor by name: %s=%s", cursor_name, gdk_cursor)
                    return new_Cursor_for_display(display, gdk_cursor)
                else:
                    global missing_cursor_names
                    if cursor_name not in missing_cursor_names:
                        cursorlog("cursor name '%s' not found", cursor_name)
                        missing_cursor_names.add(cursor_name)
        #create cursor from the pixel data:
        encoding, _, _, w, h, xhot, yhot, serial, pixels = cursor_data[0:9]
        if encoding==b"png":
            from xpra.os_util import BytesIOClass
            from PIL import Image
            buf = BytesIOClass(pixels)
            img = Image.open(buf)
            pixels = img.tobytes("raw", "BGRA")
            cursorlog("used PIL to convert png cursor to raw")
        elif encoding!=b"raw":
            cursorlog.warn("Warning: invalid cursor encoding: %s", encoding)
            return None
        if len(pixels)<w*h*4:
            import binascii
            cursorlog.warn("not enough pixels provided in cursor data: %s needed and only %s bytes found (%s)", w*h*4, len(pixels), binascii.hexlify(pixels)[:100])
            return None
        pixbuf = get_pixbuf_from_data(pixels, True, w, h, w*4)
        x = max(0, min(xhot, w-1))
        y = max(0, min(yhot, h-1))
        csize = display.get_default_cursor_size()
        cmaxw, cmaxh = display.get_maximal_cursor_size()
        if len(cursor_data)>=12:
            ssize = cursor_data[10]
            smax = cursor_data[11]
            cursorlog("server cursor sizes: default=%s, max=%s", ssize, smax)
        cursorlog("new %s cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s, default cursor size is %s, maximum=%s", encoding, xhot, yhot, serial, w, h, len(pixels), csize, (cmaxw, cmaxh))
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
                x, y = iround(x/xratio), iround(y/yratio)
        else:
            sx, sy, sw, sh = x, y, w, h
            #scale the cursors:
            if self.xscale!=1 or self.yscale!=1:
                sx, sy, sw, sh = self.srect(x, y, w, h)
            sw = max(1, sw)
            sh = max(1, sh)
            #ensure we honour the max size if there is one:
            if (cmaxw>0 and sw>cmaxw) or (cmaxh>0 and sh>cmaxh):
                ratio = 1.0
                if cmaxw>0:
                    ratio = max(ratio, float(w)/cmaxw)
                if cmaxh>0:
                    ratio = max(ratio, float(h)/cmaxh)
                cursorlog("clamping cursor size to %ix%i using ratio=%s", cmaxw, cmaxh, ratio)
                sx, sy, sw, sh = iround(x/ratio), iround(y/ratio), min(cmaxw, iround(w/ratio)), min(cmaxh, iround(h/ratio))
            if sw!=w or sh!=h:
                cursorlog("scaling cursor from %ix%i hotspot at %ix%i to %ix%i hotspot at %ix%i", w, h, x, y, sw, sh, sx, sy)
                cursor_pixbuf = pixbuf.scale_simple(sw, sh, INTERP_BILINEAR)
                x, y = sx, sy
            else:
                cursor_pixbuf = pixbuf
        #clamp to pixbuf size:
        w = cursor_pixbuf.get_width()
        h = cursor_pixbuf.get_height()
        x = max(0, min(x, w-1))
        y = max(0, min(y, h-1))
        try:
            c = new_Cursor_from_pixbuf(display, cursor_pixbuf, x, y)
        except RuntimeError as e:
            log.error("Error: failed to create cursor:")
            log.error(" %s", e)
            log.error(" using %s of size %ix%i with hotspot at %ix%i", cursor_pixbuf, w, h, x, y)
            c = None
        return c


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
        from xpra.platform.gui import gl_check as platform_gl_check
        warnings = []
        for check in (OpenGL_safety_check, platform_gl_check):
            opengllog("checking with %s", check)
            warning = check()
            opengllog("%s()=%s", check, warning)
            if warning:
                warnings.append(warning)
        self.opengl_props["info"] = ""
        if warnings:
            if enable_opengl is True:
                opengllog.warn("OpenGL safety warning (enabled at your own risk):")
                for warning in warnings:
                    opengllog.warn(" %s", warning)
                self.opengl_props["info"] = "forced enabled despite: %s" % (", ".join(warnings))
            else:
                opengllog.warn("OpenGL disabled:", warning)
                for warning in warnings:
                    opengllog.warn(" %s", warning)
                self.opengl_props["info"] = "disabled: %s" % (", ".join(warnings))
                return
        try:
            opengllog("init_opengl: going to import xpra.client.gl")
            __import__("xpra.client.gl", {}, {}, [])
            __import__("xpra.client.gl.gtk_compat", {}, {}, [])
            gl_check = __import__("xpra.client.gl.gl_check", {}, {}, ["check_support"])
            opengllog("init_opengl: gl_check=%s", gl_check)
            self.opengl_props = gl_check.check_support(force_enable=(enable_opengl is True))
            opengllog("init_opengl: found props %s", self.opengl_props)
            GTK_GL_CLIENT_WINDOW_MODULE = "xpra.client.gl.gtk%s.gl_client_window" % (2+int(is_gtk3()))
            opengllog("init_opengl: trying to load GL client window module '%s'", GTK_GL_CLIENT_WINDOW_MODULE)
            gl_client_window = __import__(GTK_GL_CLIENT_WINDOW_MODULE, {}, {}, ["GLClientWindow"])
            self.GLClientWindowClass = gl_client_window.GLClientWindow
            self.client_supports_opengl = True
            #only enable opengl by default if force-enabled or if safe to do so:
            self.opengl_enabled = (enable_opengl is True) or self.opengl_props.get("safe", False)
            self.gl_texture_size_limit = self.opengl_props.get("texture-size-limit", 16*1024)
            self.gl_max_viewport_dims = self.opengl_props.get("max-viewport-dims", (self.gl_texture_size_limit, self.gl_texture_size_limit))
            if min(self.gl_max_viewport_dims)<4*1024:
                opengllog.warn("Warning: OpenGL is disabled:")
                opengllog.warn(" the maximum viewport size is too low: %s", self.gl_max_viewport_dims)
                self.opengl_enabled = False
            elif self.gl_texture_size_limit<4*1024:
                opengllog.warn("Warning: OpenGL is disabled:")
                opengllog.warn(" the texture size limit is too low: %s", self.gl_texture_size_limit)
                self.opengl_enabled = False
            self.GLClientWindowClass.MAX_VIEWPORT_DIMS = self.gl_max_viewport_dims
            self.GLClientWindowClass.MAX_BACKING_DIMS = self.gl_texture_size_limit, self.gl_texture_size_limit
            mww, mwh = self.max_window_size
            opengllog("OpenGL: enabled=%s, texture-size-limit=%s, max-window-size=%s", self.opengl_enabled, self.gl_texture_size_limit, self.max_window_size)
            if self.opengl_enabled and self.gl_texture_size_limit<16*1024 and (mww==0 or mwh==0 or self.gl_texture_size_limit<mww or self.gl_texture_size_limit<mwh):
                #log at warn level if the limit is low:
                #(if we're likely to hit it - if the screen is as big or bigger)
                w, h = self.get_root_size()
                l = opengllog.info
                if w*2<=self.gl_texture_size_limit and h*2<=self.gl_texture_size_limit:
                    l = opengllog
                if w>=self.gl_texture_size_limit or h>=self.gl_texture_size_limit:
                    l = opengllog.warn
                l("Warning: OpenGL windows will be clamped to the maximum texture size %ix%i", self.gl_texture_size_limit, self.gl_texture_size_limit)
                l(" for OpenGL %s renderer '%s'", pver(self.opengl_props.get("opengl", "")), self.opengl_props.get("renderer", "unknown"))
            driver_info = self.opengl_props.get("renderer") or self.opengl_props.get("vendor") or "unknown card"
            if self.opengl_enabled:
                opengllog.info("OpenGL enabled with %s", driver_info)
            elif self.client_supports_opengl:
                opengllog("OpenGL supported with %s, but not enabled", driver_info)
        except ImportError as e:
            opengllog.warn("OpenGL support is missing:")
            opengllog.warn(" %s", e)
            self.opengl_props["info"] = str(e)
        except RuntimeError as e:
            opengllog.warn("OpenGL support could not be enabled on this hardware:")
            opengllog.warn(" %s", e)
            self.opengl_props["info"] = str(e)
        except Exception as e:
            opengllog.error("Error loading OpenGL support:")
            opengllog.error(" %s", e, exc_info=True)
            self.opengl_props["info"] = str(e)

    def get_client_window_classes(self, w, h, metadata, override_redirect):
        log("get_client_window_class(%i, %i, %s, %s) GLClientWindowClass=%s, opengl_enabled=%s, mmap_enabled=%s, encoding=%s", w, h, metadata, override_redirect, self.GLClientWindowClass, self.opengl_enabled, self.mmap_enabled, self.encoding)
        ms = min(self.sx(self.gl_texture_size_limit), *self.gl_max_viewport_dims)
        if self.GLClientWindowClass is None or not self.opengl_enabled or w>ms or h>ms:
            return [self.ClientWindowClass]
        return [self.GLClientWindowClass, self.ClientWindowClass]

    def toggle_opengl(self, *args):
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
            ww, wh = window._size
            try:
                bw, bh = window._backing.size
            except:
                bw, bh = ww, wh
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
                        backing.close()

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
                window = self.make_new_window(wid, x, y, ww, wh, bw, bh, metadata, override_redirect, client_properties)
                if video_decoder or csc_decoder:
                    backing = window._backing
                    backing._video_decoder = video_decoder
                    backing._csc_decoder = csc_decoder
                    backing._decoder_lock = decoder_lock
            finally:
                if decoder_lock:
                    decoder_lock.release()
        opengllog("replaced all the windows with opengl=%s: %s", self.opengl_enabled, self._id_to_window)


    def get_group_leader(self, wid, metadata, override_redirect):
        transient_for = metadata.intget("transient-for", -1)
        log("get_group_leader: transient_for=%s", transient_for)
        if transient_for>0:
            client_window = self._id_to_window.get(transient_for)
            if client_window:
                gdk_window = client_window.get_window()
                if gdk_window:
                    return gdk_window
        pid = metadata.intget("pid", -1)
        leader_xid = metadata.intget("group-leader-xid", -1)
        leader_wid = metadata.intget("group-leader-wid", -1)
        group_leader_window = self._id_to_window.get(leader_wid)
        if group_leader_window:
            #leader is another managed window
            log("found group leader window %s for wid=%s", group_leader_window, leader_wid)
            return group_leader_window
        log("get_group_leader: leader pid=%s, xid=%s, wid=%s", pid, leader_xid, leader_wid)
        reftype = "xid"
        ref = leader_xid
        if ref<0:
            reftype = "leader-wid"
            ref = leader_wid
        if ref<0:
            ci = metadata.strlistget("class-instance")
            if ci:
                reftype = "class"
                ref = "|".join(ci)
            elif pid>0:
                reftype = "pid"
                ref = pid
            elif transient_for>0:
                #this should have matched a client window above..
                #but try to use it anyway:
                reftype = "transient-for"
                ref = transient_for
            else:
                #no reference to use
                return None
        refkey = "%s:%s" % (reftype, ref)
        group_leader_window = self._ref_to_group_leader.get(refkey)
        if group_leader_window:
            log("found existing group leader window %s using ref=%s", group_leader_window, refkey)
            return group_leader_window
        #we need to create one:
        title = "%s group leader for %s" % (self.session_name or "Xpra", pid)
        #group_leader_window = gdk.Window(None, 1, 1, gdk.WINDOW_TOPLEVEL, 0, gdk.INPUT_ONLY, title)
        #static new(parent, attributes, attributes_mask)
        if is_gtk3():
            #long winded and annoying
            attributes = gdk.WindowAttr()
            attributes.width = 1
            attributes.height = 1
            attributes.title = title
            attributes.wclass = gdk.WindowWindowClass.INPUT_ONLY
            attributes.event_mask = 0
            attributes_mask = gdk.WindowAttributesType.TITLE | gdk.WindowAttributesType.WMCLASS
            group_leader_window = gdk.Window(None, attributes, attributes_mask)
            group_leader_window.resize(1, 1)
        else:
            #gtk2:
            group_leader_window = gdk.Window(None, 1, 1, gdk.WINDOW_TOPLEVEL, 0, gdk.INPUT_ONLY, title)
        self._ref_to_group_leader[refkey] = group_leader_window
        #avoid warning on win32...
        if not WIN32:
            #X11 spec says window should point to itself:
            group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid, window):
        #override so we can cleanup the group-leader if needed,
        UIXpraClient.destroy_window(self, wid, window)
        group_leader = window.group_leader
        if group_leader is None or len(self._group_leader_wids)==0:
            return
        wids = self._group_leader_wids.get(group_leader)
        if wids is None:
            #not recorded any window ids on this group leader
            #means it is another managed window, leave it alone
            return
        if wid in wids:
            wids.remove(wid)
        if len(wids)>0:
            #still has another window pointing to it
            return
        #the last window has gone, we can remove the group leader,
        #find all the references to this group leader:
        del self._group_leader_wids[group_leader]
        refs = []
        for ref, gl in self._ref_to_group_leader.items():
            if gl==group_leader:
                refs.append(ref)
        for ref in refs:
            del self._ref_to_group_leader[ref]
        log("last window for refs %s is gone, destroying the group leader %s", refs, group_leader)
        group_leader.destroy()
