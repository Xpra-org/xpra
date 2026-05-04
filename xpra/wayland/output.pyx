# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdint cimport uintptr_t

from xpra.wayland.events cimport ListenerObject

from xpra.wayland.wlroots cimport (
    wlr_output, wlr_output_layout, wlr_box, wl_signal,
    wlr_scene_output_commit, wlr_output_schedule_frame,
    wlr_output_state, wlr_output_state_init, wlr_output_commit_state, wlr_output_state_finish,
    wlr_output_state_set_scale,
    wlr_output_layout_get_box,
    WL_OUTPUT_TRANSFORM_NORMAL, WL_OUTPUT_TRANSFORM_90, WL_OUTPUT_TRANSFORM_180, WL_OUTPUT_TRANSFORM_270,
    WL_OUTPUT_TRANSFORM_FLIPPED, WL_OUTPUT_TRANSFORM_FLIPPED_90, WL_OUTPUT_TRANSFORM_FLIPPED_180, WL_OUTPUT_TRANSFORM_FLIPPED_270,
    WL_OUTPUT_SUBPIXEL_UNKNOWN, WL_OUTPUT_SUBPIXEL_NONE,
    WL_OUTPUT_SUBPIXEL_HORIZONTAL_RGB, WL_OUTPUT_SUBPIXEL_HORIZONTAL_BGR,
    WL_OUTPUT_SUBPIXEL_VERTICAL_RGB, WL_OUTPUT_SUBPIXEL_VERTICAL_BGR,
    WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED,
    DRM_FORMAT_BGRX5551, DRM_FORMAT_ARGB1555, DRM_FORMAT_ABGR1555, DRM_FORMAT_RGBA5551, DRM_FORMAT_BGRA5551,
    DRM_FORMAT_RGB565, DRM_FORMAT_BGR565, DRM_FORMAT_RGB888, DRM_FORMAT_BGR888,
    DRM_FORMAT_XRGB8888, DRM_FORMAT_XBGR8888, DRM_FORMAT_RGBX8888, DRM_FORMAT_BGRX8888,
    DRM_FORMAT_ARGB8888, DRM_FORMAT_ABGR8888, DRM_FORMAT_RGBA8888, DRM_FORMAT_BGRA8888,
    DRM_FORMAT_XRGB2101010, DRM_FORMAT_XBGR2101010, DRM_FORMAT_RGBX1010102,
    DRM_FORMAT_BGRX1010102, DRM_FORMAT_ARGB2101010, DRM_FORMAT_ABGR2101010,
    DRM_FORMAT_RGBA1010102, DRM_FORMAT_BGRA1010102, DRM_FORMAT_XRGB16161616,
    DRM_FORMAT_XBGR16161616, DRM_FORMAT_ARGB16161616, DRM_FORMAT_ABGR16161616,
)

from xpra.log import Logger

log = Logger("wayland", "display")
cdef bint debug = log.is_debug_enabled()


SUBPIXEL_STR: Dict[int, str] = {
    WL_OUTPUT_SUBPIXEL_UNKNOWN: "",
    WL_OUTPUT_SUBPIXEL_NONE: "none",
    WL_OUTPUT_SUBPIXEL_HORIZONTAL_RGB: "RGB",
    WL_OUTPUT_SUBPIXEL_HORIZONTAL_BGR: "BGR",
    WL_OUTPUT_SUBPIXEL_VERTICAL_RGB: "VRGB",
    WL_OUTPUT_SUBPIXEL_VERTICAL_BGR: "VBGR",
}

TRANSFORM_STR: Dict[int, str] = {
    WL_OUTPUT_TRANSFORM_NORMAL: "",
    WL_OUTPUT_TRANSFORM_90: "90",
    WL_OUTPUT_TRANSFORM_180: "180",
    WL_OUTPUT_TRANSFORM_270: "270",
    WL_OUTPUT_TRANSFORM_FLIPPED: "flipped",
    WL_OUTPUT_TRANSFORM_FLIPPED_90: "flipped-90",
    WL_OUTPUT_TRANSFORM_FLIPPED_180: "flipped-180",
    WL_OUTPUT_TRANSFORM_FLIPPED_270: "flipped-270",
}


RENDER_FORMAT_STR: Dict[int, str] = {
    DRM_FORMAT_BGRX5551: "BGRX5551",
    DRM_FORMAT_ARGB1555: "ARGB1555",
    DRM_FORMAT_ABGR1555: "ABGR1555",
    DRM_FORMAT_RGBA5551: "RGBA5551",
    DRM_FORMAT_BGRA5551: "BGRA5551",
    DRM_FORMAT_RGB565: "RGB565",
    DRM_FORMAT_BGR565: "BGR565",
    DRM_FORMAT_RGB888: "RGB888",
    DRM_FORMAT_BGR888: "BGR888",
    DRM_FORMAT_XRGB8888: "XRGB8888",
    DRM_FORMAT_XBGR8888: "XBGR8888",
    DRM_FORMAT_RGBX8888: "RGBX8888",
    DRM_FORMAT_BGRX8888: "BGRX8888",
    DRM_FORMAT_ARGB8888: "ARGB8888",
    DRM_FORMAT_ABGR8888: "ABGR8888",
    DRM_FORMAT_RGBA8888: "RGBA8888",
    DRM_FORMAT_BGRA8888: "BGRA8888",
    DRM_FORMAT_XRGB2101010: "XRGB2101010",
    DRM_FORMAT_XBGR2101010: "XBGR2101010",
    DRM_FORMAT_RGBX1010102: "RGBX1010102",
    DRM_FORMAT_BGRX1010102: "BGRX1010102",
    DRM_FORMAT_ARGB2101010: "ARGB2101010",
    DRM_FORMAT_ABGR2101010: "ABGR2101010",
    DRM_FORMAT_RGBA1010102: "RGBA1010102",
    DRM_FORMAT_BGRA1010102: "BGRA1010102",
    DRM_FORMAT_XRGB16161616: "XRGB16161616",
    DRM_FORMAT_XBGR16161616: "XBGR16161616",
    DRM_FORMAT_ARGB16161616: "ARGB16161616",
    DRM_FORMAT_ABGR16161616: "ABGR16161616",
}


cdef str istr(char* value):
    if value == NULL:
        return ""
    return value.decode("utf8")


cdef dict get_output_info(wlr_output *output, wlr_output_layout *output_layout):
    cdef wlr_box box
    info = {}
    def add(key: str, value: str):
        if value:
            info[key] = value
    add("name", istr(output.name))
    add("description", istr(output.description))
    add("make", istr(output.make))
    add("model", istr(output.model))
    add("serial", istr(output.serial))
    info.update({
        "physical-width": output.phys_width,
        "physical-height": output.phys_height,
        "width": output.width,
        "height": output.height,
        "enabled": bool(output.enabled),
        "scale": output.scale,
    })
    if output_layout != NULL:
        wlr_output_layout_get_box(output_layout, output, &box)
        info.update({
            "logical-x": box.x,
            "logical-y": box.y,
            "logical-width": box.width,
            "logical-height": box.height,
        })
    if output.refresh:
        info["vertical-refresh"] = round(output.refresh / 1000)
        info["refresh"] = output.refresh        # MHz
    subpixel = SUBPIXEL_STR.get(output.subpixel, "")
    if subpixel:
        info["subpixel"] = subpixel
    transform = TRANSFORM_STR.get(output.transform, "")
    if transform:
        info["transform"] = transform
    if output.adaptive_sync_supported:
        info["adaptive-sync"] = output.adaptive_sync_status == WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED
    if output.needs_frame:
        info["needs-frame"] = True
    if output.frame_pending:
        info["frame-pending"] = True
    if output.non_desktop:
        info["non-desktop"] = True
    info["commit-sequence"] = output.commit_seq
    info["render-format"] = RENDER_FORMAT_STR.get(output.render_format, "")
    # wl_list modes
    # wlr_output_mode *current_mode
    return info


# Listener slot indices for Output; N_LISTENERS sizes the listeners array.
cdef enum OutputListener:
    L_OUTPUT_FRAME
    L_DESTROY
    N_LISTENERS


cdef class Output(ListenerObject):

    def __init__(self):
        super().__init__(N_LISTENERS)

    def __repr__(self):
        return "Output(%s)" % (self.name)

    cdef void add_main_listeners(self):
        self.add_listener(L_OUTPUT_FRAME, &self.wlr_output.events.frame)
        self.add_listener(L_DESTROY, &self.wlr_output.events.destroy)

    cdef void initialize(self):
        cdef wlr_output_state state
        wlr_output_state_init(&state)
        wlr_output_state_set_scale(&state, 1.0)
        wlr_output_commit_state(self.wlr_output, &state)
        wlr_output_state_finish(&state)

        name = self.wlr_output.name.decode()
        log("new output: %r", name)
        log(" virtual output %r initialized with scale %.1f", name, self.wlr_output.scale)

    def get_description(self):
        name = istr(self.wlr_output.name)
        width = self.wlr_output.width
        height = self.wlr_output.height
        return f"{name!r} : {width}x{height}"

    # Single C shim for every Output-level listener. The slot is recovered by
    # pointer arithmetic on the listeners[] array, then dispatched to the matching Output method.
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_OUTPUT_FRAME:
            self.output_frame()
        elif slot == L_DESTROY:
            self.destroy()
        else:
            log.error("Error: unknown output listener slot %i", slot)

    cdef void output_frame(self) noexcept nogil:
        if debug:
            with gil:
                log("output_frame()")
        wlr_scene_output_commit(self.scene_output, NULL)
        wlr_output_schedule_frame(self.wlr_output)

    cdef void destroy(self) noexcept nogil:
        if debug:
            with gil:
                log("output_destroy_handler()")
        self._detach_all()

    def get_info(self) -> dict[str, str | int | bool | float]:
        return get_output_info(self.wlr_output, self.output_layout)
