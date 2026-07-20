# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket
import shlex
import subprocess

from xpra.platform.paths import get_xpra_command, get_nodock_command
from xpra.platform.dotxpra import DotXpra
from xpra.platform.gui import force_focus
from xpra.util.child_reaper import get_child_reaper
from xpra.exit_codes import exit_str
from xpra.scripts.config import OPTION_TYPES
from xpra.scripts.args import get_command_args
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import scaled_image, imagebutton, label, modify_fg, color_parse
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.util.glib import register_os_signals
from xpra.gtk.dialogs.util import hb_button
from xpra.net.constants import SocketState
from xpra.net.session_discovery import SessionEndpoint, SessionGroup, endpoint_uri, group_session_endpoints
from xpra.exit_codes import ExitCode, ExitValue
from xpra.util.system import stop_proc, get_platform_icon_name
from xpra.os_util import gi_import, WIN32, getuid, getgid
from xpra.util.env import IgnoreWarningsContext, get_saved_env
from xpra.util.i18n import _
from xpra.util.thread import check_main_thread
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
Gio = gi_import("Gio")

log = Logger("client", "util")


def pil_image_to_pixbuf(img):
    from xpra.codecs.image import to_png
    from xpra.gtk.pixbuf import GdkPixbuf
    data = to_png(img.convert("RGBA"))
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    return loader.get_pixbuf()


def get_session_info(sockpath: str) -> dict:
    # the lazy way using a subprocess
    if WIN32:
        socktype = "named-pipe"
    else:
        socktype = "socket"
    cmd = get_nodock_command() + ["id", f"{socktype}:{sockpath}"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout = p.communicate()[0]
    log("get_sessions_info(%s) returncode(%s)=%s", sockpath, cmd, p.returncode)
    if p.returncode != 0:
        return {}
    info: dict = {}
    for line in stdout.splitlines():
        parts = line.split("=", 1)
        if len(parts) == 2:
            info[parts[0]] = parts[1]
    icon = get_session_icon(sockpath, socktype)
    if icon is not None:
        info["icon"] = icon
    log("get_sessions_info(%s)=%s", sockpath, info)
    return info


def get_session_icon(sockpath: str, socktype: str):
    cmd = get_nodock_command() + ["icon", "-", f"{socktype}:{sockpath}"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        blob, _ = p.communicate()
        log("get_session_icon(%s) returncode(%s)=%s, %i bytes", sockpath, cmd, p.returncode, len(blob or b""))
        if p.returncode != 0 or not blob:
            return None
        from io import BytesIO
        from PIL import Image
        return Image.open(BytesIO(blob))
    except Exception as e:
        log("get_session_icon(%s)", sockpath, exc_info=True)
        log.warn("Warning: failed to load session icon for %s: %s", sockpath, e)
        return None


class SessionsGUI(Gtk.Window):

    def __init__(self, options, title="Xpra Session Browser"):
        check_main_thread()
        super().__init__()
        title = _(title)
        self.options = options
        self.exit_code = ExitCode.OK
        self.set_title(title)
        self.set_border_width(20)
        self.set_resizable(True)
        self.set_default_size(800, 220)
        self.set_decorated(True)
        self.set_size_request(800, 220)
        self.set_position(Gtk.WindowPosition.CENTER)
        with IgnoreWarningsContext():
            self.set_wmclass("xpra-sessions-gui", "Xpra-Sessions-GUI")
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)
        icon = get_icon_pixbuf("browse.png")
        if icon:
            self.set_icon(icon)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Xpra"
        hb.add(hb_button(_("About"), "help-about", self.show_about))
        hb.show_all()
        self.set_titlebar(hb)

        self.clients = {}
        self.clients_disconnecting = set()

        self.vbox = Gtk.VBox(homogeneous=False, spacing=20)
        self.add(self.vbox)

        title_label = label(title, font="sans 14")
        title_label.show()
        self.vbox.add(title_label)

        self.warning = label(" ")
        modify_fg(self.warning, color_parse("red"))
        self.warning.show()
        self.vbox.add(self.warning)

        self.password_box = Gtk.HBox(homogeneous=False, spacing=10)
        self.password_label = label(_("Password:"))
        al = Gtk.Alignment(xalign=1, yalign=0.5)
        al.add(self.password_label)
        al.show()
        self.password_box.add(al)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_max_length(128)
        self.password_entry.set_width_chars(16)
        self.password_entry.set_visibility(False)
        al = Gtk.Alignment(xalign=0, yalign=0.5)
        al.add(self.password_entry)
        al.show()
        self.password_box.add(al)
        self.vbox.add(self.password_box)

        self.contents = None
        self.endpoints: list[SessionEndpoint] = []
        try:
            from xpra.platform.info import get_username
            username = get_username()
        except OSError:
            username = ""
        self.local_info_cache = {}
        self.dotxpra = DotXpra(options.socket_dirs, username)
        self.poll_local_sessions()
        self.populate()
        GLib.timeout_add(5 * 1000, self.update)
        self.vbox.show()
        self.show()

    def show(self) -> None:  # pylint: disable=arguments-differ
        super().show()

        def show() -> None:
            force_focus()
            self.present()

        GLib.idle_add(show)

    def quit(self, *args) -> None:
        log("quit%s", args)
        GLib.idle_add(self.do_quit)

    def do_quit(self) -> None:
        log("do_quit()")
        self.cleanup()
        Gtk.main_quit()

    def app_signal(self, signum) -> None:
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.do_quit()

    def cleanup(self) -> None:
        self.close()

    def show_about(self, *_args) -> None:
        from xpra.gtk.dialogs.about import about
        about(parent=self)

    def update(self) -> bool:
        if self.poll_local_sessions():
            self.populate()
        return True

    def populate(self) -> None:
        self.populate_table()

    def poll_local_sessions(self) -> bool:
        # TODO: run in a thread so we don't block the UI thread!
        d = self.dotxpra.socket_details(matching_state=SocketState.LIVE)
        log("poll_local_sessions() socket_details=%s", d)
        info_cache = {}
        for d, details in d.items():
            log("poll_local_sessions() %s : %s", d, details)
            for state, display, sockpath in details:
                assert state == SocketState.LIVE
                key = (display, sockpath)
                info = self.local_info_cache.get(key)
                if not info:
                    # try to query it
                    try:
                        info = get_session_info(sockpath)
                        if not info:
                            log(" no data for '%s'", sockpath)
                            continue
                        if info.get("session-type") == "client":
                            log(" skipped client socket '%s': %s", sockpath, info)
                            continue
                    except Exception as e:
                        log("get_session_info(%s)", sockpath, exc_info=True)
                        log.error("Error querying session info for %s", sockpath)
                        log.estr(e)
                        del e
                    if not info:
                        continue
                info_cache[key] = info
        if WIN32:
            socktype = "named-pipe"
        else:
            socktype = "socket"

        def make_text(info: dict) -> dict:
            text = {"mode": socktype}
            for k, name in {
                "platform": "platform",
                "uuid": "uuid",
                "display": "display",
                "session-type": "type",
                "session-name": "name",
                "icon": "icon",
            }.items():
                v = info.get(k)
                if v is not None:
                    text[name] = v
            return text

        # first remove any records that are no longer found:
        for key in self.local_info_cache:
            if key not in info_cache:
                _display, sockpath = key
                self.endpoints = [
                    endpoint for endpoint in self.endpoints
                    if endpoint.protocol != "socket" or endpoint.domain != "local" or endpoint.address != sockpath
                ]
        # add the new ones:
        for key, info in info_cache.items():
            if key not in self.local_info_cache:
                _display, sockpath = key
                self.endpoints.append(SessionEndpoint(
                    source="local",
                    interface="",
                    protocol="socket",
                    domain="local",
                    host=socket.gethostname(),
                    address=sockpath,
                    text=make_text(info),
                ))
        log("poll_local_sessions() info_cache=%s", info_cache)
        changed = self.local_info_cache != info_cache
        self.local_info_cache = info_cache
        return changed

    def populate_table(self) -> None:
        log("populate_table: %i endpoints", len(self.endpoints))
        if self.contents:
            self.vbox.remove(self.contents)
            self.contents = None
        if not self.endpoints:
            self.contents = label(_("No sessions found"))
            self.vbox.add(self.contents)
            self.contents.show()
            self.set_size_request(440, 200)
            self.password_box.hide()
            return
        self.password_box.show()
        self.set_size_request(-1, -1)
        grid = Gtk.Grid()

        def l(s="") -> Gtk.Label:  # noqa: E743
            widget = label(s)
            widget.set_margin_start(5)
            widget.set_margin_end(5)
            return widget

        for i, text in enumerate(_(x) for x in ("Host", "Display", "Name", "Icon", "Type", "URI", "Connect", "Open in Browser")):
            grid.attach(l(text), i, 1, 1, 1)
        row = 2
        for key, session in group_session_endpoints(self.endpoints).items():
            if isinstance(key, tuple):
                title = f"{session.host} : {session.display}"
            else:
                title = session.host
            host_label = l(title)
            if session.uuid != title:
                host_label.set_tooltip_text(session.uuid)
            pwidget = None
            if session.icon is not None:
                pwidget = scaled_image(pil_image_to_pixbuf(session.icon), 28)
            if not pwidget:
                # try to use an icon for the platform:
                platform_icon_name = get_platform_icon_name(session.platform)
                if platform_icon_name:
                    pwidget = scaled_image(get_icon_pixbuf("%s.png" % platform_icon_name), 28)
                    if pwidget:
                        pwidget.set_tooltip_text(platform_icon_name)
            if not pwidget:
                pwidget = l(session.platform)
            w, c, b = self.make_connect_widgets(session)
            widgets = (
                host_label,
                l(session.display),
                l(session.session_name),
                pwidget,
                l(session.session_type),
                w,
                c,
                b,
            )
            for x, widget in enumerate(widgets):
                grid.attach(widget, x, row, 1, 1)
            row += 1
        grid.show_all()
        self.contents = grid
        self.vbox.add(grid)

    def attach(self, key, uri: str) -> None:
        self.warning.set_text("")
        # preserve ssl command line arguments
        option_types = {k: v for k, v in OPTION_TYPES.items() if k.startswith("ssl")}
        cmd = get_xpra_command() + ["attach", uri] + get_command_args(
            self.options,
            uid=getuid(), gid=getgid(),
            option_types=option_types,
            cmdline=sys.argv,
        )
        cmd_str = shlex.join(cmd)
        env = get_saved_env()
        env["XPRA_NOTTY"] = "1"
        try:
            proc = subprocess.Popen(cmd, env=env)
        except OSError as e:
            log.error("Error: failed to launch client command:")
            log.error(" %s", cmd_str)
            log.estr(e)
            self.warning.set_text(str(e))
            return
        log("attach() %s=%s", cmd_str, proc)

        def proc_exit(*args) -> None:
            log("proc_exit%s", args)
            c = proc.poll()
            if key in self.clients_disconnecting:
                self.clients_disconnecting.remove(key)
            elif c not in (0, None):
                log.warn("Warning: client command exited with code %s:", c)
                log.warn(" %s", cmd_str)
                self.warning.set_text(exit_str(c).replace("_", " "))
            if self.clients.pop(key, None):
                def update() -> None:
                    self.update()
                    self.populate()

                GLib.idle_add(update)

        get_child_reaper().add_process(proc, "client-%s" % uri, cmd, True, True, proc_exit)
        self.clients[key] = proc
        self.populate()

    def browser_open(self, endpoint: SessionEndpoint) -> None:
        import webbrowser
        password = self.password_entry.get_text()
        url = endpoint_uri(password, endpoint)
        if url.startswith("wss"):
            url = "https" + url[3:]
        else:
            assert url.startswith("ws")
            url = "http" + url[2:]
        # trim end of URL:
        #  http://192.168.1.7:10000/10 -> http://192.168.1.7:10000/
        url = url[:url.rfind("/")]
        webbrowser.open_new_tab(url)

    def make_connect_widgets(self, session: SessionGroup) -> tuple:
        key = session.key
        endpoints = session.endpoints
        d = {}
        proc = self.clients.get(key)
        if proc and proc.poll() is None:
            icon = get_icon_pixbuf("disconnected.png")

            def disconnect_client(btn) -> None:
                log("disconnect_client(%s) proc=%s", btn, proc)
                self.clients_disconnecting.add(key)
                stop_proc(proc, "client")
                self.populate()

            btn = imagebutton(_("Disconnect"), icon, clicked_callback=disconnect_client)
            return label(_("Already connected with pid=%i") % proc.pid), btn, label("")

        icon = get_icon_pixbuf("browser.png")
        bopen = imagebutton(_("Open"), icon)

        icon = get_icon_pixbuf("connect.png")
        if len(endpoints) == 1:
            # single record, single uri:
            endpoint = endpoints[0]
            uri = endpoint_uri("", endpoint)
            bopen.set_sensitive(uri.startswith("ws"))

            def browser_open(*_args) -> None:
                self.browser_open(endpoint)

            bopen.connect("clicked", browser_open)
            d[uri] = endpoint

            def clicked(*_args) -> None:
                password = self.password_entry.get_text()
                uri = endpoint_uri(password, endpoint)
                self.attach(key, uri)

            btn = imagebutton(_("Connect"), icon, clicked_callback=clicked)
            return label(uri), btn, bopen

        # multiple modes / uris
        uri_menu = Gtk.ComboBoxText()
        uri_menu.set_size_request(340, 48)
        # sort by protocol so TCP comes first
        order = {"socket": 0, "ssh": 1, "tcp": 2, "ssl": 3, "ws": 4, "wss": 8}
        if WIN32:
            # on MS Windows, prefer ssh which has a GUI for accepting keys
            # and entering the password:
            order["ssh"] = 0

        def cmp_key(endpoint: SessionEndpoint) -> str:
            mode = endpoint.mode
            host = endpoint.address
            host_len = len(host)
            # log("cmp_key(%s) text=%s, mode=%s, host=%s, host_len=%s", v, text, mode, host, host_len)
            # prefer order (from mode), then shorter host string:
            return "%s-%s" % (order.get(mode, mode), host_len)

        sendpoints = sorted(endpoints, key=cmp_key)
        has_ws = False
        for endpoint in sendpoints:
            uri = endpoint_uri("", endpoint)
            uri_menu.append_text(uri)
            d[uri] = endpoint
            if uri.startswith("ws"):
                has_ws = True

        def connect(*_args) -> None:
            uri = uri_menu.get_active_text()
            endpoint = d[uri]
            password = self.password_entry.get_text()
            uri = endpoint_uri(password, endpoint)
            self.attach(key, uri)

        uri_menu.set_active(0)
        btn = imagebutton(_("Connect"), icon, clicked_callback=connect)

        def uri_changed(*_args) -> None:
            uri = uri_menu.get_active_text()
            ws = uri.startswith("ws")
            bopen.set_sensitive(ws)
            if ws:
                bopen.set_tooltip_text("")
            elif not has_ws:
                bopen.set_tooltip_text(_("no 'ws' or 'wss' URIs found"))
            else:
                bopen.set_tooltip_text(_("select a 'ws' or 'wss' URI"))

        uri_menu.connect("changed", uri_changed)
        uri_changed()

        def browser_open_option(*_args) -> None:
            uri = uri_menu.get_active_text()
            endpoint = d[uri]
            self.browser_open(endpoint)

        bopen.connect("clicked", browser_open_option)
        return uri_menu, btn, bopen


def do_main(opts) -> ExitValue:
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.gtk.util import quit_on_signals, gtk_main
    with program_context("Xpra-Session-Browser", _("Xpra Session Browser")):
        enable_color()
        quit_on_signals("session-browser")
        gui = SessionsGUI(opts)
        register_os_signals(gui.app_signal)
        gtk_main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return gui.exit_code


def main() -> ExitValue:  # pragma: no cover
    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    return do_main(opts)


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
