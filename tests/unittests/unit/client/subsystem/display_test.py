#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, call, patch

from xpra.net.common import Packet
from xpra.net.dispatch import get_packet_handler_specs
from xpra.util.objects import AdHocStruct, typedict
from unit.test_util import silence_info, stubbable
from unit.process_test_util import DisplayContext
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


def make_icc_profile(size: int = 128) -> bytes:
    profile = bytearray(size)
    profile[:4] = size.to_bytes(4, "big")
    profile[36:40] = b"acsp"
    return bytes(profile)


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

        # the packet types declared by the `packet_handler` decorators:
        packet_handlers = {
            packet_type: getattr(DisplayClient, name)
            for name, spec in get_packet_handler_specs(DisplayClient)
            for packet_type in spec.packet_types
        }
        self.assertIn("display-show-desktop", packet_handlers)
        resize_packet_type = "display-resized"
        self.assertIn(resize_packet_type, packet_handlers)
        self.assertNotIn("desktop_size", packet_handlers)

        class Client:
            can_scale = False
            _process_resized = DisplayClient._process_resized

        client = Client()
        packet_handlers[resize_packet_type](client, Packet(resize_packet_type, 1024, 768, 3840, 2160))
        self.assertEqual(client.server_actual_desktop_size, (1024, 768))
        self.assertEqual(client.server_max_desktop_size, (3840, 2160))

    def test_update_screen_size_validates_icc(self):
        from xpra.client.subsystem.display import DisplayClient

        display = stubbable(DisplayClient)()
        display.get_screen_settings = Mock(return_value=(1024, 768, (), 1, (), 1024, 768, 96, 96, 60, {}))
        display.get_display_icc_info = Mock(return_value={})
        display.send = Mock()
        display.set_max_packet_size = Mock()
        display.get_icc_info = Mock(return_value={"data": b"invalid"})
        self.assertTrue(display.update_screen_size())
        attrs = display.send.call_args.args[1]
        self.assertNotIn("icc", attrs)

        display._last_screen_settings = ()
        display.send.reset_mock()
        profile = make_icc_profile()
        display.get_icc_info.return_value = {"source": "test", "data": bytearray(profile)}
        self.assertTrue(display.update_screen_size())
        attrs = display.send.call_args.args[1]
        self.assertEqual(attrs["icc"]["global"]["data"], profile)
        self.assertIsInstance(attrs["icc"]["global"]["data"], bytes)

    def test_update_screen_size_validates_monitor_metadata(self):
        from xpra.client.subsystem.display import DisplayClient

        display = stubbable(DisplayClient)()
        monitors = {0: {
            "geometry": [0, 0, 1024, 768],
            "name": "screen\nname",
            "manufacturer": "x" * 1000,
            "device": r"\\.\DISPLAY1",
            "scanout": {"pixel-clock": object()},
        }}
        display.get_screen_settings = Mock(return_value=(1024, 768, (), 1, (), 1024, 768, 96, 96, 60, monitors))
        display.get_display_icc_info = Mock(return_value={})
        display.get_icc_info = Mock(return_value={})
        display.send = Mock()
        display.set_max_packet_size = Mock()
        self.assertTrue(display.update_screen_size())
        sent = display.send.call_args.args[1]["monitors"]
        self.assertEqual(sent[0]["geometry"], (0, 0, 1024, 768))
        self.assertEqual(sent[0]["name"], "screen name")
        self.assertEqual(len(sent[0]["manufacturer"]), 64)
        self.assertNotIn("device", sent[0])
        self.assertNotIn("scanout", sent[0])
        monitors[0]["geometry"][2] = 1
        self.assertEqual(sent[0]["geometry"], (0, 0, 1024, 768))

    def test_display_capabilities_validate_monitor_metadata(self):
        from xpra.client.subsystem import display as display_module

        display = stubbable(display_module.DisplayClient)(Mock())
        display.refresh_rate = "auto"
        display.dpi = 96
        display.log_screen_info = False
        display.get_vrefresh = Mock(return_value=60)
        display.get_raw_vrefresh = Mock(return_value=60)
        display.get_screen_settings = Mock(return_value=(1024, 768, (), 1, (), 1024, 768, 96, 96, 60, {}))
        display.get_screen_sizes = Mock(return_value=((1024, 768),))
        display.get_monitors_info = Mock(return_value={0: {
            "geometry": (0, 0, 1024, 768),
            "name": "display\nname",
            "device": r"\\.\DISPLAY1",
        }})
        display.get_screen_caps = Mock(return_value={})
        display.get_dpi_caps = Mock(return_value={})
        display.get_scaling_caps = Mock(return_value={})
        with patch.object(display_module, "FULL_INFO", 0):
            monitors = display.get_display_caps()["monitors"]
        self.assertEqual(monitors[0]["geometry"], (0, 0, 1024, 768))
        self.assertEqual(monitors[0]["name"], "display name")
        self.assertNotIn("device", monitors[0])

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
                    },
                    # a server feature, not part of the `display` namespace:
                    "resize_screen": True,
                })
            self.assertTrue(self.mixin.server_randr)
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
        cases = (
            ({}, False, False),
            ({"shadow": True}, True, False),
            ({"desktop": True}, True, False),
            ({"monitor": True}, True, True),
            ({"mode": "shadow"}, True, False),
            ({"mode": "desktop"}, True, False),
            ({"mode": "monitor"}, True, True),
            ({"mode": "seamless"}, False, False),
            ({"mode": b"shadow"}, True, False),
            # A recognized mode takes precedence over conflicting legacy flags.
            ({"mode": "seamless", "shadow": True, "desktop": True, "monitor": True}, False, False),
            ({"mode": "desktop", "monitor": True}, True, False),
            ({"mode": "shadow", "monitor": True}, True, False),
            ({"mode": "monitor", "monitor": False}, True, True),
            # Empty, invalid and unknown modes retain the legacy fallback.
            ({"mode": "", "shadow": True}, True, False),
            ({"mode": None, "desktop": True}, True, False),
            ({"mode": "unknown", "monitor": True}, True, True),
        )
        for caps, is_desktop, is_monitor in cases:
            with self.subTest(caps=caps):
                dc = parse(caps)
                self.assertEqual(dc.server_is_desktop, is_desktop)
                self.assertEqual(dc.server_is_monitor, is_monitor)
                self.assertFalse(dc.server_multi_monitors)
        monitors = {0: {"geometry": (0, 0, 1920, 1080)}}
        monitor_caps = {
            "multi-monitors": True,
            "monitors": monitors,
            "monitors.add-resolutions": ("1920x1080", "1280x720"),
            "monitors.add-label": "Add a virtual monitor",
        }
        for caps in ({"monitor": True}, {"mode": "monitor"}, {"mode": "shadow"}):
            with self.subTest(caps=caps):
                dc = parse(caps | monitor_caps)
                self.assertTrue(dc.server_is_desktop)
                self.assertEqual(dc.server_is_monitor, caps != {"mode": "shadow"})
                self.assertTrue(dc.server_multi_monitors)
                self.assertEqual(dc.server_monitors, monitors)
                self.assertEqual(dc.server_new_monitor_resolutions, ("1920x1080", "1280x720"))
                self.assertEqual(dc.server_add_monitor_label, "Add a virtual monitor")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
