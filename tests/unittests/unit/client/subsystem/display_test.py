#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, call, patch

from xpra.net.common import Packet
from xpra.net.dispatch import SubsystemPacketHandlers
from xpra.util.objects import AdHocStruct, typedict
from unit.test_util import silence_info, stubbable
from unit.process_test_util import DisplayContext
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class DisplayClientTest(ClientMixinTest):

    def test_xsettings_negotiation(self):
        with DisplayContext():
            from xpra.client.subsystem.display import DisplayClient
            from xpra.x11.subsystem.xsettings import XSettingsServer
            from xpra.x11.xroot_props import GTK_WORKAREAS_PREFIX

            server = XSettingsServer()
            opts = AdHocStruct()
            server_caps = [({}, False)]
            for value in ("no", "yes"):
                opts.xsettings = value
                server.init(opts)
                server_caps.append((server.get_caps(None), value == "yes"))
            settings = (1, ((0, "Xft/DPI", 98304, 1), ))
            resource_manager = b"Xft.dpi:\t96\n"
            for caps, server_enabled in server_caps:
                for enabled in (False, True):
                    with self.subTest(caps=caps, enabled=enabled):
                        client = Mock(subsystems={})
                        display = DisplayClient(client)
                        opts.xsettings = enabled
                        display.init_display_watcher(opts)
                        watcher = display._x11_props
                        self.assertIsNotNone(watcher)
                        client.after_handshake.assert_called_once_with(watcher.do_setup_xprops)
                        self.assertTrue(display.parse_server_capabilities(typedict(caps | {"display": {}})))
                        xsettings_watcher = Mock()
                        xsettings_watcher.get_settings.return_value = settings
                        root_watcher = Mock()
                        root_watcher.do_notify.side_effect = lambda prop: watcher._handle_root_prop_changed(root_watcher, prop)
                        with patch.object(watcher, "init_x11_filter"), \
                             patch("xpra.x11.subsystem.xsettings_manager.XSettingsWatcher", return_value=xsettings_watcher) as xsettings_class, \
                             patch("xpra.x11.xroot_props.XRootPropWatcher", return_value=root_watcher) as root_class, \
                             patch("xpra.platform.posix.display.get_resource_manager", return_value=resource_manager):
                            callback = client.after_handshake.call_args.args[0]
                            callback()
                        sync = enabled and server_enabled
                        if sync:
                            xsettings_class.assert_called_once_with()
                            self.assertEqual(client.send_setting_change.call_args_list, [
                                call("xsettings", {"xsettings-blob": settings}),
                                call("xsettings", {"resource-manager": resource_manager}),
                            ])
                        else:
                            xsettings_class.assert_not_called()
                            client.send_setting_change.assert_not_called()
                        if enabled:
                            props = (["RESOURCE_MANAGER"] if sync else []) + ["_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
                            root_class.assert_called_once_with(props, (GTK_WORKAREAS_PREFIX, ))
                        else:
                            root_class.assert_not_called()
                        display.cleanup()

    def test_x11_filter_lifecycle(self):
        from xpra.platform.posix.display import X11DisplayPropsWatcher

        watcher = X11DisplayPropsWatcher(Mock(), False)
        with patch("xpra.x11.gtk.bindings.init_x11_filter", return_value=False) as init_filter, \
             patch("xpra.x11.gtk.bindings.cleanup_x11_filter") as cleanup_filter:
            watcher.init_x11_filter()
            self.assertTrue(watcher._x11_filter)
            watcher.cleanup()
        init_filter.assert_called_once_with()
        cleanup_filter.assert_called_once_with()

    def test_x11_window_stacking(self):
        with DisplayContext():
            from xpra.platform.posix.display import X11DisplayPropsWatcher

            def window(xid: int | None):
                model = Mock()
                gdkwindow = Mock() if xid else None
                if gdkwindow:
                    gdkwindow.get_xid.return_value = xid
                model.get_window.return_value = gdkwindow
                return model

            window_client = AdHocStruct()
            window_client._id_to_window = {
                1: window(0x101),
                2: window(0x102),
                3: window(None),
            }
            window_client.send_window_stacking = Mock()
            display = AdHocStruct()
            display.get_subsystem = lambda name: window_client if name == "window" else None
            watcher = X11DisplayPropsWatcher(display, False)
            with patch("xpra.x11.xroot_props.root_array_get",
                       return_value=(0x999, 0x102, 0x101)) as root_array_get:
                watcher._handle_root_prop_changed(None, "_NET_CLIENT_LIST_STACKING")
            root_array_get.assert_called_once_with("_NET_CLIENT_LIST_STACKING", "window")
            window_client.send_window_stacking.assert_called_once_with((2, 1))

            window_client.server_window_stacking = True
            watcher.init_x11_filter = Mock()
            root_watcher = Mock()
            with patch("xpra.x11.xroot_props.XRootPropWatcher", return_value=root_watcher) as watcher_class:
                watcher.do_setup_xprops()
            watcher_class.assert_called_once_with(["_NET_CLIENT_LIST_STACKING"], ())
            root_watcher.do_notify.assert_called_once_with("_NET_CLIENT_LIST_STACKING")
            self.assertIsNone(watcher._xsettings_watcher)

    def test_show_desktop_packet_handlers(self):
        from xpra.client.subsystem.display import DisplayClient

        class Receiver(SubsystemPacketHandlers):
            # derive from the real mixin so that `packet_handler_name` (and the
            # `PREFIX` stripping it does) is exercised, not re-implemented here:
            PREFIX = DisplayClient.PREFIX
            screen_sizes = ()

            def __init__(self):
                self.aliases = {}
                self.packet_handlers = {}

            def add_packets(self, *packet_types, **_kwargs):
                for packet_type in packet_types:
                    name = self.packet_handler_name(packet_type)
                    self.packet_handlers[packet_type] = getattr(DisplayClient, name)

        receiver = Receiver()
        DisplayClient.init_authenticated_packet_handlers(receiver)
        self.assertIn("display-show-desktop", receiver.packet_handlers)
        resize_packet_type = "display-resized"
        self.assertIn(resize_packet_type, receiver.packet_handlers)
        self.assertNotIn("desktop_size", receiver.packet_handlers)

        class Client:
            can_scale = False
            _process_resized = DisplayClient._process_resized

        client = Client()
        receiver.packet_handlers[resize_packet_type](client, Packet(resize_packet_type, 1024, 768, 3840, 2160))
        self.assertEqual(client.server_actual_desktop_size, (1024, 768))
        self.assertEqual(client.server_max_desktop_size, (3840, 2160))
        self.assertEqual(receiver.aliases, {})

    def test_display(self):
        with DisplayContext():
            from xpra.client.subsystem import display  # pylint: disable=import-outside-toplevel

            def _DisplayClient():
                # `get_root_size` / `get_screen_sizes` are this subsystem's own
                # methods, so stub them on a `stubbable` instance:
                dc = stubbable(display.DisplayClient)()

                def get_root_size():
                    return 1024, 768
                dc.get_root_size = get_root_size

                def get_screen_sizes(*_args):
                    return ((1024, 768),)
                dc.get_screen_sizes = get_screen_sizes
                return dc
            opts = AdHocStruct()
            opts.desktop_fullscreen = False
            opts.desktop_scaling = False
            opts.dpi = 144
            opts.refresh_rate = "20"
            opts.xsettings = False
            with silence_info(display):
                # the server sends its display attributes in the `display` namespace,
                # which the client requires with BC=0 (and honours with BC=1):
                self._test_mixin_class(_DisplayClient, opts, {
                    "display": {
                        "name": ":999",
                        "desktop_size": (1024, 768),
                        "max_desktop_size": (3840, 2160),
                        "actual_desktop_size": (1024, 768),
                        "resize_screen": True,
                    },
                })
            self.assertIsNotNone(self.mixin._x11_props)
            self.assertFalse(self.mixin._x11_props.xsettings_enabled)
            # `get_monitors_info` now calls through to `xpra.platform.gui.get_monitors_info`
            # rather than returning `{}` unconditionally (see the toolkit-split plan):
            called = []

            def fake_get_monitors_info(xscale, yscale):
                called.append((xscale, yscale))
                return {0: {"geometry": (0, 0, 1024, 768)}}
            import xpra.platform.gui as platform_gui
            orig = platform_gui.get_monitors_info
            platform_gui.get_monitors_info = fake_get_monitors_info
            try:
                info = self.mixin.get_monitors_info()
            finally:
                platform_gui.get_monitors_info = orig
            self.assertEqual(called, [(self.mixin.xscale, self.mixin.yscale)])
            self.assertEqual(info, {0: {"geometry": (0, 0, 1024, 768)}})
            self.assertEqual(self.mixin.get_server_position((-100, 50)), (-100, 50))

    def test_server_mode_capabilities(self):
        from xpra.util.objects import typedict
        from xpra.client.subsystem import display  # pylint: disable=import-outside-toplevel
        display_caps = {
            "name": ":999",
            "desktop_size": (1920, 1080),
            "actual_desktop_size": (1920, 1080),
        }

        def parse(caps: dict):
            dc = stubbable(display.DisplayClient)()
            with silence_info(display):
                self.assertTrue(dc.parse_server_capabilities(typedict(caps | {"display": display_caps})))
            return dc

        # the server mode and monitor features are top-level server features,
        # not part of the `display` namespace:
        dc = parse({})
        self.assertFalse(dc.server_is_desktop)
        self.assertFalse(dc.server_is_monitor)
        self.assertFalse(dc.server_multi_monitors)
        for mode in ("shadow", "desktop"):
            dc = parse({mode: True})
            self.assertTrue(dc.server_is_desktop, mode)
            self.assertFalse(dc.server_is_monitor, mode)
        monitors = {0: {"geometry": (0, 0, 1920, 1080)}}
        dc = parse({
            "monitor": True,
            "multi-monitors": True,
            "monitors": monitors,
            "monitors.add-resolutions": ("1920x1080", "1280x720"),
            "monitors.add-label": "Add a virtual monitor",
        })
        self.assertTrue(dc.server_is_desktop)
        self.assertTrue(dc.server_is_monitor)
        self.assertTrue(dc.server_multi_monitors)
        self.assertEqual(dc.server_monitors, monitors)
        self.assertEqual(dc.server_new_monitor_resolutions, ("1920x1080", "1280x720"))
        self.assertEqual(dc.server_add_monitor_label, "Add a virtual monitor")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
