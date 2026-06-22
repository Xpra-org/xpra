# cython: language_level=3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint32_t, uint64_t
from cpython.bytes cimport PyBytes_FromStringAndSize

cdef extern from "pipewire/pipewire.h":
    ctypedef struct pw_thread_loop
    ctypedef struct pw_context
    ctypedef struct pw_core
    ctypedef struct pw_stream
    ctypedef struct pw_buffer
    ctypedef struct pw_properties
    ctypedef struct spa_pod
    ctypedef struct spa_hook
    ctypedef struct spa_pod_builder

    void pw_init(int *argc, char ***argv)
    pw_thread_loop *pw_thread_loop_new(const char *name, const void *props)
    void *pw_thread_loop_get_loop(pw_thread_loop *loop)
    int pw_thread_loop_start(pw_thread_loop *loop)
    void pw_thread_loop_stop(pw_thread_loop *loop)
    void pw_thread_loop_destroy(pw_thread_loop *loop)
    void pw_thread_loop_lock(pw_thread_loop *loop)
    void pw_thread_loop_unlock(pw_thread_loop *loop)
    pw_context *pw_context_new(void *loop, pw_properties *props, size_t user_data_size)
    void pw_context_destroy(pw_context *context)
    pw_core *pw_context_connect_fd(pw_context *context, int fd, pw_properties *props, size_t user_data_size)
    int pw_core_disconnect(pw_core *core)
    pw_stream *pw_stream_new(pw_core *core, const char *name, pw_properties *props)
    void pw_stream_destroy(pw_stream *stream)
    int pw_stream_disconnect(pw_stream *stream)
    pw_buffer *pw_stream_dequeue_buffer(pw_stream *stream)
    int pw_stream_queue_buffer(pw_stream *stream, pw_buffer *buffer)

cdef extern from *:
    """
    #include <stdlib.h>
    #include <string.h>
    #include <pipewire/pipewire.h>
    #include <spa/param/video/format-utils.h>
    #include <spa/param/format-utils.h>
    #include <spa/pod/builder.h>

    static struct pw_stream_events *xpra_events_new(
        void (*state)(void *, enum pw_stream_state, enum pw_stream_state, const char *),
        void (*param)(void *, uint32_t, const struct spa_pod *),
        void (*process)(void *)) {
        struct pw_stream_events *e = calloc(1, sizeof(*e));
        e->version = PW_VERSION_STREAM_EVENTS;
        e->state_changed = state;
        e->param_changed = param;
        e->process = process;
        return e;
    }
    static struct spa_hook *xpra_hook_new(void) { return calloc(1, sizeof(struct spa_hook)); }
    static void xpra_listener(struct pw_stream *s, struct spa_hook *h,
                              const struct pw_stream_events *e, void *data) {
        pw_stream_add_listener(s, h, e, data);
    }
    static struct pw_properties *xpra_stream_props(void) {
        return pw_properties_new(PW_KEY_MEDIA_TYPE, "Video",
                                 PW_KEY_MEDIA_CATEGORY, "Capture",
                                 PW_KEY_MEDIA_ROLE, "Screen", NULL);
    }
    static int xpra_connect(struct pw_stream *s, uint32_t node, uint32_t width, uint32_t height) {
        uint8_t storage[1024];
        struct spa_pod_builder b = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
        const struct spa_pod *p = spa_pod_builder_add_object(&b,
            SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
            SPA_FORMAT_mediaType, SPA_POD_Id(SPA_MEDIA_TYPE_video),
            SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
            SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(4,
                SPA_VIDEO_FORMAT_BGRx, SPA_VIDEO_FORMAT_BGRA,
                SPA_VIDEO_FORMAT_RGBx, SPA_VIDEO_FORMAT_RGBA),
            SPA_FORMAT_VIDEO_size, SPA_POD_CHOICE_RANGE_Rectangle(
                &SPA_RECTANGLE(width, height), &SPA_RECTANGLE(1, 1),
                &SPA_RECTANGLE(16384, 16384)));
        return pw_stream_connect(s, PW_DIRECTION_INPUT, node,
            PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS, &p, 1);
    }
    static int xpra_parse_format(const struct spa_pod *p, uint32_t *format,
                                 uint32_t *width, uint32_t *height, uint64_t *modifier) {
        struct spa_video_info_raw info = {0};
        int r = spa_format_video_raw_parse(p, &info);
        if (r < 0) return r;
        *format = info.format; *width = info.size.width; *height = info.size.height;
        *modifier = info.modifier;
        return 0;
    }
    static int xpra_set_buffer_params(struct pw_stream *s, uint32_t width,
                                      uint32_t height, uint32_t stride) {
        uint8_t storage[1024];
        struct spa_pod_builder b = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
        const struct spa_pod *params[2];
        params[0] = spa_pod_builder_add_object(&b,
            SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers,
            SPA_PARAM_BUFFERS_buffers, SPA_POD_CHOICE_RANGE_Int(8, 2, 32),
            SPA_PARAM_BUFFERS_blocks, SPA_POD_Int(1),
            SPA_PARAM_BUFFERS_size, SPA_POD_Int(stride * height),
            SPA_PARAM_BUFFERS_stride, SPA_POD_Int(stride),
            SPA_PARAM_BUFFERS_dataType, SPA_POD_CHOICE_FLAGS_Int(
                (1 << SPA_DATA_MemPtr) | (1 << SPA_DATA_MemFd) | (1 << SPA_DATA_DmaBuf)));
        params[1] = spa_pod_builder_add_object(&b,
            SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
            SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Header),
            SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_header)));
        return pw_stream_update_params(s, params, 2);
    }
    static const char *xpra_format_name(uint32_t f) {
        switch (f) {
        case SPA_VIDEO_FORMAT_BGRx: return "BGRX";
        case SPA_VIDEO_FORMAT_BGRA: return "BGRA";
        case SPA_VIDEO_FORMAT_RGBx: return "RGBX";
        case SPA_VIDEO_FORMAT_RGBA: return "RGBA";
        default: return NULL;
        }
    }
    static uint32_t xpra_drm_format(uint32_t f) {
        switch (f) {
        case SPA_VIDEO_FORMAT_BGRx: return 0x34325258; /* XR24 */
        case SPA_VIDEO_FORMAT_BGRA: return 0x34325241; /* AR24 */
        case SPA_VIDEO_FORMAT_RGBx: return 0x34324258; /* XB24 */
        case SPA_VIDEO_FORMAT_RGBA: return 0x34324241; /* AB24 */
        default: return 0;
        }
    }
    static uint32_t xpra_data_count(struct pw_buffer *b) { return b->buffer->n_datas; }
    static uint32_t xpra_data_type(struct pw_buffer *b, uint32_t i) { return b->buffer->datas[i].type; }
    static int xpra_data_fd(struct pw_buffer *b, uint32_t i) { return b->buffer->datas[i].fd; }
    static void *xpra_data_ptr(struct pw_buffer *b, uint32_t i) { return b->buffer->datas[i].data; }
    static uint32_t xpra_data_maxsize(struct pw_buffer *b, uint32_t i) { return b->buffer->datas[i].maxsize; }
    static uint32_t xpra_data_mapoffset(struct pw_buffer *b, uint32_t i) { return b->buffer->datas[i].mapoffset; }
    static uint32_t xpra_chunk_offset(struct pw_buffer *b, uint32_t i) {
        return b->buffer->datas[i].chunk ? b->buffer->datas[i].chunk->offset : 0;
    }
    static uint32_t xpra_chunk_size(struct pw_buffer *b, uint32_t i) {
        return b->buffer->datas[i].chunk ? b->buffer->datas[i].chunk->size : 0;
    }
    static int32_t xpra_chunk_stride(struct pw_buffer *b, uint32_t i) {
        return b->buffer->datas[i].chunk ? b->buffer->datas[i].chunk->stride : 0;
    }
    static int xpra_is_dmabuf(uint32_t t) { return t == SPA_DATA_DmaBuf; }
    """
    void *xpra_events_new(void *state, void *param, void *process)
    spa_hook *xpra_hook_new()
    void xpra_listener(pw_stream *, spa_hook *, void *, void *)
    pw_properties *xpra_stream_props()
    int xpra_connect(pw_stream *, uint32_t, uint32_t, uint32_t)
    int xpra_parse_format(const spa_pod *, uint32_t *, uint32_t *, uint32_t *, uint64_t *)
    int xpra_set_buffer_params(pw_stream *, uint32_t, uint32_t, uint32_t)
    const char *xpra_format_name(uint32_t)
    uint32_t xpra_drm_format(uint32_t)
    uint32_t xpra_data_count(pw_buffer *)
    uint32_t xpra_data_type(pw_buffer *, uint32_t)
    int xpra_data_fd(pw_buffer *, uint32_t)
    void *xpra_data_ptr(pw_buffer *, uint32_t)
    uint32_t xpra_data_maxsize(pw_buffer *, uint32_t)
    uint32_t xpra_data_mapoffset(pw_buffer *, uint32_t)
    uint32_t xpra_chunk_offset(pw_buffer *, uint32_t)
    uint32_t xpra_chunk_size(pw_buffer *, uint32_t)
    int xpra_chunk_stride(pw_buffer *, uint32_t)
    int xpra_is_dmabuf(uint32_t)
    void free(void *)


cdef class BufferLease:
    cdef NativeCapture owner
    cdef pw_buffer *buffer
    cdef bint released

    def __init__(self):
        self.released = False

    def release(self):
        if not self.released:
            self.released = True
            if self.owner is not None:
                self.owner._release(self)

    def __del__(self):
        self.release()


cdef void state_callback(void *data, int old_state, int state, const char *error) noexcept with gil:
    cdef NativeCapture self = <NativeCapture>data
    self._state(state, error)


cdef void param_callback(void *data, uint32_t param_id, const spa_pod *param) noexcept with gil:
    cdef NativeCapture self = <NativeCapture>data
    self._format(param)


cdef void process_callback(void *data) noexcept with gil:
    cdef NativeCapture self = <NativeCapture>data
    self._process()


cdef class NativeCapture:
    cdef pw_thread_loop *loop
    cdef pw_context *context
    cdef pw_core *core
    cdef pw_stream *stream
    cdef spa_hook *hook
    cdef void *events
    cdef int fd
    cdef uint32_t node_id, width, height, spa_format
    cdef uint64_t modifier
    cdef object callback, leases
    cdef bint started, cleaned

    def __cinit__(self, int fd, uint32_t node_id, callback):
        self.fd = fd
        self.node_id = node_id
        self.callback = callback
        self.width = callback.width or 1920
        self.height = callback.height or 1080
        self.leases = set()

    def start(self):
        cdef int r
        if self.started or self.cleaned:
            return
        pw_init(NULL, NULL)
        self.loop = pw_thread_loop_new(b"xpra-pipewire-capture", NULL)
        if self.loop == NULL:
            raise RuntimeError("failed to create PipeWire thread loop")
        self.context = pw_context_new(pw_thread_loop_get_loop(self.loop), NULL, 0)
        if self.context == NULL:
            self.clean()
            raise RuntimeError("failed to create PipeWire context")
        self.core = pw_context_connect_fd(self.context, self.fd, NULL, 0)
        self.fd = -1
        if self.core == NULL:
            self.clean()
            raise RuntimeError("failed to connect to the portal PipeWire remote")
        self.stream = pw_stream_new(self.core, b"Xpra portal capture", xpra_stream_props())
        if self.stream == NULL:
            self.clean()
            raise RuntimeError("failed to create PipeWire stream")
        self.events = xpra_events_new(<void *>state_callback, <void *>param_callback, <void *>process_callback)
        self.hook = xpra_hook_new()
        if self.events == NULL or self.hook == NULL:
            self.clean()
            raise MemoryError()
        xpra_listener(self.stream, self.hook, self.events, <void *>self)
        r = xpra_connect(self.stream, self.node_id, self.width, self.height)
        if r < 0:
            self.clean()
            raise RuntimeError(f"failed to connect PipeWire stream: {r}")
        r = pw_thread_loop_start(self.loop)
        if r < 0:
            self.clean()
            raise RuntimeError(f"failed to start PipeWire thread: {r}")
        self.started = True

    def clean(self):
        cdef BufferLease lease
        if self.cleaned:
            return
        self.cleaned = True
        for lease in tuple(self.leases):
            lease.release()
        if self.loop != NULL and self.started:
            pw_thread_loop_stop(self.loop)
        self.started = False
        if self.stream != NULL:
            pw_stream_disconnect(self.stream)
            pw_stream_destroy(self.stream)
            self.stream = NULL
        if self.core != NULL:
            pw_core_disconnect(self.core)
            self.core = NULL
        if self.context != NULL:
            pw_context_destroy(self.context)
            self.context = NULL
        if self.loop != NULL:
            pw_thread_loop_destroy(self.loop)
            self.loop = NULL
        if self.hook != NULL:
            free(self.hook)
            self.hook = NULL
        if self.events != NULL:
            free(self.events)
            self.events = NULL
        if self.fd >= 0:
            import os
            os.close(self.fd)
            self.fd = -1

    def get_info(self):
        return {"native": True, "retained-buffers": len(self.leases),
                "modifier": self.modifier}

    cdef void _state(self, int state, const char *error):
        states = {-1: "error", 0: "unconnected", 1: "connecting", 2: "paused", 3: "streaming"}
        if error != NULL:
            self.callback.native_error(error.decode("utf-8", "replace"))
        self.callback.native_state_changed(states.get(state, str(state)))

    cdef void _format(self, const spa_pod *param):
        cdef int r
        cdef const char *name
        if param == NULL:
            return
        r = xpra_parse_format(param, &self.spa_format, &self.width, &self.height, &self.modifier)
        if r < 0:
            self.callback.native_error(f"failed to parse PipeWire format: {r}")
            return
        name = xpra_format_name(self.spa_format)
        if name == NULL:
            self.callback.native_error(f"unsupported PipeWire video format {self.spa_format}")
            return
        r = xpra_set_buffer_params(self.stream, self.width, self.height, self.width * 4)
        if r < 0:
            self.callback.native_error(f"failed to configure PipeWire buffers: {r}")

    cdef void _process(self):
        cdef pw_buffer *buffer = pw_stream_dequeue_buffer(self.stream)
        cdef uint32_t count, offset, size, maxsize, i
        cdef int stride
        cdef void *ptr
        cdef const char *cformat
        cdef BufferLease lease
        if buffer == NULL:
            return
        count = xpra_data_count(buffer)
        cformat = xpra_format_name(self.spa_format)
        if count == 0 or cformat == NULL:
            pw_stream_queue_buffer(self.stream, buffer)
            return
        offset = xpra_chunk_offset(buffer, 0)
        size = xpra_chunk_size(buffer, 0)
        stride = xpra_chunk_stride(buffer, 0)
        if stride <= 0:
            stride = self.width * 4
        if xpra_is_dmabuf(xpra_data_type(buffer, 0)):
            lease = BufferLease.__new__(BufferLease)
            lease.owner = self
            lease.buffer = buffer
            self.leases.add(lease)
            frame = {"type": "dmabuf", "width": self.width, "height": self.height,
                     "stride": stride, "format": cformat.decode(), "modifier": self.modifier,
                     "drm-format": xpra_drm_format(self.spa_format),
                     "fds": [], "strides": [], "offsets": [],
                     "release": lease.release}
            for i in range(count):
                frame["fds"].append(xpra_data_fd(buffer, i))
                frame["strides"].append(xpra_chunk_stride(buffer, i) or stride)
                frame["offsets"].append(xpra_data_mapoffset(buffer, i) + xpra_chunk_offset(buffer, i))
            self.callback.native_frame(frame)
            return
        ptr = xpra_data_ptr(buffer, 0)
        maxsize = xpra_data_maxsize(buffer, 0)
        if ptr != NULL and offset <= maxsize and size <= maxsize - offset:
            data = PyBytes_FromStringAndSize(<char *>ptr, offset + size)
            self.callback.native_frame({"type": "memory", "data": data,
                "offset": offset, "size": size, "width": self.width, "height": self.height,
                "stride": stride, "format": cformat.decode()})
        pw_stream_queue_buffer(self.stream, buffer)

    cdef void _release(self, BufferLease lease):
        self.leases.discard(lease)
        if self.stream != NULL and lease.buffer != NULL:
            pw_thread_loop_lock(self.loop)
            pw_stream_queue_buffer(self.stream, lease.buffer)
            pw_thread_loop_unlock(self.loop)
            lease.buffer = NULL
        lease.owner = None
