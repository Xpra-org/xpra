# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import weakref
from time import monotonic
from importlib import import_module
from collections.abc import Callable, Sequence, Iterable
from subprocess import Popen, PIPE
from threading import Event
from typing import Any

from xpra.common import noop, MIN_VREFRESH, MAX_VREFRESH, BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, repr_ellipsized, pver, bytestostr, hexstr, memoryview_to_bytes
from xpra.util.env import envint, envbool, osexpand, first_time, IgnoreWarningsContext, ignorewarnings
from xpra.util.child_reaper import get_child_reaper
from xpra.os_util import gi_import, WIN32, OSX, POSIX
from xpra.util.system import is_Wayland
from xpra.util.io import load_binary_file
from xpra.net.common import Packet
from xpra.common import FULL_INFO, VIDEO_MAX_SIZE, NotificationID, DEFAULT_METADATA_SUPPORTED, noerr
from xpra.util.stats import std_unit
from xpra.scripts.config import InitExit
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.gtk.cursors import cursor_types, get_default_cursor
from xpra.gtk.util import get_default_root_window, get_root_size, GRAB_STATUS_STRING, init_display_source
from xpra.gtk.window import GDKWindow
from xpra.gtk.info import get_monitors_info, get_screen_sizes, get_average_monitor_refresh_rate
from xpra.gtk.widget import scaled_image, label, FILE_CHOOSER_NATIVE
from xpra.gtk.pixbuf import get_icon_pixbuf, get_pixbuf_from_data
from xpra.gtk.versions import get_gtk_version_info
from xpra.exit_codes import ExitCode, ExitValue
from xpra.util.gobject import no_arg_signal
from xpra.gtk.css_overrides import inject_css_overrides
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.client.base.gobject import GObjectXpraClient
from xpra.client.gtk3.keyboard_helper import GTKKeyboardHelper
from xpra.platform.gui import force_focus
from xpra.platform.gui import (
    get_window_frame_sizes, get_window_frame_size,
    system_bell, get_wm_name, get_fixed_cursor_size,
)
from xpra.log import Logger

log = Logger("gtk", "client")
opengllog = Logger("gtk", "opengl")
cursorlog = Logger("gtk", "client", "cursor")
framelog = Logger("gtk", "client", "frame")
filelog = Logger("gtk", "client", "file")
clipboardlog = Logger("gtk", "client", "clipboard")
grablog = Logger("client", "grab")
focuslog = Logger("client", "focus")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")

missing_cursor_names = set()

METADATA_SUPPORTED = os.environ.get("XPRA_METADATA_SUPPORTED", "")
# on win32, the named cursors work, but they are hard to see
# when using the Adwaita theme
USE_LOCAL_CURSORS = envbool("XPRA_USE_LOCAL_CURSORS", not WIN32 and not is_Wayland())
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)
CLIPBOARD_NOTIFY = envbool("XPRA_CLIPBOARD_NOTIFY", True)
OPENGL_MIN_SIZE = envint("XPRA_OPENGL_MIN_SIZE", 32)
NO_OPENGL_WINDOW_TYPES = os.environ.get(
    "XPRA_NO_OPENGL_WINDOW_TYPES",
    "DOCK,TOOLBAR,MENU,UTILITY,SPLASH,DROPDOWN_MENU,POPUP_MENU,TOOLTIP,NOTIFICATION,COMBO,DND"
).split(",")
WINDOW_GROUPING = os.environ.get("XPRA_WINDOW_GROUPING", "group-leader-xid,class-instance,pid,command").split(",")

VREFRESH = envint("XPRA_VREFRESH", 0)

inject_css_overrides()
init_display_source(False)
# must come after init_display_source()
from xpra.client.gtk3.window.base import HAS_X11_BINDINGS  # noqa: E402


def get_local_cursor(cursor_name: str):
    display = Gdk.Display.get_default()
    if not cursor_name or not display:
        return None
    try:
        cursor = Gdk.Cursor.new_from_name(display, cursor_name)
    except TypeError:
        cursorlog("Gdk.Cursor.new_from_name%s", (display, cursor_name), exc_info=True)
        cursor = None
    if cursor:
        cursorlog("Gdk.Cursor.new_from_name(%s, %s)=%s", display, cursor_name, cursor)
    else:
        gdk_cursor = cursor_types.get(cursor_name.upper())
        cursorlog("gdk_cursor(%s)=%s", cursor_name, gdk_cursor)
        if gdk_cursor:
            try:
                cursor = Gdk.Cursor.new_for_display(display, gdk_cursor)
                cursorlog("Cursor.new_for_display(%s, %s)=%s", display, gdk_cursor, cursor)
            except TypeError as e:
                log("new_Cursor_for_display(%s, %s)", display, gdk_cursor, exc_info=True)
                if first_time("cursor:%s" % cursor_name.upper()):
                    log.error("Error creating cursor %s: %s", cursor_name.upper(), e)
    if cursor:
        pixbuf = cursor.get_image()
        cursorlog("image=%s", pixbuf)
        return pixbuf
    if cursor_name not in missing_cursor_names:
        cursorlog("cursor name '%s' not found", cursor_name)
        missing_cursor_names.add(cursor_name)
    return None


def get_group_ref(metadata: dict) -> str:
    # ie: refs="group-leader-xid" or "pid+class-instance"
    for ref_str in WINDOW_GROUPING:
        refs = ref_str.split(".")
        # ie: ["pid", "class-instance"]
        if not all(ref in metadata for ref in refs):
            continue
        group_refs = []
        for ref in refs:
            value = metadata[ref]
            if isinstance(value, Iterable):
                group_refs.append(f"{ref}:{csv(value)}")
            group_refs.append(f"{ref}:{value}")
        # ie: "pid=10,class-instance=foo"
        return ",".join(group_refs)
    return ""


# noinspection PyMethodMayBeStatic
class GTKXpraClient(GObjectXpraClient, UIXpraClient):
    __gsignals__ = {}
    # add signals from super classes (all no-arg signals)
    for signal_name in UIXpraClient.__signals__:
        __gsignals__[signal_name] = no_arg_signal

    ClientWindowClass: type | None = None
    GLClientWindowClass: type | None = None

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.client_type = "Python/GTK3"
        self.pinentry_proc = None
        self.sub_dialogs = {}
        self.menu_helper = None
        self.window_menu_helper = None
        self.keyboard_helper_class = GTKKeyboardHelper
        self.data_send_requests = {}
        # clipboard bits:
        self.clipboard_notification_timer = 0
        self.last_clipboard_notification = 0
        # opengl bits:
        self.client_supports_opengl = False
        self.opengl_force = False
        self.opengl_enabled = False
        self.opengl_props = {}
        self.gl_max_viewport_dims = 0, 0
        self.gl_texture_size_limit = 0
        self._cursors = weakref.WeakKeyDictionary()
        # frame request hidden window:
        self.frame_request_window = None
        # group leader bits:
        self._ref_to_group_leader = {}
        self._group_leader_wids = {}
        self._window_with_grab = 0
        self.video_max_size = VIDEO_MAX_SIZE
        try:
            self.connect("scaling-changed", self.reset_windows_cursors)
        except TypeError:
            log("no 'scaling-changed' signal")

    def init(self, opts) -> None:
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)

    def setup_frame_request_windows(self) -> None:
        # query the window manager to get the frame size:
        from xpra.x11.error import xsync
        from xpra.x11.bindings.send_wm import send_wm_request_frame_extents
        self.frame_request_window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.frame_request_window.set_title("Xpra-FRAME_EXTENTS")
        self.frame_request_window.realize()
        win = self.frame_request_window.get_window()
        xid = win.get_xid()
        framelog("setup_frame_request_windows() window=%#x", xid)
        with xsync:
            root_xid = self.get_root_xid()
            send_wm_request_frame_extents(root_xid, xid)

    def get_menu_helper(self):
        """
        menu helper used by our tray (make_tray / setup_xpra_tray)
        and for showing the menu on windows via a shortcut,
        """
        if not self.menu_helper:
            from xpra.platform.systray import get_menu_helper_class
            from xpra.client.gtk3.tray_menu import GTKTrayMenu
            from xpra.util.objects import make_instance
            mhc = (get_menu_helper_class(), GTKTrayMenu)
            log("get_menu_helper() tray menu helper classes: %s", mhc)
            self.menu_helper = make_instance(mhc, self)
        return self.menu_helper

    def get_window_menu_helper(self):
        if not self.window_menu_helper:
            from xpra.client.gtk3.tray_menu import GTKTrayMenu
            from xpra.util.objects import make_instance
            mhc = (GTKTrayMenu, )
            log("get_window_menu_helper() tray menu helper classes: %s", mhc)
            self.window_menu_helper = make_instance(mhc, self)
        return self.window_menu_helper

    def run(self) -> ExitValue:
        log(f"run() HAS_X11_BINDINGS={HAS_X11_BINDINGS}")
        from xpra.client.base import features
        if features.window:
            # call this once early:
            ignorewarnings(self.get_mouse_position)
            if HAS_X11_BINDINGS:
                self.setup_frame_request_windows()
        UIXpraClient.run(self)
        self.gtk_main()
        log(f"GTKXpraClient.run_main_loop() main loop ended, returning exit_code={self.exit_code}", )
        if self.exit_code is not None:
            return self.exit_code
        return ExitCode.OK

    def gtk_main(self) -> None:
        log(f"GTKXpraClient.gtk_main() calling {Gtk.main}", )
        Gtk.main()
        log("GTKXpraClient.gtk_main() ended")

    def quit(self, exit_code: ExitValue = 0) -> None:
        log(f"GTKXpraClient.quit({exit_code}) current exit_code={self.exit_code}")
        if self.exit_code is None:
            self.exit_code = exit_code
        if Gtk.main_level() > 0:
            # if for some reason cleanup() hangs, maybe this will fire...
            GLib.timeout_add(4 * 1000, self.exit)
            # try harder!:
            GLib.timeout_add(5 * 1000, self.force_quit, exit_code)
        self.cleanup()
        log(f"GTKXpraClient.quit({exit_code}) cleanup done, main_level={Gtk.main_level()}")
        if Gtk.main_level() > 0:
            log(f"GTKXpraClient.quit({exit_code}) main loop at level {Gtk.main_level()}, calling gtk quit via timeout")
            GLib.timeout_add(500, self.exit)

    def exit(self) -> None:
        self.show_progress(100, "terminating")
        log(f"GTKXpraClient.exit() calling {Gtk.main_quit}", )
        Gtk.main_quit()

    def cleanup(self) -> None:
        log("GTKXpraClient.cleanup()")
        self.stop_pinentry()
        for name, dialog in self.sub_dialogs.items():
            dialog.close()
        self.cancel_clipboard_notification_timer()
        mh = self.menu_helper
        if mh:
            self.menu_helper = None
            mh.cleanup()
        UIXpraClient.cleanup(self)

    def get_raw_vrefresh(self) -> int:
        rate = envint("XPRA_VREFRESH", 0)
        if rate:
            return rate
        # DisplayClient defines this method:
        try:
            rate = super().get_raw_vrefresh()
        except AttributeError:
            log("get_raw_vrefresh() not defined in super class, trying GTK")
            rate = get_average_monitor_refresh_rate()
        if rate < 0:
            return -1
        return max(MIN_VREFRESH, min(MAX_VREFRESH, rate))

    def _process_startup_complete(self, packet: Packet) -> None:
        super()._process_startup_complete(packet)
        Gdk.notify_startup_complete()
        self.remove_packet_handlers("startup-complete")

    def do_process_challenge_prompt(self, prompt="password"):
        self.stop_progress_process(f"showing {prompt} prompt")
        authlog = Logger("auth")
        self.show_progress(100, "authentication")
        PINENTRY = os.environ.get("XPRA_PINENTRY", "")
        from xpra.scripts.pinentry import get_pinentry_command
        pinentry_cmd = get_pinentry_command(PINENTRY)
        authlog(f"do_process_challenge_prompt({prompt}) get_pinentry_command({PINENTRY})={pinentry_cmd}")
        if pinentry_cmd:
            return self.handle_challenge_with_pinentry(prompt, pinentry_cmd)
        return self.process_challenge_prompt_dialog(prompt)

    def stop_pinentry(self) -> None:
        pp = self.pinentry_proc
        if pp:
            self.pinentry_proc = None
            noerr(pp.terminate)
            for fd_name in ("stdin", "stdout", "stderr"):
                fd = getattr(pp, fd_name, None)
                close: Callable = getattr(fd, "close", noop)
                noerr(close)

    def get_server_authentication_string(self) -> str:
        p = self._protocol
        server_type = ""
        if p:
            server_type = {
                "xpra": "Xpra ",
                "rfb": "VNC ",
            }.get(p.TYPE, p.TYPE)
        return f"{server_type}Server Authentication:"

    def handle_challenge_with_pinentry(self, prompt="password", cmd="pinentry") -> str | None:
        # pylint: disable=import-outside-toplevel
        authlog = Logger("auth")
        authlog("handle_challenge_with_pinentry%s", (prompt, cmd))
        try:
            proc = Popen([cmd], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        except OSError:
            authlog("pinentry failed", exc_info=True)
            return self.process_challenge_prompt_dialog(prompt)
        get_child_reaper().add_process(proc, "pinentry", cmd, True, True)
        self.pinentry_proc = proc
        q = f"Enter {prompt}"
        p = self._protocol
        if p:
            conn = getattr(p, "_conn", None)
            if conn:
                from xpra.net.bytestreams import pretty_socket
                cinfo = conn.get_info()
                endpoint = pretty_socket(cinfo.get("endpoint", conn.target)).split("?")[0]
                q += f"\n at {endpoint}"
        title = self.get_server_authentication_string()
        values: list[str] = []
        errs: list[str] = []

        def rec(value=None) -> None:
            values.append(value)

        def err(value=None) -> None:
            errs.append(value)

        from xpra.scripts.pinentry import pinentry_getpin
        pinentry_getpin(proc, title, q, rec, err)
        if not values:
            if errs and errs[0].startswith("ERR 83886179"):
                # ie 'ERR 83886179 Operation cancelled <Pinentry>'
                raise InitExit(ExitCode.PASSWORD_REQUIRED, errs[0][len("ERR 83886179"):])
            return None
        return values[0]

    def process_challenge_prompt_dialog(self, prompt="password") -> str | None:
        # challenge handlers run in a separate 'challenge' thread
        # but we need to run in the UI thread to access the GUI with Gtk
        # so we block the current thread using an event:
        wait = Event()
        values = []
        GLib.idle_add(self.do_process_challenge_prompt_dialog, values, wait, prompt)
        wait.wait()
        if not values:
            return None
        return values[0]

    def do_process_challenge_prompt_dialog(self, values: list, wait: Event, prompt="password") -> None:
        authlog = Logger("auth")
        # pylint: disable=import-outside-toplevel
        title = self.get_server_authentication_string()
        dialog = Gtk.Dialog(title=title,
                            transient_for=None,
                            modal=True,
                            destroy_with_parent=True)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT)

        def add(widget, padding=0) -> None:
            widget.set_halign(Gtk.Align.CENTER)
            widget.set_margin_start(padding)
            widget.set_margin_end(padding)
            widget.set_margin_top(padding)
            widget.set_margin_bottom(padding)
            dialog.vbox.pack_start(widget)

        title = label(title, "sans 14")
        add(title, 16)
        add(label(self.get_challenge_prompt(prompt)), 10)
        password_input = Gtk.Entry()
        password_input.set_max_length(255)
        password_input.set_width_chars(32)
        password_input.set_visibility(False)
        add(password_input, 10)
        dialog.vbox.show_all()
        dialog.password_input = password_input

        def handle_response(dialog, response) -> None:
            if values:
                return
            if OSX:
                from xpra.platform.darwin.gui import disable_focus_workaround
                disable_focus_workaround()
            password = dialog.password_input.get_text()
            dialog.hide()
            dialog.close()
            response_str = {getattr(Gtk.ResponseType, k, ""): k for k in (
                "ACCEPT", "APPLY", "CANCEL", "CLOSE", "DELETE_EVENT", "HELP", "NO", "NONE", "OK", "REJECT", "YES")}
            authlog(f"handle_response({dialog}, {response}) response={response_str.get(response)}")
            if response != Gtk.ResponseType.ACCEPT or not password:
                values.append(None)
                # for those responses, we assume that the user wants to abort authentication:
                if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.REJECT, Gtk.ResponseType.DELETE_EVENT):
                    authlog(f"exiting with response {Gtk.ResponseType(response)}")
                    self.disconnect_and_quit(ExitCode.PASSWORD_REQUIRED, "password entry was cancelled")
            else:
                values.append(password)
            wait.set()

        def password_activate(*_args) -> None:
            handle_response(dialog, Gtk.ResponseType.ACCEPT)

        password_input.connect("activate", password_activate)
        dialog.connect("response", handle_response)
        if OSX:
            from xpra.platform.darwin.gui import enable_focus_workaround
            enable_focus_workaround()
        authlog("showing challenge prompt dialog")
        dialog.show()

    def show_server_commands(self, *_args) -> None:
        sci = getattr(self, "server_commands_info", False)
        if not sci:
            log.warn("Warning: cannot show server commands")
            log.warn(" the feature is not available")
            return
        dialog = self.sub_dialogs.get("server-commands")
        if not dialog:
            from xpra.gtk.dialogs.server_commands import get_server_commands_window
            dialog = get_server_commands_window(self)
            self.sub_dialogs["server-commands"] = dialog
        dialog.show()

    def show_start_new_command(self, *args) -> None:
        ssnc = getattr(self, "server_start_new_commands", False)
        if not ssnc:
            log.warn("Warning: cannot start new commands")
            log.warn(" the feature is not available")
            return
        dialog = self.sub_dialogs.get("start-new-command")
        log(f"show_start_new_command{args} current {dialog=}, flag={self.server_start_new_commands}")
        if not dialog:
            log("server_menu=%s", Ellipsizer(self.server_menu))
            from xpra.gtk.dialogs.start_new_command import get_start_new_command_gui

            def run_command_cb(command, sharing=True) -> None:
                self.send_start_command(command, shlex.split(command), False, sharing)

            dialog = get_start_new_command_gui(run_command_cb, self.server_sharing, self.server_menu)
            self.sub_dialogs["start-new-command"] = dialog
        dialog.show()

    ################################
    # monitors
    def send_remove_monitor(self, index) -> None:
        assert self.server_monitors
        self.send("configure-monitor", "remove", "index", index)

    def send_add_monitor(self, resolution="1024x768") -> None:
        assert self.server_monitors
        self.send("configure-monitor", "add", resolution)

    ################################
    # file handling
    def ask_data_request(self, cb_answer, send_id, dtype: str, url: str, filesize: int,
                         printit: bool, openit: bool) -> None:
        GLib.idle_add(self.do_ask_data_request, cb_answer, send_id, dtype, url, filesize, printit, openit)

    def do_ask_data_request(self, cb_answer, send_id, dtype: str, url: str, filesize: int,
                            printit: bool, openit: bool) -> None:
        from xpra.gtk.dialogs.open_requests import getOpenRequestsWindow
        timeout = self.remote_file_ask_timeout

        def rec_answer(accept, newopenit: bool=openit) -> None:
            from xpra.net.file_transfer import ACCEPT
            if int(accept) == ACCEPT:
                # record our response, so we will actually accept the file when the packets arrive:
                self.data_send_requests[send_id] = (dtype, url, printit, newopenit)
            cb_answer(accept)

        dialog = getOpenRequestsWindow(self.show_file_upload, self.cancel_download)
        dialog.add_request(rec_answer, send_id, dtype, url, filesize, printit, openit, timeout)
        dialog.show()
        self.sub_dialogs["ask-data"] = dialog

    def show_ask_data_dialog(self, *_args) -> None:
        from xpra.gtk.dialogs.open_requests import getOpenRequestsWindow
        dialog = getOpenRequestsWindow(self.show_file_upload, self.cancel_download)
        dialog.show()
        self.sub_dialogs["ask-data"] = dialog

    def transfer_progress_update(self, send=True, transfer_id=0, elapsed=0, position=0, total=0, error=None) -> None:
        fad = self.sub_dialogs.get("ask-data")
        if fad:
            GLib.idle_add(fad.transfer_progress_update, send, transfer_id, elapsed, position, total, error)

    def accept_data(self, send_id, dtype: str, url: str, printit: bool, openit: bool) -> tuple[bool, bool, bool]:
        # check if we have accepted this file via the GUI:
        r = self.data_send_requests.pop(send_id, None)
        if not r:
            filelog(f"accept_data: data send request {send_id} not found")
            from xpra.net.file_transfer import FileTransferHandler
            return FileTransferHandler.accept_data(self, send_id, dtype, url, printit, openit)
        edtype = r[0]
        eurl = r[1]
        if edtype != dtype or eurl != url:
            filelog.warn("Warning: the file attributes are different")
            filelog.warn(" from the ones that were used to accept the transfer")
            s = bytestostr
            if edtype != dtype:
                filelog.warn(" expected data type '%s' but got '%s'", s(edtype), s(dtype))
            if eurl != url:
                filelog.warn(" expected url '%s',", s(eurl))
                filelog.warn("  but got url '%s'", s(url))
            return False, False, False
        # return the printit and openit flag we got from the UI:
        ui_printit = bool(r[2])
        ui_openit = bool(r[3])
        return True, ui_printit, ui_openit

    def close_file_size_warning(self) -> None:
        dialog = self.sub_dialogs.pop("file-size-warning")
        if dialog:
            # close previous warning
            dialog.close()

    def file_size_warning(self, action: str, location: str, basefilename: str, filesize: int, limit: int) -> None:

        parent = None
        msgs = (
            f"Warning: cannot {action} the file {basefilename!r}",
            f"this file is too large: {std_unit(filesize)}B",
            f"the {location} file size limit is {std_unit(limit)}B",
        )
        dialog = Gtk.MessageDialog(transient_for=parent, flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.CLOSE,
                                   text="\n".join(msgs))
        try:
            image = Gtk.Image.new_from_icon_name(Gtk.STOCK_DIALOG_WARNING, Gtk.IconSize.BUTTON)
            dialog.set_image(image)
        except Exception as e:
            log.warn(f"Warning: failed to set dialog image: {e}")
        dialog.connect("response", self.close_file_size_warning)
        dialog.show()

    def download_server_log(self, callback: Callable[[str, int], None] = noop) -> None:
        filename = "${XPRA_SERVER_LOG}"
        self.file_request_callback[filename] = callback
        self.send_request_file(filename, self.open_files)

    def send_download_request(self, *_args) -> None:
        command = ["xpra", "send-file"]
        self.send_start_command("Client-Download-File", command, True)

    def show_file_upload(self, *args) -> None:
        dialog = self.sub_dialogs.get("file-upload")
        if dialog:
            dialog.present()
            return
        filelog(f"show_file_upload{args} can open={self.remote_open_files}")
        buttons = [Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL]
        if self.remote_open_files:
            buttons += [Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT]
        buttons += [Gtk.STOCK_OK, Gtk.ResponseType.OK]
        title = "File to upload"
        if FILE_CHOOSER_NATIVE > 1 or (FILE_CHOOSER_NATIVE and not self.remote_open_files):
            dialog = Gtk.FileChooserNative(title=title, action=Gtk.FileChooserAction.OPEN)
            dialog.set_accept_label("Upload")
        else:
            dialog = Gtk.FileChooserDialog(title=title, action=Gtk.FileChooserAction.OPEN)
            dialog.add_buttons(*buttons)
            dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.connect("response", self.file_upload_dialog_response)
        dialog.show()
        self.sub_dialogs["file-upload"] = dialog

    def file_upload_dialog_response(self, dialog, v) -> None:
        def close_file_upload_dialog() -> None:
            dialog.close()
            self.sub_dialogs.pop("file-upload")

        if v not in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
            filelog(f"dialog response code {v}")
            close_file_upload_dialog()
            return
        filename = dialog.get_filename()
        filelog("file_upload_dialog_response: filename={filename!r}")
        try:
            filesize = os.stat(filename).st_size
        except OSError:
            pass
        else:
            if not self.check_file_size("upload", filename, filesize):
                close_file_upload_dialog()
                return
        gfile = dialog.get_file()
        close_file_upload_dialog()
        filelog(f"load_contents: filename={filename!r}, response={v}")
        cancellable = None
        user_data = (filename, v == Gtk.ResponseType.ACCEPT)
        gfile.load_contents_async(cancellable, self.file_upload_ready, user_data)

    def file_upload_ready(self, gfile, result, user_data):
        filelog("file_upload_ready%s", (gfile, result, user_data))
        filename, openit = user_data
        _, data, entity = gfile.load_contents_finish(result)
        filesize = len(data)
        filelog(f"load_contents_finish({result})=%s", (type(data), filesize, entity))
        if not data:
            log.warn(f"Warning: failed to load file {filename!r}")
            return
        filelog(f"load_contents: filename={filename}, {filesize} bytes, entity={entity}, openit={openit}")
        self.send_file(filename, "", data, filesize=filesize, openit=openit)

    def configure_server_debug(self, *_args) -> None:
        dialog = self.sub_dialogs.get("server-debug")
        if dialog and not dialog.is_closed:
            force_focus()
            dialog.present()
            return

        def enable(category: str) -> None:
            packet_type = "command_request" if BACKWARDS_COMPATIBLE else "control-request"
            self.send(packet_type, "debug", "enable", category)

        def disable(category: str) -> None:
            packet_type = "command_request" if BACKWARDS_COMPATIBLE else "control-request"
            self.send(packet_type, "debug", "disable", category)

        from xpra.gtk.dialogs.debug import DebugConfig
        dialog = DebugConfig("Configure Server Debug Categories",
                             enable=enable, disable=disable)
        dialog.show()
        self.sub_dialogs["server-debug"] = dialog

    def show_about(self, *_args) -> None:
        from xpra.gtk.dialogs.about import about
        force_focus()
        about()

    def show_docs(self, *_args) -> None:
        from xpra.scripts.main import show_docs
        show_docs()

    def show_shortcuts(self, *_args) -> None:
        dialog = self.sub_dialogs.get("shortcuts")
        if dialog and not dialog.is_closed:
            force_focus()
            dialog.present()
            return
        from xpra.gtk.dialogs.show_shortcuts import ShortcutInfo
        kh = self.keyboard_helper
        assert kh, "no keyboard helper"
        dialog = ShortcutInfo(kh.shortcut_modifiers, kh.key_shortcuts)
        dialog.show_all()
        self.sub_dialogs["shortcuts"] = dialog

    def show_session_info(self, *args) -> None:
        dialog = self.sub_dialogs.get("session-info")
        if dialog and not dialog.is_closed:
            # exists already: just raise its window:
            dialog.set_args(*args)
            force_focus()
            dialog.present()
            return
        conn = getattr(self._protocol, "._conn", None)
        from xpra.gtk.dialogs.session_info import SessionInfo
        dialog = SessionInfo(self, self.session_name, conn)
        dialog.set_args(*args)
        force_focus()
        dialog.show_all()
        self.sub_dialogs["session-info"] = dialog

    def show_bug_report(self, *_args) -> None:
        send_info_request = getattr(self, "send_info_request", noop)
        send_info_request()

        dialog = self.sub_dialogs.get("bug-report")
        if dialog:
            force_focus()
            dialog.show()
            return
        from xpra.gtk.dialogs.bug_report import BugReport
        dialog = BugReport()
        self.sub_dialogs["bug-report"] = dialog

        def init_bug_report() -> None:
            # skip things we aren't using:
            includes = {
                "keyboard": bool(self.keyboard_helper),
                "opengl": self.opengl_enabled,
            }

            def get_server_info() -> typedict:
                # the subsystem may not be loaded:
                return getattr(self, "server_last_info", typedict())

            dialog.init(show_about=False, get_server_info=get_server_info,
                        opengl_info=self.opengl_props,
                        includes=includes)
            dialog.show()

        # gives the server time to send an info response..
        # (by the time the user clicks on copy, it should have arrived, we hope!)

        def got_server_log(filename: str, filesize: int) -> None:
            log(f"got_server_log({filename!r}, {filesize})")
            filedata = load_binary_file(filename)
            dialog.set_server_log_data(filedata)

        from xpra.client.base import features
        if features.file:
            self.download_server_log(got_server_log)
        else:
            dialog.set_server_log_data(b"")
        GLib.timeout_add(200, init_bug_report)

    def show_debug_config(self, *_args) -> None:
        dialog = self.sub_dialogs.get("debug-config")
        if not dialog:
            from xpra.gtk.dialogs.debug import DebugConfig
            dialog = DebugConfig()
            self.sub_dialogs["debug-config"] = dialog
        dialog.show()

    def get_image(self, icon_name: str, size=None) -> Gtk.Image | None:
        with log.trap_error(f"Error getting image for icon name {icon_name} and size {size}"):
            pixbuf = get_icon_pixbuf(icon_name)
            log(f"get_image({icon_name!r}, {size}) pixbuf={pixbuf}")
            if not pixbuf:
                return None
            return scaled_image(pixbuf, size)

    def request_frame_extents(self, window) -> None:
        from xpra.x11.bindings.send_wm import send_wm_request_frame_extents
        from xpra.x11.error import xsync
        win = window.get_window()
        xid = win.get_xid()
        framelog(f"request_frame_extents({window}) xid={xid:x}")
        with xsync:
            root_xid = self.get_root_xid()
            send_wm_request_frame_extents(root_xid, xid)

    def get_frame_extents(self, window) -> dict[str, Any]:
        # try native platform code first:
        x, y = window.get_position()
        w, h = window.get_size()
        v = get_window_frame_size(x, y, w, h)  # pylint: disable=assignment-from-none
        framelog(f"get_window_frame_size{(x, y, w, h)}={v}")
        if v:
            # (OSX does give us these values via Quartz API)
            return v
        if not HAS_X11_BINDINGS:
            # nothing more we can do!
            return {}
        from xpra.x11.prop import prop_get
        gdkwin = window.get_window()
        assert gdkwin
        v = prop_get(gdkwin.get_xid(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        framelog(f"get_frame_extents({window.get_title()})={v}")
        if not v:
            return {}
        return {"frame": v}

    def get_window_frame_sizes(self) -> dict[str, Any]:
        wfs = get_window_frame_sizes()
        if self.frame_request_window:
            extents = self.get_frame_extents(self.frame_request_window)
            v = extents.get("frame", ())
            if v:
                try:
                    wm_name = get_wm_name()  # pylint: disable=assignment-from-none
                except Exception:
                    wm_name = ""
                try:
                    if len(v) == 8:
                        if first_time("invalid-frame-extents"):
                            framelog.warn(f"Warning: invalid frame extents value {v!r}")
                            framelog.warn(" expected 8 elements but found %s", len(v))
                            if wm_name:
                                framelog.warn(f" this is probably a bug in {wm_name!r}")
                            framelog.warn(f" using {v[4:]} instead")
                        v = v[4:]
                    if max(abs(value) for value in v) > 256:
                        if first_time("invalid-frame-extents"):
                            framelog.warn(f"Warning: invalid frame extents value {v!r}")
                    else:
                        l, r, t, b = v
                        wfs["frame"] = (l, r, t, b)
                        wfs["offset"] = (l, t)
                except Exception as e:
                    framelog.warn(f"Warning: invalid frame extents value {v!r}")
                    framelog.warn(f" {e}")
                    if wm_name:
                        framelog.warn(f" this is probably a bug in {wm_name!r}")
        framelog(f"get_window_frame_sizes()={wfs}")
        return wfs

    def _add_statusicon_tray(self, tray_classes: list[type]) -> list[type]:
        if not is_Wayland():
            try:
                from xpra.gtk.statusicon_tray import GTKStatusIconTray
                # unlikely to work with gnome:
                PREFER_STATUSICON = envbool("XPRA_PREFER_STATUSICON", False)
                if PREFER_STATUSICON:
                    tray_classes.insert(0, GTKStatusIconTray)
                else:
                    tray_classes.append(GTKStatusIconTray)
            except Exception as e:
                log.warn("Warning: failed to load StatusIcon tray")
                log.warn(" %s", e)
        return tray_classes

    def get_tray_classes(self) -> list[type]:
        from xpra.client.subsystem.tray import TrayClient
        return self._add_statusicon_tray(TrayClient.get_tray_classes(self))

    def get_system_tray_classes(self) -> list[type]:
        from xpra.client.subsystem.window import WindowClient
        return self._add_statusicon_tray(WindowClient.get_system_tray_classes(self))

    def supports_system_tray(self) -> bool:
        #  always True: we can always use Gtk.StatusIcon as fallback
        return True

    def get_root_window(self):
        return get_default_root_window()

    def get_root_xid(self) -> int:
        assert HAS_X11_BINDINGS
        from xpra.x11.bindings.window import X11WindowBindings
        return X11WindowBindings().get_root_xid()

    def get_root_size(self) -> tuple[int, int]:
        return get_root_size()

    def get_raw_mouse_position(self) -> tuple[int, int]:
        root = self.get_root_window()
        if not root:
            return -1, -1
        return root.get_pointer()[-3:-1]

    def get_mouse_position(self) -> tuple[int, int]:
        p = self.get_raw_mouse_position()
        return self.cp(p[0], p[1])

    def get_current_modifiers(self) -> list[str]:
        root = self.get_root_window()
        if root is None:
            return []
        modifiers_mask = root.get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)

    def make_hello(self) -> dict[str, Any]:
        capabilities = UIXpraClient.make_hello(self)
        capabilities["named_cursors"] = len(cursor_types) > 0
        capabilities["encoding.transparency"] = self.has_transparency()
        if FULL_INFO > 1:
            capabilities.setdefault("versions", {}).update(get_gtk_version_info())
        EXPORT_ICON_DATA = envbool("XPRA_EXPORT_ICON_DATA", FULL_INFO > 1)
        if EXPORT_ICON_DATA:
            # tell the server which icons GTK can use
            # so it knows when it should supply one as fallback
            it = Gtk.IconTheme.get_default()
            if it:
                # this would add our bundled icon directory
                # to the search path, but I don't think we have
                # any extra icons that matter in there:
                # from xpra.platform.paths import get_icon_dir
                # d = get_icon_dir()
                # if d not in it.get_search_path():
                #    it.append_search_path(d)
                #    it.rescan_if_needed()
                log(f"default icon theme: {it}")
                log(f"icon search path: {it.get_search_path()}")
                log(f"contexts: {it.list_contexts()}")
                icons = []
                for context in it.list_contexts():
                    icons += it.list_icons(context)
                log(f"icons: {icons}")
                capabilities["theme.default.icons"] = tuple(set(icons))
        if METADATA_SUPPORTED:
            ms = [x.strip() for x in METADATA_SUPPORTED.split(",")]
        else:
            # this is currently unused, and slightly redundant because of metadata.supported below:
            capabilities["window.states"] = [
                "fullscreen", "maximized",
                "sticky", "above", "below",
                "shaded", "iconified",
                "skip-taskbar", "skip-pager",
            ]
            ms = list(DEFAULT_METADATA_SUPPORTED)
            # 4.4:
            ms += ["parent", "relative-position"]
        if POSIX:
            # this is only really supported on X11, but posix is easier to check for..
            # "strut" and maybe even "fullscreen-monitors" could also be supported on other platforms I guess
            ms += ["shaded", "bypass-compositor", "strut", "fullscreen-monitors", "locale"]
        if HAS_X11_BINDINGS:
            ms += ["x11-property", "focused"]
            XSHAPE = envbool("XPRA_XSHAPE", True)
            if XSHAPE:
                ms += ["shape"]
        log("metadata.supported: %s", ms)
        capabilities["metadata.supported"] = ms
        capabilities.setdefault("window", {})["frame_sizes"] = self.get_window_frame_sizes()
        capabilities.setdefault("encoding", {})["icons"] = {
            "greedy": True,  # we don't set a default window icon anymore
            "size": (64, 64),  # size we want
            "max_size": (128, 128),  # limit
        }
        return capabilities

    def has_transparency(self) -> bool:
        if not envbool("XPRA_ALPHA", True):
            return False
        screen = Gdk.Screen.get_default()
        if screen is None:
            return is_Wayland()
        return screen.get_rgba_visual() is not None

    def get_monitors_info(self) -> dict[int, Any]:
        return get_monitors_info(self.xscale, self.yscale)

    def get_screen_sizes(self, xscale=1, yscale=1) -> list[tuple[int, int]]:
        return get_screen_sizes(xscale, yscale)

    def reset_windows_cursors(self, *_args) -> None:
        cursorlog("reset_windows_cursors() resetting cursors for: %s", tuple(self._cursors.keys()))
        for w, cursor_data in tuple(self._cursors.items()):
            self.set_windows_cursor([w], cursor_data)

    def set_windows_cursor(self, windows, cursor_data) -> None:
        cursorlog(f"set_windows_cursor({windows}, args[{len(cursor_data)}])")
        cursor = None
        if cursor_data:
            try:
                cursor = self.make_cursor(cursor_data)
                cursorlog(f"make_cursor(..)={cursor}")
            except Exception as e:
                log.warn("error creating cursor: %s (using default)", e, exc_info=True)
            if cursor is None:
                # use default:
                cursor = get_default_cursor()
        for w in windows:
            w.set_cursor_data(cursor_data)
            # the cursor should only apply to the window contents (aka "drawingarea"),
            # and not the headerbar:
            gtkwin = getattr(w, "drawing_area", w)
            gdkwin = gtkwin.get_window()
            # trays don't have a gdk window
            if gdkwin:
                self._cursors[w] = cursor_data
                gdkwin.set_cursor(cursor)

    def make_cursor(self, cursor_data: Sequence) -> Gdk.Cursor | None:
        # if present, try cursor ny name:
        display = Gdk.Display.get_default()
        if not display:
            return None
        cursorlog("make_cursor(%s) has-name=%s, has-cursor-types=%s, xscale=%s, yscale=%s, USE_LOCAL_CURSORS=%s",
                  Ellipsizer(cursor_data),
                  len(cursor_data) >= 10, bool(cursor_types), self.xscale, self.yscale, USE_LOCAL_CURSORS)
        pixbuf = None
        if len(cursor_data) >= 10 and cursor_types and USE_LOCAL_CURSORS:
            cursor_name = bytestostr(cursor_data[9])
            pixbuf = get_local_cursor(cursor_name)
        # create cursor from the pixel data:
        encoding, _, _, w, h, xhot, yhot, serial, pixels = cursor_data[0:9]
        encoding = bytestostr(encoding)
        if encoding != "raw":
            cursorlog.warn("Warning: invalid cursor encoding: %s", encoding)
            return None
        if not pixbuf:
            if not pixels:
                cursorlog.warn("Warning: no cursor pixel data")
                cursorlog.warn(f" in cursor data {cursor_data}")
                return None
            if len(pixels) < w * h * 4:
                cursorlog.warn("Warning: not enough pixels provided in cursor data")
                cursorlog.warn(" %s needed and only %s bytes found:", w * h * 4, len(pixels))
                cursorlog.warn(" '%s')", repr_ellipsized(hexstr(pixels)))
                return None
            pixbuf = get_pixbuf_from_data(pixels, True, w, h, w * 4)
        else:
            w = pixbuf.get_width()
            h = pixbuf.get_height()
            pixels = pixbuf.get_pixels()
        x = max(0, min(xhot, w - 1))
        y = max(0, min(yhot, h - 1))
        csize = display.get_default_cursor_size()
        cmaxw, cmaxh = display.get_maximal_cursor_size()
        if len(cursor_data) >= 12:
            ssize = cursor_data[10]
            smax = cursor_data[11]
            cursorlog("server cursor sizes: default=%s, max=%s", ssize, smax)
        cursorlog("new %s cursor at %s,%s with serial=%#x, dimensions: %sx%s, len(pixels)=%s",
                  encoding, xhot, yhot, serial, w, h, len(pixels))
        cursorlog("default cursor size is %s, maximum=%s", csize, (cmaxw, cmaxh))
        fw, fh = get_fixed_cursor_size()
        if fw > 0 and fh > 0 and (w != fw or h != fh):
            # OS wants a fixed cursor size! (win32 does, and GTK doesn't do this for us)
            if w <= fw and h <= fh:
                cursorlog("pasting %ix%i cursor to fixed OS size %ix%i", w, h, fw, fh)
                try:
                    from PIL import Image  # @UnresolvedImport pylint: disable=import-outside-toplevel
                except ImportError:
                    return None
                img = Image.frombytes("RGBA", (w, h), memoryview_to_bytes(pixels), "raw", "BGRA", w * 4, 1)
                target = Image.new("RGBA", (fw, fh))
                target.paste(img, (0, 0, w, h))
                pixels = target.tobytes("raw", "BGRA")
                cursor_pixbuf = get_pixbuf_from_data(pixels, True, fw, fh, fw * 4)
            else:
                cursorlog("scaling cursor from %ix%i to fixed OS size %ix%i", w, h, fw, fh)
                cursor_pixbuf = pixbuf.scale_simple(fw, fh, GdkPixbuf.InterpType.BILINEAR)
                xratio, yratio = w / fw, h / fh
                x, y = round(x / xratio), round(y / yratio)
        else:
            sx, sy, sw, sh = x, y, w, h
            # scale the cursors:
            if self.xscale != 1 or self.yscale != 1:
                sx, sy, sw, sh = self.srect(x, y, w, h)
            sw = max(1, sw)
            sh = max(1, sh)
            # ensure we honour the max size if there is one:
            if 0 < cmaxw < sw or 0 < cmaxh < sh:
                ratio = 1.0
                if cmaxw > 0:
                    ratio = max(ratio, w / cmaxw)
                if cmaxh > 0:
                    ratio = max(ratio, h / cmaxh)
                cursorlog("clamping cursor size to %ix%i using ratio=%s", cmaxw, cmaxh, ratio)
                sx, sy = round(x / ratio), round(y / ratio)
                sw, sh = min(cmaxw, round(w / ratio)), min(cmaxh, round(h / ratio))
            if sw != w or sh != h:
                cursorlog("scaling cursor from %ix%i hotspot at %ix%i to %ix%i hotspot at %ix%i",
                          w, h, x, y, sw, sh, sx, sy)
                cursor_pixbuf = pixbuf.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
                x, y = sx, sy
            else:
                cursor_pixbuf = pixbuf
        if SAVE_CURSORS:
            cursor_pixbuf.savev("cursor-%#x.png" % serial, "png", [], [])
        # clamp to pixbuf size:
        w = cursor_pixbuf.get_width()
        h = cursor_pixbuf.get_height()
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        try:
            c = Gdk.Cursor.new_from_pixbuf(display, cursor_pixbuf, x, y)
        except RuntimeError as e:
            log.error("Error: failed to create cursor:")
            log.estr(e)
            log.error(" Gdk.Cursor.new_from_pixbuf%s", (display, cursor_pixbuf, x, y))
            log.error(" using size %ix%i with hotspot at %ix%i", w, h, x, y)
            c = None
        return c

    def process_ui_capabilities(self, caps: typedict) -> None:
        UIXpraClient.process_ui_capabilities(self, caps)
        # this requires the "DisplayClient" mixin:
        if not hasattr(self, "screen_size_changed"):
            return
        # always one screen per display:
        screen = Gdk.Screen.get_default()
        screen.connect("size-changed", self.screen_size_changed)

    def window_grab(self, wid: int, window) -> None:
        event_mask = Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
        event_mask |= Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK
        event_mask |= Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        confine_to = None
        cursor = None
        etime = Gtk.get_current_event_time()
        with IgnoreWarningsContext():
            r = Gdk.pointer_grab(window.get_window(), True, event_mask, confine_to, cursor, etime)
            grablog("pointer_grab(..)=%s", GRAB_STATUS_STRING.get(r, r))
            # also grab the keyboard so the user won't Alt-Tab away:
            r = Gdk.keyboard_grab(window.get_window(), False, etime)
            grablog("keyboard_grab(..)=%s", GRAB_STATUS_STRING.get(r, r))
        self._window_with_grab = wid

    def window_ungrab(self) -> None:
        grablog("window_ungrab()")
        etime = Gtk.get_current_event_time()
        with IgnoreWarningsContext():
            Gdk.pointer_ungrab(etime)
            Gdk.keyboard_ungrab(etime)
        self._window_with_grab = 0

    def window_bell(self, window, device: int, percent: int, pitch: int, duration: int, bell_class,
                    bell_id: int, bell_name: str) -> None:
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = self.get_root_window()
        xid = 0
        if hasattr(gdkwindow, "get_xid"):
            xid = gdkwindow.get_xid()
        log(f"window_bell(..) {gdkwindow=}, {xid=}")
        if not system_bell(xid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
            # fallback to simple beep:
            Gdk.beep()

    def _process_raise_window(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self._id_to_window.get(wid)
        focuslog(f"going to raise window {wid:#x} - {window}")
        if window:
            if window.has_toplevel_focus():
                log("window already has top level focus")
                return
            window.present()

    def _process_restack_window(self, packet: Packet) -> None:
        wid = packet.get_wid()
        detail = packet.get_i8(2)
        other_wid = packet.get_wid(3)
        above = int(detail == 0)
        window = self._id_to_window.get(wid)
        other_window = self._id_to_window.get(other_wid)
        focuslog("restack window %s - %s %s %s",
                 wid, window, ["above", "below"][above], other_window)
        if window:
            window.restack(other_window, above)

    def opengl_setup_failure(self, summary="Xpra OpenGL GPU Acceleration Failure", body="") -> None:
        OK = "0"
        DISABLE = "1"

        def notify_callback(event, nid, action_id, *args):
            log("notify_callback(%s, %s, %s, %s)", event, nid, action_id, args)
            if event == "notification-close":
                return
            if event != "notification-action":
                log.warn(f"Warning: unexpected event {event}")
                return
            if nid != NotificationID.OPENGL:
                log.warn(f"Warning: unexpected notification id {nid}")
                return
            if action_id == DISABLE:
                from xpra.platform.paths import get_user_conf_dirs
                dirs = get_user_conf_dirs()
                for d in dirs:
                    conf_file = osexpand(os.path.join(d, "xpra.conf"))
                    try:
                        with open(conf_file, "a", encoding="latin1") as f:
                            f.write("\n")
                            f.write("# user chose to disable the opengl warning:\n")
                            f.write("opengl=nowarn\n")
                        log.info("OpenGL warning will be silenced from now on,")
                        log.info(" '%s' has been updated", conf_file)
                        break
                    except OSError:
                        log("failed to create / append to config file '%s'", conf_file, exc_info=True)

        def delayed_notify() -> None:
            if self.exit_code is not None:
                return
            if OSX:
                # don't bother logging an error on MacOS,
                # OpenGL is being deprecated
                log.info(summary)
                log.info(body)
                return
            actions = (OK, "OK", DISABLE, "Don't show this warning again")
            self.may_notify(NotificationID.OPENGL, summary, body, actions,
                            icon_name="opengl", callback=notify_callback)

        # wait for the main loop to run:
        GLib.timeout_add(2 * 1000, delayed_notify)

    def glinit_error(self, msg: str, err) -> None:
        opengllog("OpenGL initialization error", exc_info=True)
        self.GLClientWindowClass = None
        self.client_supports_opengl = False
        opengllog.error("%s", msg)
        for x in str(err).split("\n"):
            opengllog.error(" %s", x)
        self.opengl_props["info"] = str(err)
        self.opengl_props["enabled"] = False
        self.opengl_setup_failure(body=str(err))

    def glinit_warn(self, warning: str) -> None:
        if self.opengl_enabled and not self.opengl_force:
            self.opengl_enabled = False
            opengllog.warn("Warning: OpenGL is disabled:")
        opengllog.warn(" %s", warning)

    def validate_texture_size(self) -> None:
        if self.do_validate_texture_size():
            return
        # log at warn level if the limit is low:
        # (if we're likely to hit it - if the screen is as big or bigger)
        w, h = self.get_root_size()
        log_fn = opengllog.info
        if w * 2 <= self.gl_texture_size_limit and h * 2 <= self.gl_texture_size_limit:
            log_fn = opengllog.debug
        if w >= self.gl_texture_size_limit or h >= self.gl_texture_size_limit:
            log_fn = opengllog.warn
        log_fn("Warning: OpenGL windows will be clamped to the maximum texture size %ix%i",
               self.gl_texture_size_limit, self.gl_texture_size_limit)
        glver = pver(self.opengl_props.get("opengl", ""))
        renderer = self.opengl_props.get("renderer", "unknown")
        log_fn(f" for OpenGL {glver} renderer {renderer!r}")

    def do_validate_texture_size(self) -> bool:
        mww, mwh = self.max_window_size
        lim = self.gl_texture_size_limit
        if lim >= 16 * 1024:
            return True
        if mww > 0 and mww > lim:
            return False
        if mwh > 0 and mwh > lim:
            return False
        return True

    # OpenGL bits:
    def init_opengl(self, enable_opengl: str) -> None:
        opengllog(f"init_opengl({enable_opengl})")
        # enable_opengl can be True, False, force, probe-failed, probe-success, or None (auto-detect)
        # ie: "on:native,gtk", "auto", "no"
        # ie: "probe-failed:SIGSEGV"
        # ie: "probe-success"
        parts = enable_opengl.split(":", 1)
        enable_option = parts[0].lower()  # ie: "on"
        opengllog(f"init_opengl: enable_option={enable_option}")
        if enable_option in ("probe-failed", "probe-error", "probe-crash", "probe-warning", "probe-disabled"):
            msg = enable_option.replace("-", " ")
            if len(parts) > 1 and any(len(x) for x in parts[1:]):
                msg += ": %s" % csv(parts[1:])
            self.opengl_props["info"] = "disabled, %s" % msg
            if enable_option != "probe-disabled":
                self.opengl_setup_failure(body=msg)
            return
        if enable_option in FALSE_OPTIONS:
            self.opengl_props["info"] = "disabled by configuration"
            return
        warnings = []
        self.opengl_props["info"] = ""
        if enable_option == "force":
            self.opengl_force = True
        elif enable_option != "probe-success":
            from xpra.platform.gui import gl_check as platform_gl_check
            opengllog("checking with %s", platform_gl_check)
            warning = platform_gl_check()
            opengllog("%s()=%s", platform_gl_check, warning)
            if warning:
                warnings.append(warning)

        if warnings:
            if enable_option in ("", "auto"):
                opengllog.warn("OpenGL disabled:")
                for warning in warnings:
                    opengllog.warn(" %s", warning)
                self.opengl_props["info"] = "disabled: %s" % csv(warnings)
                return
            if enable_option == "probe-success":
                opengllog.warn("OpenGL enabled, despite some warnings:")
            else:
                opengllog.warn("OpenGL safety warning (enabled at your own risk):")
            for warning in warnings:
                opengllog.warn(" %s", warning)
            self.opengl_props["info"] = "enabled despite: %s" % csv(warnings)
        try:
            opengllog("init_opengl: going to import xpra.opengl")
            import_module("xpra.opengl")
            from xpra.opengl.window import get_gl_client_window_module, test_gl_client_window
            self.opengl_props, gl_client_window_module = get_gl_client_window_module(enable_opengl)
            if not gl_client_window_module:
                opengllog.warn("Warning: no OpenGL backend module found")
                self.client_supports_opengl = False
                self.opengl_props["info"] = "disabled: no module found"
                return
            opengllog("init_opengl: found props %s", self.opengl_props)
            self.GLClientWindowClass = gl_client_window_module.GLClientWindow
            self.client_supports_opengl = True
            # only enable opengl by default if force-enabled or if safe to do so:
            enabled_by_option = enable_option in (list(TRUE_OPTIONS) + ["auto"])
            self.opengl_enabled = self.opengl_force or enabled_by_option or self.opengl_props.get("safe", False)
            self.gl_texture_size_limit = self.opengl_props.get("texture-size-limit", 16 * 1024)
            dims = self.gl_texture_size_limit, self.gl_texture_size_limit
            self.gl_max_viewport_dims = self.opengl_props.get("max-viewport-dims", dims)
            renderer = self.opengl_props.get("renderer", "unknown")
            parts = renderer.split("(")
            if len(parts) > 1 and len(parts[0]) > 10:
                renderer = parts[0].strip()
            driver_info = renderer or self.opengl_props.get("vendor") or "unknown card"

            from xpra.opengl.check import MIN_SIZE
            if min(self.gl_max_viewport_dims) < MIN_SIZE:
                self.glinit_warn("the maximum viewport size is too low: %s" % (self.gl_max_viewport_dims,))
            if self.gl_texture_size_limit < MIN_SIZE:
                self.glinit_warn("the texture size limit is too low: %s" % (self.gl_texture_size_limit,))
            if driver_info.startswith("SVGA3D") and os.environ.get("WAYLAND_DISPLAY"):
                self.glinit_warn("SVGA3D driver is buggy under Wayland")
            self.GLClientWindowClass.MAX_VIEWPORT_DIMS = self.gl_max_viewport_dims
            self.GLClientWindowClass.MAX_BACKING_DIMS = self.gl_texture_size_limit, self.gl_texture_size_limit
            opengllog("OpenGL: enabled=%s, texture-size-limit=%s, max-window-size=%s",
                      self.opengl_enabled, self.gl_texture_size_limit, self.max_window_size)

            if self.opengl_enabled:
                self.validate_texture_size()
            if self.opengl_enabled and enable_opengl != "probe-success" and not self.opengl_force:
                draw_result = test_gl_client_window(self.GLClientWindowClass,
                                                    max_window_size=self.max_window_size,
                                                    pixel_depth=self.pixel_depth)
                if not draw_result.get("success", False):
                    self.glinit_error("OpenGL test rendering failed:",
                                      draw_result.get("message", "") or "unknown error")
                    return
                opengllog(f"OpenGL test rendering succeeded: {draw_result}")
            if self.opengl_enabled:
                glvstr = ".".join(str(v) for v in self.opengl_props.get("opengl", ()))
                opengllog.info(f"OpenGL {glvstr} enabled on {driver_info!r}")
                module = self.opengl_props.get("module", "unknown")
                backend = self.opengl_props.get("backend", "unknown")
                opengllog.info(f" using {module} {backend} backend")
                opengllog.info(" zerocopy is %s", ["not available", "available"][self.opengl_props.get("zerocopy", 0)])
                # don't try to handle video dimensions bigger than this:
                mvs = min(8192, self.gl_texture_size_limit)
                self.video_max_size = (mvs, mvs)
            elif self.client_supports_opengl:
                opengllog(f"OpenGL supported on {driver_info!r}, but not enabled")
            self.opengl_props["enabled"] = self.opengl_enabled
            if self.opengl_enabled and not warnings and OSX:
                # non-opengl is slow on MacOS:
                self.opengl_force = True
        except ImportError as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("OpenGL accelerated rendering is not available:", e)
        except RuntimeError as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("OpenGL support could not be enabled on this hardware:", e)
        except Exception as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("Error loading OpenGL support:", e)

    def get_client_window_classes(self, geom: tuple[int, int, int, int], metadata: typedict,
                                  override_redirect: bool) -> Sequence[type]:
        log("get_client_window_class%s", (geom, metadata, override_redirect))
        log(" ClientWindowClass=%s, GLClientWindowClass=%s, opengl_enabled=%s, encoding=%s",
            self.ClientWindowClass, self.GLClientWindowClass, self.opengl_enabled, self.encoding)
        window_classes: list[type] = []
        if self.GLClientWindowClass:
            ww, wh = geom[2], geom[3]
            if self.can_use_opengl(ww, wh, metadata, override_redirect):
                window_classes.append(self.GLClientWindowClass)
            else:
                opengllog(f"OpenGL not available for {ww}x{wh} {override_redirect=} window {metadata}")
        if self.ClientWindowClass:
            window_classes.append(self.ClientWindowClass)
        return tuple(window_classes)

    def can_use_opengl(self, w: int, h: int, metadata: typedict, override_redirect: bool) -> bool:
        opengllog(f"can_use_opengl {self.GLClientWindowClass=}, {self.opengl_enabled=}, {self.opengl_force=}")
        if self.GLClientWindowClass is None or not self.opengl_enabled:
            return False
        if not self.opengl_force:
            # verify texture limits:
            ms = min(self.sx(self.gl_texture_size_limit), *self.gl_max_viewport_dims)
            if w > ms or h > ms:
                return False
            # avoid opengl for small windows:
            if w <= OPENGL_MIN_SIZE or h <= OPENGL_MIN_SIZE:
                log("not using opengl for small window: %ix%i", w, h)
                return False
            # avoid opengl for tooltips:
            window_types = metadata.strtupleget("window-type")
            if any(x in NO_OPENGL_WINDOW_TYPES for x in window_types):
                log("not using opengl for %s window-type", csv(window_types))
                return False
            if metadata.intget("transient-for", 0) > 0:
                log("not using opengl for transient-for window")
                return False
            if metadata.strget("content-type").find("text") >= 0:
                return False
        if WIN32:
            # these checks can't be forced ('opengl_force')
            # win32 opengl just doesn't do alpha or undecorated windows properly:
            if override_redirect:
                return False
            if metadata.boolget("has-alpha", False):
                return False
            if not metadata.boolget("decorations", True):
                return False
            hbl = (self.headerbar or "").lower().strip()
            if hbl not in FALSE_OPTIONS:
                # any risk that we may end up using headerbar,
                # means we can't enable opengl
                return False
        return True

    def toggle_opengl(self, *_args) -> None:
        self.opengl_enabled = not self.opengl_enabled
        opengllog("opengl_toggled: %s", self.opengl_enabled)
        # now replace all the windows with new ones:
        for wid, window in tuple(self._id_to_window.items()):
            self.reinit_window(wid, window)
        opengllog("replaced all the windows with opengl=%s: %s", self.opengl_enabled, self._id_to_window)
        self.reinit_window_icons()

    def find_window(self, metadata: typedict, metadata_key: str = "transient-for"):
        fwid = metadata.intget(metadata_key, -1)
        log("find_window(%s, %s) wid=%#x", metadata, metadata_key, fwid)
        if fwid > 0:
            return self._id_to_window.get(fwid)
        return None

    def find_gdk_window(self, metadata: typedict, metadata_key="transient-for"):
        client_window = self.find_window(metadata, metadata_key)
        if client_window:
            gdk_window = client_window.get_window()
            if gdk_window:
                return gdk_window
        return None

    def get_group_leader(self, wid: int, metadata: typedict, _override_redirect: bool):
        def find_gdk_window(metadata_key="transient-for"):
            return self.find_gdk_window(metadata, metadata_key)

        win = find_gdk_window("group-leader-wid") or find_gdk_window("transient-for") or find_gdk_window("parent")
        log(f"get_group_leader(..)={win}")
        if win:
            return win

        ref_metadata = dict(metadata)
        ref_metadata["wid"] = wid
        refkey = get_group_ref(ref_metadata)
        log(f"get_group_leader: refkey={refkey}, metadata={metadata}, refs={self._ref_to_group_leader}")
        group_leader_window = self._ref_to_group_leader.get(refkey)
        if group_leader_window:
            log("found existing group leader window %s using ref=%s", group_leader_window, refkey)
            return group_leader_window
        # we need to create one:
        title = "%s group leader for window %s" % (self.session_name or "Xpra", wid)
        # group_leader_window = Gdk.Window(None, 1, 1, Gtk.WindowType.TOPLEVEL, 0, Gdk.INPUT_ONLY, title)
        # static new(parent, attributes, attributes_mask)
        group_leader_window = GDKWindow(wclass=Gdk.WindowWindowClass.INPUT_ONLY, title=title)
        self._ref_to_group_leader[refkey] = group_leader_window
        # avoid warning on win32...
        if not WIN32:
            # X11 spec says window should point to itself:
            group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid: int, window) -> None:
        # override so we can cleanup the group-leader if needed,
        from xpra.client.subsystem.window import WindowClient
        WindowClient.destroy_window(self, wid, window)
        group_leader = window.group_leader
        if group_leader is None or not self._group_leader_wids:
            return
        wids = self._group_leader_wids.get(group_leader)
        if wids is None:
            # not recorded any window ids on this group leader
            # means it is another managed window, leave it alone
            return
        if wid in wids:
            wids.remove(wid)
        if wids:
            # still has another window pointing to it
            return
        # the last window has gone, we can remove the group leader,
        # find all the references to this group leader:
        del self._group_leader_wids[group_leader]
        refs = []
        for ref, gl in self._ref_to_group_leader.items():
            if gl == group_leader:
                refs.append(ref)
        for ref in refs:
            del self._ref_to_group_leader[ref]
        log("last window for refs %s is gone, destroying the group leader %s", refs, group_leader)
        group_leader.close()

    def setup_clipboard_helper(self, helper_class, options: dict):
        from xpra.client.subsystem.clipboard import ClipboardClient
        ch = ClipboardClient.setup_clipboard_helper(self, helper_class, options)

        # check for loops after handshake:

        def register_clipboard_toggled(*_args) -> None:
            def clipboard_toggled(*_args) -> None:
                # reset tray icon:
                self.local_clipboard_requests = 0
                self.remote_clipboard_requests = 0
                self.clipboard_notify(0)

            self.connect("clipboard-toggled", clipboard_toggled)

        self.after_handshake(register_clipboard_toggled)
        if self.server_clipboard:
            # from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.clipboard_toggled)
        return ch

    def cancel_clipboard_notification_timer(self) -> None:
        cnt = self.clipboard_notification_timer
        if cnt:
            self.clipboard_notification_timer = 0
            GLib.source_remove(cnt)

    def clipboard_notify(self, n: int) -> None:
        tray = getattr(self, "tray", None)
        if not tray or not CLIPBOARD_NOTIFY:
            return
        clipboardlog(f"clipboard_notify({n}) notification timer={self.clipboard_notification_timer}")
        self.cancel_clipboard_notification_timer()
        if n > 0 and self.clipboard_enabled:
            self.last_clipboard_notification = monotonic()
            tray.set_icon("clipboard")
            tray.set_tooltip(f"{n} clipboard requests in progress")
            tray.set_blinking(True)
        else:
            # no more pending clipboard transfers,
            # reset the tray icon,
            # but wait at least N seconds after the last clipboard transfer:
            N = 1
            delay = max(0, round(1000 * (self.last_clipboard_notification + N - monotonic())))

            self.clipboard_notification_timer = GLib.timeout_add(delay, self.reset_tray_icon)

    def reset_tray_icon(self) -> None:
        self.clipboard_notification_timer = 0
        tray = self.tray
        if not tray:
            return
        tray.set_icon(None)  # None means back to default icon
        tray.set_tooltip(self.get_tray_title())
        tray.set_blinking(False)
