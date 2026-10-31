#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.codecs.nvidia.cuda import d3d11
from xpra.util.objects import typedict

try:
    from xpra.codecs.nvidia.cuda import context
except ImportError:
    context = None


@unittest.skipIf(context is None, "PyCUDA is not available")
class TestCUDADeviceSelection(unittest.TestCase):

    def setUp(self):
        self.luids = (b"capture0", b"adapter1")
        self.devices = [Mock(), Mock()]
        for i, device in enumerate(self.devices):
            device.name.return_value = f"GPU {i}"
            device.pci_bus_id.return_value = f"0000:0{i + 1}:00.0"
            device.compute_capability.return_value = (8, 6)
        self.free_pct = [35, 90]
        self.contexts = []
        self.prefs = {"load-balancing": "memory"}
        self.enterContext(patch.object(context, "WIN32", True))
        self.enterContext(patch.object(context, "MIN_FREE_MEMORY", 10))
        self.enterContext(patch.object(context, "get_pref", self.prefs.get))
        self.enterContext(patch.object(context, "init_all_devices", return_value=[0, 1]))
        self.enterContext(patch.object(context, "DEVICE_STATE", {}))
        self.enterContext(patch.object(context, "rr", 0))
        self.enterContext(patch.object(context, "driver_init", return_value=True))
        self.enterContext(patch.object(context, "check_device", return_value=True))
        device_factory = self.enterContext(patch.object(context, "Device", side_effect=self.devices.__getitem__))
        device_factory.count.return_value = len(self.devices)
        self.enterContext(patch.object(context, "make_device_context", side_effect=self.make_device_context))
        self.get_luid = self.enterContext(patch.object(d3d11, "get_device_luid", side_effect=self.luids.__getitem__))
        self.enterContext(patch.object(context, "log", Mock()))

    def tearDown(self):
        for cuda_context in self.contexts:
            cuda_context.pop.assert_called_once_with()
            cuda_context.detach.assert_called_once_with()

    def make_device_context(self, device_id):
        cuda_context = Mock()
        self.contexts.append(cuda_context)
        return self.devices[device_id], cuda_context, self.free_pct[device_id]

    def select(self, **options):
        return context.get_device_context(typedict({"cuda-adapter-luid": self.luids[0], **options})).device_id

    def test_capture_adapter_preferred_over_both_policies(self):
        for policy in ("memory", "round-robin"):
            with self.subTest(policy=policy):
                self.prefs["load-balancing"] = policy
                self.assertEqual(self.select(), 0)

    def test_explicit_device_overrides_adapter(self):
        self.assertEqual(self.select(cuda_device=1), 1)
        self.prefs["device-id"] = "1"
        self.assertEqual(self.select(), 1)
        self.prefs.pop("device-id")
        self.prefs["device-name"] = "GPU 1"
        self.assertEqual(self.select(), 1)
        self.get_luid.assert_not_called()

    def test_missing_or_unmatched_adapter_uses_normal_policy(self):
        for luid in (b"", b"missing0"):
            with self.subTest(luid=luid):
                self.assertEqual(self.select(**{"cuda-adapter-luid": luid}), 1)

    def test_non_windows_ignores_adapter(self):
        with patch.object(context, "WIN32", False):
            self.assertEqual(self.select(), 1)
        self.get_luid.assert_not_called()

    def test_disabled_adapter_is_not_selected(self):
        with patch.object(context, "init_all_devices", return_value=[1]):
            self.assertEqual(self.select(), 1)
        self.get_luid.assert_called_once_with(1)

    def test_failing_adapter_is_not_preferred(self):
        context.DEVICE_STATE[0] = False
        self.assertEqual(self.select(), 1)

    def test_adapter_must_meet_compute_and_memory_requirements(self):
        self.devices[0].compute_capability.return_value = (2, 0)
        self.assertEqual(self.select(), 1)
        self.devices[0].compute_capability.return_value = (8, 6)
        self.free_pct[0] = 5
        self.assertEqual(self.select(), 1)

    def test_luid_query_failure_falls_back(self):
        self.get_luid.side_effect = RuntimeError("LUID not supported")
        self.assertEqual(self.select(), 1)

    def test_luid_query_failure_does_not_hide_other_adapter(self):
        self.get_luid.side_effect = (RuntimeError("LUID not supported"), self.luids[1])
        self.assertEqual(self.select(**{"cuda-adapter-luid": self.luids[1]}), 1)

    def test_context_creation_failure_falls_back(self):
        with patch.object(context, "make_device_context", side_effect=lambda i: () if i == 0 else self.make_device_context(i)):
            self.assertEqual(self.select(), 1)


if __name__ == "__main__":
    unittest.main()
