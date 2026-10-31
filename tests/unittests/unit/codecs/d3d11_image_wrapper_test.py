#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import weakref

from xpra.codecs.constants import CodecStateException
from xpra.os_util import WIN32


W, H = 8, 4


class FakeCapture:
    """ a capture with a 'desktop texture' of W x H BGRX pixels, the byte values give their position """

    def __init__(self, max_snapshots=4):
        self.max_snapshots = max_snapshots
        self.snapshots = []
        self.released = []
        self.downloads = []
        self.closed = False
        self.frame = 0

    def pixel(self, x: int, y: int) -> bytes:
        return bytes((x, y, self.frame, 0))

    def download(self, texture: int, x: int, y: int, width: int, height: int) -> bytes:
        if self.closed:
            raise RuntimeError("closed")
        self.downloads.append((texture, x, y, width, height))
        if texture:
            # snapshots keep the frame and the origin they were taken from:
            frame, ox, oy = texture >> 16, (texture >> 8) & 0xff, texture & 0xff
            return b"".join(bytes((ox + x + i, oy + y + j, frame, 0)) for j in range(height) for i in range(width))
        return b"".join(self.pixel(x + i, y + j) for j in range(height) for i in range(width))

    def snapshot(self, x: int, y: int, width: int, height: int):
        from xpra.platform.win32.d3d11.image import D3D11Texture
        if len(self.snapshots) - len(self.released) >= self.max_snapshots:
            return None
        texture = D3D11Texture((self.frame << 16) | (x << 8) | y, 1, 0, 0, width, height)
        self.snapshots.append(texture)
        return texture

    def release_snapshot(self, texture) -> None:
        self.released.append(texture)


def expected(x: int, y: int, width: int, height: int, frame: int = 0) -> bytes:
    return b"".join(bytes((x + i, y + j, frame, 0)) for j in range(height) for i in range(width))


@unittest.skipUnless(WIN32, "the d3d11 package is only available on MS Windows")
class TestDXGIImageWrapper(unittest.TestCase):

    def make_image(self, capture, x=0, y=0, width=W, height=H):
        from xpra.platform.win32.d3d11.image import DXGIImageWrapper
        return DXGIImageWrapper(x, y, width, height, "BGRX", 32, capture)

    def test_no_gpu_buffer_until_frozen_on_gpu(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        self.assertIsNone(image.get_gpu_buffer())
        self.assertFalse(image.has_pixels())
        self.assertTrue(image.freeze_on_gpu())
        texture = image.get_gpu_buffer()
        self.assertIsNotNone(texture)
        self.assertEqual((texture.width, texture.height), (W, H))
        # still nothing downloaded:
        self.assertFalse(image.has_pixels())
        self.assertEqual(capture.downloads, [])
        image.free()

    def test_frozen_image_keeps_its_frame(self):
        capture = FakeCapture()
        image = self.make_image(capture, 2, 1, 4, 2)
        image.freeze_on_gpu()
        capture.frame = 1
        # downloads come from the snapshot, not from the newer frame:
        self.assertEqual(image.get_pixels(), expected(2, 1, 4, 2, 0))
        # while an image that was not frozen shows the current frame:
        live = self.make_image(capture, 2, 1, 4, 2)
        self.assertEqual(live.get_pixels(), expected(2, 1, 4, 2, 1))

    def test_freeze_downloads_the_region(self):
        capture = FakeCapture()
        image = self.make_image(capture, 1, 2, 3, 2)
        self.assertTrue(image.freeze())
        self.assertEqual(capture.downloads, [(0, 1, 2, 3, 2)])
        self.assertEqual(image.get_pixels(), expected(1, 2, 3, 2))
        self.assertIsNone(image.get_gpu_buffer())
        self.assertEqual(image.get_rowstride(), 3 * 4)

    def test_double_free_releases_once(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        image.freeze_on_gpu()
        image.free()
        image.free()
        self.assertEqual(len(capture.released), 1)
        self.assertIs(capture.released[0], capture.snapshots[0])

    def test_free_after_capture_closed(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        image.freeze_on_gpu()
        capture.closed = True
        image.free()
        self.assertEqual(len(capture.released), 1)
        # and an image that cannot be downloaded any more says so:
        image = self.make_image(capture)
        with self.assertRaises(RuntimeError):
            image.get_pixels()

    def test_sub_image_only_downloads_the_area(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        sub = image.get_sub_image(W - 2, 0, 2, H)
        self.assertEqual(sub.get_pixels(), expected(W - 2, 0, 2, H))
        self.assertEqual((sub.get_target_x(), sub.get_target_y()), (W - 2, 0))
        self.assertFalse(image.has_pixels())
        self.assertEqual(capture.downloads, [(0, W - 2, 0, 2, H)])

    def test_sub_image_reuses_existing_pixels(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        image.get_pixels()
        capture.frame = 1
        sub = image.get_sub_image(1, 1, 2, 2)
        self.assertEqual(sub.get_pixels(), expected(1, 1, 2, 2, 0))
        self.assertEqual(len(capture.downloads), 1)

    def test_sub_image_of_a_snapshot(self):
        capture = FakeCapture()
        image = self.make_image(capture, 2, 1, 4, 3)
        image.freeze_on_gpu()
        capture.frame = 1
        sub = image.get_sub_image(1, 1, 2, 2)
        self.assertEqual(sub.get_pixels(), expected(3, 2, 2, 2, 0))

    def test_restride_downloads_first(self):
        capture = FakeCapture()
        image = self.make_image(capture)
        self.assertTrue(image.restride(W * 4 + 8))
        self.assertEqual(image.get_rowstride(), W * 4 + 8)
        self.assertEqual(len(image.get_pixels()), (W * 4 + 8) * H)
        image = self.make_image(capture)
        self.assertFalse(image.may_restride())
        self.assertTrue(image.has_pixels())

    def test_freeze_on_gpu_falls_back_to_download(self):
        capture = FakeCapture(max_snapshots=1)
        first = self.make_image(capture)
        first.freeze_on_gpu()
        second = self.make_image(capture)
        self.assertTrue(second.freeze_on_gpu())
        self.assertIsNone(second.get_gpu_buffer())
        self.assertTrue(second.has_pixels())
        first.free()
        third = self.make_image(capture)
        third.freeze_on_gpu()
        self.assertIsNotNone(third.get_gpu_buffer())

    def test_base_freeze_on_gpu(self):
        from xpra.codecs.image import ImageWrapper
        image = ImageWrapper(0, 0, W, H, b"\0" * W * H * 4, "BGRX", 32, W * 4)
        self.assertFalse(image.freeze_on_gpu())
        self.assertIsNone(image.get_gpu_buffer())


@unittest.skipUnless(WIN32, "D3D11 is only available on MS Windows")
class TestTexturePool(unittest.TestCase):

    def setUp(self):
        try:
            from xpra.platform.win32.d3d11.device import get_shared_device, TexturePool
            self.device = get_shared_device()
        except (ImportError, RuntimeError) as e:
            self.skipTest(f"no D3D11 device: {e}")
        self.pool = TexturePool(self.device.get_ptr())

    def tearDown(self):
        self.pool.close()

    def test_reuse_and_limits(self):
        from xpra.platform.win32.d3d11 import device
        fmt = 87    # DXGI_FORMAT_B8G8R8A8_UNORM
        first = self.pool.acquire(64, 32, fmt)
        self.assertTrue(first)
        self.pool.release(first, 64, 32, fmt)
        # idle textures of the same size are re-used:
        self.assertEqual(self.pool.acquire(64, 32, fmt), first)
        other = self.pool.acquire(32, 64, fmt)
        self.assertNotEqual(other, first)
        self.assertEqual(self.pool.get_info()["outstanding"], 2)
        self.pool.release(first, 64, 32, fmt)
        self.pool.release(other, 32, 64, fmt)
        # running out:
        textures = [self.pool.acquire(16, 16, fmt) for _ in range(device.MAX_SNAPSHOTS + 1)]
        self.assertEqual(textures[-1], 0)
        self.assertTrue(all(textures[:-1]))
        for texture in textures[:-1]:
            self.pool.release(texture, 16, 16, fmt)
        info = self.pool.get_info()
        self.assertEqual(info["outstanding"], 0)
        self.assertEqual(info["idle"]["16x16"], device.MAX_IDLE_SNAPSHOTS)

    def test_release_after_close(self):
        fmt = 87
        texture = self.pool.acquire(16, 16, fmt)
        self.pool.close()
        self.assertEqual(self.pool.acquire(16, 16, fmt), 0)
        # released directly:
        self.pool.release(texture, 16, 16, fmt)
        self.assertEqual(self.pool.get_info()["idle"], {})


class CPUCapture:

    def __init__(self):
        self.closed = False
        self.downloads = []
        self.frame = 0

    def download(self, texture, x, y, width, height):
        if self.closed:
            raise CodecStateException("capture closed")
        self.downloads.append((x, y, width, height))
        return bytes((self.frame,)) * (width * height * 4)


@unittest.skipUnless(WIN32, "the d3d11 package is only available on MS Windows")
class TestDXGIImageWrapperCPU(unittest.TestCase):

    def make_image(self, capture):
        from xpra.platform.win32.d3d11.image import DXGIImageWrapper
        return DXGIImageWrapper(2, 1, 4, 2, "BGRX", 32, capture)

    def test_freeze_downloads_once_and_keeps_the_frame(self):
        capture = CPUCapture()
        image = self.make_image(capture)
        self.assertIsNone(image.get_gpu_buffer())
        self.assertFalse(image.has_pixels())
        self.assertTrue(image.freeze())
        capture.frame = 1
        self.assertEqual(image.get_pixels(), bytes(32))
        self.assertEqual(capture.downloads, [(2, 1, 4, 2)])
        self.assertIsNone(image.get_gpu_buffer())
        image.free()

    def test_keeps_capture_alive_until_freed(self):
        capture = CPUCapture()
        ref = weakref.ref(capture)
        image = self.make_image(capture)
        del capture
        self.assertIsNotNone(ref())
        self.assertEqual(image.get_pixels(), bytes(32))
        image.free()
        image.free()
        self.assertIsNone(ref())
        self.assertFalse(image.get_pixels())

    def test_capture_cleaned_before_download(self):
        capture = CPUCapture()
        image = self.make_image(capture)
        capture.closed = True
        with self.assertRaises(CodecStateException):
            image.get_pixels()
        self.assertFalse(image.has_pixels())
        image.free()

    def test_sub_image_and_restride_download_pixels(self):
        capture = CPUCapture()
        image = self.make_image(capture)
        image.set_target_x(20)
        image.set_target_y(10)
        image.set_full_range(False)
        sub = image.get_sub_image(1, 1, 2, 1)
        self.assertEqual(sub.get_pixels(), bytes(8))
        self.assertEqual((sub.get_target_x(), sub.get_target_y()), (21, 11))
        self.assertFalse(sub.get_full_range())
        self.assertTrue(image.restride(20))
        self.assertEqual(len(image.get_pixels()), 40)
        self.assertEqual(capture.downloads, [(3, 2, 2, 1), (2, 1, 4, 2)])
        image.free()
        sub.free()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
