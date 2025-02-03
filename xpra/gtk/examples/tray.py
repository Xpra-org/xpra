#!/usr/bin/env python3
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import get_native_tray_menu_helper_class, get_native_tray_classes
from xpra.platform.paths import get_icon_filename
from xpra.gtk.widget import scaled_image
from xpra.common import noop
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("client")


class FakeApplication:

    def __init__(self):
        self.display_desc = {}
        self.session_name = "Test System Tray"
        self.windows_enabled = True
        self.readonly = False
        self.opengl_enabled = False
        self.modal_windows = False
        self.server_bell = False
        self.server_cursors = False
        self.server_readonly = False
        self.server_client_shutdown = True
        self.server_sharing = True
        self.server_sharing_toggle = True
        self.server_lock = True
        self.server_lock_toggle = True
        self.server_av_sync = True
        self.server_virtual_video_devices = 4
        self.server_webcam = True
        self.server_audio_send = True
        self.server_audio_receive = True
        self.server_clipboard = False
        self.server_encodings = ["png", "rgb"]
        self.server_encodings_with_quality = []
        self.server_encodings_with_speed = []
        self.server_start_new_commands = True
        self.server_xdg_menu = False
        self.server_commands_info = None
        self.server_multi_monitors = False
        self.server_bandwidth_limit = 0
        self.server_monitors = {}
        self.bandwidth_limit = 0
        self.speaker_allowed = True
        self.speaker_enabled = True
        self.microphone_enabled = True
        self.microphone_allowed = True
        self.client_supports_opengl = True
        self.client_supports_notifications = True
        self.client_supports_system_tray = True
        self.client_supports_clipboard = True
        self.client_supports_cursors = True
        self.client_supports_bell = True
        self.client_supports_sharing = True
        self.client_lock = False
        self.download_server_log = None
        self.remote_file_transfer = True
        self.remote_file_transfer_ask = True
        self.notifications_enabled = False
        self.client_clipboard_direction = "both"
        self.clipboard_enabled = True
        self.cursors_enabled = True
        self.default_cursor_data = None
        self.bell_enabled = False
        self.keyboard_helper = None
        self.av_sync = True
        self.webcam_forwarding = True
        self.webcam_device = None
        self.can_scale = True
        self.xscale = 1.0
        self.yscale = 1.0
        self.quality = 80
        self.speed = 50
        self.encoding = "png"
        self.send_download_request = None
        self._remote_subcommands = ()
        self._process_encodings = noop
        self._window_to_id = {}
        self.remote_printing_ask = False
        self.remote_open_files_ask = False
        self.remote_open_url_ask = False
        self._remote_server_log = ""
        self.start_new_commands = False
        classes = [get_native_tray_menu_helper_class()]
        try:
            from xpra.client.gtk3.tray_menu import GTKTrayMenu
            classes.append(GTKTrayMenu)
        except ImportError as e:
            log.warn("failed to load GTK tray menu class: %s", e)
        for hclass in classes:
            if hclass:
                try:
                    self.menu_helper = hclass(self)
                except Exception as e:
                    log.warn("failed to create menu helper %s: %s", hclass, e)
        assert self.menu_helper
        menu = self.menu_helper.build()
        tray_classes = list(get_native_tray_classes())
        try:
            from xpra.client.gtk3.statusicon_tray import GTKStatusIconTray
            tray_classes.append(GTKStatusIconTray)
        except ImportError:
            log("no StatusIcon tray")
        for tray_class in tray_classes:
            try:
                xpra_app_id = 0
                tray_icon_filename = "xpra"
                self.tray = tray_class(self, xpra_app_id, menu, "Test System Tray", tray_icon_filename,
                                       self.xpra_tray_geometry, self.xpra_tray_click,
                                       self.xpra_tray_mouseover, self.xpra_tray_exit)
            except Exception as e:
                log.warn("failed to create tray %s: %s", tray_class, e)
        self.tray.set_tooltip("Test System Tray")

    def after_handshake(self, cb: Callable, *args) -> None:
        GLib.idle_add(cb, *args)

    def on_server_setting_changed(self, setting: str, cb: Callable) -> None:
        """ this method is part of the GUI client "interface" """

    def connect(self, *args) -> None:
        """ this method is part of the GUI client "interface" """

    def get_encodings(self) -> Sequence[str]:
        from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
        return PREFERRED_ENCODING_ORDER

    def show_start_new_command(self, *_args):
        """ this method is part of the GUI client "interface" """

    def show_server_commands(self, *_args):
        """ this method is part of the GUI client "interface" """

    def show_ask_data_dialog(self, *_args):
        """ this method is part of the GUI client "interface" """

    def show_file_upload(self, *_args):
        """ this method is part of the GUI client "interface" """

    def send_sharing_enabled(self, *_args):
        """ this method is part of the GUI client "interface" """

    def get_image(self, icon_name: str, size=None):
        with log.trap_error(f"Error loading image for icon {icon_name!r} and size {size}"):
            if not icon_name:
                return None
            icon_filename = get_icon_filename(icon_name)
            if not icon_filename:
                return None
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(filename=icon_filename)
            if not pixbuf:
                return None
            return scaled_image(pixbuf, size)

    def xpra_tray_click(self, button: int, pressed: bool, time: int = 0):
        log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
        if button == 1 and pressed:
            GLib.idle_add(self.menu_helper.activate, button, time)
        elif button == 3 and not pressed:
            GLib.idle_add(self.menu_helper.popup, button, time)

    def xpra_tray_mouseover(self, *args):
        log("xpra_tray_mouseover(%s)", args)

    def xpra_tray_exit(self, *args):
        log("xpra_tray_exit%s", args)
        Gtk.main_quit()

    def xpra_tray_geometry(self, *args):
        log("xpra_tray_geometry%s geometry=%s", args, self.tray.get_geometry())

    def disconnect_and_quit(self, *_args):
        Gtk.main_quit()


def main() -> int:
    with program_context("tray", "Tray"):
        from xpra.util.system import is_X11
        if is_X11():
            from xpra.x11.gtk.display_source import init_gdk_display_source
            init_gdk_display_source()
        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("tray test")
        FakeApplication()
        Gtk.main()
    return 0


if __name__ == "__main__":
    main()
