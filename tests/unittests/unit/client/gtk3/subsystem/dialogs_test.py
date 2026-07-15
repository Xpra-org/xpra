#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Event
from unittest.mock import patch


class Widget:

    def set_halign(self, *_args) -> None:
        pass

    def set_margin_start(self, *_args) -> None:
        pass

    def set_margin_end(self, *_args) -> None:
        pass

    def set_margin_top(self, *_args) -> None:
        pass

    def set_margin_bottom(self, *_args) -> None:
        pass


class Entry(Widget):

    def set_max_length(self, *_args) -> None:
        pass

    def set_width_chars(self, *_args) -> None:
        pass

    def set_visibility(self, *_args) -> None:
        pass

    def connect(self, *_args) -> None:
        pass


class VBox:

    def pack_start(self, *_args) -> None:
        pass

    def show_all(self) -> None:
        pass


class Dialog:

    def __init__(self, **_kwargs):
        self.vbox = VBox()

    def add_button(self, *_args) -> None:
        pass

    def connect(self, *_args) -> None:
        pass

    def show(self) -> None:
        pass


class DialogsClientTest(unittest.TestCase):

    def show_challenge_prompt(self, challenge=None) -> list[str]:
        from xpra.client.gtk3.dialogs import GTKDialogClient

        class Client:
            subsystems = {"challenge": challenge} if challenge else {}
            _protocol = None

            @staticmethod
            def idle_add(*_args, **_kwargs) -> int:
                return 0

            @staticmethod
            def timeout_add(*_args, **_kwargs) -> int:
                return 0

            @staticmethod
            def source_remove(*_args, **_kwargs) -> None:
                pass

        labels = []

        def make_label(text, *_args):
            labels.append(text)
            return Widget()

        dialogs = GTKDialogClient(Client())
        with (
            patch("xpra.client.gtk3.dialogs.Gtk.Dialog", Dialog),
            patch("xpra.client.gtk3.dialogs.Gtk.Entry", Entry),
            patch("xpra.client.gtk3.dialogs.label", side_effect=make_label),
        ):
            dialogs.do_process_challenge_prompt_dialog([], Event(), "PIN")
        return labels

    def test_challenge_prompt_uses_challenge_subsystem(self):
        prompts = []

        class Challenge:

            @staticmethod
            def get_challenge_prompt(prompt="password") -> str:
                prompts.append(prompt)
                return f"prompt: {prompt}"

        labels = self.show_challenge_prompt(Challenge())
        self.assertEqual(prompts, ["PIN"])
        self.assertIn("prompt: PIN", labels)

    def test_challenge_prompt_without_challenge_subsystem(self):
        self.assertIn("Password", self.show_challenge_prompt())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
