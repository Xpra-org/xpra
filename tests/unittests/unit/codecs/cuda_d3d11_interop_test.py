#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
import unittest
from collections import Counter
from unittest.mock import patch

try:
    from xpra.codecs.nvidia.cuda import d3d11
except ImportError:
    d3d11 = None


class Texture:
    def __init__(self, texture, x=0, y=0):
        self.texture = texture
        self.x = x
        self.y = y


def value(arg):
    """ the object passed using `byref()` """
    return arg._obj


class FakeCUDA:
    LUID = b"\x6c\x1f\x01\x00\x00\x00\x00\x00"

    def __init__(self):
        self.registered = {}
        self.calls = []
        self.copies = []
        self.mapped = 0
        self.fail_register = 0

    def cuDeviceGet(self, device, ordinal):
        value(device).value = ordinal
        return 0

    def cuDeviceGetLuid(self, luid, node_mask, device):
        ctypes.memmove(luid, self.LUID, 8)
        return 0

    def cuGraphicsD3D11RegisterResource(self, resource, texture, flags):
        self.calls.append("register")
        if self.fail_register:
            return self.fail_register
        handle = 0x1000 + len(self.calls)
        value(resource).value = handle
        self.registered[handle] = texture.value
        return 0

    def cuGraphicsResourceSetMapFlags(self, resource, flags):
        assert flags == d3d11.CU_GRAPHICS_MAP_RESOURCE_FLAGS_READ_ONLY
        return 0

    def cuGraphicsMapResources(self, count, resources, stream):
        self.mapped += 1
        return 0

    def cuGraphicsSubResourceGetMappedArray(self, array, resource, index, level):
        value(array).value = 0xa000 + resource.value
        return 0

    def cuGraphicsUnmapResources(self, count, resources, stream):
        self.mapped -= 1
        return 0

    def cuGraphicsUnregisterResource(self, resource):
        handle = resource.value
        del self.registered[handle]
        return 0

    def cuMemcpy2D(self, copy):
        c = value(copy)
        self.copies.append((c.srcMemoryType, c.srcArray, c.srcXInBytes, c.srcY,
                            c.dstMemoryType, c.dstDevice, c.dstPitch, c.WidthInBytes, c.Height))
        return 0


@unittest.skipIf(d3d11 is None, "NVIDIA CUDA D3D11 module is not available")
class TestD3D11Interop(unittest.TestCase):

    def setUp(self):
        self.refs = Counter()

        def add_ref(ptr):
            self.refs[ptr] += 1

        def release(ptr):
            self.refs[ptr] -= 1
        self.enterContext(patch.object(d3d11, "com_add_ref", add_ref))
        self.enterContext(patch.object(d3d11, "com_release", release))
        self.cuda = FakeCUDA()
        self.interop = d3d11.D3D11Interop(0, lib=self.cuda)

    def test_luid(self):
        self.assertEqual(self.interop.luid, FakeCUDA.LUID)

    def test_copy(self):
        self.interop.copy_to(Texture(0x500, 3, 7), 0xd000, 10240, 640, 480)
        self.assertEqual(self.cuda.mapped, 0)
        (src_type, src_array, src_x, src_y, dst_type, dst, pitch, width, height), = self.cuda.copies
        self.assertEqual((src_type, dst_type), (d3d11.CU_MEMORYTYPE_ARRAY, d3d11.CU_MEMORYTYPE_DEVICE))
        self.assertEqual((src_x, src_y), (3 * 4, 7))
        self.assertEqual((dst, pitch, width, height), (0xd000, 10240, 640 * 4, 480))
        self.assertTrue(src_array)

    def test_registrations_are_cached_and_bounded(self):
        for _ in range(3):
            self.interop.copy_to(Texture(0x500), 0xd000, 1024, 16, 16)
        self.assertEqual(self.cuda.calls.count("register"), 1)
        self.assertEqual(self.refs[0x500], 1)
        textures = [0x600 + i for i in range(d3d11.MAX_REGISTRATIONS)]
        for texture in textures:
            self.interop.copy_to(Texture(texture), 0xd000, 1024, 16, 16)
        # the oldest one was evicted, and its reference released:
        self.assertEqual(self.refs[0x500], 0)
        self.assertEqual(len(self.cuda.registered), d3d11.MAX_REGISTRATIONS)
        self.interop.clean()
        self.assertEqual(self.cuda.registered, {})
        self.assertFalse(any(self.refs.values()))

    def test_failed_registration_releases(self):
        self.cuda.fail_register = 1
        with self.assertRaises(RuntimeError):
            self.interop.copy_to(Texture(0x700), 0xd000, 1024, 16, 16)
        self.assertEqual(self.refs[0x700], 0)
        self.assertEqual(self.interop.registrations, {})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
