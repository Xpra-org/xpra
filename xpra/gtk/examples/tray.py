#!/usr/bin/env python3
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.systray import get_backends, get_menu_helper_class
from xpra.platform.paths import get_icon_filename
from xpra.client.gui.fake_client import FakeClient
from xpra.gtk.widget import scaled_image
from xpra.common import noop
from xpra.util.objects import AdHocStruct
from xpra.log import Logger, consume_verbose_argv

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("client")


def struct(**kwargs):
    obj = AdHocStruct()
    obj.__dict__.update(kwargs)
    return obj


class FakeApplication(FakeClient):

    def __init__(self):
        super().__init__()
        self._subsystems = {}
        self.display_desc = {}
        self.session_name = "Test System Tray"
        self.server_session_name = ""
        self.windows_enabled = True
        self.modal_windows = False
        self.server_bell = False
        self.server_client_shutdown = True
        self.server_sharing = True
        self.server_sharing_toggle = True
        self.server_lock = True
        self.server_lock_toggle = True
        self.client_supports_sharing = True
        self.client_lock = False
        self.remote_file_transfer = True
        self.remote_file_transfer_ask = True
        self._remote_subcommands = ()
        self.remote_printing_ask = False
        self.remote_open_files_ask = False
        self.remote_open_url_ask = False
        self._remote_server_log = ""
        self.client_supports_system_tray = True
        self.init_fake_subsystems()
        classes = [get_menu_helper_class()]
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
        tray_classes = list(get_backends())
        try:
            from xpra.gtk.statusicon_tray import GTKStatusIconTray
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
        self._subsystems["tray"] = self.tray
        self.tray.set_tooltip("Test System Tray")

    def init_fake_subsystems(self) -> None:
        self.server_bell = False
        self.client_supports_bell = True
        self.bell_enabled = False
        self.wheel_map = {
            4: 4,
            5: 5,
        }

        opengl = struct(
            enabled=False,
            client_supports=True,
            properties={},
        )
        command = struct(
            server_start_new_commands=True,
            server_commands_info=None,
            server_commands_signals=(),
            start_new_commands=False,
            server_menu=False,
            send_start_command=noop,
        )
        display = struct(
            can_scale=True,
            xscale=1.0,
            yscale=1.0,
            server_multi_monitors=False,
            server_monitors={},
            server_add_monitor_label="",
            server_new_monitor_resolutions=(),
        )
        display.scaleset = lambda xscale, yscale: self.set_scaling(display, xscale, yscale)
        display.cp = lambda x, y: (round(x * display.xscale), round(y * display.yscale))

        encoding = struct(
            encoding="png",
            quality=80,
            min_quality=-1,
            speed=50,
            min_speed=-1,
            server_encodings=["png", "rgb"],
            server_encodings_with_quality=[],
            server_encodings_with_speed=[],
            server_encodings_with_lossless_mode=[],
            get_encodings=self.get_encodings,
            get_core_encodings=self.get_encodings,
            send_quality=noop,
            send_min_quality=noop,
            send_speed=noop,
            send_min_speed=noop,
        )
        encoding.set_encoding = lambda enc: self.set_encoding(encoding, enc)

        audio = struct(
            speaker_allowed=True,
            speaker_enabled=True,
            microphone_allowed=True,
            microphone_enabled=True,
            server_send=True,
            server_receive=True,
            av_sync=True,
            av_sync_delta=0,
            server_av_sync=True,
            send_audio_sync=noop,
        )
        audio.start_receiving_audio = lambda: self.set_audio_enabled(audio, "speaker_enabled", True)
        audio.stop_receiving_audio = lambda: self.set_audio_enabled(audio, "speaker_enabled", False)
        audio.start_sending_audio = lambda: self.set_audio_enabled(audio, "microphone_enabled", True)
        audio.stop_sending_audio = lambda: self.set_audio_enabled(audio, "microphone_enabled", False)

        webcam = struct(
            server_enabled=True,
            forwarding=True,
            device=None,
            device_no=-1,
        )
        webcam.start_sending_webcam = lambda device_no=0, device="": self.set_webcam_device(webcam, device_no, device)
        webcam.stop_sending_webcam = lambda: self.set_webcam_device(webcam, -1, None)

        self._subsystems.update({
            "audio": audio,
            "bandwidth": struct(
                server_limit=0,
                limit=0,
                send_limit=noop,
            ),
            "clipboard": struct(
                server_clipboard=False,
                client_supports_clipboard=True,
                clipboard_enabled=True,
                clipboard_helper=None,
                client_clipboard_direction="both",
                send_clipboard_selections=noop,
                emit=noop,
            ),
            "command": command,
            "cursor": struct(
                server_enabled=False,
                client_supports=True,
                enabled=True,
                default_data=None,
                reset_cursor=noop,
            ),
            "display": display,
            "encoding": encoding,
            "keyboard": struct(helper=None),
            "notification": struct(
                client_supports=True,
                enabled=False,
            ),
            "opengl": opengl,
            "webcam": webcam,
            "window": self,
        })

    def get_subsystem(self, name: str):
        return self._subsystems.get(name)

    @staticmethod
    def set_scaling(display, xscale: float, yscale: float) -> None:
        display.xscale = xscale
        display.yscale = yscale

    @staticmethod
    def set_encoding(encoding, value: str) -> None:
        encoding.encoding = value

    @staticmethod
    def set_audio_enabled(audio, name: str, enabled: bool) -> None:
        setattr(audio, name, enabled)

    @staticmethod
    def set_webcam_device(webcam, device_no: int, device) -> None:
        webcam.device_no = device_no
        webcam.device = device

    def set_bell_enabled(self, enabled: bool) -> None:
        self.bell_enabled = enabled

    def send_refresh_all(self, *_args) -> None:
        log("send_refresh_all ignored")

    def reinit_windows(self, *_args) -> None:
        log("reinit_windows ignored")

    def reinit_window_icons(self, *_args) -> None:
        log("reinit_window_icons ignored")

    def after_handshake(self, cb: Callable, *args) -> None:
        GLib.idle_add(cb, *args)

    def on_server_setting_changed(self, setting: str, cb: Callable) -> None:
        """ this method is part of the GUI client "interface" """

    def connect(self, *args) -> None:
        """ this method is part of the GUI client "interface" """

    def get_encodings(self) -> Sequence[str]:
        from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
        return PREFERRED_ENCODING_ORDER

    def show_start_new_command(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def show_server_commands(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def show_ask_data_dialog(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def show_file_upload(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_sharing_enabled(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_lock_enabled(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_notify_enabled(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_cursors_enabled(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_remove_monitor(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_add_monitor(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_shutdown_server(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def configure_server_debug(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def download_server_log(self, *_args) -> None:
        """ this method is part of the GUI client "interface" """

    def send_download_request(self, *_args) -> None:
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

    def xpra_tray_click(self, button: int, pressed: bool, time: int = 0) -> None:
        log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
        if button == 1 and pressed:
            GLib.idle_add(self.menu_helper.activate, button, time)
        elif button == 3 and not pressed:
            GLib.idle_add(self.menu_helper.popup, button, time)

    def xpra_tray_mouseover(self, *args) -> None:
        log("xpra_tray_mouseover(%s)", args)

    def xpra_tray_exit(self, *args) -> None:
        log("xpra_tray_exit%s", args)
        Gtk.main_quit()

    def xpra_tray_geometry(self, *args) -> None:
        log("xpra_tray_geometry%s geometry=%s", args, self.tray.get_geometry())

    def disconnect_and_quit(self, *_args) -> None:
        Gtk.main_quit()


def main(argv: list[str]) -> int:
    with program_context("tray", "Tray"):
        consume_verbose_argv(argv, "all")
        from xpra.util.system import is_X11
        if is_X11():
            from xpra.gtk.util import init_display_source
            init_display_source(False)
        from xpra.gtk.util import quit_on_signals, gtk_main
        quit_on_signals("tray test")
        FakeApplication()
        gtk_main()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
