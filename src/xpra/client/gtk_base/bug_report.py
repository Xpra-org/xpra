#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import time

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_pango, is_gtk3
from xpra.gtk_common.gtk_util import (
    window_defaults, gtk_main, add_close_accel, scaled_image,
    pixbuf_new_from_file, get_display_info, get_default_root_window,
    choose_file, get_gtk_version_info,
    JUSTIFY_LEFT, WIN_POS_CENTER, FILE_CHOOSER_ACTION_SAVE,
    )
from xpra.platform.gui import force_focus
from xpra.util import nonl, envint, repr_ellipsized
from xpra.os_util import strtobytes, hexstr, PYTHON3
from xpra.log import Logger

log = Logger("util")

gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()

STEP_DELAY = envint("XPRA_BUG_REPORT_STEP_DELAY", 0)


class BugReport(object):

    def init(self, show_about=True, get_server_info=None, opengl_info=None, includes=None):
        self.show_about = show_about
        self.get_server_info = get_server_info
        self.opengl_info = opengl_info
        self.includes = includes or {}
        self.setup_window()

    def setup_window(self):
        self.window = gtk.Window()
        window_defaults(self.window)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 300)
        self.window.set_title("Xpra Bug Report")

        icon_pixbuf = self.get_icon("bugs.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(15)

        # Title
        hbox = gtk.HBox(False, 0)
        icon_pixbuf = self.get_icon("xpra.png")
        if icon_pixbuf and self.show_about:
            from xpra.gtk_common.about import about
            logo_button = gtk.Button("")
            settings = logo_button.get_settings()
            settings.set_property('gtk-button-images', True)
            logo_button.connect("clicked", about)
            logo_button.set_tooltip_text("About")
            image = gtk.Image()
            image.set_from_pixbuf(icon_pixbuf)
            logo_button.set_image(image)
            hbox.pack_start(logo_button, expand=False, fill=False)

        label = gtk.Label("Xpra Bug Report Tool")
        label.modify_font(pango.FontDescription("sans 14"))
        hbox.pack_start(label, expand=True, fill=True)
        vbox.pack_start(hbox)

        #the box containing all the input:
        ibox = gtk.VBox(False, 0)
        ibox.set_spacing(3)
        vbox.pack_start(ibox)

        # Description
        al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(gtk.Label("Please describe the problem:"))
        ibox.pack_start(al)
        #self.description = gtk.Entry(max=128)
        #self.description.set_width_chars(40)
        self.description = gtk.TextView()
        self.description.set_accepts_tab(True)
        self.description.set_justification(JUSTIFY_LEFT)
        self.description.set_border_width(2)
        self.description.set_size_request(300, 80)
        #self.description.modify_bg(STATE_NORMAL, gdk.Color(red=32768, green=32768, blue=32768))
        ibox.pack_start(self.description, expand=False, fill=False)

        # Toggles:
        al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(gtk.Label("Include:"))
        ibox.pack_start(al)
        #generic toggles:
        from xpra.gtk_common.keymap import get_gtk_keymap
        from xpra.codecs.loader import codec_versions, load_codecs
        load_codecs()
        try:
            from xpra.sound.wrapper import query_sound
            def get_sound_info():
                return query_sound()
        except ImportError:
            get_sound_info = None
        def get_gl_info():
            if self.opengl_info:
                return self.opengl_info
            try:
                from xpra.client.gl.gtk_base.gtkgl_check import check_support
                return check_support(force_enable=True)
            except Exception as e:
                return {"error" : str(e)}
        from xpra.net.net_util import get_info as get_net_info
        from xpra.platform.paths import get_info as get_path_info
        from xpra.platform.gui import get_info as get_gui_info
        from xpra.version_util import get_version_info, get_platform_info, get_host_info
        def get_sys_info():
            from xpra.platform.info import get_user_info
            from xpra.scripts.config import read_xpra_defaults
            return {
                    "argv"          : sys.argv,
                    "path"          : sys.path,
                    "exec_prefix"   : sys.exec_prefix,
                    "executable"    : sys.executable,
                    "version"       : get_version_info(),
                    "platform"      : get_platform_info(),
                    "host"          : get_host_info(),
                    "paths"         : get_path_info(),
                    "gtk"           : get_gtk_version_info(),
                    "gui"           : get_gui_info(),
                    "display"       : get_display_info(),
                    "user"          : get_user_info(),
                    "env"           : os.environ,
                    "config"        : read_xpra_defaults(),
                    }
        get_screenshot, take_screenshot_fn = None, None
        #screenshot: may have OS-specific code
        try:
            from xpra.platform.gui import take_screenshot
            take_screenshot_fn = take_screenshot
        except ImportError:
            log("failed to load platfrom specific screenshot code", exc_info=True)
        if not take_screenshot_fn:
            #try with Pillow:
            try:
                from PIL import ImageGrab           #@UnresolvedImport
                from io import BytesIO
                def pillow_imagegrab_screenshot():
                    img = ImageGrab.grab()
                    out = BytesIO()
                    img.save(out, format="PNG")
                    v = out.getvalue()
                    out.close()
                    return (img.width, img.height, "png", img.width*3, v)
                take_screenshot_fn = pillow_imagegrab_screenshot
            except Exception as e:
                log("cannot use Pillow's ImageGrab: %s", e)
        if not take_screenshot_fn:
            #default: gtk screen capture
            try:
                from xpra.server.shadow.gtk_root_window_model import GTKImageCapture
                rwm = GTKImageCapture(get_default_root_window())
                take_screenshot_fn = rwm.take_screenshot
            except Exception:
                log.warn("Warning: failed to load gtk screenshot code", exc_info=True)
        log("take_screenshot_fn=%s", take_screenshot_fn)
        if take_screenshot_fn:
            def _get_screenshot():
                #take_screenshot() returns: w, h, "png", rowstride, data
                return take_screenshot_fn()[4]
            get_screenshot = _get_screenshot
        self.toggles = (
                   ("system",       "txt",  "System",           get_sys_info,
                    "Xpra version, platform and host information"),
                   ("network",      "txt",  "Network",          get_net_info,
                    "Compression, packet encoding and encryption"),
                   ("encoding",     "txt",  "Encodings",        codec_versions,
                    "Picture encodings supported"),
                   ("opengl",       "txt",  "OpenGL",           get_gl_info,
                    "OpenGL driver and features"),
                   ("sound",        "txt",  "Sound",            get_sound_info,
                    "Sound codecs and GStreamer version information"),
                   ("keyboard",     "txt",  "Keyboard Mapping", get_gtk_keymap,
                    "Keyboard layout and key mapping"),
                   ("xpra-info",    "txt",  "Server Info",      self.get_server_info,
                    "Full server information from 'xpra info'"),
                   ("screenshot",   "png",  "Screenshot",       get_screenshot,
                    ""),
                   )
        for name, _, title, value_cb, tooltip in self.toggles:
            cb = gtk.CheckButton(title+[" (not available)", ""][bool(value_cb)])
            cb.set_active(self.includes.get(name, True))
            cb.set_sensitive(bool(value_cb))
            cb.set_tooltip_text(tooltip)
            ibox.pack_start(cb)
            setattr(self, name, cb)

        # Buttons:
        hbox = gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        def btn(label, tooltip, callback, icon_name=None):
            btn = gtk.Button(label)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            if icon_name:
                icon = self.get_icon(icon_name)
                if icon:
                    btn.set_image(scaled_image(icon, 24))
            hbox.pack_start(btn)
            return btn

        btn("Copy to clipboard", "Copy all data to clipboard", self.copy_clicked, "clipboard.png")
        btn("Save", "Save Bug Report", self.save_clicked, "download.png")
        btn("Cancel", "", self.close, "quit.png")

        def accel_close(*_args):
            self.close()
        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)


    def show(self):
        log("show()")
        if not self.window:
            self.setup_window()
        force_focus()
        self.window.show_all()
        self.window.present()

    def hide(self):
        log("hide()")
        if self.window:
            self.window.hide()

    def close(self, *args):
        log("close%s", args)
        if self.window:
            self.hide()
            self.window = None
        return True

    def destroy(self, *args):
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None


    def run(self):
        log("run()")
        gtk_main()
        log("run() gtk_main done")

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        gtk.main_quit()


    def get_icon(self, icon_name):
        from xpra.platform.paths import get_icon_dir
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None


    def get_data(self):
        log("get_data() collecting bug report data")
        data = []
        tb = self.description.get_buffer()
        buf = tb.get_text(*tb.get_bounds(), include_hidden_chars=False)
        if buf:
            data.append(("Description", "", "txt", buf))
        for name, dtype, title, value_cb, tooltip in self.toggles:
            if not bool(value_cb):
                continue
            cb = getattr(self, name)
            assert cb is not None
            if not cb.get_active():
                continue
            log("%s is enabled (%s)", name, tooltip)
            #OK, the checkbox is selected, get the data
            value = value_cb
            if not isinstance(value_cb, dict):
                try:
                    value = value_cb()
                except TypeError:
                    log.error("Error collecting %s bug report data using %s", name, value_cb, exc_info=True)
                    value = str(value_cb)
                    dtype = "txt"
                except Exception as e:
                    log.error("Error collecting %s bug report data using %s", name, value_cb, exc_info=True)
                    value = e
                    dtype = "txt"
            if value is None:
                s = "not available"
            elif isinstance(value, dict):
                s = os.linesep.join("%s : %s" % (k.ljust(32), nonl(str(v))) for k,v in sorted(value.items()))
            elif isinstance(value, (list, tuple)):
                s = os.linesep.join(str(x) for x in value)
            else:
                s = value
            log("%s (%s) %s: %s", title, tooltip, dtype, repr_ellipsized(s))
            data.append((title, tooltip, dtype, s))
            time.sleep(STEP_DELAY)
        return data

    def copy_clicked(self, *_args):
        data = self.get_data()
        def cdata(v):
            if isinstance(v, bytes):
                return hexstr(v)
            return str(v)
        text = os.linesep.join("%s: %s%s%s%s" % (title, tooltip, os.linesep, cdata(v), os.linesep)
                               for (title,tooltip,dtype,v) in data if dtype=="txt")
        clipboard = gtk.clipboard_get(gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text)
        log.info("%s characters copied to clipboard", len(text))

    def save_clicked(self, *_args):
        file_filter = gtk.FileFilter()
        file_filter.set_name("ZIP")
        file_filter.add_pattern("*.zip")
        choose_file(self.window, "Save Bug Report Data", FILE_CHOOSER_ACTION_SAVE, gtk.STOCK_SAVE, self.do_save)

    def do_save(self, filename):
        log("do_save(%s)", filename)
        if not filename.lower().endswith(".zip"):
            filename = filename+".zip"
        basenoext = os.path.splitext(os.path.basename(filename))[0]
        data = self.get_data()
        import zipfile
        zf = zipfile.ZipFile(filename, mode='w', compression=zipfile.ZIP_DEFLATED)
        try:
            for title, tooltip, dtype, s in data:
                cfile = os.path.join(basenoext, title.replace(" ", "_")+"."+dtype)
                info = zipfile.ZipInfo(cfile, date_time=time.localtime(time.time()))
                info.compress_type = zipfile.ZIP_DEFLATED
                #very poorly documented:
                info.external_attr = 0o644 << 16
                info.comment = strtobytes(tooltip)
                if PYTHON3 and isinstance(s, bytes):
                    try:
                        try:
                            import tempfile
                            temp = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".screenshot", delete=False)
                            with temp:
                                temp.write(s)
                                temp.flush()
                        except OSError as e:
                            log.error("Error: cannot create mmap file:")
                            log.error(" %s", e)
                        else:
                            zf.write(temp.name, cfile, zipfile.ZIP_STORED)
                    finally:
                        if temp:
                            os.unlink(temp.name)
                else:
                    zf.writestr(info, str(s))
        finally:
            zf.close()
