# This file is part of Xpra.
# Copyright (C) 2018-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from datetime import datetime
from subprocess import check_call
from collections.abc import Callable

from xpra.os_util import POSIX, gi_import
from xpra.util.env import osexpand
from xpra.util.parsing import parse_simple_dict
from xpra.util.thread import start_thread
from xpra.scripts.config import make_defaults_struct
from xpra.log import Logger

log = Logger("util")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")


DISCLAIMER = """
IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES(INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT(INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""".replace("\n", "")


def sync() -> None:
    if POSIX:
        check_call("sync")


def get_user_config_file() -> str:
    from xpra.platform.paths import get_user_conf_dirs
    return osexpand(os.path.join(get_user_conf_dirs()[0], "conf.d", "99_configure_tool.conf"))


def parse_user_config_file() -> dict[str, str | list[str]]:
    filename = get_user_config_file()
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf8") as f:
        data = f.read().replace("\r", "\n")
        return parse_simple_dict(data, sep="\n")


def save_user_config_file(options: dict) -> None:
    filename = get_user_config_file()
    conf_dir = os.path.dirname(filename)
    if not os.path.exists(conf_dir):
        os.mkdir(conf_dir, mode=0o755)
    with open(filename, "w", encoding="utf8") as f:
        f.write("# generated on " + datetime.now().strftime("%c")+"\n\n")
        for k, v in options.items():
            f.write(f"{k} = {v}\n")


def update_config_attribute(attribute: str, value) -> None:
    log(f"update config: {attribute}={value}")
    config = parse_user_config_file()
    config[attribute] = str(value)
    save_user_config_file(config)


def with_config(cb: Callable) -> None:
    # load config in a thread as this involves IO,
    # then run the callback in the UI thread
    def load_config():
        defaults = make_defaults_struct()
        GLib.idle_add(cb, defaults)

    start_thread(load_config, "load-config", daemon=True)


def run_gui(gui_class) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk.signals import install_signal_handlers
    with program_context("xpra-configure-gui", "Xpra Configure GUI"):
        enable_color()
        init()
        gui = gui_class()
        install_signal_handlers("xpra-configure-gui", gui.app_signal)
        ready()
        gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0
