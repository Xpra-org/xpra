# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from time import monotonic
from xpra.os_util import bytestostr, strtobytes, memoryview_to_bytes

from xpra.log import Logger
log = Logger("encoder", "evdi")

from libc.string cimport memset, memcpy
from xpra.buffers.membuf cimport getbuf, MemBuf
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, int32_t, uint32_t

DEF DRM_MODE_DPMS_ON = 0
DEF DRM_MODE_DPMS_STANDBY = 1
DEF DRM_MODE_DPMS_SUSPEND = 2
DEF DRM_MODE_DPMS_OFF = 3

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
        void (*dpms_handler)(int dpms_mode, void *user_data)
        void (*mode_changed_handler)(evdi_mode mode, void *user_data)
        void (*update_ready_handler)(int buffer_to_be_updated, void *user_data)
        void (*crtc_state_handler)(int state, void *user_data)
        void (*cursor_set_handler)(evdi_cursor_set cursor_set, void *user_data)
        void (*cursor_move_handler)(evdi_cursor_move cursor_move, void *user_data)
        void (*ddcci_data_handler)(evdi_ddcci_data ddcci_data, void *user_data)
        void *user_data

    ctypedef struct evdi_logging:
        void (*function)(void *user_data, const char *fmt, ...)
        void *user_data;

    #define EVDI_INVALID_HANDLE NULL
    evdi_device_status evdi_check_device(int device)
    evdi_handle evdi_open(int device)
    int evdi_add_device()

    void evdi_close(evdi_handle handle)
    void evdi_connect(evdi_handle handle, const unsigned char *edid,
          const unsigned int edid_length,
          const uint32_t sku_area_limit)
    void evdi_disconnect(evdi_handle handle)
    void evdi_enable_cursor_events(evdi_handle handle, bint enable)

    void evdi_grab_pixels(evdi_handle handle, evdi_rect *rects, int *num_rects)
    void evdi_register_buffer(evdi_handle handle, evdi_buffer buffer)
    void evdi_unregister_buffer(evdi_handle handle, int bufferId)
    bint evdi_request_update(evdi_handle handle, int bufferId)
    void evdi_ddcci_response(evdi_handle handle, const unsigned char *buffer,
                             const uint32_t buffer_length, const bint result)

    void evdi_handle_events(evdi_handle handle, evdi_event_context *evtctx)
    evdi_selectable evdi_get_event_ready(evdi_handle handle)
    void evdi_set_logging(evdi_logging evdi_logging)


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


def get_version():
    cdef evdi_lib_version version
    evdi_get_lib_version(&version)
    return (version.version_major, version.version_minor, version.version_patchlevel)


cdef class Capture:
    pass


cdef void evdi_logging_function(void *user_data, const char *fmt, ...):
    s = bytestostr(fmt)
    log("evdi: %s", s)


def catpure_logging():
    cdef evdi_logging log_config
    log_config.function = &evdi_logging_function
    log_config.user_data = NULL
    evdi_set_logging(log_config)



cdef void dpms_handler(int dpms_mode, void *user_data):
    log.info("dpms_handler(%i, %#x)", dpms_mode, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.dpms_handler(dpms_mode)

cdef void mode_changed_handler(evdi_mode mode, void *user_data):
    log.info("mode_changed_handler(%ix%i-%i@%i, %#x)", mode.width, mode.height, mode.bits_per_pixel, mode.refresh_rate, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.mode_changed_handler(mode)

cdef void update_ready_handler(int buffer_to_be_updated, void *user_data):
    log.info("update_ready_handler(%i, %#x)", buffer_to_be_updated, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.update_ready_handler(buffer_to_be_updated)

cdef void crtc_state_handler(int state, void *user_data):
    log.info("crtc_state_handler(%i, %#x)", state, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.crtc_state_handler(state)

cdef void cursor_set_handler(evdi_cursor_set cursor_set, void *user_data):
    log.info("cursor_set_handler(%ix%i, %#x)", cursor_set.width, cursor_set.height, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.cursor_set_handler(cursor_set)

cdef void cursor_move_handler(evdi_cursor_move cursor_move, void *user_data):
    log.info("cursor_move_handler(%ix%i, %#x)", cursor_move.x, cursor_move.y, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.cursor_move_handler(cursor_move)

cdef void ddcci_data_handler(evdi_ddcci_data ddcci_data, void *user_data):
    log.info("ddcci_data_handler(%#x, %#x)", ddcci_data.address, <uintptr_t> user_data)
    cdef EvdiDevice evdi_device = devices.get(<uintptr_t> user_data)
    if evdi_device:
        evdi_device.ddcci_data_handler(ddcci_data)


#maps device numbers to our device object:
devices = {}


cdef class EvdiDevice:
    cdef int device
    cdef evdi_handle handle
    cdef evdi_event_context event_context
    cdef object buffers
    cdef evdi_mode mode
    cdef int dpms_mode

    def __init__(self, int device):
        self.device = device
        self.handle = evdi_open(device)
        self.dpms_mode = -1
        if not self.handle:
            raise ValueError("cannot open %i" % device)

        memset(&self.mode, 0, sizeof(evdi_mode))
        self.event_context.dpms_handler = &dpms_handler
        self.event_context.mode_changed_handler = &mode_changed_handler
        self.event_context.update_ready_handler = &update_ready_handler
        self.event_context.crtc_state_handler = &crtc_state_handler
        self.event_context.cursor_set_handler = &cursor_set_handler
        self.event_context.cursor_move_handler = &cursor_move_handler
        self.event_context.ddcci_data_handler = &ddcci_data_handler
        self.event_context.user_data = <void *> ((<uintptr_t> device) & 0xFFFF)
        self.buffers = {}
        devices[device] = self

    cdef void dpms_handler(self, int dpms_mode):
        log.info("dpms_handler(%i) %s", dpms_mode, MODE_STR.get(dpms_mode, "INVALID"))
        self.dpms_mode = dpms_mode
        self.unregister_buffers()
        self.may_start()
    
    def may_start(self):
        if self.dpms_mode==DRM_MODE_DPMS_ON and self.mode.width>0 and self.mode.height>0:
            buf_id = 1
            if not self.buffers:
                self.register_buffer(buf_id)
            if self.request_update(buf_id):
                self.update_ready_handler(buf_id)
    
    cdef void mode_changed_handler(self, evdi_mode mode):
        log.info("mode_changed_handler(%ix%i-%i@%i)", mode.width, mode.height, mode.bits_per_pixel, mode.refresh_rate)
        memcpy(&self.mode, &mode, sizeof(evdi_mode))
        self.unregister_buffers()
        self.may_start()

    cdef void update_ready_handler(self, int buffer_to_be_updated):
        log.info("update_ready_handler(%i)", buffer_to_be_updated)
        self.grab_pixels(buffer_to_be_updated)

    def grab_pixels(self, buf_id):
        buf = self.buffers.get(buf_id)
        if not buf:
            raise ValueError("unknown buffer %i" % buf_id)
        cdef int nrects = 16
        cdef MemBuf pyrects = getbuf(16*sizeof(evdi_rect))
        cdef evdi_rect *rects = <evdi_rect *>pyrects.get_mem()
        evdi_grab_pixels(self.handle, rects, &nrects)
        log("evdi_grab_pixels(%#x, %#x, %i)", <uintptr_t> self.handle, <uintptr_t> rects, nrects)
        if nrects:
            from PIL import Image
            pixels = memoryview_to_bytes(memoryview(buf))
            rowstride = self.mode.width*4
            pil_image = Image.frombuffer("RGBA", (self.mode.width, self.mode.height), pixels, "raw", "BGRA", rowstride)
            for i in range(nrects):
                log(" %i : %i,%i to %i,%i", i, rects[i].x1, rects[i].y1, rects[i].x2, rects[i].y2)
                w = rects[i].x2 - rects[i].x1
                h = rects[i].y2 - rects[i].y1
                if w>0 and h>0:
                    sub = pil_image.crop((rects[i].x1, rects[i].y1, rects[i].x2, rects[i].y2))
                    sub.save("%s-%i.png" % (monotonic(), i), "PNG")
                    
                        
        #TODO: save areas to test png files


    cdef void crtc_state_handler(self, int state):
        log.info("crtc_state_handler(%i)", state)
    
    cdef void cursor_set_handler(self, evdi_cursor_set cursor_set):
        log.info("cursor_set_handler(%ix%i)", cursor_set.width, cursor_set.height)
    
    cdef void cursor_move_handler(self, evdi_cursor_move cursor_move):
        log.info("cursor_move_handler(%ix%i)", cursor_move.x, cursor_move.y)
    
    cdef void ddcci_data_handler(self, evdi_ddcci_data ddcci_data):
        log.info("ddcci_data_handler(%#x)", ddcci_data.address)

    def connect(self, edid):
        b = strtobytes(edid)
        cdef const unsigned char *edid_bin = b
        cdef unsigned int edid_length = len(b)
        cdef uint32_t sku_area_limit = 4096*4096*4
        log("connect with edid %s (length=%i)", <uintptr_t> edid_bin, edid_length)
        evdi_connect(self.handle, edid_bin, <const unsigned int> edid_length, <const uint32_t> sku_area_limit)

    def handle_events(self):
        cdef evdi_selectable fd = evdi_get_event_ready(self.handle)
        log("handle_events() fd=%i", fd)
        import select
        count = 0
        while count<100:
            log("will wait for events")
            r = select.select([fd], [], [], 1)
            log("select(..)=%s", r)
            if fd in r[0]:
                evdi_handle_events(self.handle, &self.event_context)
            else:
                count += 1
                if count%10==0 and self.buffers:
                    self.may_start()

    def register_buffer(self, int buf_id):
        cdef evdi_buffer buf
        buf.id = buf_id
        buf.width = self.mode.width
        buf.height = self.mode.height
        buf.stride = buf.width*4
        buf.rect_count = 0
        buf.rects = NULL
        buf.rect_count = 0
        cdef MemBuf pybuf = getbuf(self.mode.width*self.mode.height*4)
        buf.buffer = <void *>pybuf.get_mem()
        #cdef int nrects = 0
        #pybuf = getbuf(w*h*4)
        #buf.buffer = <void *>pybuf.get_mem()
        #pybuf = getbuf(8192)
        #buf.rects = <evdi_rect *> pybuf.get_mem()
        #buf.rect_count = 128
        #pybuf = getbuf(8192)
        #cdef evdi_rect *rects = <evdi_rect *> pybuf.get_mem()
        evdi_register_buffer(self.handle, buf)
        log.info("register_buffer(%i) pybuf=%s", buf_id, pybuf)
        self.buffers[buf_id] = pybuf

    def request_update(self, buf_id):
        cdef bint update = evdi_request_update(self.handle, buf_id)
        log("evdi_request_update(%#x, %i)=%s", <uintptr_t> self.handle, buf_id, update)
        return update
        #if update:
        #    evdi_grab_pixels(handle, rects, &nrects)
        #    log("evdi_grab_pixels(%#x, %#x, %i)", <uintptr_t> handle, <uintptr_t> buf.rects, nrects)

    def unregister_buffers(self):
        for buf_id in self.buffers.keys():
            log("unregister_buffer %i", buf_id)
            evdi_unregister_buffer(self.handle, buf_id)
        self.buffers = {}

    def cleanup(self):
        self.unregister_buffers()
        evdi_disconnect(self.handle)
        evdi_close(self.handle)


cdef test_device(int device):
    log("opening card %i", device)
    cdef EvdiDevice d = EvdiDevice(device)
    import binascii
    #xrandr --addmode DVI-I-1-1 1280x720
    #xrandr --output DVI-I-1-1 --mode 1280x720 --right-of  DP-2
    #https://github.com/linuxhw/EDID/tree/master/
    #EDIDv2_1280x720:
    #edid_hex = b"00ffffffffffff004e845d00010000000115010380311c782a0dc9a05747982712484c20000001010101010101010101010101010101011d007251d01e2046285500e812110000188c0ad08a20e02d10103e9600e81211000018000000fc0048444d492054560a2020202020000000fd00313d0f2e08000a202020202020018e02031d714701020384111213230907078301000068030c001000b82d00011d007251d01e206e285500e8121100001e000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000039"
    #edid_hex = b"00ffffffffffff0005b4380001010101020d0103801e17782a80f8a3554799240d4d50bfee00614c310a0101010101010101010181c064190040410026301888360030e410000018000000fd00324b1e3e08000a202020202020000000ff003233363233303230303037340a000000fc004c322d313530542b202020200a00ef"
    #800x600:
    edid_hex = b"00ffffffffffff0031d8000000000000051601036d1b1478ea5ec0a4594a982520505401000045400101010101010101010101010101a00f200031581c202880140015d01000001e000000ff004c696e75782023300a20202020000000fd003b3d242605000a202020202020000000fc004c696e757820535647410a202000c2"
    edid = binascii.unhexlify(edid_hex)
    d.connect(edid)
    d.handle_events()
    d.cleanup()
    return True


def selftest(full=False):
    import os
    from xpra.log import LOG_FORMAT, enable_color
    format_string = LOG_FORMAT
    log.enable_debug()
    enable_color(format_string=format_string)
    log.info("evdi version %s", ".".join(str(x) for x in get_version()))
    #catpure_logging()
    log.enable_debug()
    for f in sorted(os.listdir("/dev/dri")):
        if f.startswith("card"):
            try:
                device = int(f[4:])
                r = evdi_check_device(device)
                log.info("%2i: %s", device, STATUS_STR.get(r, r))
                if r==AVAILABLE:
                    if test_device(device):
                        break
            except ValueError:
                pass
