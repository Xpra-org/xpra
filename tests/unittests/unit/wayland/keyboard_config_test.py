#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.util.objects import typedict
from xpra.keyboard.nokeyboard import NoKeyboardDevice
from xpra.server.source.keyboard import KeyboardConnection
from xpra.wayland.server.keyboard_config import KeyboardConfig
from xpra.wayland.server.subsystem.keyboard import WaylandKeyboardManager


class FakeDevice(NoKeyboardDevice):
    """ records the keymaps installed on it - the real one is a `wlr_keyboard` """
    __slots__ = ("installed", )

    def __init__(self):
        self.installed: list[tuple[str, str, str, str]] = []

    def set_layout(self, layout="us", model="pc105", variant="", options="") -> bool:
        self.installed.append((layout, model, variant, options))
        return True


class Opts:
    """ only the `keyboard_*` options are ever read from here """

    def __init__(self, **kwargs):
        self.keyboard_sync = True
        self.keyboard_layout = ""
        self.keyboard_layouts = ""
        self.keyboard_variant = ""
        self.keyboard_variants = ""
        self.keyboard_options = ""
        for k, v in kwargs.items():
            setattr(self, f"keyboard_{k}", v)


class FakeSource(KeyboardConnection):
    """ stands in for the per-client connection object """

    def __init__(self, uuid: str):
        self.uuid = uuid
        self.init_state()

    def effective_readonly(self) -> bool:
        return False


class KeyboardConfigTest(unittest.TestCase):

    def test_parse_hello(self):
        # the hello packet nests everything in a `keymap` dictionary:
        kc = KeyboardConfig()
        mods = kc.parse(typedict({
            "keymap": {
                "layout": "de",
                "variant": "nodeadkeys",
                "options": "compose:ralt",
                "query_struct": {"model": "pc104"},
            },
        }))
        self.assertEqual((kc.layout, kc.model, kc.variant, kc.options),
                         ("de", "pc104", "nodeadkeys", "compose:ralt"))
        self.assertEqual(mods, 4)

    def test_parse_config_packet(self):
        # the `keyboard-config` packet sends the same attributes at the top level:
        kc = KeyboardConfig()
        kc.parse(typedict({"layout": "fr", "query_struct": {"model": "pc105"}}))
        self.assertEqual((kc.layout, kc.model, kc.variant, kc.options), ("fr", "pc105", "", ""))
        # re-sending the same values changes nothing:
        self.assertEqual(kc.parse(typedict({"layout": "fr", "query_struct": {"model": "pc105"}})), 0)

    def test_set_layout(self):
        # the legacy `layout-changed` packet, which does not carry the model:
        kc = KeyboardConfig()
        kc.parse(typedict({"layout": "fr", "query_struct": {"model": "pc105"}}))
        self.assertTrue(kc.set_layout("gb", "", ""))
        self.assertEqual((kc.layout, kc.model, kc.variant), ("gb", "pc105", ""))
        self.assertFalse(kc.set_layout("gb", "", ""))

    def test_hash(self):
        kc = KeyboardConfig()
        # an empty configuration must not look like one that was applied:
        self.assertEqual(kc.get_hash(), "")
        kc.parse(typedict({"layout": "fr"}))
        self.assertNotEqual(kc.get_hash(), "")
        self.assertNotEqual(KeyboardConfig().get_hash(), kc.get_hash())


class WaylandKeymapInstallTest(unittest.TestCase):

    @staticmethod
    def make_manager(**opts) -> tuple[WaylandKeyboardManager, FakeDevice]:
        device = FakeDevice()
        server = Mock()
        server.compositor.get_keyboard_device.return_value = device
        # no `control` subsystem, so no control commands are registered:
        server.get_subsystem.return_value = None
        manager = WaylandKeyboardManager(server=server)
        manager.init_state()
        manager.init(Opts(**opts))
        manager.setup()
        return manager, device

    def connect(self, manager, uuid: str, keymap: dict) -> FakeSource:
        # what `parse_hello_ui_keyboard` does for every new keyboard client:
        ss = FakeSource(uuid)
        ss.keyboard_config = manager.get_keyboard_config(typedict({"keyboard": True, "keymap": keymap}))
        manager.set_keymap(ss)
        return ss

    def test_server_layout_option(self):
        # `--keyboard-layout=fr` must reach the device before any client connects:
        manager, device = self.make_manager(layout="fr")
        self.assertEqual(device.installed, [("fr", "pc105", "", "")])
        # the config recorded as current is the one installed on the seat:
        self.assertEqual(manager.config_hash, manager.config.get_hash())

    def test_no_layout_installs_nothing(self):
        # the device compiles its own default keymap when it is created,
        # so a client which tells us nothing must not cause a re-install:
        manager, device = self.make_manager(layout="")
        self.assertEqual(device.installed, [])
        self.connect(manager, "client-1", {})
        self.assertEqual(device.installed, [])

    def test_client_layout(self):
        manager, device = self.make_manager(layout="")
        ss = self.connect(manager, "client-1", {
            "layout": "de", "variant": "nodeadkeys", "query_struct": {"model": "pc105"},
        })
        self.assertEqual(device.installed, [("de", "pc105", "nodeadkeys", "")])
        # the delayed `keyboard-config` packet repeats the same values:
        ss.keyboard_config.parse(typedict({"layout": "de", "variant": "nodeadkeys",
                                           "query_struct": {"model": "pc105"}}))
        manager.set_keymap(ss, True)
        self.assertEqual(device.installed, [("de", "pc105", "nodeadkeys", "")],
                         "an unchanged keymap must not be re-installed")
        # now the client actually switches layout:
        ss.keyboard_config.parse(typedict({"layout": "fr", "query_struct": {"model": "pc105"}}))
        manager.set_keymap(ss, True)
        self.assertEqual(device.installed[-1], ("fr", "pc105", "", ""))

    def test_last_client_owns_the_keymap(self):
        # there is a single `wlr_keyboard` shared by the whole seat:
        manager, device = self.make_manager(layout="")
        self.connect(manager, "client-1", {"layout": "de"})
        self.connect(manager, "client-2", {"layout": "es"})
        self.assertEqual([x[0] for x in device.installed], ["de", "es"])

    def test_readonly_client_cannot_change_the_keymap(self):
        manager, device = self.make_manager(layout="fr")
        ss = FakeSource("readonly-client")
        ss.effective_readonly = lambda: True
        ss.keyboard_config = manager.get_keyboard_config(typedict({"keymap": {"layout": "de"}}))
        manager.set_keymap(ss)
        self.assertEqual([x[0] for x in device.installed], ["fr"])

    def test_disabled_keyboard(self):
        manager, device = self.make_manager(layout="")
        ss = FakeSource("client-1")
        ss.keyboard_config = manager.get_keyboard_config(typedict({"keyboard": False, "keymap": {"layout": "de"}}))
        self.assertFalse(ss.keyboard_config.enabled)
        manager.set_keymap(ss)
        self.assertEqual(device.installed, [])

    def test_no_device(self):
        # `install_keymap` must cope with a server that has no keyboard device:
        manager, _ = self.make_manager(layout="")
        manager.device = None
        self.connect(manager, "client-1", {"layout": "de"})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
