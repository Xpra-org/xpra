# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from enum import IntEnum
from time import monotonic
from xpra.common import roundup
from xpra.util.str_fn import memoryview_to_bytes


def clone_plane(plane):
    if isinstance(plane, memoryview):
        return plane.tobytes()
    return plane[:]


class PlanarFormat(IntEnum):
    PACKED = 0
    PLANAR_2 = 2
    PLANAR_3 = 3
    PLANAR_4 = 4
    INVALID = -1


class ImageWrapper:
    PACKED: PlanarFormat = PlanarFormat.PACKED
    PLANAR_2: PlanarFormat = PlanarFormat.PLANAR_2
    PLANAR_3: PlanarFormat = PlanarFormat.PLANAR_3
    PLANAR_4: PlanarFormat = PlanarFormat.PLANAR_4
    PLANE_OPTIONS: tuple[PlanarFormat, PlanarFormat, PlanarFormat, PlanarFormat] = (
        PACKED, PLANAR_2, PLANAR_3, PLANAR_4,
    )

    def __init__(self, x: int, y: int, width: int, height: int, pixels, pixel_format: str, depth: int, rowstride,
                 bytesperpixel: int = 4, planes: PlanarFormat = PACKED, thread_safe: bool = True, palette=None,
                 full_range=True):
        self.x: int = x
        self.y: int = y
        self.target_x: int = x
        self.target_y: int = y
        self.width: int = width
        self.height: int = height
        self.pixels = pixels
        self.pixel_format = pixel_format
        self.depth: int = depth
        self.rowstride = rowstride
        self.bytesperpixel: int = bytesperpixel
        self.planes: PlanarFormat = planes
        self.thread_safe: bool = thread_safe
        self.freed: bool = False
        self.timestamp: int = int(monotonic() * 1000)
        self.palette = palette
        self.full_range = full_range
        if width <= 0 or height <= 0:
            raise ValueError(f"invalid geometry {x},{y},{width},{height}")

    def _cn(self):
        try:
            return type(self).__name__
        except AttributeError:  # pragma: no cover
            return type(self)

    def __repr__(self) -> str:
        return "%s(%s:%s:%s)" % (
            self._cn(), self.pixel_format, self.get_geometry(), getattr(self.planes, "name", self.planes),
        )

    def get_geometry(self) -> tuple[int, int, int, int, int]:
        return self.x, self.y, self.width, self.height, self.depth

    def get_x(self) -> int:
        return self.x

    def get_y(self) -> int:
        return self.y

    def get_target_x(self) -> int:
        return self.target_x

    def get_target_y(self) -> int:
        return self.target_y

    def set_target_x(self, target_x: int):
        self.target_x = target_x

    def set_target_y(self, target_y: int):
        self.target_y = target_y

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_rowstride(self):
        return self.rowstride

    def get_depth(self) -> int:
        return self.depth

    def get_bytesperpixel(self) -> int:
        return self.bytesperpixel

    def get_size(self) -> int:
        return self.rowstride * self.height

    def get_pixel_format(self) -> str:
        return self.pixel_format

    def get_pixels(self):
        return self.pixels

    def get_planes(self) -> PlanarFormat:
        return self.planes

    def get_palette(self):
        return self.palette

    def get_full_range(self) -> bool:
        return self.full_range

    def get_gpu_buffer(self):
        return None

    def has_pixels(self) -> bool:
        return bool(self.pixels)

    def is_thread_safe(self) -> bool:
        """ if True, free() and clone_pixel_data() can be called from any thread,
            if False, free() and clone_pixel_data() must be called from the same thread.
            Used by XImageWrapper to ensure X11 images are freed from the UI thread.
        """
        return self.thread_safe

    def get_timestamp(self) -> int:
        """ time in millis """
        return self.timestamp

    def set_timestamp(self, timestamp: int) -> None:
        self.timestamp = timestamp

    def set_planes(self, planes: PlanarFormat) -> None:
        self.planes = planes

    def set_rowstride(self, rowstride: int) -> None:
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format) -> None:
        self.pixel_format = pixel_format

    def set_palette(self, palette) -> None:
        self.palette = palette

    def set_full_range(self, full_range: bool) -> None:
        self.full_range = full_range

    def set_pixels(self, pixels) -> None:
        if self.freed:
            raise RuntimeError("image wrapper has already been freed")
        self.pixels = pixels

    def allocate_buffer(self, _buf_len, _free_existing=1) -> int:
        if self.freed:
            raise RuntimeError("image wrapper has already been freed")
        # only defined for XImage wrappers:
        return 0

    def may_restride(self) -> bool:
        newstride = roundup(self.width * self.bytesperpixel, 4)
        if self.rowstride > newstride:
            return self.restride(newstride)
        return False

    def restride(self, rowstride: int) -> bool:
        if self.freed:
            raise RuntimeError("image wrapper has already been freed")
        if self.planes > 0:
            # not supported yet for planar images
            return False
        pixels = self.pixels
        assert pixels, "no pixel data to restride"
        oldstride = self.rowstride
        pos = 0
        lines = []
        for _ in range(self.height):
            lines.append(memoryview_to_bytes(pixels[pos:pos + rowstride]))
            pos += oldstride
        if self.height > 0 and oldstride < rowstride:
            # the last few lines may need padding if the new rowstride is bigger
            # (usually just the last line)
            # we do this here to avoid slowing down the main loop above
            # as this should be a rarer case
            for h in range(self.height):
                i = -(1 + h)
                line = lines[i]
                if len(line) < rowstride:
                    lines[i] = line + b"\0" * (rowstride - len(line))
                else:
                    break
        self.rowstride = rowstride
        self.pixels = b"".join(lines)
        return True

    def freeze(self) -> bool:
        if self.freed:
            raise RuntimeError("image wrapper has already been freed")
        # some wrappers (XShm) need to be told to stop updating the pixel buffer
        return False

    def clone_pixel_data(self) -> None:
        if self.freed:
            raise RuntimeError("image wrapper has already been freed")
        pixels = self.pixels
        planes = self.planes
        if not pixels:
            raise ValueError("no pixel data to clone")
        if planes < 0:
            raise ValueError(f"invalid number of planes {planes}")
        if planes == 0:
            # no planes, simple buffer:
            self.pixels = clone_plane(pixels)
        else:
            self.pixels = [clone_plane(pixels[i]) for i in range(planes)]
        self.thread_safe = True
        if self.freed:  # pragma: no cover
            # could be a race since this can run threaded
            self.free()

    def get_sub_image(self, x: int, y: int, w: int, h: int):
        # raise NotImplementedError("no sub-images for %s" % type(self))
        if w <= 0 or h <= 0:
            raise ValueError(f"invalid sub-image size: {w}x{h}")
        if x + w > self.width:
            raise ValueError(f"invalid sub-image width: {x}+{w} greater than image width {self.width}")
        if y + h > self.height:
            raise ValueError(f"invalid sub-image height: {y}+{h} greater than image height {self.height}")
        if self.planes != ImageWrapper.PACKED:
            raise NotImplementedError("cannot sub-divide a planar image!")
        if x == 0 and y == 0 and w == self.width and h == self.height:
            # same dimensions, use the same wrapper
            return self
        # copy to local variables:
        pixels = self.pixels
        oldstride = self.rowstride
        pos = y * oldstride + x * self.bytesperpixel
        newstride = w * self.bytesperpixel
        lines = []
        for _ in range(h):
            lines.append(memoryview_to_bytes(pixels[pos:pos + newstride]))
            pos += oldstride
        image = ImageWrapper(self.x + x, self.y + y, w, h, b"".join(lines), self.pixel_format, self.depth, newstride,
                             planes=self.planes, thread_safe=True, palette=self.palette, full_range=self.full_range)
        image.set_target_x(self.target_x + x)
        image.set_target_y(self.target_y + y)
        return image

    def __del__(self) -> None:
        self.free()

    def __dealloc__(self):
        self.free()

    def free(self) -> None:
        if not hasattr(self, "freed"):
            return
        if not self.freed:
            self.freed = True
            self.planes = PlanarFormat.INVALID
            self.pixels = ()
            self.pixel_format = ""
