# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from typing import Iterable

from xpra.os_util import gi_import, getuid
from xpra.util.system import is_distribution_variant
from xpra.util.thread import start_thread
from xpra.util.io import get_status_output, which
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


SUPPORTED_RPM_DISTROS = ("Fedora", "CentOS", "RedHat", "AlmaLinux", "RockyLinux", "OracleLinux")
SUPPORTED_DEB_DISTROS = ("Debian", "Ubuntu")
SUPPORTED_DISTROS = SUPPORTED_RPM_DISTROS + SUPPORTED_DEB_DISTROS


def get_terminal() -> str:
    # solution based on https://github.com/i3/i3/blob/next/i3-sensible-terminal
    for terminal in (
        os.environ.get("TERMINAL", ""),
        "x-terminal-emulator",
        "mate-terminal", "gnome-terminal",
        "terminator", "xfce4-terminal", "urxvt", "rxvt", "termit",
        "Eterm", "aterm", "uxterm", "xterm", "roxterm", "termite",
        "lxterminal", "terminology", "st", "qterminal", "lilyterm",
        "tilix", "terminix", "konsole", "kitty", "guake", "tilda",
        "alacritty", "hyper", "wezterm", "rio",
    ):
        if terminal:
            cmd = which(terminal)
            if cmd:
                return cmd
    return ""


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.terminal = get_terminal()
        self.sudo = which("sudo")
        self.package_switch: dict[str, Gtk.Switch] = {}
        self.package_system = ""
        self.initial_state: dict[str, bool] = {}
        self.current_state: dict[str, bool] = {}
        self.apply_button = None
        super().__init__(
            "Install or remove Xpra Packages",
            "package.png",
            wm_class=("xpra-configure-packages-gui", "Xpra Configure Packages GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        self.add_widget(label("Install or remove xpra packages", font="sans 20"))

        def fail(messages: Iterable[str]) -> None:
            self.populate_form(messages, ("Exit", self.dismiss))
        if not self.terminal:
            fail((
                "Unable to locate a terminal application to use.",
                "Either install a commonly used one (ie: `xterm`),",
                "or set the `TERMINAL` environment variable.",
                ""))
            return
        if not self.sudo and getuid() != 0:
            fail((
                "Unable to locate `sudo`.",
                ""))
            return

        if not any(is_distribution_variant(x) for x in SUPPORTED_DISTROS):
            url = "https://github.com/Xpra-org/xpra/wiki/Platforms"
            fail((
                "Sorry, this tool is not supported on your distribution.",
                "",
                f"Plaase see <a href='{url}'>support platforms</a>",
                ""))
            return
        if any(is_distribution_variant(x) for x in SUPPORTED_RPM_DISTROS):
            pkgcmd = "dnf"
            querycmd = "rpm"
            self.package_system = "dnf"
        else:
            pkgcmd = "apt"
            querycmd = "dpkg"
            self.package_system = "apt"
        pkgcmd_path = which(pkgcmd)
        if not pkgcmd_path:
            fail((
                f"Unable to locate the {pkgcmd!r} command.",
                ""))
            return
        querycmd_path = which(querycmd)
        if not querycmd_path:
            fail((
                f"Unable to locate the {querycmd!r} command.",
                ""))
            return
        lines = (
            "This tool can be used to add or remove a complete set of features.",
            "This is somewhat similar to turning features on or off,",
            "but in a more global and definitive way.",
            "This requires super-user privileges via `sudo` for regular users.",
        )
        text = "\n".join(lines)
        lbl = label(text, font="Sans 14")
        lbl.set_line_wrap(True)
        lbl.set_use_markup(True)
        self.add_widget(lbl)

        grid = Gtk.Grid()
        grid.set_margin_start(40)
        grid.set_margin_end(40)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)

        for i, (package, description) in enumerate(
                {
                    "Client": "For connecting to servers",
                    "Client GTK3": "The main xpra client",
                    "HTML5": "The html5 client",
                    "Server": "For creating sessions",
                    "X11": "X11 component for both clients and servers",
                    "Audio": "Audio support: forwarding of speaker and microphone",
                    "Codecs": "Core picture compression codecs",
                    "Codecs Extras": "video compression codecs with heavier footprint and / or licensing requirements",
                    "Codecs NVidia": "extra proprietary NVidia codecs",
                }.items()
        ):
            pkg = package.lower().replace(" ", "-")
            lbl = label(package, tooltip=description)
            lbl.set_hexpand(True)
            # this causes the Switch to be displayed wrong!
            # lbl.set_halign(Gtk.Align.START)
            grid.attach(lbl, 0, i, 1, 1)
            switch = Gtk.Switch()
            switch.set_sensitive(False)
            grid.attach(switch, 1, i, 1, 1)
            self.package_switch[pkg] = switch

        self.apply_button = self.add_buttons(
            ("Exit", self.dismiss),
            ("Apply", self.apply),
        )[1]
        self.apply_button.set_sensitive(False)

        self.show_all()
        start_thread(self.query_packages, "query-packages", daemon=True)

    def query_packages(self, connect=True) -> None:
        if self.package_system == "dnf":
            cmd = "rpm -qa"
        else:
            cmd = "dpkg --list | awk '{print $2}'"
        r, out, err = get_status_output(cmd, shell=True)
        if r:
            log.error("Error: failed to retrieve the list of packages")
            log.error(f" err={err}")
            return
        package_list = sorted(out.replace("\r", "\n").split("\n"))
        log(f"{package_list=}")

        def find_package(name: str) -> bool:
            if name in package_list:
                return True
            partial = [x for x in package_list if x.startswith(name)]
            # ie: "xpra-6.0-r36666.x86_64"
            for x in partial:
                remainder = x[len(name):]
                if remainder[0] != "-":
                    continue
                # make sure the next part is a number:
                # `xpra-codecs-extras` should not match `xpra-codecs`
                # but `xpra-codecs-6.0` should match `xpra-codecs`
                if remainder[1] in "0123456789":
                    return True
            return False

        for package, switch in self.package_switch.items():
            found = find_package(f"xpra-{package}")
            self.initial_state[package] = found
            self.current_state[package] = found
            switch.set_state(found)
            if connect:
                switch.connect("state-set", self.toggle_package, package)
            switch.set_sensitive(True)

    def sync_switches(self) -> None:
        for package, switch in self.package_switch.items():
            state = self.current_state[package]
            if switch.get_state() != state:
                switch.set_state(state)

    def toggle_package(self, widget, state, package: str) -> None:
        if not widget.get_sensitive():
            return
        enabled = bool(state)
        self.current_state[package] = enabled
        # now toggle any packages depending on this one:
        # ie: xpra-codecs-extras depends on xpra-coddecs
        if enabled:
            for k in self.current_state.keys():
                if package.startswith(k) and k != package:
                    # if `xpra-codecs-extras` was enabled, enable `xpra-codecs`:
                    self.current_state[k] = True
        else:
            for k in self.current_state.keys():
                if k.startswith(package) and k != package:
                    # if `xpra-codecs` was disabled, disable `xpra-codecs-extras`:
                    self.current_state[k] = False
        self.sync_switches()
        self.apply_button.set_sensitive(self.current_state != self.initial_state)
        log("toggle_package%s", (widget, state, package))

    def apply(self, *_args) -> None:
        remove = [
            f"xpra-{x}" for x in self.initial_state.keys()
            if self.initial_state[x] and not self.current_state[x]
        ]
        install = [
            f"xpra-{x}" for x in self.initial_state.keys()
            if not self.initial_state[x] and self.current_state[x]
        ]
        log(f"apply: {remove=}, {install=}")
        command = [self.sudo] if getuid() > 0 else []
        command += [self.terminal, "-e"]
        package_commands = []
        if remove:
            package_commands.append(f"{self.package_system} remove " + " ".join(remove))
        if install:
            package_commands.append(f"{self.package_system} install " + " ".join(install))
        # ie: shell_command = "dnf remove xpra-html5;dnf install xpra-client"
        shell_command = shlex.quote(";".join(package_commands))
        command += [f"bash -c {shell_command}"]
        log(f"{command=}")

        def update_packages() -> None:
            r = get_status_output(command)[0]
            log(f"update_packages() {command=} returned {r}")
            self.query_packages(False)
        self.apply_button.set_sensitive(False)
        start_thread(update_packages, "update-packages", daemon=True)


def main(_args) -> int:
    from xpra.gtk.configure.common import run_gui
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
