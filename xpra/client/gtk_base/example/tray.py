#!/usr/bin/env python
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#test application for tray and menu

from xpra.gtk_common.gobject_compat import import_gtk, import_glib, is_gtk3
from xpra.gtk_common.gtk_util import scaled_image, pixbuf_new_from_file
from xpra.platform.gui import get_native_tray_menu_helper_class, get_native_tray_classes
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("client")

gtk = import_gtk()
glib = import_glib()


class FakeApplication:

    def __init__(self):
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove
        self.session_name = "Test System Tray"
        self.mmap_enabled = False
        self.windows_enabled = True
        self.readonly = False
        self.server_readonly = False
        self.server_client_shutdown = True
        self.server_sharing = True
        self.server_sharing_toggle = True
        self.server_lock = True
        self.server_lock_toggle = True
        self.server_av_sync = True
        self.server_virtual_video_devices = 4
        self.server_webcam = True
        self.server_sound_send = True
        self.server_sound_receive = True
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
        try:
            if is_gtk3():
                from xpra.client.gtk3.tray_menu import GTK3TrayMenu as GTKTrayMenu
            else:
                from xpra.client.gtk2.tray_menu import GTK2TrayMenu as GTKTrayMenu
        except ImportError as e:
            log.warn("failed to load GTK tray menu class: %s", e)
        for x in (get_native_tray_menu_helper_class(), GTKTrayMenu):
            if x:
                try:
                    self.menu_helper = x(self)
                except Exception as e:
                    log.warn("failed to create menu helper %s: %s", x, e)
        assert self.menu_helper
        menu = self.menu_helper.build()
        try:
            from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
        except ImportError:
            GTKStatusIconTray = None
        for x in (get_native_tray_classes()+[GTKStatusIconTray]):
            if x:
                try:
                    XPRA_APP_ID = 0
                    tray_icon_filename = "xpra"
                    self.tray = x(self, XPRA_APP_ID, menu, "Test System Tray", tray_icon_filename,
                                  self.xpra_tray_geometry, self.xpra_tray_click,
                                  self.xpra_tray_mouseover, self.xpra_tray_exit)
                except Exception as e:
                    log.warn("failed to create tray %s: %s", x, e)
        self.tray.set_tooltip("Test System Tray")

    def after_handshake(self, cb, *args):
        self.idle_add(cb, *args)

    def on_server_setting_changed(self, setting, cb):
        pass

    def connect(self, *args):
        pass

    def get_encodings(self):
        from xpra.codecs.codec_constants import PREFERED_ENCODING_ORDER
        return PREFERED_ENCODING_ORDER

    def show_start_new_command(self, *_args):
        pass
    def show_server_commands(self, *_args):
        pass
    def show_ask_data_dialog(self, *_args):
        pass
    def show_file_upload(self, *_args):
        pass

    def send_sharing_enabled(self, *_args):
        pass


    def get_image(self, icon_name, size=None):
        try:
            if not icon_name:
                return None
            icon_filename = get_icon_filename(icon_name)
            if not icon_filename:
                return None
            pixbuf = pixbuf_new_from_file(icon_filename)
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except Exception:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return None


    def xpra_tray_click(self, button, pressed, time=0):
        log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
        if button==1 and pressed:
            self.idle_add(self.menu_helper.activate, button, time)
        elif button==3 and not pressed:
            self.idle_add(self.menu_helper.popup, button, time)

    def xpra_tray_mouseover(self, *args):
        log("xpra_tray_mouseover(%s)", args)

    def xpra_tray_exit(self, *args):
        log("xpra_tray_exit%s", args)
        gtk.main_quit()

    def xpra_tray_geometry(self, *args):
        log("xpra_tray_geometry%s geometry=%s", args, self.tray.get_geometry())



def main():
    import signal
    def signal_handler(*_args):
        gtk.main_quit()
    signal.signal(signal.SIGINT, signal_handler)
    FakeApplication()
    gtk.main()


if __name__ == "__main__":
    main()
