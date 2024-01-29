# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import weakref
from time import monotonic
from subprocess import Popen, PIPE
from threading import Event
from typing import Dict, Any, List, Type, Tuple, Optional
from gi.repository import Gtk, Gdk, GdkPixbuf  # @UnresolvedImport

from xpra.client.gtk3.gtk_client_window_base import HAS_X11_BINDINGS, XSHAPE
from xpra.util import (
    updict, pver, flatten_dict, noerr,
    envbool, envint, repr_ellipsized, ellipsizer, csv, first_time, typedict,
    DEFAULT_METADATA_SUPPORTED, NotificationID,
    )
from xpra.os_util import (
    bytestostr, strtobytes, memoryview_to_bytes,
    hexstr, load_binary_file, osexpand,
    WIN32, OSX, POSIX, is_Wayland,
    )
from xpra.net.common import PacketType
from xpra.common import FULL_INFO, VIDEO_MAX_SIZE
from xpra.simple_stats import std_unit
from xpra.scripts.config import TRUE_OPTIONS, FALSE_OPTIONS, InitExit
from xpra.gtk_common.cursor_names import cursor_types
from xpra.gtk_common.gtk_util import (
    get_gtk_version_info, scaled_image, get_default_cursor, color_parse,
    get_icon_pixbuf,
    get_pixbuf_from_data,
    get_default_root_window, get_root_size,
    get_screen_sizes, get_monitors_info,
    GDKWindow,
    GRAB_STATUS_STRING,
    )
from xpra.exit_codes import ExitCode
from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.gtk_common.css_overrides import inject_css_overrides
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.client.base.gobject_client_base import GObjectXpraClient
from xpra.client.gtk3.gtk_keyboard_helper import GTKKeyboardHelper
from xpra.client.mixins.window_manager import WindowClient
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
screenlog = Logger("gtk", "client", "screen")
filelog = Logger("gtk", "client", "file")
clipboardlog = Logger("gtk", "client", "clipboard")
notifylog = Logger("gtk", "notify")
grablog = Logger("client", "grab")
focuslog = Logger("client", "focus")

missing_cursor_names = set()

METADATA_SUPPORTED = os.environ.get("XPRA_METADATA_SUPPORTED")
#on win32, the named cursors work, but they are hard to see
#when using the Adwaita theme
USE_LOCAL_CURSORS = envbool("XPRA_USE_LOCAL_CURSORS", not WIN32 and not is_Wayland())
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)
CLIPBOARD_NOTIFY = envbool("XPRA_CLIPBOARD_NOTIFY", True)
OPENGL_MIN_SIZE = envint("XPRA_OPENGL_MIN_SIZE", 32)
NO_OPENGL_WINDOW_TYPES = os.environ.get("XPRA_NO_OPENGL_WINDOW_TYPES",
                                        "DOCK,TOOLBAR,MENU,UTILITY,SPLASH,DROPDOWN_MENU,POPUP_MENU,TOOLTIP,NOTIFICATION,COMBO,DND").split(",")

inject_css_overrides()


# pylint: disable=import-outside-toplevel
class GTKXpraClient(GObjectXpraClient, UIXpraClient):
    __gsignals__ = {}
    #add signals from super classes (all no-arg signals)
    for signal_name in UIXpraClient.__signals__:
        __gsignals__[signal_name] = no_arg_signal

    ClientWindowClass : Optional[Type] = None
    GLClientWindowClass : Optional[Type] = None

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.pinentry_proc = None
        self.shortcuts_info = None
        self.session_info = None
        self.bug_report = None
        self.file_size_dialog = None
        self.file_ask_dialog = None
        self.file_dialog = None
        self.start_new_command = None
        self.server_commands = None
        self.keyboard_helper_class = GTKKeyboardHelper
        self.border = None
        self.data_send_requests = {}
        #clipboard bits:
        self.clipboard_notification_timer = 0
        self.last_clipboard_notification = 0
        #opengl bits:
        self.client_supports_opengl = False
        self.opengl_force = False
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
        self._window_with_grab = 0
        self.video_max_size = VIDEO_MAX_SIZE
        try:
            self.connect("scaling-changed", self.reset_windows_cursors)
        except TypeError:
            log("no 'scaling-changed' signal")
        #detect when the UI thread isn't responding:
        self.UI_watcher = None
        self.connect("first-ui-received", self.start_UI_watcher)


    def init(self, opts) -> None:
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)


    def setup_frame_request_windows(self) -> None:
        #query the window manager to get the frame size:
        from xpra.gtk_common.error import xsync
        from xpra.x11.bindings.send_wm import send_wm_request_frame_extents
        self.frame_request_window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.frame_request_window.set_title("Xpra-FRAME_EXTENTS")
        root = self.get_root_window()
        self.frame_request_window.realize()
        with xsync:
            win = self.frame_request_window.get_window()
            xid = win.get_xid()
            framelog("setup_frame_request_windows() window=%#x", xid)
            send_wm_request_frame_extents(root.get_xid(), xid)

    def run(self) -> int:
        log(f"run() HAS_X11_BINDINGS={HAS_X11_BINDINGS}")
        if HAS_X11_BINDINGS:
            self.setup_frame_request_windows()
        UIXpraClient.run(self)
        self.gtk_main()
        log(f"GTKXpraClient.run_main_loop() main loop ended, returning exit_code={self.exit_code}", )
        return self.exit_code

    def gtk_main(self) -> None:
        log(f"GTKXpraClient.gtk_main() calling {Gtk.main}",)
        Gtk.main()
        log("GTKXpraClient.gtk_main() ended")


    def quit(self, exit_code=0) -> None:
        log(f"GTKXpraClient.quit({exit_code}) current exit_code={self.exit_code}")
        if self.exit_code is None:
            self.exit_code = exit_code
        if Gtk.main_level()>0:
            #if for some reason cleanup() hangs, maybe this will fire...
            self.timeout_add(4*1000, self.exit)
            #try harder!:
            self.timeout_add(5*1000, self.force_quit)
        self.cleanup()
        log(f"GTKXpraClient.quit({exit_code}) cleanup done, main_level={Gtk.main_level()}")
        if Gtk.main_level()>0:
            log(f"GTKXpraClient.quit({exit_code}) main loop at level {Gtk.main_level()}, calling gtk quit via timeout")
            self.timeout_add(500, self.exit)

    def force_quit(self) -> None:
        from xpra.os_util import force_quit
        log(f"GTKXpraClient.force_quit() calling {force_quit}")
        force_quit()

    def exit(self) -> None:
        self.show_progress(100, "terminating")
        log(f"GTKXpraClient.exit() calling {Gtk.main_quit}", )
        Gtk.main_quit()

    def cleanup(self) -> None:
        log("GTKXpraClient.cleanup()")
        self.stop_pinentry()
        if self.shortcuts_info:
            self.shortcuts_info.close()
            self.shortcuts_info = None
        if self.session_info:
            self.session_info.close()
            self.session_info = None
        if self.bug_report:
            self.bug_report.close()
            self.bug_report = None
        self.close_file_size_warning()
        self.close_file_upload_dialog()
        self.close_ask_data_dialog()
        self.cancel_clipboard_notification_timer()
        if self.start_new_command:
            self.start_new_command.close()
            self.start_new_command = None
        if self.server_commands:
            self.server_commands.close()
            self.server_commands = None
        uw = self.UI_watcher
        if uw:
            self.UI_watcher = None
            uw.stop()
        UIXpraClient.cleanup(self)

    def start_UI_watcher(self, _client) -> None:
        from xpra.platform.ui_thread_watcher import get_UI_watcher
        self.UI_watcher = get_UI_watcher(self.timeout_add, self.source_remove)
        self.UI_watcher.start()
        #if server supports it, enable UI thread monitoring workaround when needed:
        def UI_resumed():
            self.send("resume", True, tuple(self._id_to_window.keys()))
            #maybe the system was suspended?
            #so we may want to call WindowClient.resume()
            resume = getattr(self, "resume", None)
            if resume:
                resume()
        def UI_failed():
            self.send("suspend", True, tuple(self._id_to_window.keys()))
        self.UI_watcher.add_resume_callback(UI_resumed)
        self.UI_watcher.add_fail_callback(UI_failed)


    def get_vrefresh(self) -> int:
        rate = envint("XPRA_VREFRESH", 0)
        if rate:
            return rate
        #try via GTK:
        rates = {}
        display = Gdk.Display.get_default()
        for m in range(display.get_n_monitors()):
            monitor = display.get_monitor(m)
            log(f"monitor {m} ({monitor.get_model()}) refresh-rate={monitor.get_refresh_rate()}")
            rates[m] = monitor.get_refresh_rate()
        rate = -1
        if rates:
            rate = round(min(rates.values())/1000)
        if rate<30 or rate>250:
            rate = super().get_vrefresh()
        return rate


    def _process_startup_complete(self, packet : PacketType) -> None:
        super()._process_startup_complete(packet)
        Gdk.notify_startup_complete()


    def do_process_challenge_prompt(self, prompt="password"):
        authlog = Logger("auth")
        self.show_progress(100, "authentication")
        PINENTRY = os.environ.get("XPRA_PINENTRY", "")
        from xpra.scripts.pinentry_wrapper import get_pinentry_command
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
                if hasattr(fd, "close"):
                    noerr(fd.close)

    def get_server_authentication_string(self) -> str:
        p = self._protocol
        server_type = ""
        if p:
            server_type = {
                "xpra"  : "Xpra ",
                "rfb"   : "VNC ",
                }.get(p.TYPE, p.TYPE)
        return f"{server_type}Server Authentication:"

    def handle_challenge_with_pinentry(self, prompt="password", cmd="pinentry"):
        # pylint: disable=import-outside-toplevel
        authlog = Logger("auth")
        authlog("handle_challenge_with_pinentry%s", (prompt, cmd))
        try:
            proc = Popen([cmd], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        except OSError:
            authlog("pinentry failed", exc_info=True)
            return self.process_challenge_prompt_dialog(prompt)
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
        values = []
        errs = []
        def rec(value=None):
            values.append(value)
        def err(value=None):
            errs.append(value)
        from xpra.scripts.pinentry_wrapper import pinentry_getpin
        pinentry_getpin(proc, title, q, rec, err)
        if not values:
            if errs and errs[0].startswith("ERR 83886179"):
                #ie 'ERR 83886179 Operation cancelled <Pinentry>'
                raise InitExit(ExitCode.PASSWORD_REQUIRED, errs[0][len("ERR 83886179"):])
            return None
        return values[0]

    def process_challenge_prompt_dialog(self, prompt="password"):
        #challenge handlers run in a separate 'challenge' thread
        #but we need to run in the UI thread to access the GUI with Gtk
        #so we block the current thread using an event:
        wait = Event()
        values = []
        self.idle_add(self.do_process_challenge_prompt_dialog, values, wait, prompt)
        wait.wait()
        if not values:
            return None
        return values[0]

    def do_process_challenge_prompt_dialog(self, values : list, wait : Event, prompt="password") -> None:
        # pylint: disable=import-outside-toplevel
        title = self.get_server_authentication_string()
        dialog = Gtk.Dialog(title,
               None,
               Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT)
        dialog.add_button(Gtk.STOCK_OK,     Gtk.ResponseType.ACCEPT)
        def add(widget, padding=0):
            a = Gtk.Alignment()
            a.set(0.5, 0.5, 1, 1)
            a.add(widget)
            a.set_padding(padding, padding, padding, padding)
            dialog.vbox.pack_start(a)
        import gi
        gi.require_version("Pango", "1.0")  # @UndefinedVariable
        from gi.repository import Pango  # @UnresolvedImport
        title = Gtk.Label(label=title)
        title.modify_font(Pango.FontDescription("sans 14"))
        add(title, 16)
        add(Gtk.Label(label=self.get_challenge_prompt(prompt)), 10)
        password_input = Gtk.Entry()
        password_input.set_max_length(255)
        password_input.set_width_chars(32)
        password_input.set_visibility(False)
        add(password_input, 10)
        dialog.vbox.show_all()
        dialog.password_input = password_input
        def handle_response(dialog, response):
            if OSX:
                from xpra.platform.darwin.gui import disable_focus_workaround
                disable_focus_workaround()
            password = dialog.password_input.get_text()
            dialog.hide()
            dialog.close()
            response_str = dict((getattr(Gtk.ResponseType, k, ""), k) for k in (
                "ACCEPT", "APPLY", "CANCEL", "CLOSE", "DELETE_EVENT", "HELP", "NO", "NONE", "OK", "REJECT", "YES"))
            log(f"handle_response({dialog}, {response}) response={response_str.get(response)}")
            if response!=Gtk.ResponseType.ACCEPT or not password:
                values.append(None)
                #for those responses, we assume that the user wants to abort authentication:
                if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.REJECT, Gtk.ResponseType.DELETE_EVENT):
                    self.disconnect_and_quit(ExitCode.PASSWORD_REQUIRED, "password entry was cancelled")
            else:
                values.append(password)
            wait.set()
        def password_activate(*_args):
            handle_response(dialog, Gtk.ResponseType.ACCEPT)
        password_input.connect("activate", password_activate)
        dialog.connect("response", handle_response)
        if OSX:
            from xpra.platform.darwin.gui import enable_focus_workaround
            enable_focus_workaround()
        dialog.show()


    def setup_connection(self, conn):
        conn = super().setup_connection(conn)
        #now that we have display_desc, parse the border again:
        self.parse_border(False)
        return conn


    def show_border_help(self) -> None:
        if not first_time("border-help"):
            return
        log.info(" border format: color[,size][:off]")
        log.info("  eg: red,10")
        log.info("  eg: ,5")
        log.info("  eg: auto,5")
        log.info("  eg: blue")

    def parse_border(self, warn=True) -> None:
        enabled = not self.border_str.endswith(":off")
        parts = [x.strip() for x in self.border_str.replace(":off", "").split(",")]
        color_str = parts[0]
        if color_str.lower() in ("none", "no", "off", "0"):
            return
        if color_str.lower()=="help":
            self.show_border_help()
            return
        color_str = color_str.replace(":off", "")
        if color_str in ("auto", ""):
            from hashlib import sha256
            m = sha256()
            endpoint = self.display_desc.get("display_name")
            if endpoint:
                m.update(strtobytes(endpoint))
            color_str = "#%s" % m.hexdigest()[:6]
            log(f"border color derived from {endpoint}: {color_str}")
        try:
            color = color_parse(color_str)
            assert color is not None
        except Exception as e:
            if warn:
                log.warn(f"Warning: invalid border color specified '{color_str!r}'")
                if str(e):
                    log.warn(" %s", e)
                self.show_border_help()
            color = color_parse("red")
        alpha = 0.6
        size = 4
        if len(parts)==2:
            size_str = parts[1]
            try:
                size = int(size_str)
            except Exception as e:
                if warn:
                    log.warn(f"Warning: invalid border size specified {size_str!r}")
                    log.warn(f" {e}")
                    self.show_border_help()
            if size<=0:
                log(f"border size is {size}, disabling it")
                return
            if size>=45:
                log.warn(f"Warning: border size is too large: {size}, clipping it")
                size = 45
        from xpra.client.gui.window_border import WindowBorder
        self.border = WindowBorder(enabled, color.red/65536.0, color.green/65536.0, color.blue/65536.0, alpha, size)
        log("parse_border(%s)=%s", self.border_str, self.border)


    def show_server_commands(self, *_args) -> None:
        if not self.server_commands_info:
            log.warn("Warning: cannot show server commands")
            log.warn(" the feature is not available on the server")
            return
        if self.server_commands is None:
            from xpra.client.gtk3.server_commands import getServerCommandsWindow
            self.server_commands = getServerCommandsWindow(self)
        self.server_commands.show()

    def show_start_new_command(self, *args) -> None:
        if not self.server_start_new_commands:
            log.warn("Warning: cannot start new commands")
            log.warn(" the feature is currently disabled on the server")
            return
        log(f"show_start_new_command{args} current start_new_command={self.start_new_command}, flag={self.server_start_new_commands}")
        if self.start_new_command is None:
            from xpra.client.gtk3.start_new_command import getStartNewCommand
            def run_command_cb(command, sharing=True):
                self.send_start_command(command, command, False, sharing)
            self.start_new_command = getStartNewCommand(run_command_cb,
                                                        self.server_sharing,
                                                        self.server_xdg_menu)
        self.start_new_command.show()


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
    def ask_data_request(self, cb_answer, send_id, dtype, url, filesize, printit, openit):
        self.idle_add(self.do_ask_data_request, cb_answer, send_id, dtype, url, filesize, printit, openit)

    def do_ask_data_request(self, cb_answer, send_id, dtype, url, filesize, printit, openit):
        from xpra.client.gtk3.open_requests import getOpenRequestsWindow
        timeout = self.remote_file_ask_timeout
        def rec_answer(accept, newopenit=openit):
            from xpra.net.file_transfer import ACCEPT
            if int(accept)==ACCEPT:
                #record our response, so we will actually accept the file when the packets arrive:
                self.data_send_requests[send_id] = (dtype, url, printit, newopenit)
            cb_answer(accept)
        self.file_ask_dialog = getOpenRequestsWindow(self.show_file_upload, self.cancel_download)
        self.file_ask_dialog.add_request(rec_answer, send_id, dtype, url, filesize, printit, openit, timeout)
        self.file_ask_dialog.show()

    def close_ask_data_dialog(self):
        fad = self.file_ask_dialog
        if fad:
            self.file_ask_dialog = None
            fad.close()

    def show_ask_data_dialog(self, *_args):
        from xpra.client.gtk3.open_requests import getOpenRequestsWindow
        self.file_ask_dialog = getOpenRequestsWindow(self.show_file_upload, self.cancel_download)
        self.file_ask_dialog.show()

    def transfer_progress_update(self, send=True, transfer_id=0, elapsed=0, position=0, total=0, error=None):
        fad = self.file_ask_dialog
        if fad:
            self.idle_add(fad.transfer_progress_update, send, transfer_id, elapsed, position, total, error)


    def accept_data(self, send_id, dtype, url, printit, openit):
        #check if we have accepted this file via the GUI:
        r = self.data_send_requests.pop(send_id, None)
        if not r:
            filelog(f"accept_data: data send request {send_id} not found")
            from xpra.net.file_transfer import FileTransferHandler
            return FileTransferHandler.accept_data(self, send_id, dtype, url, printit, openit)
        edtype = r[0]
        eurl = r[1]
        if edtype!=dtype or eurl!=url:
            filelog.warn("Warning: the file attributes are different")
            filelog.warn(" from the ones that were used to accept the transfer")
            s = bytestostr
            if edtype!=dtype:
                filelog.warn(" expected data type '%s' but got '%s'", s(edtype), s(dtype))
            if eurl!=url:
                filelog.warn(" expected url '%s',", s(eurl))
                filelog.warn("  but got url '%s'", s(url))
            return None
        #return the printit and openit flag we got from the UI:
        return (r[2], r[3])

    def file_size_warning(self, action, location, basefilename, filesize, limit):
        if self.file_size_dialog:
            #close previous warning
            self.file_size_dialog.close()
            self.file_size_dialog = None
        parent = None
        msgs = (
                f"Warning: cannot {action} the file {basefilename!r}",
                f"this file is too large: {std_unit(filesize)}B",
                f"the {location} file size limit is {std_unit(limit)}B",
                )
        self.file_size_dialog = Gtk.MessageDialog(parent, Gtk.DialogFlags.DESTROY_WITH_PARENT, Gtk.MessageType.INFO,
                                                  Gtk.ButtonsType.CLOSE, "\n".join(msgs))
        try:
            image = Gtk.Image.new_from_stock(Gtk.STOCK_DIALOG_WARNING, Gtk.IconSize.BUTTON)
            self.file_size_dialog.set_image(image)
        except Exception as e:
            log.warn(f"Warning: failed to set dialog image: {e}")
        self.file_size_dialog.connect("response", self.close_file_size_warning)
        self.file_size_dialog.show()

    def close_file_size_warning(self, *_args):
        fsd = self.file_size_dialog
        if fsd:
            self.file_size_dialog = None
            fsd.close()

    def download_server_log(self, callback=None):
        filename = "${XPRA_SERVER_LOG}"
        if callback:
            self.file_request_callback[filename] = callback
        self.send_request_file(filename, self.open_files)

    def send_download_request(self, *_args):
        command = ["xpra", "send-file"]
        self.send_start_command("Client-Download-File", command, True)

    def show_file_upload(self, *args):
        if self.file_dialog:
            self.file_dialog.present()
            return
        filelog(f"show_file_upload{args} can open={self.remote_open_files}")
        buttons = [Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL]
        if self.remote_open_files:
            buttons += [Gtk.STOCK_OPEN,      Gtk.ResponseType.ACCEPT]
        buttons += [Gtk.STOCK_OK,        Gtk.ResponseType.OK]
        self.file_dialog = Gtk.FileChooserDialog(
            "File to upload",
            parent=None,
            action=Gtk.FileChooserAction.OPEN,
            buttons=tuple(buttons))
        self.file_dialog.set_default_response(Gtk.ResponseType.OK)
        self.file_dialog.connect("response", self.file_upload_dialog_response)
        self.file_dialog.show()

    def close_file_upload_dialog(self):
        fd = self.file_dialog
        if fd:
            fd.close()
            self.file_dialog = None

    def file_upload_dialog_response(self, dialog, v):
        if v not in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
            filelog(f"dialog response code {v}")
            self.close_file_upload_dialog()
            return
        filename = dialog.get_filename()
        filelog("file_upload_dialog_response: filename={filename!r}")
        try:
            filesize = os.stat(filename).st_size
        except OSError:
            pass
        else:
            if not self.check_file_size("upload", filename, filesize):
                self.close_file_upload_dialog()
                return
        gfile = dialog.get_file()
        self.close_file_upload_dialog()
        filelog(f"load_contents: filename={filename!r}, response={v}")
        cancellable = None
        user_data = (filename, v==Gtk.ResponseType.ACCEPT)
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


    def show_about(self, *_args) -> None:
        from xpra.gtk_common.about import about
        force_focus()
        about()

    def show_docs(self, *_args) -> None:
        from xpra.scripts.main import run_docs
        run_docs()

    def show_shortcuts(self, *_args) -> None:
        if self.shortcuts_info and not self.shortcuts_info.is_closed:
            force_focus()
            self.shortcuts_info.present()
            return
        from xpra.client.gtk3.show_shortcuts import ShortcutInfo
        kh = self.keyboard_helper
        assert kh, "no keyboard helper"
        self.shortcuts_info = ShortcutInfo(kh.shortcut_modifiers, kh.key_shortcuts)
        self.shortcuts_info.show_all()

    def show_session_info(self, *args) -> None:
        if self.session_info and not self.session_info.is_closed:
            #exists already: just raise its window:
            self.session_info.set_args(*args)
            force_focus()
            self.session_info.present()
            return
        p = self._protocol
        conn = p._conn if p else None
        from xpra.client.gtk3.session_info import SessionInfo
        self.session_info = SessionInfo(self, self.session_name, conn)
        self.session_info.set_args(*args)
        force_focus()
        self.session_info.show_all()

    def show_bug_report(self, *_args) -> None:
        self.send_info_request()
        if self.bug_report:
            force_focus()
            self.bug_report.show()
            return
        from xpra.client.gtk3.bug_report import BugReport
        self.bug_report = BugReport()
        def init_bug_report():
            #skip things we aren't using:
            includes ={
                       "keyboard"       : bool(self.keyboard_helper),
                       "opengl"         : self.opengl_enabled,
                       }
            def get_server_info():
                return self.server_last_info
            self.bug_report.init(show_about=False,
                                 get_server_info=get_server_info,
                                 opengl_info=self.opengl_props,
                                 includes=includes)
            self.bug_report.show()
        #gives the server time to send an info response..
        #(by the time the user clicks on copy, it should have arrived, we hope!)
        def got_server_log(filename, filesize):
            log(f"got_server_log({filename!r}, {filesize})")
            filedata = load_binary_file(filename)
            self.bug_report.set_server_log_data(filedata)
        self.download_server_log(got_server_log)
        self.timeout_add(200, init_bug_report)


    def get_image(self, icon_name, size=None):
        try:
            pixbuf = get_icon_pixbuf(icon_name)
            log(f"get_image({icon_name!r}, {size}) pixbuf={pixbuf}")
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except Exception:
            log.error(f"Error: get_image({icon_name!r}, {size})", icon_name, size, exc_info=True)
            return None


    def request_frame_extents(self, window) -> None:
        from xpra.x11.bindings.send_wm import send_wm_request_frame_extents
        from xpra.gtk_common.error import xsync
        root = self.get_root_window()
        with xsync:
            win = window.get_window()
            xid = win.get_xid()
            framelog(f"request_frame_extents({window}) xid={xid:x}")
            send_wm_request_frame_extents(root.get_xid(), xid)

    def get_frame_extents(self, window):
        #try native platform code first:
        x, y = window.get_position()
        w, h = window.get_size()
        v = get_window_frame_size(x, y, w, h)   #pylint: disable=assignment-from-none
        framelog(f"get_window_frame_size{(x, y, w, h)}={v}")
        if v:
            #(OSX does give us these values via Quartz API)
            return v
        if not HAS_X11_BINDINGS:
            #nothing more we can do!
            return None
        from xpra.x11.gtk_x11.prop import prop_get
        gdkwin = window.get_window()
        assert gdkwin
        v = prop_get(gdkwin.get_xid(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        framelog(f"get_frame_extents({window.get_title()})={v}")
        return v

    def get_window_frame_sizes(self):
        wfs = get_window_frame_sizes()
        if self.frame_request_window:
            v = self.get_frame_extents(self.frame_request_window)
            if v:
                try:
                    wm_name = get_wm_name() #pylint: disable=assignment-from-none
                except Exception:
                    wm_name = ""
                try:
                    if len(v)==8:
                        if first_time("invalid-frame-extents"):
                            framelog.warn(f"Warning: invalid frame extents value {v!r}")
                            if wm_name:
                                framelog.warn(f" this is probably a bug in {wm_name!r}")
                            framelog.warn(f" using {v[4:]} instead")
                        v = v[4:]
                    l, r, t, b = v
                    wfs["frame"] = (l, r, t, b)
                    wfs["offset"] = (l, t)
                except Exception as e:
                    framelog.warn(f"Warning: invalid frame extents value {v}")
                    framelog.warn(f" {e}")
                    if wm_name:
                        framelog.warn(f" this is probably a bug in {wm_name!r}")
        framelog(f"get_window_frame_sizes()={wfs}")
        return wfs


    def _add_statusicon_tray(self, tray_list) -> List[Type]:
        #add Gtk.StatusIcon tray, but not under wayland:
        if not is_Wayland():
            try:
                from xpra.client.gtk3.statusicon_tray import GTKStatusIconTray
                if os.environ.get("XDG_SESSION_DESKTOP", "").lower().find("gnome")>=0 or WIN32 or OSX:
                    # unlikely to work, so try last
                    tray_list.append(GTKStatusIconTray)
                else:
                    tray_list.insert(0, GTKStatusIconTray)
            except Exception as e:
                log.warn("failed to load StatusIcon tray: %s" % e)
        return tray_list

    def get_tray_classes(self) -> List[Type]:
        from xpra.client.mixins.tray import TrayClient
        return self._add_statusicon_tray(TrayClient.get_tray_classes(self))

    def get_system_tray_classes(self) -> List[Type]:
        return self._add_statusicon_tray(WindowClient.get_system_tray_classes(self))


    def supports_system_tray(self) -> bool:
        #always True: we can always use Gtk.StatusIcon as fallback
        return True


    def get_root_window(self):
        return get_default_root_window()

    def get_root_size(self):
        return get_root_size()


    def get_raw_mouse_position(self):
        root = self.get_root_window()
        if not root:
            return -1, -1
        return root.get_pointer()[-3:-1]

    def get_mouse_position(self):
        p = self.get_raw_mouse_position()
        return self.cp(p[0], p[1])

    def get_current_modifiers(self) -> List[str]:
        root = self.get_root_window()
        if root is None:
            return []
        modifiers_mask = root.get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)


    def make_hello(self) -> Dict[str,Any]:
        capabilities = UIXpraClient.make_hello(self)
        capabilities["named_cursors"] = len(cursor_types)>0
        capabilities["encoding.transparency"] = self.has_transparency()
        if FULL_INFO>1:
            capabilities.update(flatten_dict(get_gtk_version_info()))
        EXPORT_ICON_DATA = envbool("XPRA_EXPORT_ICON_DATA", FULL_INFO>1)
        if EXPORT_ICON_DATA:
            #tell the server which icons GTK can use
            #so it knows when it should supply one as fallback
            it = Gtk.IconTheme.get_default()
            if it:
                #this would add our bundled icon directory
                #to the search path, but I don't think we have
                #any extra icons that matter in there:
                #from xpra.platform.paths import get_icon_dir
                #d = get_icon_dir()
                #if d not in it.get_search_path():
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
            #this is currently unused, and slightly redundant because of metadata.supported below:
            capabilities["window.states"] = [
                "fullscreen", "maximized",
                "sticky", "above", "below",
                "shaded", "iconified",
                "skip-taskbar", "skip-pager",
                ]
            ms = list(DEFAULT_METADATA_SUPPORTED)
            #4.4:
            ms += ["parent", "relative-position"]
        if POSIX:
            #this is only really supported on X11, but posix is easier to check for..
            #"strut" and maybe even "fullscreen-monitors" could also be supported on other platforms I guess
            ms += ["shaded", "bypass-compositor", "strut", "fullscreen-monitors"]
        if HAS_X11_BINDINGS:
            ms += ["x11-property"]
            if XSHAPE:
                ms += ["shape"]
        log("metadata.supported: %s", ms)
        capabilities["metadata.supported"] = ms
        updict(capabilities, "pointer", {
            "grabs" : True,
            "relative" : True,
            })
        updict(capabilities, "window", {
               "initiate-moveresize"    : True,     #v4 servers assume this is available
               "frame_sizes"            : self.get_window_frame_sizes()
               })
        updict(capabilities, "encoding", {
                    "icons.greedy"      : True,         #we don't set a default window icon any more
                    "icons.size"        : (64, 64),     #size we want
                    "icons.max_size"    : (128, 128),   #limit
                    })
        return capabilities


    def has_transparency(self) -> bool:
        if not envbool("XPRA_ALPHA", True):
            return False
        screen = Gdk.Screen.get_default()
        if screen is None:
            return is_Wayland()
        return screen.get_rgba_visual() is not None


    def get_monitors_info(self) -> Dict[int,Any]:
        return get_monitors_info(self.xscale, self.yscale)

    def get_screen_sizes(self, xscale=1, yscale=1) -> List:
        return get_screen_sizes(xscale, yscale)


    def reset_windows_cursors(self, *_args):
        cursorlog("reset_windows_cursors() resetting cursors for: %s", tuple(self._cursors.keys()))
        for w,cursor_data in tuple(self._cursors.items()):
            self.set_windows_cursor([w], cursor_data)


    def set_windows_cursor(self, windows, cursor_data):
        cursorlog(f"set_windows_cursor({windows}, args[{len(cursor_data)}])")
        cursor = None
        if cursor_data:
            try:
                cursor = self.make_cursor(cursor_data)
                cursorlog(f"make_cursor(..)={cursor}")
            except Exception as e:
                log.warn("error creating cursor: %s (using default)", e, exc_info=True)
            if cursor is None:
                #use default:
                cursor = get_default_cursor()
        for w in windows:
            w.set_cursor_data(cursor_data)
            gdkwin = w.get_window()
            #trays don't have a gdk window
            if gdkwin:
                self._cursors[w] = cursor_data
                gdkwin.set_cursor(cursor)

    def make_cursor(self, cursor_data):
        #if present, try cursor ny name:
        display = Gdk.Display.get_default()
        if not display:
            return
        cursorlog("make_cursor(%s) has-name=%s, has-cursor-types=%s, xscale=%s, yscale=%s, USE_LOCAL_CURSORS=%s",
                  ellipsizer(cursor_data),
                  len(cursor_data)>=10, bool(cursor_types), self.xscale, self.yscale, USE_LOCAL_CURSORS)
        pixbuf = None
        if len(cursor_data)>=10 and cursor_types:
            cursor_name = bytestostr(cursor_data[9])
            if cursor_name and USE_LOCAL_CURSORS:
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
                elif cursor_name not in missing_cursor_names:
                    cursorlog("cursor name '%s' not found", cursor_name)
                    missing_cursor_names.add(cursor_name)
        #create cursor from the pixel data:
        encoding, _, _, w, h, xhot, yhot, serial, pixels = cursor_data[0:9]
        encoding = bytestostr(encoding)
        if encoding!="raw":
            cursorlog.warn("Warning: invalid cursor encoding: %s", encoding)
            return None
        if not pixbuf:
            if not pixels:
                cursorlog.warn("Warning: no cursor pixel data")
                cursorlog.warn(f" in cursor data {cursor_data}")
                return None
            if len(pixels)<w*h*4:
                cursorlog.warn("Warning: not enough pixels provided in cursor data")
                cursorlog.warn(" %s needed and only %s bytes found:", w*h*4, len(pixels))
                cursorlog.warn(" '%s')", repr_ellipsized(hexstr(pixels)))
                return None
            pixbuf = get_pixbuf_from_data(pixels, True, w, h, w*4)
        else:
            w = pixbuf.get_width()
            h = pixbuf.get_height()
            pixels = pixbuf.get_pixels()
        x = max(0, min(xhot, w-1))
        y = max(0, min(yhot, h-1))
        csize = display.get_default_cursor_size()
        cmaxw, cmaxh = display.get_maximal_cursor_size()
        if len(cursor_data)>=12:
            ssize = cursor_data[10]
            smax = cursor_data[11]
            cursorlog("server cursor sizes: default=%s, max=%s", ssize, smax)
        cursorlog("new %s cursor at %s,%s with serial=%#x, dimensions: %sx%s, len(pixels)=%s",
                  encoding, xhot, yhot, serial, w, h, len(pixels))
        cursorlog("default cursor size is %s, maximum=%s", csize, (cmaxw, cmaxh))
        fw, fh = get_fixed_cursor_size()
        if fw>0 and fh>0 and (w!=fw or h!=fh):
            #OS wants a fixed cursor size! (win32 does, and GTK doesn't do this for us)
            if w<=fw and h<=fh:
                cursorlog("pasting %ix%i cursor to fixed OS size %ix%i", w, h, fw, fh)
                try:
                    from PIL import Image  # @UnresolvedImport pylint: disable=import-outside-toplevel
                except ImportError:
                    return None
                img = Image.frombytes("RGBA", (w, h), memoryview_to_bytes(pixels), "raw", "BGRA", w*4, 1)
                target = Image.new("RGBA", (fw, fh))
                target.paste(img, (0, 0, w, h))
                pixels = target.tobytes("raw", "BGRA")
                cursor_pixbuf = get_pixbuf_from_data(pixels, True, fw, fh, fw*4)
            else:
                cursorlog("scaling cursor from %ix%i to fixed OS size %ix%i", w, h, fw, fh)
                cursor_pixbuf = pixbuf.scale_simple(fw, fh, GdkPixbuf.InterpType.BILINEAR)
                xratio, yratio = w/fw, h/fh
                x, y = round(x/xratio), round(y/yratio)
        else:
            sx, sy, sw, sh = x, y, w, h
            #scale the cursors:
            if self.xscale!=1 or self.yscale!=1:
                sx, sy, sw, sh = self.srect(x, y, w, h)
            sw = max(1, sw)
            sh = max(1, sh)
            #ensure we honour the max size if there is one:
            if 0<cmaxw<sw or 0<cmaxh<sh:
                ratio = 1.0
                if cmaxw>0:
                    ratio = max(ratio, w/cmaxw)
                if cmaxh>0:
                    ratio = max(ratio, h/cmaxh)
                cursorlog("clamping cursor size to %ix%i using ratio=%s", cmaxw, cmaxh, ratio)
                sx, sy = round(x/ratio), round(y/ratio)
                sw, sh = min(cmaxw, round(w/ratio)), min(cmaxh, round(h/ratio))
            if sw!=w or sh!=h:
                cursorlog("scaling cursor from %ix%i hotspot at %ix%i to %ix%i hotspot at %ix%i",
                          w, h, x, y, sw, sh, sx, sy)
                cursor_pixbuf = pixbuf.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
                x, y = sx, sy
            else:
                cursor_pixbuf = pixbuf
        if SAVE_CURSORS:
            cursor_pixbuf.savev("cursor-%#x.png" % serial, "png", [], [])
        #clamp to pixbuf size:
        w = cursor_pixbuf.get_width()
        h = cursor_pixbuf.get_height()
        x = max(0, min(x, w-1))
        y = max(0, min(y, h-1))
        try:
            c = Gdk.Cursor.new_from_pixbuf(display, cursor_pixbuf, x, y)
        except RuntimeError as e:
            log.error("Error: failed to create cursor:")
            log.estr(e)
            log.error(" Gdk.Cursor.new_from_pixbuf%s", (display, cursor_pixbuf, x, y))
            log.error(" using size %ix%i with hotspot at %ix%i", w, h, x, y)
            c = None
        return c


    def process_ui_capabilities(self, caps : typedict) -> None:
        UIXpraClient.process_ui_capabilities(self, caps)
        #this requires the "DisplayClient" mixin:
        if not hasattr(self, "screen_size_changed"):
            return
        #always one screen per display:
        screen = Gdk.Screen.get_default()
        screen.connect("size-changed", self.screen_size_changed)


    def window_grab(self, wid, window) -> None:
        em = Gdk.EventMask
        event_mask = (em.BUTTON_PRESS_MASK |
                      em.BUTTON_RELEASE_MASK |
                      em.POINTER_MOTION_MASK  |
                      em.POINTER_MOTION_HINT_MASK |
                      em.ENTER_NOTIFY_MASK |
                      em.LEAVE_NOTIFY_MASK)
        confine_to = None
        cursor = None
        etime = Gtk.get_current_event_time()
        r = Gdk.pointer_grab(window.get_window(), True, event_mask, confine_to, cursor, etime)
        grablog("pointer_grab(..)=%s", GRAB_STATUS_STRING.get(r, r))
        #also grab the keyboard so the user won't Alt-Tab away:
        r = Gdk.keyboard_grab(window.get_window(), False, etime)
        grablog("keyboard_grab(..)=%s", GRAB_STATUS_STRING.get(r, r))
        self._window_with_grab = wid

    def window_ungrab(self) -> None:
        grablog("window_ungrab()")
        etime = Gtk.get_current_event_time()
        Gdk.pointer_ungrab(etime)
        Gdk.keyboard_ungrab(etime)
        self._window_with_grab = 0


    def window_bell(self, window, device, percent:int, pitch:int, duration:int, bell_class, bell_id:int, bell_name:str) -> None:
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = self.get_root_window()
        log(f"window_bell(..) gdkwindow={gdkwindow}")
        if not system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name):
            #fallback to simple beep:
            Gdk.beep()


    def _process_raise_window(self, packet : PacketType) -> None:
        wid = packet[1]
        window = self._id_to_window.get(wid)
        focuslog(f"going to raise window {wid} - {window}")
        if window:
            if window.has_toplevel_focus():
                log("window already has top level focus")
                return
            window.present()

    def _process_restack_window(self, packet : PacketType) -> None:
        wid, detail, other_wid = packet[1:4]
        above = bool(detail==0)
        window = self._id_to_window.get(wid)
        other_window = self._id_to_window.get(other_wid)
        focuslog("restack window %s - %s %s %s",
            wid, window, ["above", "below"][above], other_window)
        if window:
            window.restack(other_window, above)

    def opengl_setup_failure(self, summary = "Xpra OpenGL Acceleration Failure", body="") -> None:
        OK = "0"
        DISABLE = "1"
        def notify_callback(event, nid, action_id, *args):
            log("notify_callback(%s, %s, %s, %s)", event, nid, action_id, args)
            if event=="notification-close":
                return
            if event!="notification-action":
                log.warn(f"Warning: unexpected event {event}")
                return
            if nid!=NotificationID.OPENGL:
                log.warn(f"Warning: unexpected notification id {nid}")
                return
            if action_id==DISABLE:
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
        def delayed_notify():
            if self.exit_code is not None:
                return
            if OSX:
                #don't bother logging an error on MacOS,
                #OpenGL is being deprecated
                log.info(summary)
                log.info(body)
                return
            actions = (OK, "OK", DISABLE, "Don't show this warning again")
            self.may_notify(NotificationID.OPENGL, summary, body, actions,
                            icon_name="opengl", callback=notify_callback)
        #wait for the main loop to run:
        self.timeout_add(2*1000, delayed_notify)

    #OpenGL bits:
    def init_opengl(self, enable_opengl:str) -> None:
        opengllog(f"init_opengl({enable_opengl})")
        #enable_opengl can be True, False, force, probe-failed, probe-success, or None (auto-detect)
        #ie: "on:native,gtk", "auto", "no"
        #ie: "probe-failed:SIGSEGV"
        #ie: "probe-success"
        enable_opengl = (enable_opengl or "")
        parts = enable_opengl.split(":", 1)
        enable_option = parts[0].lower()        #ie: "on"
        opengllog(f"init_opengl: enable_option={enable_option}")
        if enable_option in ("probe-failed", "probe-error", "probe-crash"):
            msg = enable_option.replace("-", " ")
            if len(parts)>1 and any(len(x) for x in parts[1:]):
                msg += ": %s" % csv(parts[1:])
            self.opengl_props["info"] = "disabled, %s" % msg
            self.opengl_setup_failure(body=msg)
            return
        if enable_option in FALSE_OPTIONS:
            self.opengl_props["info"] = "disabled by configuration"
            return
        warnings = []
        self.opengl_props["info"] = ""
        if enable_option=="force":
            self.opengl_force = True
        elif enable_option!="probe-success":
            from xpra.scripts.config import OpenGL_safety_check
            from xpra.platform.gui import gl_check as platform_gl_check
            for check in (OpenGL_safety_check, platform_gl_check):
                opengllog("checking with %s", check)
                warning = check()
                opengllog("%s()=%s", check, warning)
                if warning:
                    warnings.append(warning)

        def err(msg, e):
            opengllog("OpenGL initialization error", exc_info=True)
            self.GLClientWindowClass = None
            self.client_supports_opengl = False
            opengllog.error("%s", msg)
            for x in str(e).split("\n"):
                opengllog.error(" %s", x)
            self.opengl_props["info"] = str(e)
            self.opengl_props["enabled"] = False
            self.opengl_setup_failure(body=str(e))

        if warnings:
            if enable_option in ("", "auto"):
                opengllog.warn("OpenGL disabled:")
                for warning in warnings:
                    opengllog.warn(" %s", warning)
                self.opengl_props["info"] = "disabled: %s" % csv(warnings)
                return
            if enable_option=="probe-success":
                opengllog.warn("OpenGL enabled, despite some warnings:")
            else:
                opengllog.warn("OpenGL safety warning (enabled at your own risk):")
            for warning in warnings:
                opengllog.warn(" %s", warning)
            self.opengl_props["info"] = "enabled despite: %s" % csv(warnings)
        try:
            opengllog("init_opengl: going to import xpra.client.gl")
            __import__("xpra.client.gl", {}, {}, [])
            from xpra.client.gl.window_backend import (
                get_gl_client_window_module,
                test_gl_client_window,
                )
            force_enable = self.opengl_force or (enable_option in TRUE_OPTIONS)
            self.opengl_props, gl_client_window_module = get_gl_client_window_module(force_enable)
            if not gl_client_window_module:
                opengllog.warn("Warning: no OpenGL backend module found")
                self.client_supports_opengl = False
                self.opengl_props["info"] = "disabled: no module found"
                return
            opengllog("init_opengl: found props %s", self.opengl_props)
            self.GLClientWindowClass = gl_client_window_module.GLClientWindow
            self.client_supports_opengl = True
            #only enable opengl by default if force-enabled or if safe to do so:
            self.opengl_enabled = self.opengl_force or enable_option in (list(TRUE_OPTIONS)+["auto"]) or self.opengl_props.get("safe", False)
            self.gl_texture_size_limit = self.opengl_props.get("texture-size-limit", 16*1024)
            self.gl_max_viewport_dims = self.opengl_props.get("max-viewport-dims",
                                                              (self.gl_texture_size_limit, self.gl_texture_size_limit))
            renderer = self.opengl_props.get("renderer", "unknown")
            parts = renderer.split("(")
            if len(parts)>1 and len(parts[0])>10:
                renderer = parts[0].strip()
            driver_info = renderer or self.opengl_props.get("vendor") or "unknown card"
            def disablewarn(msg):
                opengllog.warn("Warning: OpenGL is disabled:")
                opengllog.warn(" %s", msg)
                self.opengl_enabled = False
            if min(self.gl_max_viewport_dims)<4*1024:
                disablewarn("the maximum viewport size is too low: %s" % (self.gl_max_viewport_dims,))
            elif self.gl_texture_size_limit<4*1024:
                disablewarn("the texture size limit is too low: %s" % (self.gl_texture_size_limit,))
            elif driver_info.startswith("SVGA3D") and os.environ.get("WAYLAND_DISPLAY"):
                disablewarn("SVGA3D driver is buggy under Wayland")
            self.GLClientWindowClass.MAX_VIEWPORT_DIMS = self.gl_max_viewport_dims
            self.GLClientWindowClass.MAX_BACKING_DIMS = self.gl_texture_size_limit, self.gl_texture_size_limit
            mww, mwh = self.max_window_size
            opengllog("OpenGL: enabled=%s, texture-size-limit=%s, max-window-size=%s",
                      self.opengl_enabled, self.gl_texture_size_limit, self.max_window_size)
            if self.opengl_enabled and self.gl_texture_size_limit<16*1024 and (mww==0 or mwh==0 or self.gl_texture_size_limit<mww or self.gl_texture_size_limit<mwh):
                #log at warn level if the limit is low:
                #(if we're likely to hit it - if the screen is as big or bigger)
                w, h = self.get_root_size()
                l = opengllog.info
                if w*2<=self.gl_texture_size_limit and h*2<=self.gl_texture_size_limit:
                    l = opengllog
                if w>=self.gl_texture_size_limit or h>=self.gl_texture_size_limit:
                    l = opengllog.warn
                l("Warning: OpenGL windows will be clamped to the maximum texture size %ix%i",
                  self.gl_texture_size_limit, self.gl_texture_size_limit)
                glver = pver(self.opengl_props.get("opengl", ""))
                l(f" for OpenGL {glver} renderer {renderer!r}")
            if self.opengl_enabled and enable_opengl!="probe-success" and not self.opengl_force:
                draw_result = test_gl_client_window(self.GLClientWindowClass, max_window_size=self.max_window_size, pixel_depth=self.pixel_depth)
                if not draw_result.get("success", False):
                    err("OpenGL test rendering failed:", draw_result.get("message", "unknown error"))
                    return
                log("OpenGL test rendering succeeded")
            if self.opengl_enabled:
                opengllog.info(f"OpenGL enabled on {driver_info!r}")
                #don't try to handle video dimensions bigger than this:
                mvs = min(8192, self.gl_texture_size_limit)
                self.video_max_size = (mvs, mvs)
            elif self.client_supports_opengl:
                opengllog(f"OpenGL supported on {driver_info!r}, but not enabled")
            self.opengl_props["enabled"] = self.opengl_enabled
            if self.opengl_enabled and not warnings and OSX:
                #non-opengl is slow on MacOS:
                self.opengl_force = True
        except ImportError as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            err("OpenGL accelerated rendering is not available:", e)
        except RuntimeError as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            err("OpenGL support could not be enabled on this hardware:", e)
        except Exception as e:
            opengllog(f"init_opengl({enable_opengl})", exc_info=True)
            err("Error loading OpenGL support:", e)

    def get_client_window_classes(self, w : int, h : int, metadata : typedict, override_redirect : bool) -> Tuple[Type,...]:
        log("get_client_window_class%s ClientWindowClass=%s, GLClientWindowClass=%s, opengl_enabled=%s, mmap_enabled=%s, encoding=%s",
            (w, h, metadata, override_redirect),
            self.ClientWindowClass, self.GLClientWindowClass,
            self.opengl_enabled, self.mmap_enabled, self.encoding)
        if self.can_use_opengl(w, h, metadata, override_redirect):
            return (self.GLClientWindowClass, self.ClientWindowClass)
        return (self.ClientWindowClass,)

    def can_use_opengl(self, w : int, h : int, metadata : typedict, override_redirect : bool) -> bool:
        if self.GLClientWindowClass is None or not self.opengl_enabled:
            return False
        if not self.opengl_force:
            #verify texture limits:
            ms = min(self.sx(self.gl_texture_size_limit), *self.gl_max_viewport_dims)
            if w>ms or h>ms:
                return False
            #avoid opengl for small windows:
            if w<=OPENGL_MIN_SIZE or h<=OPENGL_MIN_SIZE:
                log("not using opengl for small window: %ix%i", w, h)
                return False
            #avoid opengl for tooltips:
            window_types = metadata.strtupleget("window-type")
            if any(x in (NO_OPENGL_WINDOW_TYPES) for x in window_types):
                log("not using opengl for %s window-type", csv(window_types))
                return False
            if metadata.intget("transient-for", 0)>0:
                log("not using opengl for transient-for window")
                return False
            if metadata.strget("content-type", "").find("text")>=0:
                return False
        if WIN32:
            #these checks can't be forced ('opengl_force')
            #win32 opengl just doesn't do alpha or undecorated windows properly:
            if override_redirect:
                return False
            if metadata.boolget("has-alpha", False):
                return False
            if not metadata.boolget("decorations", True):
                return False
            hbl = (self.headerbar or "").lower().strip()
            if hbl not in FALSE_OPTIONS:
                #any risk that we may end up using headerbar,
                #means we can't enable opengl
                return False
        return True

    def toggle_opengl(self, *_args) -> None:
        self.opengl_enabled = not self.opengl_enabled
        opengllog("opengl_toggled: %s", self.opengl_enabled)
        #now replace all the windows with new ones:
        for wid, window in tuple(self._id_to_window.items()):
            self.reinit_window(wid, window)
        opengllog("replaced all the windows with opengl=%s: %s", self.opengl_enabled, self._id_to_window)
        self.reinit_window_icons()


    def find_window(self, metadata, metadata_key="transient-for"):
        fwid = metadata.intget(metadata_key, -1)
        log("find_window(%s, %s) wid=%s", metadata, metadata_key, fwid)
        if fwid>0:
            return self._id_to_window.get(fwid)
        return None

    def find_gdk_window(self, metadata, metadata_key="transient-for"):
        client_window = self.find_window(metadata, metadata_key)
        if client_window:
            gdk_window = client_window.get_window()
            if gdk_window:
                return gdk_window
        return None

    def get_group_leader(self, wid:int, metadata, _override_redirect):
        def find_gdk_window(metadata_key="transient-for"):
            return self.find_gdk_window(metadata, metadata_key)
        win = find_gdk_window("group-leader-wid") or find_gdk_window("transient-for") or find_gdk_window("parent")
        log(f"get_group_leader(..)={win}")
        if win:
            return win
        pid = metadata.intget("pid", -1)
        leader_xid = metadata.intget("group-leader-xid", -1)
        log(f"get_group_leader: leader pid={pid}, xid={leader_xid}")
        reftype = "xid"
        ref = leader_xid
        if ref<0:
            ci = metadata.strtupleget("class-instance")
            if ci:
                reftype = "class"
                ref = "|".join(ci)
            elif pid>0:
                reftype = "pid"
                ref = pid
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
        #group_leader_window = Gdk.Window(None, 1, 1, Gtk.WindowType.TOPLEVEL, 0, Gdk.INPUT_ONLY, title)
        #static new(parent, attributes, attributes_mask)
        group_leader_window = GDKWindow(wclass=Gdk.WindowWindowClass.INPUT_ONLY, title=title)
        self._ref_to_group_leader[refkey] = group_leader_window
        #avoid warning on win32...
        if not WIN32:
            #X11 spec says window should point to itself:
            group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid:int, window) -> None:
        #override so we can cleanup the group-leader if needed,
        WindowClient.destroy_window(self, wid, window)
        group_leader = window.group_leader
        if group_leader is None or not self._group_leader_wids:
            return
        wids = self._group_leader_wids.get(group_leader)
        if wids is None:
            #not recorded any window ids on this group leader
            #means it is another managed window, leave it alone
            return
        if wid in wids:
            wids.remove(wid)
        if wids:
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


    def setup_clipboard_helper(self, helperClass):
        from xpra.client.mixins.clipboard import ClipboardClient
        ch = ClipboardClient.setup_clipboard_helper(self, helperClass)
        #check for loops after handshake:
        def register_clipboard_toggled(*_args):
            def clipboard_toggled(*_args):
                #reset tray icon:
                self.local_clipboard_requests = 0
                self.remote_clipboard_requests = 0
                self.clipboard_notify(0)
            self.connect("clipboard-toggled", clipboard_toggled)
        self.after_handshake(register_clipboard_toggled)
        if self.server_clipboard:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.clipboard_toggled)
        return ch

    def cancel_clipboard_notification_timer(self) -> None:
        cnt = self.clipboard_notification_timer
        if cnt:
            self.clipboard_notification_timer = 0
            self.source_remove(cnt)

    def clipboard_notify(self, n:int) -> None:
        tray = self.tray
        if not tray or not CLIPBOARD_NOTIFY:
            return
        clipboardlog(f"clipboard_notify({n}) notification timer={self.clipboard_notification_timer}")
        self.cancel_clipboard_notification_timer()
        if n>0 and self.clipboard_enabled:
            self.last_clipboard_notification = monotonic()
            tray.set_icon("clipboard")
            tray.set_tooltip(f"{n} clipboard requests in progress")
            tray.set_blinking(True)
        else:
            #no more pending clipboard transfers,
            #reset the tray icon,
            #but wait at least N seconds after the last clipboard transfer:
            N = 1
            delay = max(0, round(1000*(self.last_clipboard_notification+N-monotonic())))
            def reset_tray_icon():
                self.clipboard_notification_timer = 0
                tray = self.tray
                if not tray:
                    return
                tray.set_icon(None)    #None means back to default icon
                tray.set_tooltip(self.get_tray_title())
                tray.set_blinking(False)
            self.clipboard_notification_timer = self.timeout_add(delay, reset_tray_icon)
