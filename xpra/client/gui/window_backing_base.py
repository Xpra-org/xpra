# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from threading import Lock
from collections import deque
from typing import Any
from collections.abc import Callable, Iterable, Sequence

from xpra.net import compression
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, first_time
from xpra.codecs.loader import get_codec
from xpra.codecs.video import getVideoHelper, VdictEntry, CodecSpec
from xpra.codecs.constants import TransientCodecException, CodecStateException
from xpra.common import Gravity, PaintCallbacks
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("paint")
videolog = Logger("video", "paint")

PAINT_BOX = envint("XPRA_PAINT_BOX", 0)
WEBP_PILLOW = envbool("XPRA_WEBP_PILLOW", False)
WEBP_YUV = envbool("XPRA_WEBP_YUV", False)
REPAINT_ALL = envbool("XPRA_REPAINT_ALL", False)
SHOW_FPS = envbool("XPRA_SHOW_FPS", False)
# prefer csc scaling to cairo's own scaling:
PREFER_CSC_SCALING = envbool("XPRA_PREFER_CSC_SCALING", True)

_PIL_font = None


def load_pillow_font():
    global _PIL_font
    if _PIL_font:
        return _PIL_font
    from PIL import ImageFont  # pylint: disable=import-outside-toplevel
    for font_file in (
            "/usr/share/fonts/gnu-free/FreeMono.ttf",
            "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
    ):
        if os.path.exists(font_file):
            try:
                _PIL_font = ImageFont.load_path(font_file)
                return _PIL_font
            except OSError:
                pass
    _PIL_font = ImageFont.load_default()
    return _PIL_font


# ie:
# CSC_OPTIONS = { "YUV420P" : {"RGBX" : [swscale.spec], "BGRX" : ...} }
CSC_OPTIONS: dict[str, VdictEntry] = {}
VIDEO_DECODERS: dict[str, VdictEntry] = {}
_loaded_video = False


def load_video() -> None:
    global _loaded_video
    if _loaded_video:
        return
    _loaded_video = True
    vh = getVideoHelper()
    for csc_in in vh.get_csc_inputs():
        CSC_OPTIONS[csc_in] = vh.get_csc_specs(csc_in)
    log("csc options: %s", CSC_OPTIONS)
    for encoding in vh.get_decodings():
        VIDEO_DECODERS[encoding] = vh.get_decoder_specs(encoding)
    log("video decoders: %s", VIDEO_DECODERS)


def fire_paint_callbacks(callbacks: PaintCallbacks, success: int | bool = True, message="") -> None:
    for callback in callbacks:
        with log.trap_error("Error calling %s with %s", callback, (success, message)):
            callback(success, message)


def rgba_text(text: str, width: int = 64, height: int = 32, x: int = 20, y: int = 10, bg=(128, 128, 128, 32)) -> bytes:
    try:
        from PIL import Image, ImageDraw  # pylint: disable=import-outside-toplevel
    except ImportError:
        log("rgba_text(..)", exc_info=True)
        if first_time("pillow-text-overlay"):
            log.warn("Warning: cannot show text overlay without python pillow")
        return b""
    rgb_format = "RGBA"
    img = Image.new(rgb_format, (width, height), color=bg)
    draw = ImageDraw.Draw(img)
    font = load_pillow_font()
    draw.text((x, y), text, "blue", font=font)
    return img.tobytes("raw", rgb_format)


def choose_decoder(decoders_for_cs: list[CodecSpec], max_setup_cost=100) -> CodecSpec:
    # for now, just rank by setup-cost, so gstreamer decoders come last:
    scores: dict[int, list[int]] = {}
    for index, decoder_spec in enumerate(decoders_for_cs):
        cost = decoder_spec.setup_cost
        if cost > max_setup_cost:
            continue
        scores.setdefault(cost, []).append(index)
    if not scores:
        raise RuntimeError("no decoders available!")
    best_score = sorted(scores)[0]
    options_for_score = scores[best_score]
    # if multiple decoders have the same score, just use the first one:
    chosen = decoders_for_cs[options_for_score[0]]
    videolog(f"choose_decoder({decoders_for_cs})={chosen}")
    return chosen


class WindowBackingBase:
    """
    Generic superclass for all Backing code,
    see CairoBackingBase and GTKWindowBacking subclasses for actual implementations
    """
    RGB_MODES: Sequence[str] = ()

    def __init__(self, wid: int, window_alpha: bool):
        load_video()
        self.wid: int = wid
        self.size: tuple[int, int] = (0, 0)
        self.render_size: tuple[int, int] = (0, 0)
        # padding between the window contents and where we actually draw the backing
        # (ie: if the window is bigger than the backing,
        # we may be rendering the backing in the center of the window)
        self.offsets: tuple[int, int, int, int] = (0, 0, 0, 0)  # top,left,bottom,right
        self.gravity: int = 0
        self._alpha_enabled = window_alpha
        self._backing = None
        self._video_decoder = None
        self._csc_decoder = None
        self._decoder_lock = Lock()
        self._PIL_encodings = []
        self.default_paint_box_line_width = PAINT_BOX or 1
        self.paint_box_line_width = PAINT_BOX
        self.pointer_overlay = ()
        self.cursor_data = None
        self.default_cursor_data = None
        self.jpeg_decoder = None
        self.webp_decoder = None
        self.pil_decoder = get_codec("dec_pillow")
        if self.pil_decoder:
            self._PIL_encodings = self.pil_decoder.get_encodings()
        self.jpeg_decoder = get_codec("dec_jpeg")
        self.webp_decoder = get_codec("dec_webp")
        self.spng_decoder = get_codec("dec_spng")
        self.avif_decoder = get_codec("dec_avif")
        self.nvjpeg_decoder = get_codec("dec_nvjpeg")
        self.nvdec_decoder = get_codec("nvdec")
        self.cuda_context = None
        self.draw_needs_refresh: bool = True
        self.repaint_all: bool = REPAINT_ALL
        self.mmap = None
        self.fps_events: deque = deque(maxlen=120)
        self.fps_buffer_size: tuple[int, int] = (0, 0)
        self.fps_buffer_update_time: float = 0
        self.fps_value: int = 0
        self.fps_refresh_timer: int = 0
        self.paint_stats: dict[str, int] = {}

    def recpaint(self, encoding: str) -> None:
        self.paint_stats[encoding] = self.paint_stats.get(encoding, 0) + 1

    def get_rgb_formats(self) -> Sequence[str]:
        if self._alpha_enabled:
            return self.RGB_MODES
        # remove modes with alpha:
        return tuple(x for x in self.RGB_MODES if x.find("A") < 0)

    def get_info(self) -> dict[str, Any]:
        info = {
            "rgb-formats": self.get_rgb_formats(),
            "transparency": self._alpha_enabled,
            "mmap": bool(self.mmap),
            "size": self.size,
            "render-size": self.render_size,
            "offsets": self.offsets,
            "fps": self.fps_value,
            "paint": self.paint_stats,
        }
        vd = self._video_decoder
        if vd:
            info["video-decoder"] = vd.get_info()
        csc = self._csc_decoder
        if csc:
            info["csc"] = csc.get_info()
        return info

    def record_fps_event(self) -> None:
        self.fps_events.append(monotonic())
        now = monotonic()
        elapsed = now - self.fps_buffer_update_time
        if elapsed > 0.2:
            self.update_fps()

    def update_fps(self) -> None:
        self.fps_buffer_update_time = monotonic()
        self.fps_value = self.calculate_fps()
        if self.is_show_fps():
            text = f"{self.fps_value} fps"
            width, height = 64, 32
            self.fps_buffer_size = (width, height)
            pixels = rgba_text(text, width, height)
            if pixels:
                self.update_fps_buffer(width, height, pixels)

    def update_fps_buffer(self, width: int, height: int, pixels) -> None:
        raise NotImplementedError

    def calculate_fps(self) -> int:
        pe = list(self.fps_events)
        if not pe:
            return 0
        e0 = pe[0]
        now = monotonic()
        elapsed = now - e0
        if 0 < elapsed <= 1 and len(pe) >= 5:
            return round(len(pe) / elapsed)
        cutoff = now - 1
        count = 0
        while pe and pe.pop() >= cutoff:
            count += 1
        return count

    def is_show_fps(self) -> bool:
        if not SHOW_FPS and self.paint_box_line_width <= 0:
            return False
        # show fps if the value is non-zero:
        if self.fps_value > 0:
            return True
        pe = list(self.fps_events)
        if not pe:
            return False
        last_fps_event = pe[-1]
        # or if there was an event less than `max_time` seconds ago:
        max_time = 4
        return monotonic() - last_fps_event < max_time

    def cancel_fps_refresh(self) -> None:
        frt = self.fps_refresh_timer
        if frt:
            self.fps_refresh_timer = 0
            GLib.source_remove(frt)

    def enable_mmap(self, mmap_area) -> None:
        self.mmap = mmap_area

    def gravity_copy_coords(self, oldw: int, oldh: int, bw: int, bh: int) -> tuple[int, int, int, int, int, int]:
        sx = sy = dx = dy = 0

        def center_y() -> tuple[int, int]:
            if bh >= oldh:
                # take the whole source, paste it in the middle
                return 0, (bh - oldh) // 2
            # skip the edges of the source, paste all of it
            return (oldh - bh) // 2, 0

        def center_x() -> tuple[int, int]:
            if bw >= oldw:
                return 0, (bw - oldw) // 2
            return (oldw - bw) // 2, 0

        def east_x() -> tuple[int, int]:
            if bw >= oldw:
                return 0, bw - oldw
            return oldw - bw, 0

        def west_x() -> tuple[int, int]:
            return 0, 0

        def north_y() -> tuple[int, int]:
            return 0, 0

        def south_y() -> tuple[int, int]:
            if bh >= oldh:
                return 0, bh - oldh
            return oldh - bh, 0

        g = self.gravity
        if not g or g == Gravity.NorthWest:
            # undefined (or 0), use NW
            sx, dx = west_x()
            sy, dy = north_y()
        elif g == Gravity.North:
            sx, dx = center_x()
            sy, dy = north_y()
        elif g == Gravity.NorthEast:
            sx, dx = east_x()
            sy, dy = north_y()
        elif g == Gravity.West:
            sx, dx = west_x()
            sy, dy = center_y()
        elif g == Gravity.Center:
            sx, dx = center_x()
            sy, dy = center_y()
        elif g == Gravity.East:
            sx, dx = east_x()
            sy, dy = center_y()
        elif g == Gravity.SouthWest:
            sx, dx = west_x()
            sy, dy = south_y()
        elif g == Gravity.South:
            sx, dx = center_x()
            sy, dy = south_y()
        elif g == Gravity.SouthEast:
            sx, dx = east_x()
            sy, dy = south_y()
        elif g == Gravity.Static and first_time(f"Gravity.Static-{self.wid}"):
            log.warn(f"Warning: window {self.wid} requested static gravity")
            log.warn(" this is not implemented yet")
        w = min(bw, oldw)
        h = min(bh, oldh)
        return sx, sy, dx, dy, w, h

    def gravity_adjust(self, x: int, y: int, options: typedict) -> tuple[int, int]:
        # if the window size has changed,
        # adjust the coordinates honouring the window gravity:
        window_size = options.inttupleget("window-size")
        g = self.gravity
        log("gravity_adjust%s window_size=%s, size=%s, gravity=%s",
            (x, y, options), window_size, self.size, g or "unknown")
        if not window_size:
            return x, y
        if window_size == self.size:
            return x, y
        if g == 0 or self.gravity == Gravity.NorthWest:
            return x, y
        oldw, oldh = window_size
        bw, bh = self.size

        def center_y() -> int:
            if bh >= oldh:
                return y + (bh - oldh) // 2
            return y - (oldh - bh) // 2

        def center_x() -> int:
            if bw >= oldw:
                return x + (bw - oldw) // 2
            return x - (oldw - bw) // 2

        def east_x() -> int:
            if bw >= oldw:
                return x + (bw - oldw)
            return x - (oldw - bw)

        def west_x() -> int:
            return x

        def north_y() -> int:
            return y

        def south_y() -> int:
            if bh >= oldh:
                return y + (bh - oldh)
            return y - (oldh - bh)

        if g == Gravity.North:
            return center_x(), north_y()
        if g == Gravity.NorthEast:
            return east_x(), north_y()
        if g == Gravity.West:
            return west_x(), center_y()
        if g == Gravity.Center:
            return center_x(), center_y()
        if g == Gravity.East:
            return east_x(), center_y()
        if g == Gravity.SouthWest:
            return west_x(), south_y()
        if g == Gravity.South:
            return center_x(), south_y()
        if g == Gravity.SouthEast:
            return east_x(), south_y()
        # if self.gravity==Gravity.Static:
        #    pass
        return x, y

    def assign_cuda_context(self, opengl=False):
        if self.cuda_context is None:
            from xpra.codecs.nvidia.cuda.context import (
                get_default_device_context,  # @NoMove pylint: disable=no-name-in-module, import-outside-toplevel
                cuda_device_context,
            )
            dev = get_default_device_context()
            assert dev, "no cuda device context"
            # pylint: disable=import-outside-toplevel
            self.cuda_context = cuda_device_context(dev.device_id, dev.device, opengl)
            # create the context now as this is the part that takes time:
            self.cuda_context.make_context()
        return self.cuda_context

    def free_cuda_context(self) -> None:
        cc = self.cuda_context
        if cc:
            self.cuda_context = None
            cc.free()

    def close(self) -> None:
        self.free_cuda_context()
        self.cancel_fps_refresh()
        self._backing = None
        log("%s.close() video_decoder=%s", self, self._video_decoder)
        # try without blocking, if that fails then
        # the lock is held by the decoding thread,
        # and it will run the cleanup after releasing the lock
        # (it checks for self._backing None)
        self.close_decoder(False)

    def close_decoder(self, blocking=False) -> bool:
        videolog("close_decoder(%s)", blocking)
        dl = self._decoder_lock
        if dl is None or not dl.acquire(blocking):  # pylint: disable=consider-using-with
            videolog("close_decoder(%s) lock %s not acquired", blocking, dl)
            return False
        try:
            self.do_clean_video_decoder()
            self.do_clean_csc_decoder()
            return True
        finally:
            dl.release()

    def do_clean_video_decoder(self) -> None:
        if self._video_decoder:
            self._video_decoder.clean()
            self._video_decoder = None

    def do_clean_csc_decoder(self) -> None:
        if self._csc_decoder:
            self._csc_decoder.clean()
            self._csc_decoder = None

    def get_encoding_properties(self) -> dict[str, Any]:
        return {
            "encodings.rgb_formats": self.get_rgb_formats(),
            "encoding.transparency": self._alpha_enabled,
            "encoding.full_csc_modes": self._get_full_csc_modes(self.get_rgb_formats()),
            "encoding.send-window-size": True,
            "encoding.render-size": self.render_size,
        }

    def _get_full_csc_modes(self, rgb_modes: Iterable[str]) -> dict[str, Any]:
        # calculate the server CSC modes the server is allowed to use
        # based on the client CSC modes we can convert to in the backing class we use
        # and trim the transparency if we cannot handle it
        target_rgb_modes = tuple(rgb_modes)
        if not self._alpha_enabled:
            target_rgb_modes = tuple(x for x in target_rgb_modes if x.find("A") < 0)
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*target_rgb_modes)
        full_csc_modes["webp"] = [x for x in rgb_modes if x in ("BGRX", "BGRA", "RGBX", "RGBA")]
        full_csc_modes["jpeg"] = [x for x in rgb_modes if x in ("BGRX", "BGRA", "RGBX", "RGBA", "YUV420P")]
        if self._alpha_enabled:
            # this would not match any target rgb modes anyway,
            # best not to have it in the list at all:
            full_csc_modes["jpega"] = [x for x in rgb_modes if x in ("BGRA", "RGBA")]
        videolog("_get_full_csc_modes(%s) with alpha=%s, target_rgb_modes=%s",
                 rgb_modes, self._alpha_enabled, target_rgb_modes)
        for e in sorted(full_csc_modes.keys()):
            modes = full_csc_modes.get(e)
            videolog(" * %s : %s", e, modes)
        return full_csc_modes

    def set_cursor_data(self, cursor_data) -> None:
        self.cursor_data = cursor_data

    def paint_jpeg(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        self.do_paint_jpeg("jpeg", img_data, x, y, width, height, options, callbacks)

    def paint_jpega(self, img_data, x: int, y: int, width: int, height: int,
                    options: typedict, callbacks: PaintCallbacks) -> None:
        self.do_paint_jpeg("jpega", img_data, x, y, width, height, options, callbacks)

    def nv_decode(self, encoding: str, img_data, width: int, height: int, options: typedict):
        if width < 16 or height < 16:
            return None
        nvdec = self.nvdec_decoder
        nvjpeg = self.nvjpeg_decoder
        if not nvdec and not nvjpeg:
            return None
        try:
            with self.assign_cuda_context(False):
                if nvdec and encoding in nvdec.get_encodings():
                    return nvdec.decompress_and_download(encoding, img_data, width, height, options)
                if nvjpeg and encoding in nvjpeg.get_encodings():
                    return nvjpeg.decompress_and_download("RGB", img_data, options)
                return None
        except TransientCodecException as e:
            log(f"nv_decode failed: {e} - will retry")
            return None
        except RuntimeError as e:
            self.nvdec_decoder = self.nvjpeg_decoder = None
            log(f"nv_decode {encoding=}", exc_info=True)
            log.warn("Warning: nv decode error, disabling hardware accelerated decoding for this window")
            log.warn(f" {e}")
            return None

    def do_paint_jpeg(self, encoding: str, img_data, x: int, y: int, width: int, height: int,
                      options: typedict, callbacks: PaintCallbacks) -> None:
        img = self.nv_decode(encoding, img_data, width, height, options)
        if img is None:
            assert self.jpeg_decoder is not None
            img = self.jpeg_decoder.decompress_to_rgb(img_data, options)
        self.paint_image_wrapper(encoding, img, x, y, width, height, options, callbacks)

    def paint_avif(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks):
        img = self.avif_decoder.decompress(img_data, options)
        self.paint_image_wrapper("avif", img, x, y, width, height, options, callbacks)

    def paint_pillow(self, coding: str, img_data, x: int, y: int, width: int, height: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        # can be called from any thread
        rgb_format, img_data, iwidth, iheight, rowstride = self.pil_decoder.decompress(coding, img_data, options)
        self.ui_paint_rgb(coding, rgb_format, img_data,
                          x, y, iwidth, iheight, width, height, rowstride, options, callbacks)

    def paint_spng(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        rgba, rgb_format, iwidth, iheight = self.spng_decoder.decompress(img_data, options)
        rowstride = iwidth * len(rgb_format)
        self.ui_paint_rgb("png", rgb_format, rgba,
                          x, y, iwidth, iheight, width, height, rowstride, options, callbacks)

    def paint_webp(self, img_data, x: int, y: int, width: int, height: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        if not self.webp_decoder or WEBP_PILLOW:
            # if webp is enabled, then Pillow should be able to take care of it:
            self.paint_pillow("webp", img_data, x, y, width, height, options, callbacks)
            return
        if WEBP_YUV:
            img = self.webp_decoder.decompress_to_yuv(img_data, options)
            self.paint_image_wrapper("webp", img, x, y, width, height, options, callbacks)
            return
        img = self.webp_decoder.decompress_to_rgb(img_data, options)
        self.paint_image_wrapper("webp", img, x, y, width, height, options, callbacks)

    def paint_rgb(self, rgb_format: str, raw_data, x: int, y: int, width: int, height: int, rowstride: int,
                  options, callbacks: PaintCallbacks) -> None:
        """ can be called from a non-UI thread """
        # was a compressor used?
        comp = tuple(x for x in compression.ALL_COMPRESSORS if options.intget(x, 0))
        if comp:
            if len(comp) != 1:
                raise ValueError(f"more than one compressor specified: {comp!r}")
            compressor = comp[0]
            if compressor != "lz4":
                raise ValueError(f"pixel data can only be compressed with lz4, not {compressor!r}")
            rgb_data = compression.decompress_by_name(raw_data, algo=compressor)
        else:
            rgb_data = raw_data
        self.ui_paint_rgb("rgb", rgb_format, rgb_data,
                          x, y, width, height, width, height, rowstride, options, callbacks)

    def ui_paint_rgb(self, *args) -> None:
        """ calls do_paint_rgb from the ui thread """
        self.with_gfx_context(self.do_paint_rgb, *args)

    def paint_image_wrapper(self, encoding: str, img, x: int, y: int, width: int, height: int,
                            options: typedict, callbacks: PaintCallbacks) -> None:
        self.with_gfx_context(self.do_paint_image_wrapper, encoding, img, x, y, width, height, options, callbacks)

    def do_paint_image_wrapper(self, context, encoding: str, img, x: int, y: int, width: int, height: int,
                               options: typedict, callbacks: PaintCallbacks) -> None:
        pixel_format = img.get_pixel_format()
        if pixel_format in ("NV12", "YUV420P", "YUV422P", "YUV444P"):
            # jpeg may be decoded to these formats by nvjpeg / nvdec
            enc_width, enc_height = options.intpair("scaled_size", (width, height))
            self.do_video_paint(encoding, img, x, y, enc_width, enc_height, width, height, options, callbacks)
            return
        if img.get_planes() > 1:
            raise ValueError(f"cannot handle {img.get_planes()} in this backend")
        # if the backing can't handle this format,
        # ie: tray only supports RGBA
        if pixel_format not in self.get_rgb_formats():
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.rgb_transform import rgb_reformat
            has_alpha = pixel_format.find("A") >= 0 and self._alpha_enabled
            rgb_reformat(img, self.get_rgb_formats(), has_alpha)
            pixel_format = img.get_pixel_format()
        # replace with the actual rgb format we get from the decoder / rgb_reformat:
        options["rgb_format"] = pixel_format
        w = img.get_width()
        h = img.get_height()
        pixels = img.get_pixels()
        stride = img.get_rowstride()
        self.do_paint_rgb(context, encoding, pixel_format, pixels, x, y, w, h, width, height, stride, options, callbacks)
        img.free()

    def with_gfx_context(self, function: Callable, *args) -> None:
        # the opengl backend overrides this function
        # to provide the opengl context, we use None here:
        GLib.idle_add(function, None, *args)

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        # see subclasses `GLWindowBackingBase` and `CairoBacking`
        raise NotImplementedError()

    def eos(self) -> None:
        dl = self._decoder_lock
        with dl:
            self.do_clean_csc_decoder()
            self.do_clean_video_decoder()

    def make_csc(self, src_width: int, src_height: int, src_format: str,
                 dst_width: int, dst_height: int, dst_format_options: Iterable[str],
                 options: typedict):
        q = options.intget("quality", 50)
        speed = min(100, 100 - q, round(100.0 * (src_width * src_height) / (dst_width * dst_height)))

        in_options = CSC_OPTIONS.get(src_format, {})
        videolog("make_csc%s",
                 (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, speed))
        need_scaling = src_width != dst_width or src_height != dst_height
        # note: the best scores are the lowest!
        csc_scores = {}
        for dst_format in dst_format_options:
            specs = in_options.get(dst_format)
            videolog("make_csc specs(%s)=%s", dst_format, specs)
            if not specs:
                continue
            for spec in specs:
                v = self.validate_csc_size(spec, src_width, src_height, dst_width, dst_height)
                if v:
                    # not suitable
                    continue
                score = - (spec.quality + spec.speed + spec.score_boost)
                # see issue #4270
                # the cairo backend can only do zero-copy paints from BGRX / BGRA pixel formats
                if dst_format not in ("BGRA", "BGRX"):
                    score += 50
                if need_scaling and not spec.can_scale and PREFER_CSC_SCALING:
                    # keep it, but not a good score:
                    score += 100
                csc_scores.setdefault(score, []).append((dst_format, spec))

        def nomatch() -> None:
            videolog.error("Error: no matching csc options")
            videolog.error(f" for {src_format!r} {src_width}x{src_height} input")
            videolog.error(f" to {csv(dst_format_options)} {dst_width}x{dst_height} output")
            videolog.error(f" speed={speed}")
            videolog.error(" all csc options:")
            for k, vdict in CSC_OPTIONS.items():
                videolog.error(" * %-10s : %s", k, csv(vdict))
            videolog.error(f" tested {src_format!r} to:")
            for dst_format in dst_format_options:
                specs = in_options.get(dst_format)
                if not specs:
                    videolog.error(" * %-10s : no match", dst_format)
                    continue
                videolog.error(" * %-10s:", dst_format)
                for spec in specs:
                    errs = []
                    size_error = self.validate_csc_size(spec, src_width, src_height, dst_width, dst_height)
                    if size_error:
                        errs.append(size_error)
                    if not spec.can_scale and (src_width != dst_width or src_height != dst_height):
                        errs.append("scaling not supported")
                    videolog.error(f"              - {spec}{csv(errs)}")

        videolog(f"csc scores: {csc_scores}")
        if not csc_scores:
            nomatch()
            raise ValueError(f"no csc options for {src_format!r} input in " + csv(CSC_OPTIONS.keys()))

        # make a copy to override speed:
        options = typedict(options)
        options["speed"] = speed
        for score in sorted(csc_scores):
            for dst_format, spec in csc_scores.get(score):
                try:
                    csc = spec.codec_class()
                    width = dst_width if (spec.can_scale and PREFER_CSC_SCALING) else src_width
                    height = dst_height if (spec.can_scale and PREFER_CSC_SCALING) else src_height
                    csc.init_context(src_width, src_height, src_format,
                                     width, height, dst_format, options)
                    return csc
                except Exception as e:
                    videolog("make_csc%s",
                             (src_width, src_height, src_format, dst_width, dst_height, dst_format_options, options),
                             exc_info=True)
                    videolog.error("Error: failed to create csc instance %s", spec.codec_class)
                    videolog.error(" for %s to %s: %s", src_format, dst_format, e)
        nomatch()
        raise ValueError(f"no csc options for {src_format!r} input in " + csv(CSC_OPTIONS.keys()))

    @staticmethod
    def validate_csc_size(spec, src_width: int, src_height: int, dst_width: int, dst_height: int) -> str:
        if src_width < spec.min_w:
            return f"source width {src_width} is out of range: minimum is {spec.min_w}"
        if src_height < spec.min_h:
            return f"source height {src_height} is out of range: minimum is {spec.min_h}"
        if dst_width < spec.min_w:
            return f"target width {dst_width} is out of range: minimum is {spec.min_w}"
        if dst_height < spec.min_h:
            return f"target height {dst_height} is out of range: minimum is {spec.min_h}"
        if src_width > spec.max_w:
            return f"source width {src_width} is out of range: maximum is {spec.max_w}"
        if src_height > spec.max_h:
            return f"source height {src_height} is out of range: maximum is {spec.max_h}"
        if dst_width > spec.max_w:
            return f"target width {dst_width} is out of range: maximum is {spec.max_w}"
        if dst_height > spec.max_h:
            return f"target height {dst_height} is out of range: maximum is {spec.max_h}"
        return ""

    def paint_with_video_decoder(self, coding: str, img_data, x: int, y: int, width: int, height: int,
                                 options: typedict, callbacks: PaintCallbacks) -> None:
        dl = self._decoder_lock
        if dl is None:
            fire_paint_callbacks(callbacks, False, "no lock - retry")
            return
        with dl:
            vd = self._video_decoder

            def restart(msg: str, *args) -> None:
                if vd or self._csc_decoder:
                    videolog("paint_with_video_decoder: "+msg, *args)
                    self.do_clean_video_decoder()
                    self.do_clean_csc_decoder()

            if self._backing is None:
                restart("no backing")
                message = f"window {self.wid} is already gone!"
                log(message)
                fire_paint_callbacks(callbacks, -1, message)
                return

            enc_width, enc_height = options.intpair("scaled_size", (width, height))
            input_colorspace = options.strget("csc", "YUV420P")
            if vd:
                frame = options.intget("frame", -1)
                # first frame should always be no 0
                # (but some encoders start at 1..)
                if frame == 0:
                    restart("first frame of new stream")
                elif vd.get_encoding() != coding:
                    restart("encoding changed from %s to %s", vd.get_encoding(), coding)
                elif vd.get_width() != enc_width or vd.get_height() != enc_height:
                    restart("video dimensions have changed from %s to %s",
                            (vd.get_width(), vd.get_height()), (enc_width, enc_height))
                elif vd.get_colorspace() != input_colorspace:
                    # this should only happen on encoder restart, which means this should be the first frame:
                    videolog.warn("Warning: colorspace unexpectedly changed from %s to %s",
                                  vd.get_colorspace(), input_colorspace)
                    videolog.warn(f" decoding {coding} frame {frame} using {vd.get_type()}")
                    restart("colorspace mismatch")
            if self._video_decoder is None:
                # find the best decoder type and instantiate it:
                decoder_options: VdictEntry = VIDEO_DECODERS.get(coding, {})
                if not decoder_options:
                    raise RuntimeError(f"no video decoders for {coding!r}")
                all_decoders_for_cs: Sequence[CodecSpec] = decoder_options.get(input_colorspace, {})
                if not all_decoders_for_cs:
                    raise RuntimeError(f"no video decoders for {coding!r} and {input_colorspace!r}")
                decoders_for_cs = list(all_decoders_for_cs)
                while not self._video_decoder:
                    decoder_spec = choose_decoder(decoders_for_cs)
                    videolog("paint_with_video_decoder: new %s%s",
                             decoder_spec.codec_type, (coding, enc_width, enc_height, input_colorspace))
                    try:
                        vd = decoder_spec.codec_class()
                        vd.init_context(coding, enc_width, enc_height, input_colorspace, options)
                        self._video_decoder = vd
                        break
                    except TransientCodecException as e:
                        log("%s.init_context(..)", vd, exc_info=True)
                        log.warn(f"Warning: failed to initialize decoder {decoder_spec.codec_type}: {e}")
                        decoder_spec.setup_cost += 10
                    except RuntimeError as e:
                        log("%s.init_context(..)", vd, exc_info=True)
                        log.warn(f"Warning: failed to initialize decoder {decoder_spec.codec_type}: {e}")
                        decoder_spec.setup_cost += 50
                    if decoder_spec.setup_cost > 100:
                        decoders_for_cs.remove(decoder_spec)
                        if not decoders_for_cs:
                            decoder_options.pop(input_colorspace, None)
                            if not decoder_options:
                                VIDEO_DECODERS.pop(coding, None)
                            msg = f"no decoders for {coding!r} and {input_colorspace!r}"
                            fire_paint_callbacks(callbacks, -1, msg)
                            log(f"{msg}: {all_decoders_for_cs}")
                            return
                videolog("paint_with_video_decoder: info=%s", vd.get_info())
            try:
                img = vd.decompress_image(img_data, options)
            except CodecStateException as e:
                restart(str(e))
                img = None
            if not img:
                if options.intget("delayed", 0) > 0:
                    # there are further frames queued up,
                    # and this frame references those, so assume all is well:
                    fire_paint_callbacks(callbacks)
                else:
                    fire_paint_callbacks(callbacks, False,
                                         "video decoder %s failed to decode %i bytes of %s data" % (
                                             vd.get_type(), len(img_data), coding))
                    videolog.error("Error: decode failed on %s bytes of %s data", len(img_data), coding)
                    videolog.error(" %sx%s pixels using %s", width, height, vd.get_type())
                    videolog.error(" frame options:")
                    for k, v in options.items():
                        videolog.error(f"    {k:10}={v}")
                return

            x, y = self.gravity_adjust(x, y, options)
            self.do_video_paint(coding, img, x, y, enc_width, enc_height, width, height, options, callbacks)
        if self._backing is None:
            self.close_decoder(True)

    def do_video_paint(self, coding: str, img, x: int, y: int, enc_width: int, enc_height: int, width: int, height: int,
                       options: typedict, callbacks: PaintCallbacks) -> None:
        target_rgb_formats = self.get_rgb_formats()
        # as some video formats like vpx can forward transparency
        # also we could skip the csc step in some cases:
        pixel_format = img.get_pixel_format()
        cd = self._csc_decoder
        csc_width = width if PREFER_CSC_SCALING else enc_width
        csc_height = height if PREFER_CSC_SCALING else enc_height
        if cd is not None:
            if cd.get_src_format() != pixel_format:
                videolog("do_video_paint csc: switching src format from %s to %s",
                         cd.get_src_format(), pixel_format)
                self.do_clean_csc_decoder()
            elif cd.get_dst_format() not in target_rgb_formats:
                videolog("do_video_paint csc: switching dst format from %s to %s",
                         cd.get_dst_format(), target_rgb_formats)
                self.do_clean_csc_decoder()
            elif cd.get_src_width() != enc_width or cd.get_src_height() != enc_height:
                videolog("do_video_paint csc: switching src size from %sx%s to %sx%s",
                         enc_width, enc_height, cd.get_src_width(), cd.get_src_height())
                self.do_clean_csc_decoder()
            elif cd.get_dst_width() != csc_width or cd.get_dst_height() != csc_height:
                videolog("do_video_paint csc: switching dst size from %sx%s to %sx%s",
                         cd.get_dst_width(), cd.get_dst_height(), csc_width, csc_height)
                self.do_clean_csc_decoder()
        if self._csc_decoder is None:
            # use higher quality csc to compensate for lower quality source
            # (which generally means that we downscaled via YUV422P or lower)
            # or when upscaling the video:
            cd = self.make_csc(enc_width, enc_height, pixel_format,
                               csc_width, csc_height, target_rgb_formats, options)
            videolog("do_video_paint new csc decoder: %s", cd)
            self._csc_decoder = cd
        rgb_format = cd.get_dst_format()
        rgb = cd.convert_image(img)
        videolog("do_video_paint rgb using %s.convert_image(%s)=%s", cd, img, rgb)
        img.free()
        if rgb.get_planes() != 0:
            raise RuntimeError(f"invalid number of planes for {rgb_format}: {rgb.get_planes()}")

        # this will also take care of firing callbacks (from the UI thread):
        self.paint_image_wrapper(coding, rgb, x, y, width, height, options, callbacks)

    def paint_mmap(self, img_data, x: int, y: int, width: int, height: int, rowstride: int,
                   options: typedict, callbacks: PaintCallbacks) -> None:
        if not self.mmap:
            raise RuntimeError("mmap paint packet without a valid mmap read area")
        from xpra.net.mmap import mmap_read
        # newer versions use the 'chunks' option, older versions overload the 'img_data'
        chunks = options.tupleget("chunks") or img_data
        data, free_cb = mmap_read(self.mmap.mmap, *chunks)
        callbacks.append(free_cb)
        rgb_format = options.strget("rgb_format", "RGB")
        # Note: BGR(A) is only handled by gl.backing
        x, y = self.gravity_adjust(x, y, options)
        self.ui_paint_rgb("mmap", rgb_format, data, x, y, width, height, width, height, rowstride,
                          options, callbacks)

    def paint_scroll(self, img_data, options: typedict, callbacks: PaintCallbacks) -> None:
        log("paint_scroll%s", (img_data, options, callbacks))
        raise NotImplementedError(f"no paint scroll on {type(self)}")

    def draw_region(self, x: int, y: int, width: int, height: int, coding: str, img_data, rowstride: int,
                    options: typedict, callbacks: PaintCallbacks) -> None:
        """ dispatches the paint to one of the paint_XXXX methods """
        self.recpaint(coding)
        try:
            assert self._backing is not None
            log("draw_region(%s, %s, %s, %s, %s, %s bytes, %s, %s, %s)",
                x, y, width, height, coding, len(img_data), rowstride, options, callbacks)
            options["encoding"] = coding  # used for choosing the color of the paint box
            if coding == "mmap":
                self.paint_mmap(img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding in ("rgb24", "rgb32"):
                # avoid confusion over how many bytes-per-pixel we may have:
                rgb_format = options.strget("rgb_format") or {
                    "rgb24": "RGB",
                    "rgb32": "RGBX",
                }.get(coding, "RGB")
                self.paint_rgb(rgb_format, img_data, x, y, width, height, rowstride, options, callbacks)
            elif coding in VIDEO_DECODERS:
                self.paint_with_video_decoder(coding,
                                              img_data, x, y, width, height, options, callbacks)
            elif self.jpeg_decoder and coding == "jpeg":
                self.paint_jpeg(img_data, x, y, width, height, options, callbacks)
            elif self.jpeg_decoder and coding == "jpega":
                self.paint_jpega(img_data, x, y, width, height, options, callbacks)
            elif self.avif_decoder and coding == "avif":
                self.paint_avif(img_data, x, y, width, height, options, callbacks)
            elif coding == "webp":
                self.paint_webp(img_data, x, y, width, height, options, callbacks)
            elif self.spng_decoder and coding == "png":
                self.paint_spng(img_data, x, y, width, height, options, callbacks)
            elif coding in self._PIL_encodings:
                self.paint_pillow(coding, img_data, x, y, width, height, options, callbacks)
            elif coding == "scroll":
                self.paint_scroll(img_data, options, callbacks)
            else:
                self.do_draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)
        except Exception:
            if self._backing is None:
                fire_paint_callbacks(callbacks, -1, "this backing is closed - retry?")
            else:
                raise

    # noinspection PyMethodMayBeStatic
    def do_draw_region(self, _x: int, _y: int, _width: int, _height: int, coding: str,
                       _img_data, _rowstride: int,
                       _options: typedict, callbacks: PaintCallbacks) -> None:
        msg = f"invalid encoding: {coding!r}"
        log.error("Error: %s", msg)
        fire_paint_callbacks(callbacks, False, msg)
