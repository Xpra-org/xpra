# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from collections.abc import Callable
from subprocess import Popen, PIPE
from threading import Event

from xpra.client.base.stub import StubClientMixin
from xpra.common import noop, may_show_progress, noerr
from xpra.exit_codes import ExitCode
from xpra.gtk.widget import FILE_CHOOSER_NATIVE, label
from xpra.net.common import BACKWARDS_COMPATIBLE, pretty_socket
from xpra.os_util import gi_import, OSX
from xpra.scripts.config import InitExit
from xpra.util.child_reaper import get_child_reaper
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.util.stats import std_unit
from xpra.util.str_fn import Ellipsizer
from xpra.platform.gui import force_focus
from xpra.log import Logger

log = Logger("gtk", "client")
filelog = Logger("gtk", "client", "file")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")


class GTKDialogClient(StubClientMixin):
    PREFIX = "dialogs"

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        self.pinentry_proc = None
        self.sub_dialogs = {}

    def cleanup(self) -> None:
        self.stop_pinentry()
        for name, dialog in tuple(self.sub_dialogs.items()):
            log("closing %s dialog %s", name, dialog)
            dialog.close()
        self.sub_dialogs.clear()

    def do_process_challenge_prompt(self, prompt="password"):
        if progress := self.get_subsystem("progress"):
            progress.stop_progress_process(f"showing {prompt} prompt")
        authlog = Logger("auth")
        may_show_progress(self.client, 100, "authentication")
        PINENTRY = os.environ.get("XPRA_PINENTRY", "")
        from xpra.scripts.pinentry import get_pinentry_command
        pinentry_cmd = get_pinentry_command(PINENTRY)
        authlog(f"do_process_challenge_prompt({prompt}) get_pinentry_command({PINENTRY})={pinentry_cmd}")
        if pinentry_cmd:
            return self.handle_challenge_with_pinentry(prompt, pinentry_cmd)
        return self.process_challenge_prompt_dialog(prompt)

    def stop_pinentry(self) -> None:
        if pp := self.pinentry_proc:
            self.pinentry_proc = None
            noerr(pp.terminate)
            for fd_name in ("stdin", "stdout", "stderr"):
                fd = getattr(pp, fd_name, None)
                close: Callable = getattr(fd, "close", noop)
                noerr(close)

    def get_server_authentication_string(self) -> str:
        p = self.client._protocol
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
        if p := self.client._protocol:
            conn = getattr(p, "_conn", None)
            if conn:
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
        add(label(self.client.get_challenge_prompt(prompt)), 10)
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
                    self.client.disconnect_and_quit(ExitCode.PASSWORD_REQUIRED, "password entry was cancelled")
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
        cmd = self.get_subsystem("command")
        sci = bool(cmd and cmd.server_commands_info)
        if not sci:
            log.warn("Warning: cannot show server commands")
            log.warn(" the feature is not available")
            return
        dialog = self.sub_dialogs.get("server-commands")
        if not dialog:
            from xpra.gtk.dialogs.server_commands import get_server_commands_window
            dialog = get_server_commands_window(self.client)
            self.sub_dialogs["server-commands"] = dialog
        dialog.show()

    def show_start_new_command(self, *args) -> None:
        cmd = self.get_subsystem("command")
        ssnc = bool(cmd and cmd.server_start_new_commands)
        if not ssnc:
            log.warn("Warning: cannot start new commands")
            log.warn(" the feature is not available")
            return
        dialog = self.sub_dialogs.get("start-new-command")
        log(f"show_start_new_command{args} current {dialog=}, flag={ssnc}")
        if not dialog:
            log("server_menu=%s", Ellipsizer(cmd.server_menu))
            from xpra.gtk.dialogs.start_new_command import get_start_new_command_gui

            def run_command_cb(command, sharing=True) -> None:
                cmd.send_start_command(command, shlex.split(command), False, sharing)

            dialog = get_start_new_command_gui(run_command_cb, self.client.server_sharing, cmd.server_menu)
            self.sub_dialogs["start-new-command"] = dialog
        dialog.show()

    def ask_data_request(self, cb_answer, send_id, dtype: str, url: str, filesize: int,
                         printit: bool, openit: bool, mimetype: str = "",
                         options: typedict | None = None) -> None:
        GLib.idle_add(self.do_ask_data_request, cb_answer, send_id, dtype, url, filesize,
                      printit, openit, mimetype, options)

    def do_ask_data_request(self, cb_answer, send_id, dtype: str, url: str, filesize: int,
                            printit: bool, openit: bool, mimetype: str = "",
                            options: typedict | None = None) -> None:
        from xpra.gtk.dialogs.open_requests import get_open_requests_window
        file_sub = self.get_subsystem("file")
        timeout = file_sub.remote_file_ask_timeout

        def rec_answer(accept, newopenit: bool=openit) -> None:
            from xpra.net.file_transfer import ACCEPT
            if int(accept) == ACCEPT:
                # record our response, so we will actually accept the file when the packets arrive:
                file_sub.record_data_request_acceptance(send_id, dtype, url, mimetype, filesize,
                                                        printit, newopenit, options)
            cb_answer(accept)

        dialog = get_open_requests_window(self.show_file_upload, file_sub.cancel_download)
        dialog.add_request(rec_answer, send_id, dtype, url, filesize, printit, openit, timeout)
        dialog.show()
        self.sub_dialogs["ask-data"] = dialog

    def show_ask_data_dialog(self, *_args) -> None:
        from xpra.gtk.dialogs.open_requests import get_open_requests_window
        file_sub = self.get_subsystem("file")
        dialog = get_open_requests_window(self.show_file_upload, file_sub.cancel_download)
        dialog.show()
        self.sub_dialogs["ask-data"] = dialog

    def transfer_progress_update(self, send=True, transfer_id=0, elapsed=0, position=0, total=0, error=None) -> None:
        if fad := self.sub_dialogs.get("ask-data"):
            GLib.idle_add(fad.transfer_progress_update, send, transfer_id, elapsed, position, total, error)

    def close_file_size_warning(self, *_args) -> None:
        if dialog := self.sub_dialogs.pop("file-size-warning", None):
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
        self.sub_dialogs["file-size-warning"] = dialog

    def download_server_log(self, callback: Callable[[str, int], None] = noop) -> None:
        filename = "${XPRA_SERVER_LOG}"
        file_sub = self.get_subsystem("file")
        file_sub.send_request_file(filename, file_sub.open_files, "*.log", callback=callback)

    def send_download_request(self, *_args) -> None:
        cmd = self.get_subsystem("command")
        if not cmd:
            log.warn("Warning: cannot request a download")
            log.warn(" the command subsystem is not available")
            return
        command = ["xpra", "send-file"]
        cmd.send_start_command("Client-Download-File", command, True)

    def show_file_upload(self, *args) -> None:
        if dialog := self.sub_dialogs.get("file-upload"):
            dialog.present()
            return
        file_sub = self.get_subsystem("file")
        remote_open_files = file_sub.remote_open_files
        filelog(f"show_file_upload{args} can open={remote_open_files}")
        buttons = [Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL]
        if remote_open_files:
            buttons += [Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT]
        buttons += [Gtk.STOCK_OK, Gtk.ResponseType.OK]
        title = "File to upload"
        if FILE_CHOOSER_NATIVE > 1 or (FILE_CHOOSER_NATIVE and not remote_open_files):
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
            if fu_dialog := self.sub_dialogs.pop("file-upload", None):
                fu_dialog.close()

        if v not in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
            filelog(f"dialog response code {v}")
            close_file_upload_dialog()
            return
        filename = dialog.get_filename()
        filelog(f"file_upload_dialog_response: filename={filename!r}")
        try:
            filesize = os.stat(filename).st_size
        except OSError:
            pass
        else:
            if not self.get_subsystem("file").check_file_size("upload", filename, filesize):
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
        self.get_subsystem("file").send_file(filename, "", data, filesize=filesize, openit=openit)

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
        keyboard = self.get_subsystem("keyboard")
        kh = keyboard.helper if keyboard else None
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
        conn = getattr(self.client._protocol, "_conn", None)
        from xpra.gtk.dialogs.session_info import SessionInfo
        dialog = SessionInfo(self.client, self.client.session_name, conn)
        dialog.set_args(*args)
        force_focus()
        dialog.show_all()
        self.sub_dialogs["session-info"] = dialog

    def show_bug_report(self, *_args) -> None:
        server_info = self.get_subsystem("server-info")
        if server_info:
            server_info.send_info_request()

        if dialog := self.sub_dialogs.get("bug-report"):
            force_focus()
            dialog.show()
            return
        from xpra.gtk.dialogs.bug_report import BugReport
        dialog = BugReport()
        self.sub_dialogs["bug-report"] = dialog

        def init_bug_report() -> None:
            # skip things we aren't using:
            keyboard = self.get_subsystem("keyboard")
            gl = self.get_subsystem("opengl")
            includes = {
                "keyboard": bool(keyboard and keyboard.helper),
                "opengl": bool(gl and gl.enabled),
            }

            def get_server_info() -> typedict:
                # the subsystem may not be loaded:
                return getattr(server_info, "last_info", typedict())

            dialog.init(show_about=False, get_server_info=get_server_info,
                        opengl_info=gl.properties if gl else {},
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
