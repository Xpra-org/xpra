#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch


class FakeAudio:

    def __init__(self, audio_sink="auto", speaker_enabled=False):
        self.audio_sink = audio_sink
        self.speaker_enabled = speaker_enabled
        self.speaker_allowed = True
        self.server_send = True
        self.callbacks = {}
        self.calls = []

    def connect(self, signal, callback) -> None:
        self.callbacks[signal] = callback

    def start_receiving_audio(self) -> None:
        self.calls.append("start")
        self.speaker_enabled = True

    def stop_receiving_audio(self) -> None:
        self.calls.append("stop")
        self.speaker_enabled = False


class FakeClient:

    def __init__(self, audio):
        self.audio = audio

    def get_subsystem(self, subsystem):
        assert subsystem == "audio"
        return self.audio


class FakeMenuItem:

    def __init__(self, label=""):
        self.label = label
        self.active = False
        self.submenu = None
        self.callback = None

    def set_draw_as_radio(self, _draw_as_radio) -> None:
        pass

    def set_active(self, active) -> None:
        self.active = active

    def get_active(self):
        return self.active

    def get_label(self):
        return self.label

    def set_sensitive(self, _sensitive) -> None:
        pass

    def set_tooltip_text(self, _tooltip) -> None:
        pass

    def set_submenu(self, submenu) -> None:
        self.submenu = submenu

    def get_submenu(self):
        return self.submenu

    def connect(self, _signal, callback) -> None:
        self.callback = callback

    def activate(self) -> None:
        self.active = not self.active
        self.callback(self)


class FakeMenu:

    def __init__(self):
        self.children = []

    def append(self, item) -> None:
        self.children.append(item)

    def get_children(self):
        return self.children

    def show_all(self) -> None:
        pass


def ensure_item_selected(menu, item) -> None:
    if item.get_active():
        for child in menu.get_children():
            if child is not item:
                child.set_active(False)
    elif not any(child.get_active() for child in menu.get_children() if child is not item):
        item.set_active(True)


class TrayMenuTest(unittest.TestCase):

    @staticmethod
    def make_speaker_menu(audio):
        from xpra.client.gtk3 import tray_menu
        helper = object.__new__(tray_menu.GTKTrayMenu)
        helper.client = FakeClient(audio)
        helper.menuitem = lambda title, *_args: FakeMenuItem(title)
        helper.after_handshake = lambda callback, *args: callback(*args)
        fake_gtk = SimpleNamespace(
            Menu=FakeMenu,
            CheckMenuItem=FakeMenuItem,
            SeparatorMenuItem=FakeMenuItem,
        )
        with patch("xpra.audio.gstreamer_util.get_sink_plugins",
                   return_value=["pulsesink", "alsasink"]), \
                patch("xpra.audio.gstreamer_util.get_default_sink_plugin",
                      return_value="pulsesink"), \
                patch.object(tray_menu, "Gtk", fake_gtk), \
                patch.object(tray_menu, "ensure_item_selected", ensure_item_selected):
            speaker = helper.make_speakermenuitem()
        return speaker.get_submenu()

    def test_start_menu_checksum_includes_icons(self):
        from xpra.client.gtk3.tray_menu import start_menu_checksum
        menu = {
            "Utilities": {
                "IconData": b"category-one",
                "IconType": "png",
                "Entries": {
                    "Editor": {
                        "command": "editor",
                        "IconData": b"icon-one",
                        "IconType": "png",
                    },
                },
            },
        }
        checksum = start_menu_checksum(menu)
        menu["Utilities"]["Entries"]["Editor"]["IconData"] = b"icon-two"
        assert start_menu_checksum(menu) != checksum

    def test_speaker_menu_sink_selection(self):
        audio = FakeAudio(speaker_enabled=True)
        menu = self.make_speaker_menu(audio)
        items = menu.get_children()
        self.assertEqual([x.get_label() for x in items], ["Off", "", "Pulseaudio", "ALSA"])
        self.assertTrue(items[2].get_active())

        items[3].activate()
        self.assertEqual(audio.audio_sink, "alsasink")
        self.assertEqual(audio.calls, ["stop", "start"])

        items[0].activate()
        self.assertEqual(audio.calls, ["stop", "start", "stop"])

    def test_speaker_menu_preserves_selected_sink_options(self):
        audio = FakeAudio("pulsesink:device=speakers")
        menu = self.make_speaker_menu(audio)
        items = menu.get_children()
        self.assertTrue(items[0].get_active())

        items[2].activate()
        self.assertEqual(audio.audio_sink, "pulsesink:device=speakers")
        self.assertEqual(audio.calls, ["start"])

    def test_speaker_menu_returns_to_off_when_sink_fails(self):
        audio = FakeAudio()
        audio.start_receiving_audio = lambda: audio.calls.append("start")
        menu = self.make_speaker_menu(audio)
        items = menu.get_children()

        items[2].activate()
        self.assertEqual(audio.calls, ["start"])
        self.assertTrue(items[0].get_active())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
