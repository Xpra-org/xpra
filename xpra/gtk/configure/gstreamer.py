# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import sleep
from textwrap import wrap
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.util.env import envint
from xpra.util.str_fn import csv
from xpra.util.thread import start_thread
from xpra.gtk.configure.common import run_gui
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label
from xpra.platform.paths import get_image
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("gstreamer", "util")

STEP_DELAY = envint("XPRA_CONFIGURE_STEP_DELAY", 100)


def _set_labels_text(widgets, *messages: str) -> None:
    for i, widget in enumerate(widgets):
        if i < len(messages):
            widget.set_text(messages[i])
        else:
            widget.set_text("")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.warning_pixbuf = get_image("warning.png")
        size = (800, 554)
        if self.warning_pixbuf:
            size = self.warning_pixbuf.get_width() + 20, self.warning_pixbuf.get_height() + 20
        self.layout = None
        self.warning_labels: list[Gtk.Label] = []
        self.labels: list[Gtk.Label] = []
        self.buttons: list[Gtk.Button] = []
        self.elements: Sequence[str] = ()
        super().__init__(
            "Configure Xpra's GStreamer Codecs",
            "gstreamer.png",
            wm_class=("xpra-configure-gstreamer-gui", "Xpra Configure GStreamer GUI"),
            default_size=size,
            header_bar=(False, False),
            parent=parent,
        )
        self.set_resizable(False)

    def add_layout(self) -> None:
        if not self.layout:
            layout = Gtk.Layout()
            layout.set_margin_top(0)
            layout.set_margin_bottom(0)
            layout.set_margin_start(0)
            layout.set_margin_end(0)
            self.layout = layout
            self.vbox.add(layout)

    def populate(self) -> None:
        self.set_box_margin(0, 0, 0, 0)
        self.add_layout()
        if self.warning_pixbuf:
            image = Gtk.Image.new_from_pixbuf(self.warning_pixbuf)
            self.layout.put(image, 0, 0)
        for i in range(3):
            lbl = label("", font="Sans 22")
            self.warning_labels.append(lbl)
            self.layout.put(lbl, 86, 70 + i * 40)
        for i in range(11):
            lbl = label("", font="Sans 12")
            self.layout.put(lbl, 78, 180 + i * 24)
            self.labels.append(lbl)

        self.set_warning_labels(
            "This tool can cause your system to crash,",
            "it may even damage hardware in rare cases.",
            "            Use with caution.",
        )
        self.set_labels("", "", *wrap(DISCLAIMER))
        self.add_buttons(
            ("Understood", self.detect_elements),
            ("Get me out of here", self.dismiss)
        )

    def set_warning_labels(self, *messages) -> None:
        _set_labels_text(self.warning_labels, *messages)

    def set_labels(self, *messages) -> None:
        _set_labels_text(self.labels, *messages)

    def add_buttons(self, *buttons) -> list[Gtk.Button]:
        # remove existing buttons:
        for button in self.buttons:
            self.layout.remove(button)
        i = 0
        x = 400 - 100 * len(buttons)
        for text, callback in buttons:
            button = Gtk.Button.new_with_label(text)
            button.connect("clicked", callback)
            button.show()
            self.buttons.append(button)
            self.layout.put(button, x + 200 * i, 450)
            i += 1
        return self.buttons

    def detect_elements(self, *_args) -> None:
        self.set_warning_labels(
            "Probing the GStreamer elements available,",
            "please wait.",
        )
        self.set_labels()
        self.add_buttons(("Abort and exit", self.dismiss))
        messages: list[str] = []

        def update_messages() -> None:
            sleep(STEP_DELAY / 1000)
            GLib.idle_add(self.set_labels, *messages)

        def add_message(msg: str) -> None:
            messages.append(msg)
            update_messages()

        def update_message(msg: str) -> None:
            messages[-1] = msg
            update_messages()

        def probe_elements() -> None:
            add_message("Loading the GStreamer bindings")
            try:
                gst = gi_import("Gst")
                update_message("loaded the GStreamer bindings")
                add_message("initializing GStreamer")
                gst.init(None)
                update_message("initialized GStreamer")
            except Exception as e:
                log("Warning failed to import GStreamer", exc_info=True)
                update_message(f"Failed to load GStreamer: {e}")
                return
            try:
                add_message("locating plugins")
                from xpra.gstreamer.common import import_gst, get_all_plugin_names
                import_gst()
                self.elements = get_all_plugin_names()
                update_message(f"found {len(self.elements)} elements")
            except Exception as e:
                log("Warning failed to load GStreamer plugins", exc_info=True)
                update_message(f"Failed to load plugins: {e}")
                return
            if not self.elements:
                update_message("no elements found - cannot continue")
                return
            pset = set(self.elements)
            need = {"capsfilter", "videoconvert", "videoscale", "queue"}
            missing = tuple(need - pset)
            if missing:
                add_message("some essential plugins are missing: " + csv(missing))
                add_message("install them then you can run this tool again")
                return
            add_message("all the essential plugins have been found")
            want = {"x264enc", "vp8enc", "vp9enc", "webmmux"}
            found = tuple(want & pset)
            if not found:
                add_message("no default encoders found,")
                add_message("install at least one plugin from: " + csv(want))
                add_message("then you can run this tool again")
                return
            try:
                from xpra.platform.shadow_server import GSTREAMER_CAPTURE_ELEMENTS
            except ImportError:
                pass
            else:
                want |= set(GSTREAMER_CAPTURE_ELEMENTS)
            missing = tuple(want - pset)
            if missing:
                add_message("some useful extra plugins you may want to install: " + csv(missing))

            GLib.timeout_add(STEP_DELAY * 6, self.add_buttons,
                             ("configure shadow mode", self.configure_shadow),
                             ("configure encoding", self.configure_encoding),
                             ("configure decoding", self.configure_decoding),
                             )

        start_thread(probe_elements, "probe-elements", daemon=True)

    def configure_encoding(self, *_args) -> None:
        pass

    def configure_decoding(self, *_args) -> None:
        pass

    def configure_shadow(self, *_args) -> None:
        pass


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
DISCLAIMER = """
IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES(INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT(INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""".replace("\n", "")
