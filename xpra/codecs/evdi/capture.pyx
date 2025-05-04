# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import select
import binascii
from time import monotonic
from typing import Tuple, List
from collections.abc import Sequence

from xpra.util.env import envbool
from xpra.util.str_fn import bytestostr, strtobytes, memoryview_to_bytes

from xpra.log import Logger
log = Logger("evdi")

from libc.string cimport memset, memcpy
from xpra.buffers.membuf cimport getbuf, MemBuf
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, int32_t, uint32_t

DEF DRM_MODE_DPMS_ON = 0
DEF DRM_MODE_DPMS_STANDBY = 1
DEF DRM_MODE_DPMS_SUSPEND = 2
DEF DRM_MODE_DPMS_OFF = 3

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")

#https://github.com/linuxhw/EDID/tree/master/
#EDIDv2_1280x720:
#edid_hex = b"00ffffffffffff004e845d00010000000115010380311c782a0dc9a05747982712484c20000001010101010101010101010101010101011d007251d01e2046285500e812110000188c0ad08a20e02d10103e9600e81211000018000000fc0048444d492054560a2020202020000000fd00313d0f2e08000a202020202020018e02031d714701020384111213230907078301000068030c001000b82d00011d007251d01e206e285500e8121100001e000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000039"
#edid_hex = b"00ffffffffffff0005b4380001010101020d0103801e17782a80f8a3554799240d4d50bfee00614c310a0101010101010101010181c064190040410026301888360030e410000018000000fd00324b1e3e08000a202020202020000000ff003233363233303230303037340a000000fc004c322d313530542b202020200a00ef"
#800x600:
DEFAULT_EDID = binascii.unhexlify(b"00ffffffffffff0031d8000000000000051601036d1b1478ea5ec0a4594a982520505401000045400101010101010101010101010101a00f200031581c202880140015d01000001e000000ff004c696e75782023300a20202020000000fd003b3d242605000a202020202020000000fc004c696e757820535647410a202000c2")
DEFAULT_SIZE = 800*600


cdef extern from "evdi_lib.h":
    ctypedef struct evdi_lib_version:
        int version_major
        int version_minor
        int version_patchlevel

    void evdi_get_lib_version(evdi_lib_version *version)

    ctypedef struct evdi_device_context:
        pass
    ctypedef evdi_device_context *evdi_handle
    ctypedef int evdi_selectable

    ctypedef enum evdi_device_status:
        AVAILABLE
        UNRECOGNIZED
        NOT_PRESENT

    ctypedef struct evdi_rect:
        int x1, y1, x2, y2

    ctypedef struct evdi_mode:
        int width
        int height
        int refresh_rate
        int bits_per_pixel
        unsigned int pixel_format

    ctypedef struct evdi_buffer:
        int id
        void *buffer
        int width
        int height
        int stride
        evdi_rect *rects
        int rect_count

    ctypedef struct evdi_cursor_set:
        int32_t hot_x
        int32_t hot_y
        uint32_t width
        uint32_t height
        uint8_t enabled
        uint32_t buffer_length
        uint32_t *buffer
        uint32_t pixel_format
        uint32_t stride

    ctypedef struct evdi_cursor_move:
        int32_t x
        int32_t y

    ctypedef struct evdi_ddcci_data:
        uint16_t address
        uint16_t flags
        uint32_t buffer_length
        uint8_t *buffer

    ctypedef struct evdi_event_context:
        void (*dpms_handler)(int dpms_mode, void *user_data) noexcept
        void (*mode_changed_handler)(evdi_mode mode, void *user_data) noexcept
        void (*update_ready_handler)(int buffer_to_be_updated, void *user_data) noexcept
        void (*crtc_state_handler)(int state, void *user_data) noexcept
        void (*cursor_set_handler)(evdi_cursor_set cursor_set, void *user_data) noexcept
        void (*cursor_move_handler)(evdi_cursor_move cursor_move, void *user_data) noexcept
        void (*ddcci_data_handler)(evdi_ddcci_data ddcci_data, void *user_data) noexcept
        void *user_data

    ctypedef struct evdi_logging:
        void (*function)(void *user_data, const char *fmt, ...) noexcept
        void *user_data;

    #define EVDI_INVALID_HANDLE NULL
    evdi_device_status evdi_check_device(int device)
    evdi_handle evdi_open(int device)
    int evdi_add_device()
    evdi_handle evdi_open_attached_to_fixed(const char *sysfs_parent_device, size_t length)

    void evdi_close(evdi_handle handle)
    void evdi_disconnect(evdi_handle handle)

    void evdi_grab_pixels(evdi_handle handle, evdi_rect *rects, int *num_rects)
    void evdi_register_buffer(evdi_handle handle, evdi_buffer buffer)
    void evdi_unregister_buffer(evdi_handle handle, int bufferId)
    bint evdi_request_update(evdi_handle handle, int bufferId)
    void evdi_ddcci_response(evdi_handle handle, const unsigned char *buffer,
                             const uint32_t buffer_length, const bint result)

    void evdi_handle_events(evdi_handle handle, evdi_event_context *evtctx)
    evdi_selectable evdi_get_event_ready(evdi_handle handle)
    void evdi_set_logging(evdi_logging evdi_logging)

    void evdi_connect2(evdi_handle handle, const unsigned char *edid,
          const unsigned int edid_length,
          const uint32_t pixel_area_limit,
          const uint32_t pixel_per_second_limit)
    void evdi_enable_cursor_events(evdi_handle handle, bint enable)


STATUS_STR = {
    AVAILABLE       : "available",
    UNRECOGNIZED    : "unrecognized",
    NOT_PRESENT     : "not-present",
}

MODE_STR = {
    DRM_MODE_DPMS_ON        : "ON",
    DRM_MODE_DPMS_STANDBY   : "STANDBY",
    DRM_MODE_DPMS_SUSPEND   : "SUSPEND",
    DRM_MODE_DPMS_OFF       : "OFF",
}


def get_version() -> Sequence[int]:
    cdef evdi_lib_version version
    evdi_get_lib_version(&version)
    return (version.version_major, version.version_minor, version.version_patchlevel)


cdef void evdi_logging_function(void *user_data, const char *fmt, ...) noexcept:
    pybytes = fmt[:]
    log(f"evdi: %s", pybytes.decode("latin1"))


def capture_logging() -> None:
    cdef evdi_logging log_config
    log_config.function = &evdi_logging_function
    log_config.user_data = NULL
    evdi_set_logging(log_config)


def reset_logging() -> None:
    cdef evdi_logging log_config
    log_config.function = NULL
    log_config.user_data = NULL
    evdi_set_logging(log_config)


#maps device numbers to our device object:
devices = {}

cdef void dpms_handler(int dpms_mode, void *user_data) noexcept:
    log(f"dpms_handler({dpms_mode}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.dpms_handler(dpms_mode)

cdef void mode_changed_handler(evdi_mode mode, void *user_data) noexcept:
    log(f"mode_changed_handler({mode.width}x{mode.height}-{mode.bits_per_pixel}@{mode.refresh_rate}, %#x)",
        <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.mode_changed_handler(mode)

cdef void update_ready_handler(int buffer_to_be_updated, void *user_data) noexcept:
    log(f"update_ready_handler({buffer_to_be_updated}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.update_ready_handler(buffer_to_be_updated)

cdef void crtc_state_handler(int state, void *user_data) noexcept:
    log(f"crtc_state_handler({state}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.crtc_state_handler(state)

cdef void cursor_set_handler(evdi_cursor_set cursor_set, void *user_data) noexcept:
    log(f"cursor_set_handler({cursor_set.width}x{cursor_set.height}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.cursor_set_handler(cursor_set)

cdef void cursor_move_handler(evdi_cursor_move cursor_move, void *user_data) noexcept:
    log(f"cursor_move_handler({cursor_move.x}x{cursor_move.y}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.cursor_move_handler(cursor_move)

cdef void ddcci_data_handler(evdi_ddcci_data ddcci_data, void *user_data) noexcept:
    log(f"ddcci_data_handler({ddcci_data.address:x}, %#x)", <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.ddcci_data_handler(ddcci_data)


cdef class EvdiDevice:
    cdef int device
    cdef object damage_cb
    cdef evdi_handle handle
    cdef evdi_event_context event_context
    cdef object buffers
    cdef evdi_mode mode
    cdef int dpms_mode
    cdef object edid
    cdef int export_buffer

    def __init__(self, int device, damage_cb=None):
        self.device = device
        self.damage_cb = damage_cb
        self.handle = NULL
        self.buffers = {}
        self.edid = None
        self.dpms_mode = DRM_MODE_DPMS_OFF
        self.export_buffer = 0
        memset(&self.mode, 0, sizeof(evdi_mode))
        memset(&self.event_context, 0, sizeof(evdi_event_context))
        self.event_context.dpms_handler = &dpms_handler
        self.event_context.mode_changed_handler = &mode_changed_handler
        self.event_context.update_ready_handler = &update_ready_handler
        self.event_context.crtc_state_handler = &crtc_state_handler
        self.event_context.cursor_set_handler = &cursor_set_handler
        self.event_context.cursor_move_handler = &cursor_move_handler
        self.event_context.ddcci_data_handler = &ddcci_data_handler
        self.event_context.user_data = <void *> (<uintptr_t> device)
        devices[device] = self

    def __repr__(self):
        return f"EvdiDevice({self.device} - {self.mode.width}x{self.mode.height})"

    def open(self) -> None:
        if self.handle:
            raise RuntimeError("this evdi device is already open")
        if self.device >=0:
            self.handle = evdi_open(self.device)
        else:
            self.handle = evdi_open_attached_to_fixed(NULL, 0)
        if not self.handle:
            raise ValueError(f"cannot open {self.device}")

    def close(self) -> None:
        h = self.handle
        if h:
            self.handle = NULL
            evdi_close(h)


    cdef void dpms_handler(self, int dpms_mode) noexcept:
        log(f"dpms_handler({dpms_mode}) %s", MODE_STR.get(dpms_mode, "INVALID"))
        if self.dpms_mode==dpms_mode:
            #unchanged
            return
        self.dpms_mode = dpms_mode
        if dpms_mode!=DRM_MODE_DPMS_ON:
            self.unregister_buffers()

    cdef void mode_changed_handler(self, evdi_mode mode):
        log(f"mode_changed_handler({mode.width}x{mode.height}-{mode.bits_per_pixel}@{mode.refresh_rate}")
        memcpy(&self.mode, &mode, sizeof(evdi_mode))
        self.unregister_buffers()
        log(f"mode_changed_handler dpms_mode={MODE_STR.get(self.dpms_mode, self.dpms_mode)}")
        if self.dpms_mode==DRM_MODE_DPMS_ON and self.mode.width>0 and self.mode.height>0:
            for buf_id in (1, 2):
                if buf_id not in self.buffers:
                    self.register_buffer(buf_id)
            buf_id = 1
            self.export_buffer = buf_id
            log(f"using buffer {buf_id}")
            if self.request_update(buf_id):
                self.grab_pixels(buf_id)

    cdef void update_ready_handler(self, int buffer_to_be_updated):
        log(f"update_ready_handler({buffer_to_be_updated})")
        self.grab_pixels(buffer_to_be_updated)

    def grab_pixels(self, buf_id) -> Tuple:
        if not self.handle:
            raise RuntimeError("no device handle")
        buf = self.buffers.get(buf_id)
        if not buf:
            raise ValueError(f"unknown buffer {buf_id}")
        cdef int nrects = 128
        cdef evdi_rect[128] rects
        evdi_grab_pixels(self.handle, rects, &nrects)
        cdef int rowstride = self.mode.width*4
        if SAVE_TO_FILE:
            try:
                from PIL import Image
                from PIL import __version__ as pil_version
                # older versions of PIL cannot use the memoryview directly:
                try:
                    major = int(pil_version.split(".")[0])
                except ValueError:
                    major = 0
                if major < 10:
                    pixels = memoryview(buf)
                else:
                    pixels = memoryview_to_bytes(memoryview(buf))
                pil_image = Image.frombuffer("RGBA", (self.mode.width, self.mode.height), pixels, "raw", "BGRA", rowstride)
                pil_image = pil_image.convert("RGB")
                filename = f"{monotonic()}.jpg"
                pil_image.save(filename, "JPEG")
                log(f"saved to {filename}")
                if nrects:
                    for i in range(nrects):
                        log(" %i : %i,%i to %i,%i", i, rects[i].x1, rects[i].y1, rects[i].x2, rects[i].y2)
                        w = rects[i].x2 - rects[i].x1
                        h = rects[i].y2 - rects[i].y1
                        if w>0 and h>0 and (w<self.mode.width or h<self.mode.height):
                            sub = pil_image.crop((rects[i].x1, rects[i].y1, rects[i].x2, rects[i].y2))
                            sub.save(f"{monotonic()}-{i}.jpg", "JPEG")
            except KeyboardInterrupt as e:
                log(f"{e}")
                self.cleanup()
                return
            except Exception:
                self.cleanup()
                return
        areas = tuple((rects[i].x1, rects[i].y1, rects[i].x2 - rects[i].x1, rects[i].y2 - rects[i].y1) for i in range(nrects))
        log(f"evdi_grab_pixels(%#x, %#x, {nrects}) areas={areas}", <uintptr_t> self.handle, <uintptr_t> rects)
        cdef int buf_size = rowstride * self.mode.height
        buf_slice = memoryview(buf)[:buf_size]
        damage_cb = self.damage_cb
        if damage_cb:
            self.damage_cb(self.mode.width, self.mode.height, buf_slice, areas)
        #toggle buffer:
        self.export_buffer = 3-self.export_buffer
        return self.mode.width, self.mode.height, buf_slice, areas


    cdef void crtc_state_handler(self, int state):
        log(f"crtc_state_handler({state})")

    cdef void cursor_set_handler(self, evdi_cursor_set cursor_set):
        log(f"cursor_set_handler({cursor_set.width}x{cursor_set.height})")

    cdef void cursor_move_handler(self, evdi_cursor_move cursor_move):
        log(f"cursor_move_handler({cursor_move.x}x{cursor_move.y})")

    cdef void ddcci_data_handler(self, evdi_ddcci_data ddcci_data):
        log("ddcci_data_handler(%#x)", ddcci_data.address)

    def enable_cursor_events(self, enable=True) -> None:
        evdi_enable_cursor_events(self.handle, int(enable))


    def connect(self, edid=DEFAULT_EDID) -> None:
        if not self.handle:
            raise RuntimeError("no device handle")
        if self.edid:
            raise RuntimeError("device is already connected")
        self.edid = strtobytes(edid)
        cdef uint32_t pixel_area_limit = 1920*1080
        if edid==DEFAULT_EDID:
            pixel_area_limit = DEFAULT_SIZE
        cdef int Hz = 60
        try:
            from pyedid import parse_edid
            edid_data = parse_edid(self.edid)._asdict()
            log.error(f"edid: f{edid_data}")
        except ImportError as e:
            log.warn("Warning: cannot parse EDID")
            log.warn(f" {e}")
        except ValueError as e:
            log.warn("Warning: invalid EDID data")
            log.warn(f" {e}")
        else:
            log.info(f"evdi using monitor edid: {edid_data}")
            pixel_area_limit = DEFAULT_SIZE
            maxw = 800
            maxh = 600
            for w, h, hz in edid_data.get("resolutions", ()):
                maxw = max(w, maxw)
                maxh = max(h, maxh)
                Hz = max(Hz, round(hz))
            pixel_area_limit = maxw*maxh
        cdef const unsigned char *edid_bin = self.edid
        cdef unsigned int edid_length = len(self.edid)
        cdef uint32_t pixel_per_second_limit = pixel_area_limit*Hz
        log(f"connect with edid {edid!r} (length={edid_length})")
        evdi_connect2(self.handle, edid_bin, <const unsigned int> edid_length,
                     <const uint32_t> pixel_area_limit,
                     <const uint32_t> pixel_per_second_limit)

    def disconnect(self) -> None:
        e = self.edid
        if e:
            self.edid = None
            evdi_disconnect(self.handle)

    def get_event_fd(self) -> int:
        return evdi_get_event_ready(self.handle)

    def handle_events(self) -> None:
        if not self.handle:
            raise RuntimeError("no device handle")
        if not self.edid:
            raise RuntimeError("device is not connected")
        evdi_handle_events(self.handle, &self.event_context)

    def handle_all_events(self) -> None:
        if not self.handle:
            raise RuntimeError("no device handle")
        if not self.edid:
            raise RuntimeError("device is not connected")
        cdef evdi_selectable fd = evdi_get_event_ready(self.handle)
        log(f"handle_all_events() fd={fd}")
        while self.handle!=NULL and self.edid:
            r = select.select([fd], [], [], 0)
            log(f"handle_all_events() select(..)={r}")
            if fd not in r[0]:
                break
            evdi_handle_events(self.handle, &self.event_context)

    def event_loop(self, run_time=10) -> None:
        cdef evdi_selectable fd = evdi_get_event_ready(self.handle)
        log(f"handle_events() fd={fd}")
        start = monotonic()
        while monotonic()-start<run_time and self.handle!=NULL and self.edid:
            log("waiting for events")
            r = select.select([fd], [], [], 0.020)
            log(f"select(..)={r}")
            if self.handle==NULL or not self.edid:
                break
            if fd in r[0]:
                evdi_handle_events(self.handle, &self.event_context)
            if self.buffers and self.export_buffer:
                self.refresh()

    def refresh(self) -> Tuple | None:
        buf_id = self.export_buffer
        #log(f"refresh() export_buffer={buf_id}")
        if buf_id in (1, 2):
            r = self.request_update(buf_id)
            if r:
                return self.grab_pixels(buf_id)
        return None

    def register_buffer(self, int buf_id) -> None:
        cdef evdi_buffer buf
        buf.id = buf_id
        buf.width = self.mode.width
        buf.height = self.mode.height
        buf.stride = buf.width*self.mode.bits_per_pixel//8
        buf.rect_count = 0
        buf.rects = NULL
        cdef MemBuf pybuf = getbuf(self.mode.width*self.mode.height*4)
        buf.buffer = <void *>pybuf.get_mem()
        evdi_register_buffer(self.handle, buf)
        log(f"register_buffer({buf_id}) pybuf={pybuf}")
        self.buffers[buf_id] = pybuf

    def request_update(self, buf_id) -> int:
        cdef bint update = evdi_request_update(self.handle, buf_id)
        log(f"evdi_request_update(%#x, {buf_id})={update}", <uintptr_t> self.handle)
        return update

    def unregister_buffers(self) -> None:
        for buf_id in self.buffers.keys():
            log(f"unregister_buffer {buf_id}")
            evdi_unregister_buffer(self.handle, buf_id)
        self.buffers = {}
        self.export_buffer = 0

    def cleanup(self) -> None:
        self.unregister_buffers()
        self.disconnect()
        self.close()

    def __del__(self):
        self.cleanup()


def test_device(int device) -> bool:
    log(f"opening card {device}")
    cdef EvdiDevice d = EvdiDevice(device)
    d.open()
    d.connect(DEFAULT_EDID)
    d.enable_cursor_events()
    d.event_loop()
    d.cleanup()
    return True


def find_evdi_devices() -> List[str]:
    import os
    devices = []
    for f in sorted(os.listdir("/dev/dri")):
        if not f.startswith("card"):
            continue
        try:
            device = int(f[len("card"):])
            r = evdi_check_device(device)
            log(f"find_evdi_devices() evdi_check_device({device})={r}")
            if r==AVAILABLE:
                devices.append(device)
        except ValueError:
            pass
    log(f"find_evdi_devices()={devices}")
    return devices


def add_evdi_device() -> None:
    r = evdi_add_device()
    log("evdi_add_device()=%i", r)


def selftest(full=False) -> None:
    from xpra.log import LOG_FORMAT, enable_color
    format_string = LOG_FORMAT
    enable_color(format_string=format_string)
    log("evdi version " + ".".join(str(x) for x in get_version()))
    if full:
        #capture_logging()
        devices = find_evdi_devices()
        if devices:
            for device in devices:
                test_device(device)
        #reset_logging()
