#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import time
from typing import Any
from collections.abc import Callable

from xpra.common import ScreenshotData, noop
from xpra.gtk.util import get_default_root_window
from xpra.gtk.window import add_close_accel
from xpra.gtk.info import get_display_info
from xpra.gtk.widget import scaled_image, label, choose_file
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.versions import get_gtk_version_info
from xpra.platform.gui import force_focus
from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue
from xpra.util.str_fn import nonl, repr_ellipsized, hexstr
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.common import FULL_INFO
from xpra.log import Logger

log = Logger("util")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

STEP_DELAY = envint("XPRA_BUG_REPORT_STEP_DELAY", 0)


def get_pillow_imagegrab_fn() -> Callable:
    try:
        from PIL import ImageGrab
        from io import BytesIO
    except ImportError as e:
        log("cannot use Pillow's ImageGrab: %s", e)
        return noop

    def pillow_imagegrab() -> ScreenshotData:
        img = ImageGrab.grab()
        out = BytesIO()
        img.save(out, format="PNG")
        pixels = out.getvalue()
        out.close()
        return img.width, img.height, "png", img.width * 3, pixels

    return pillow_imagegrab


class BugReport:

    def __init__(self):
        self.checkboxes = {}
        self.server_log = None
        self.show_about = True
        self.get_server_info: Callable | None = None
        self.opengl_info: dict = {}
        self.includes: dict = {}
        self.window: Gtk.Window | None = None
        self.description: Gtk.TextView | None = None
        self.toggles: tuple = ()

    def init(self, show_about: bool = True,
             get_server_info: Callable | None = None,
             opengl_info=None, includes=None):
        self.show_about = show_about
        self.get_server_info = get_server_info
        self.opengl_info = opengl_info
        self.includes = includes or {}
        self.setup_window()

    def setup_window(self) -> None:
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 300)
        self.window.set_title("Xpra Bug Report")

        icon_pixbuf = get_icon_pixbuf("bugs.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)

        # Title
        hbox = Gtk.HBox(homogeneous=False, spacing=0)
        icon_pixbuf = get_icon_pixbuf("xpra.png")
        if icon_pixbuf and self.show_about:
            from xpra.gtk.dialogs.about import about
            logo_button = Gtk.Button(label="")
            settings = logo_button.get_settings()
            settings.set_property('gtk-button-images', True)

            def show_about(*_args):
                about(parent=self.window)

            logo_button.connect("clicked", show_about)
            logo_button.set_tooltip_text("About")
            image = Gtk.Image()
            image.set_from_pixbuf(icon_pixbuf)
            logo_button.set_image(image)
            hbox.pack_start(logo_button, expand=False, fill=False)

        # the box containing all the input:
        ibox = Gtk.VBox(homogeneous=False, spacing=0)
        ibox.set_spacing(3)
        vbox.pack_start(ibox)

        # Description
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(label("Please describe the problem:"))
        ibox.pack_start(al)
        self.description = Gtk.TextView()
        self.description.set_accepts_tab(True)
        self.description.set_justification(Gtk.Justification.LEFT)
        self.description.set_border_width(2)
        self.description.set_size_request(300, 80)
        ibox.pack_start(self.description, expand=False, fill=False)

        # Toggles:
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(label("Include:"))
        ibox.pack_start(al)
        # generic toggles:
        from xpra.gtk.keymap import get_gtk_keymap
        from xpra.codecs.loader import codec_versions, load_codecs, show_codecs
        load_codecs()
        show_codecs()
        try:
            from xpra.audio.wrapper import query_audio

            def get_audio_info() -> typedict:
                return query_audio()
        except ImportError:
            get_audio_info = None

        def get_gl_info():
            if self.opengl_info:
                return self.opengl_info

        from xpra.net.net_util import get_info as get_net_info
        from xpra.platform.paths import get_info as get_path_info
        from xpra.platform.gui import get_info as get_gui_info
        from xpra.util.version import get_version_info, get_platform_info, get_host_info

        def get_sys_info() -> dict[str, Any]:
            from xpra.platform.info import get_user_info
            from xpra.scripts.config import read_xpra_defaults
            return {
                "argv": sys.argv,
                "path": sys.path,
                "exec_prefix": sys.exec_prefix,
                "executable": sys.executable,
                "version": get_version_info(),
                "platform": get_platform_info(),
                "host": get_host_info(FULL_INFO),
                "paths": get_path_info(),
                "gtk": get_gtk_version_info(),
                "gui": get_gui_info(),
                "display": get_display_info(),
                "user": get_user_info(),
                "env": os.environ,
                "config": read_xpra_defaults(),
            }

        get_screenshot: Callable = noop
        take_screenshot_fn: Callable = noop
        # screenshot: may have OS-specific code
        try:
            from xpra.platform.gui import take_screenshot
            take_screenshot_fn = take_screenshot
        except ImportError:
            log("failed to load platform specific screenshot code", exc_info=True)
        if take_screenshot_fn == noop:
            # try with Pillow:
            take_screenshot_fn = get_pillow_imagegrab_fn()
        if take_screenshot_fn == noop:
            # default: gtk screen capture
            try:
                from xpra.server.shadow.gtk_root_window_model import GTKImageCapture
                rwm = GTKImageCapture(get_default_root_window())
                take_screenshot_fn = rwm.take_screenshot
            except (ImportError, AttributeError):
                log.warn("Warning: failed to load gtk screenshot code", exc_info=True)
        log("take_screenshot_fn=%s", take_screenshot_fn)
        if take_screenshot_fn != noop:
            def _get_screenshot():
                # take_screenshot() returns: w, h, "png", rowstride, data
                return take_screenshot_fn()[4]

            get_screenshot = _get_screenshot

        def get_server_log():
            return self.server_log

        self.toggles = (
            ("system", "txt", "System", get_sys_info, True,
             "Xpra version, platform and host information - including hostname and account information"),
            ("server-log", "txt", "Server Log", get_server_log, bool(self.server_log),
             "Xpra version, platform and host information - including hostname and account information"),
            ("network", "txt", "Network", get_net_info, True,
             "Compression, packet encoding and encryption"),
            ("encoding", "txt", "Encodings", codec_versions, bool(codec_versions),
             "Picture encodings supported"),
            ("opengl", "txt", "OpenGL", get_gl_info, bool(self.opengl_info),
             "OpenGL driver and features"),
            ("audio", "txt", "Audio", get_audio_info, bool(get_audio_info),
             "Audio codecs and GStreamer version information"),
            ("keyboard", "txt", "Keyboard Mapping", get_gtk_keymap, True,
             "Keyboard layout and key mapping"),
            ("xpra-info", "txt", "Server Info", self.get_server_info, bool(self.get_server_info),
             "Full server information from 'xpra info'"),
            ("screenshot", "png", "Screenshot", get_screenshot, bool(get_screenshot),
             ""),
        )
        self.checkboxes = {}
        for name, _, title, value_cb, sensitive, tooltip in self.toggles:
            cb = Gtk.CheckButton(label=title + [" (not available)", ""][bool(value_cb)])
            cb.set_active(self.includes.get(name, True))
            cb.set_sensitive(sensitive)
            cb.set_tooltip_text(tooltip)
            ibox.pack_start(cb)
            self.checkboxes[name] = cb

        # Buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        vbox.pack_start(hbox)

        def btn(text, tooltip_text, callback, icon_name=None) -> Gtk.Button:
            b = Gtk.Button(label=text)
            b.set_tooltip_text(tooltip_text)
            b.connect("clicked", callback)
            if icon_name:
                icon = get_icon_pixbuf(icon_name)
                if icon:
                    b.set_image(scaled_image(icon, 24))
            hbox.pack_start(b)
            return b

        btn("Copy to clipboard", "Copy all data to clipboard", self.copy_clicked, "clipboard.png")
        btn("Save", "Save Bug Report", self.save_clicked, "download.png")
        btn("Cancel", "", self.close, "quit.png")

        def accel_close(*_args) -> None:
            self.close()

        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def set_server_log_data(self, filedata) -> None:
        self.server_log = filedata
        cb = self.checkboxes.get("server-log")
        log("set_server_log_data(%i bytes) cb=%s", len(filedata or b""), cb)
        if cb:
            cb.set_sensitive(bool(filedata))

    def show(self) -> None:
        log("show()")
        if not self.window:
            self.setup_window()
        force_focus()
        self.window.show_all()
        self.window.present()

    def hide(self) -> None:
        log("hide()")
        if self.window:
            self.window.hide()

    def close(self, *_args) -> bool:
        self.hide_window()
        return True

    def hide_window(self) -> None:
        log("hide_window()")
        if self.window:
            self.hide()
            self.window = None

    def destroy(self, *args) -> None:
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None

    @staticmethod
    def run() -> ExitValue:
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")
        return 0

    def quit(self, *args) -> None:
        log("quit%s", args)
        self.hide_window()
        Gtk.main_quit()

    def get_data(self) -> list[tuple[str, str, str, str]]:
        log("get_data() collecting bug report data")
        data = []
        tb = self.description.get_buffer()
        buf = tb.get_text(*tb.get_bounds(), include_hidden_chars=False)
        if buf:
            data.append(("Description", "", "txt", buf))
        for name, dtype, title, value_cb, _, tooltip in self.toggles:
            if not bool(value_cb):
                continue
            cb = self.checkboxes.get(name)
            assert cb is not None
            if not cb.get_active():
                continue
            log("%s is enabled (%s)", name, tooltip)
            # OK, the checkbox is selected, get the data
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
                s = os.linesep.join("%s : %s" % (k.ljust(32), nonl(str(v))) for k, v in sorted(value.items()))
            elif isinstance(value, (list, tuple)):
                s = os.linesep.join(str(x) for x in value)
            else:
                s = value
            log("%s (%s) %s: %s", title, tooltip, dtype, repr_ellipsized(s))
            data.append((title, tooltip, dtype, s))
            time.sleep(STEP_DELAY)
        return data

    def copy_clicked(self, *_args) -> None:
        data = self.get_data()

        def cdata(v) -> str:
            if isinstance(v, bytes):
                return hexstr(v)
            return str(v)

        text = os.linesep.join("%s: %s%s%s%s" % (title, tooltip, os.linesep, cdata(v), os.linesep)
                               for (title, tooltip, dtype, v) in data if dtype == "txt")
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, len(text))
        log.info("%s characters copied to clipboard", len(text))

    def save_clicked(self, *_args) -> None:
        file_filter = Gtk.FileFilter()
        file_filter.set_name("ZIP")
        file_filter.add_pattern("*.zip")
        choose_file(self.window, "Save Bug Report Data", Gtk.FileChooserAction.SAVE, Gtk.STOCK_SAVE, self.do_save)

    def do_save(self, filename: str) -> None:
        log("do_save(%s)", filename)
        if not filename.lower().endswith(".zip"):
            filename = filename + ".zip"
        basenoext = os.path.splitext(os.path.basename(filename))[0]
        data = self.get_data()
        import zipfile
        zf = None
        try:
            zf = zipfile.ZipFile(filename, mode='w', compression=zipfile.ZIP_DEFLATED)
            for title, tooltip, dtype, s in data:
                cfile = os.path.join(basenoext, title.replace(" ", "_") + "." + dtype)
                # noinspection PyTypeChecker
                info = zipfile.ZipInfo(cfile, date_time=tuple(time.localtime(time.time())))
                info.compress_type = zipfile.ZIP_DEFLATED
                # very poorly documented:
                info.external_attr = 0o644 << 16
                info.comment = str(tooltip).encode("utf8")
                if isinstance(s, bytes):
                    rm: str = ""
                    try:
                        try:
                            import tempfile
                            temp = tempfile.NamedTemporaryFile(prefix="xpra.", suffix=".%s" % dtype, delete=False)
                            rm = temp.name
                            with temp:
                                temp.write(s)
                                temp.flush()
                        except OSError as e:
                            log.error("Error: cannot create mmap file:")
                            log.estr(e)
                        else:
                            zf.write(temp.name, cfile, zipfile.ZIP_STORED if dtype == "png" else zipfile.ZIP_DEFLATED)
                    finally:
                        if rm:
                            os.unlink(rm)
                else:
                    zf.writestr(info, str(s))
        except OSError as e:
            log("do_save(%s) failed to save zip file", filename, exc_info=True)
            dialog = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.CLOSE, "Failed to save ZIP file")
            dialog.format_secondary_text("%s" % e)

            def close(*_args) -> None:
                dialog.close()

            dialog.connect("response", close)
            dialog.show_all()
        finally:
            if zf:
                zf.close()


def main(argv=()) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.platform.gui import init, set_default_icon
    from xpra.gtk.util import init_display_source
    with program_context("Xpra-Bug-Report", "Xpra Bug Report"):
        from xpra.log import enable_color
        enable_color()
        init_display_source()
        set_default_icon("bugs.png")
        init()

        from xpra.log import enable_debug_for
        if "-v" in argv:
            enable_debug_for("util")

        from xpra.gtk.signals import register_os_signals
        app = BugReport()
        app.close = app.quit
        app.init(True)
        register_os_signals(app.quit, "Bug Report")
        try:
            from xpra.platform.gui import ready as gui_ready
            gui_ready()
            app.show()
            app.run()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
