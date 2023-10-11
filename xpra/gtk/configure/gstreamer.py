# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
from textwrap import wrap

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label
from xpra.platform.paths import get_image
from xpra.log import Logger

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

log = Logger("gstreamer", "util")

DISCLAIMER = """
IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES(INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT(INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""".replace("\n", "")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent:Gtk.Window|None=None):
        self.warning_shown = False
        self.warning_pixbuf = get_image("warning.png")
        size = (800, 554)
        if self.warning_pixbuf:
            size = self.warning_pixbuf.get_width(), self.warning_pixbuf.get_height()
        super().__init__(
            "Configure Xpra's GStreamer Codecs",
            "gstreamer.png",
            wm_class=("xpra-configure-gstreamer-gui", "Xpra Configure GStreamer GUI"),
            default_size=size,
            header_bar=(True, False),
            parent=parent,
        )
        self.set_resizable(False)

    def populate(self):
        for x in self.vbox.get_children():
            self.vbox.remove(x)
        if not self.warning_shown:
            self.populate_with_warning()
        else:
            self.add_widget(label("Configure Xpra GStreamer Codecs", font="sans 20"))

        self.vbox.show_all()

    def populate_with_warning(self):
        layout = Gtk.Layout()
        self.vbox.add(layout)
        if self.warning_pixbuf:
            image = Gtk.Image.new_from_pixbuf(self.warning_pixbuf)
            layout.put(image, 0, 0)
        for i, text in enumerate((
            "This tool can cause your system to crash,",
            "it may even damage hardware in rare cases.",
            "            Use with caution.",
        )):
            lbl = label(text, font="Sans 22")
            layout.put(lbl, 86, 70+i*40)
        for i, line in enumerate(wrap(DISCLAIMER, width=70)):
            lbl = label(line, font="Sans 12")
            layout.put(lbl, 72, 220+i*24)
        button = Gtk.Button.new_with_label("Understood")
        button.connect("clicked", self.understood)
        layout.put(button, 200, 450)
        button = Gtk.Button.new_with_label("Get me out of here")
        button.connect("clicked", self.dismiss)
        layout.put(button, 400, 450)
        self.warning_shown = True

    def understood(self, *args):
        self.warning_shown = True
        self.populate()


def main() -> int:
    from xpra.gtk.configure.main import run_gui
    return run_gui(ConfigureGUI)

if __name__ == "__main__":
    import sys
    sys.exit(main())
