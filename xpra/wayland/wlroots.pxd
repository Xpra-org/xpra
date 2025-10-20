# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uintptr_t, uint8_t, uint32_t, uint64_t, int32_t
from libc.time cimport timespec

ctypedef void wlr_session
ctypedef void wlr_swapchain


DEF WLR_KEYBOARD_KEYS_CAP = 32
DEF WLR_LED_COUNT = 3
DEF WLR_MODIFIER_COUNT = 8


cdef extern from "xkbcommon/xkbcommon.h":
    cdef struct xkb_keymap:
        pass

    ctypedef struct xkb_state:
        pass

    ctypedef uint32_t xkb_led_index_t
    ctypedef uint32_t xkb_mod_index_t

    cdef enum xkb_context_flags:
        XKB_CONTEXT_NO_FLAGS
        XKB_CONTEXT_NO_DEFAULT_INCLUDES
        XKB_CONTEXT_NO_ENVIRONMENT_NAMES
        XKB_CONTEXT_NO_SECURE_GETENV

    cdef enum xkb_keymap_compile_flags:
        XKB_KEYMAP_COMPILE_NO_FLAGS

    cdef enum xkb_state_component:
        XKB_STATE_MODS_DEPRESSED
        XKB_STATE_MODS_LATCHED
        XKB_STATE_MODS_LOCKED
        XKB_STATE_MODS_EFFECTIVE
        XKB_STATE_LAYOUT_DEPRESSED
        XKB_STATE_LAYOUT_LATCHED
        XKB_STATE_LAYOUT_LOCKED
        XKB_STATE_LAYOUT_EFFECTIVE
        XKB_STATE_LEDS

    cdef enum xkb_state_match:
        XKB_STATE_MATCH_ANY
        XKB_STATE_MATCH_ALL
        XKB_STATE_MATCH_NON_EXCLUSIVE

    cdef enum xkb_key_direction:
        XKB_KEY_UP
        XKB_KEY_DOWN

    cdef struct xkb_context:
        pass

    cdef struct xkb_rule_names:
        const char *rules
        const char *model
        const char *layout
        const char *variant
        const char *options

    cdef enum xkb_keymap_format:
        XKB_KEYMAP_FORMAT_TEXT_V1

    xkb_context* xkb_context_new(xkb_context_flags flags)
    void xkb_context_unref(xkb_context *context)

    xkb_keymap* xkb_keymap_new_from_names(xkb_context *context, const xkb_rule_names *names, xkb_keymap_compile_flags flags)
    void xkb_keymap_unref(xkb_keymap *keymap)

    char *xkb_keymap_get_as_string(xkb_keymap *keymap, xkb_keymap_format format)


cdef extern from "linux/input-event-codes.h":
    int BTN_MOUSE       # 0x110
    int BTN_LEFT
    int BTN_RIGHT
    int BTN_MIDDLE
    int BTN_SIDE
    int BTN_EXTRA
    int BTN_FORWARD
    int BTN_BACK
    int BTN_TASK



cdef extern from "drm/drm_fourcc.h":
    # RGB 15 / 16 bit:
    uint32_t DRM_FORMAT_BGRX5551
    uint32_t DRM_FORMAT_ARGB1555
    uint32_t DRM_FORMAT_ABGR1555
    uint32_t DRM_FORMAT_RGBA5551
    uint32_t DRM_FORMAT_BGRA5551
    uint32_t DRM_FORMAT_RGB565
    uint32_t DRM_FORMAT_BGR565
    # 24-bit:
    uint32_t DRM_FORMAT_RGB888
    uint32_t DRM_FORMAT_BGR888
    # 32-bit no alpha:
    uint32_t DRM_FORMAT_XRGB8888
    uint32_t DRM_FORMAT_XBGR8888
    uint32_t DRM_FORMAT_RGBX8888
    uint32_t DRM_FORMAT_BGRX8888
    # 32-bit with alpha:
    uint32_t DRM_FORMAT_ARGB8888
    uint32_t DRM_FORMAT_ABGR8888
    uint32_t DRM_FORMAT_RGBA8888
    uint32_t DRM_FORMAT_BGRA8888
    # 30-bit no alpha:
    uint32_t DRM_FORMAT_XRGB2101010
    uint32_t DRM_FORMAT_XBGR2101010
    uint32_t DRM_FORMAT_RGBX1010102
    uint32_t DRM_FORMAT_BGRX1010102
    # 30-bit with alpha:
    uint32_t DRM_FORMAT_ARGB2101010
    uint32_t DRM_FORMAT_ABGR2101010
    uint32_t DRM_FORMAT_RGBA1010102
    uint32_t DRM_FORMAT_BGRA1010102
    # 64-bit:
    uint32_t DRM_FORMAT_XRGB16161616
    uint32_t DRM_FORMAT_XBGR16161616
    uint32_t DRM_FORMAT_ARGB16161616
    uint32_t DRM_FORMAT_ABGR16161616


cdef extern from "wayland-util.h":
    cdef struct wl_list:
        wl_list *prev
        wl_list *next

    ctypedef struct wl_array:
        size_t size
        size_t alloc
        void *data

    void wl_array_init(wl_array *array)
    void wl_array_release(wl_array *array)
    void *wl_array_add(wl_array *array, size_t size)


cdef extern from "wayland-server-core.h":
    cdef struct wl_global:
        pass
    cdef struct wl_display:
        pass
    cdef struct wl_event_loop:
        pass
    cdef struct wl_client:
        pass
    cdef struct wl_resource:
        pass

    ctypedef struct wl_interface:
        const char *name
        int version
        int method_count
        const void *methods
        int event_count
        const void *events

    ctypedef void (*wl_global_bind_func_t)(wl_client *client, void *data, uint32_t version, uint32_t id)

    ctypedef void (*wl_notify_func_t)(wl_listener *listener, void *data)
    cdef struct wl_listener:
        wl_notify_func_t notify
        wl_list link
    ctypedef struct wl_signal:
        wl_list listener_list

    wl_display *wl_display_create()
    void wl_display_destroy(wl_display *display)
    void wl_display_destroy_clients(wl_display *display)
    void wl_display_run(wl_display *display)
    wl_event_loop *wl_display_get_event_loop(wl_display *display)
    const char *wl_display_add_socket_auto(wl_display *display)
    void wl_signal_add(wl_signal *signal, wl_listener *listener) nogil
    void wl_list_remove(wl_list *elm) nogil
    wl_event_loop *wl_event_loop_create()
    void wl_event_loop_destroy(wl_event_loop *loop)
    int wl_event_loop_get_fd(wl_event_loop *loop)
    int wl_event_loop_dispatch(wl_event_loop *loop, int timeout)

    void wl_display_flush_clients(wl_display *display)

    wl_global* wl_global_create(wl_display *display, const wl_interface *interface,
                                int version, void *data, wl_global_bind_func_t bind)
    void wl_global_destroy(wl_global *_global)

    wl_resource* wl_resource_create(wl_client *client, const wl_interface *interface, int version, uint32_t id)
    void wl_resource_set_implementation(wl_resource *resource, const void *implementation, void *data,
        void (*destroy)(wl_resource *resource)
    )

    void wl_resource_destroy(wl_resource *resource)
    void* wl_resource_get_user_data(wl_resource *resource)
    void wl_resource_post_event(wl_resource *resource, uint32_t opcode, ...)
    wl_client* wl_resource_get_client(wl_resource *resource)

    wl_client* wl_client_create(wl_display *display, int fd)
    void wl_client_destroy(wl_client *client)
    wl_display* wl_client_get_display(wl_client *client)


cdef extern from "wayland-server-protocol.h":
    cdef enum wl_seat_capability:
        WL_SEAT_CAPABILITY_POINTER
        WL_SEAT_CAPABILITY_KEYBOARD
        WL_SEAT_CAPABILITY_TOUCH

    cdef enum wl_output_subpixel:
        WL_OUTPUT_SUBPIXEL_UNKNOWN
        WL_OUTPUT_SUBPIXEL_NONE
        WL_OUTPUT_SUBPIXEL_HORIZONTAL_RGB
        WL_OUTPUT_SUBPIXEL_HORIZONTAL_BGR
        WL_OUTPUT_SUBPIXEL_VERTICAL_RGB
        WL_OUTPUT_SUBPIXEL_VERTICAL_BGR

    cdef enum wl_output_transform:
        WL_OUTPUT_TRANSFORM_NORMAL
        WL_OUTPUT_TRANSFORM_90
        WL_OUTPUT_TRANSFORM_180
        WL_OUTPUT_TRANSFORM_270
        WL_OUTPUT_TRANSFORM_FLIPPED
        WL_OUTPUT_TRANSFORM_FLIPPED_90
        WL_OUTPUT_TRANSFORM_FLIPPED_180
        WL_OUTPUT_TRANSFORM_FLIPPED_270

    cdef enum wl_pointer_axis:
        WL_POINTER_AXIS_VERTICAL_SCROLL
        WL_POINTER_AXIS_HORIZONTAL_SCROLL

    cdef enum wl_pointer_axis_relative_direction:
        WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL
        WL_POINTER_AXIS_RELATIVE_DIRECTION_INVERTED

    cdef enum wl_pointer_axis_source:
        WL_POINTER_AXIS_SOURCE_WHEEL
        WL_POINTER_AXIS_SOURCE_FINGER
        WL_POINTER_AXIS_SOURCE_CONTINUOUS
        WL_POINTER_AXIS_SOURCE_WHEEL_TILT

    cdef enum wl_keyboard_key_state:
        WL_KEYBOARD_KEY_STATE_RELEASED
        WL_KEYBOARD_KEY_STATE_PRESSED

    cdef enum wl_keyboard_keymap_format:
        WL_KEYBOARD_KEYMAP_FORMAT_NO_KEYMAP
        WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1

    cdef extern const wl_interface wl_keyboard_interface

    int WL_KEYBOARD_KEYMAP
    int WL_KEYBOARD_ENTER
    int WL_KEYBOARD_LEAVE
    int WL_KEYBOARD_KEY
    int WL_KEYBOARD_MODIFIERS
    int WL_KEYBOARD_REPEAT_INFO

cdef extern from "wayland-client.h":
    ctypedef struct wl_display:
        pass

    ctypedef struct wl_proxy:
        pass

    ctypedef struct wl_registry:
        pass

    # Client-side display functions
    wl_display* wl_display_connect_to_fd(int fd)
    void wl_display_disconnect(wl_display *display)
    int wl_display_dispatch(wl_display *display)
    int wl_display_roundtrip(wl_display *display)
    int wl_display_get_fd(wl_display *display)


cdef extern from "wlr/util/box.h":
    cdef struct wlr_box:
        int x
        int y
        int width
        int height


cdef extern from "wlr/util/addon.h":
    cdef struct wlr_addon_set:
        pass


cdef extern from "wlr/util/log.h":
    cdef enum wlr_log_importance:
        WLR_SILENT
        WLR_ERROR
        WLR_INFO
        WLR_DEBUG

    void wlr_log_init(wlr_log_importance verbosity, void *callback)
    void wlr_log(wlr_log_importance verbosity, const char *fmt, ...) nogil


cdef extern from "wlr/util/edges.h":
    cdef enum wlr_edges:
        WLR_EDGE_NONE
        WLR_EDGE_TOP
        WLR_EDGE_BOTTOM
        WLR_EDGE_LEFT
        WLR_EDGE_RIGHT

cdef extern from "wlr/types/wlr_buffer.h":
    enum wlr_buffer_data_ptr_access_flag:
        WLR_BUFFER_DATA_PTR_ACCESS_READ
        WLR_BUFFER_DATA_PTR_ACCESS_WRITE

    enum wlr_buffer_cap:
        WLR_BUFFER_CAP_DATA_PTR
        WLR_BUFFER_CAP_DMABUF
        WLR_BUFFER_CAP_SHM

    cdef struct wlr_buffer_events:
        wl_signal destroy
        wl_signal release

    ctypedef void* wlr_buffer_impl
    cdef struct wlr_buffer:
        const wlr_buffer_impl *impl
        int width, height
        bint dropped
        size_t n_locks
        bint accessing_data_ptr
        wlr_buffer_events events
        wlr_addon_set addons

    cdef struct wlr_client_buffer:
        wlr_buffer base
        wlr_texture *texture
        wlr_buffer *source

    wlr_buffer *wlr_buffer_lock(wlr_buffer *buffer)
    void wlr_buffer_unlock(wlr_buffer *buffer)

    cdef struct wlr_dmabuf_attributes:
        int32_t width
        int32_t height
        uint32_t format
        uint64_t modifier
        int32_t n_planes
        uint32_t offset[4]
        uint32_t stride[4]
        int32_t fd[4]
    bint wlr_buffer_get_dmabuf(wlr_buffer *buffer, wlr_dmabuf_attributes *attribs)

    cdef struct wlr_shm_attributes:
        int fd
        uint32_t width
        uint32_t height
        uint32_t stride
        uint32_t format
        void *data
        size_t size
    bint wlr_buffer_get_shm(wlr_buffer *buffer, wlr_shm_attributes *attribs)

    bint wlr_buffer_begin_data_ptr_access(wlr_buffer *buffer, uint32_t flags,
                                          void **data, uint32_t *format, size_t *stride)
    void wlr_buffer_end_data_ptr_access(wlr_buffer *buffer)


cdef extern from "wlr/render/wlr_texture.h":
    cdef struct wlr_renderer_events:
        wl_signal destroy
        wl_signal lost
    cdef struct wlr_renderer_features:
        bint output_color_transform
        bint timeline
    cdef struct wlr_renderer:
        uint32_t render_buffer_caps
        wlr_renderer_events events
        wlr_renderer_features features
    cdef struct wlr_texture:
        wlr_texture_impl *impl
        uint32_t width
        uint32_t height
        wlr_renderer *renderer

    cdef struct wlr_texture_read_pixels_options:
        # Memory location to read pixels into
        void *data
        # Format used for writing the pixel data
        uint32_t format
        # Stride in bytes for the data
        uint32_t stride
        # Destination offsets
        uint32_t dst_x
        uint32_t dst_y
        # Source box of the texture to read from. If empty, the full texture is assumed.
        const wlr_box src_box

    bint wlr_texture_read_pixels(wlr_texture *texture, wlr_texture_read_pixels_options *options) nogil
    void wlr_texture_destroy(wlr_texture *texture)

    wlr_texture *wlr_texture_from_buffer(wlr_renderer *renderer, wlr_buffer *buffer)


cdef extern from "wlr/render/pass.h":
    cdef enum wlr_render_blend_mode:
        WLR_RENDER_BLEND_MODE_PREMULTIPLIED
        WLR_RENDER_BLEND_MODE_NONE

    cdef enum wlr_scale_filter_mode:
        WLR_SCALE_FILTER_BILINEAR
        WLR_SCALE_FILTER_NEAREST

    cdef struct pixman_region32_t:
        pass

    cdef struct wlr_render_texture_options:
        wlr_texture *texture
        # wlr_fbox src_box
        wlr_box dst_box
        const float *alpha
        const pixman_region32_t *clip
        # wlr_drm_syncobj_timeline *wait_timeline
        uint64_t wait_point

    cdef struct wlr_render_pass:
        pass

    cdef struct wlr_buffer_pass_options:
        pass

    wlr_render_pass *wlr_renderer_begin_buffer_pass(wlr_renderer *renderer,
                       wlr_buffer *buffer, const wlr_buffer_pass_options *options)
    bint wlr_render_pass_submit(wlr_render_pass *render_pass)
    void wlr_render_pass_add_texture(wlr_render_pass *render_pass, const wlr_render_texture_options *options)

    cdef struct wlr_render_color:
        float r, g, b, a;

    cdef struct wlr_render_rect_options:
        wlr_box box
        wlr_render_color color
        # const pixman_region32_t *clip
        wlr_render_blend_mode blend_mode

    cdef struct wlr_render_color:
        float r
        float g
        float b
        float a

    void wlr_render_pass_add_rect(wlr_render_pass *render_pass, const wlr_render_rect_options *options)


cdef extern from "wlr/render/pixman.h":
    wlr_renderer *wlr_pixman_renderer_create()


cdef extern from "wlr/types/wlr_output.h":
    cdef enum wlr_output_mode_aspect_ratio:
        WLR_OUTPUT_MODE_ASPECT_RATIO_NONE
        WLR_OUTPUT_MODE_ASPECT_RATIO_4_3
        WLR_OUTPUT_MODE_ASPECT_RATIO_16_9
        WLR_OUTPUT_MODE_ASPECT_RATIO_64_27
        WLR_OUTPUT_MODE_ASPECT_RATIO_256_135

    cdef enum wlr_output_adaptive_sync_status:
        WLR_OUTPUT_ADAPTIVE_SYNC_DISABLED
        WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED

    cdef enum wlr_output_state_field:
        WLR_OUTPUT_STATE_BUFFER
        WLR_OUTPUT_STATE_DAMAGE
        WLR_OUTPUT_STATE_MODE
        WLR_OUTPUT_STATE_ENABLED
        WLR_OUTPUT_STATE_SCALE
        WLR_OUTPUT_STATE_TRANSFORM
        WLR_OUTPUT_STATE_ADAPTIVE_SYNC_ENABLED
        WLR_OUTPUT_STATE_GAMMA_LUT
        WLR_OUTPUT_STATE_RENDER_FORMAT
        WLR_OUTPUT_STATE_SUBPIXEL
        WLR_OUTPUT_STATE_LAYERS
        WLR_OUTPUT_STATE_WAIT_TIMELINE
        WLR_OUTPUT_STATE_SIGNAL_TIMELINE

    cdef enum wlr_output_state_mode_type:
        WLR_OUTPUT_STATE_MODE_FIXED
        WLR_OUTPUT_STATE_MODE_CUSTOM

    cdef struct wlr_output_mode:
        int32_t width
        int32_t height
        int32_t refresh     # mHz
        bint preferred
        wlr_output_mode_aspect_ratio picture_aspect_ratio
        # wl_list link

    cdef struct wlr_output_state:
        uint32_t committed
        bint allow_reconfiguration

    cdef struct wlr_output_events:
        wl_signal frame
        wl_signal damage
        wl_signal needs_frame
        wl_signal precommit
        wl_signal commit
        wl_signal present
        wl_signal bind
        wl_signal description
        wl_signal request_state
        wl_signal destroy

    ctypedef void wlr_output_cursor
    ctypedef void wlr_output_impl
    ctypedef void wl_event_source
    cdef struct wlr_output:
        const wlr_output_impl *impl
        wlr_backend *backend
        wl_event_loop *event_loop

        #wl_global *global
        wl_list resources

        char *name
        char *description
        char *make
        char *model
        char *serial
        int32_t phys_width
        int32_t phys_height

        wl_list modes
        wlr_output_mode *current_mode
        int32_t width
        int32_t height
        int32_t refresh     # mHz, may be zero

        bint enabled
        float scale
        wl_output_subpixel subpixel
        wl_output_transform transform
        wlr_output_adaptive_sync_status adaptive_sync_status
        uint32_t render_format
        bint adaptive_sync_supported
        bint needs_frame
        bint frame_pending
        bint non_desktop
        uint32_t commit_seq
        wlr_output_events events
        wl_event_source *idle_frame
        wl_event_source *idle_done
        int attach_render_locks
        wl_list cursors
        wlr_output_cursor *hardware_cursor
        wlr_swapchain *cursor_swapchain
        wlr_buffer *cursor_front_buffer
        int software_cursor_locks
        wl_list layers
        wlr_allocator *allocator
        wlr_renderer *renderer
        wlr_swapchain *swapchain
        wlr_addon_set addons
        void *data

    void wlr_output_init_render(wlr_output *output, wlr_allocator *allocator, wlr_renderer *renderer) nogil
    void wlr_output_schedule_frame(wlr_output *output) nogil
    void wlr_output_state_init(wlr_output_state *state) nogil
    int wlr_output_commit_state(wlr_output *output, const wlr_output_state *state) nogil
    void wlr_output_state_finish(wlr_output_state *state) nogil


cdef extern from "wlr/types/wlr_output_layout.h":
    cdef struct wlr_output_layout:
        pass

    wlr_output_layout* wlr_output_layout_create(wl_display *display)
    void wlr_output_layout_destroy(wlr_output_layout *layout)
    void wlr_output_layout_add_auto(wlr_output_layout *layout, wlr_output *output) nogil


cdef extern from "wlr/types/wlr_input_device.h":
    cdef enum wlr_input_device_type:
        WLR_INPUT_DEVICE_KEYBOARD
        WLR_INPUT_DEVICE_POINTER
        WLR_INPUT_DEVICE_TOUCH
        WLR_INPUT_DEVICE_TABLET
        WLR_INPUT_DEVICE_TABLET_PAD
        WLR_INPUT_DEVICE_SWITCH

    cdef struct wlr_input_device:
        wlr_input_device_type type
        unsigned int vendor
        unsigned int product
        char *name
        void *data

    wlr_keyboard* wlr_keyboard_from_input_device(wlr_input_device *device)


cdef extern from "wlr/types/wlr_seat.h":
    cdef struct wlr_seat_client:
        wl_client *client
        wl_resource *seat_resource
        wl_list link
        # Keyboard resources for this client
        wl_list keyboards
        wl_list pointers
        wl_list touches

    cdef struct wlr_seat:
        wl_list clients  # wlr_seat_client list
        char *name

    cdef enum wlr_button_state:
        WLR_BUTTON_RELEASED
        WLR_BUTTON_PRESSED

    cdef struct wlr_axis_orientation:
        int32_t acc_discrete[2]
        int32_t last_discrete[2]
        double acc_axis

    wlr_seat* wlr_seat_create(wl_display *display, const char *name)
    void wlr_seat_destroy(wlr_seat *seat)
    void wlr_seat_set_capabilities(wlr_seat *seat, uint32_t capabilities)
    void wlr_seat_pointer_notify_enter(wlr_seat *seat, wlr_surface *surface, double sx, double sy)
    void wlr_seat_pointer_notify_motion(wlr_seat *seat, uint32_t time_msec, double sx, double sy)
    void wlr_seat_pointer_notify_button(wlr_seat *seat, uint32_t time_msec, uint32_t button, uint32_t state)
    void wlr_seat_pointer_notify_frame(wlr_seat *seat)
    void wlr_seat_pointer_notify_clear_focus(wlr_seat *seat)
    void wlr_seat_pointer_notify_axis(wlr_seat *seat, uint32_t time_msec, wl_pointer_axis orientation,
                                       double value, int32_t value_discrete, wl_pointer_axis_source source,
                                       wl_pointer_axis_relative_direction relative_direction)

    void wlr_seat_keyboard_notify_key(wlr_seat *seat, uint32_t time_msec, uint32_t key, uint32_t state)
    void wlr_seat_keyboard_notify_modifiers(wlr_seat *seat, wlr_keyboard_modifiers *modifiers)
    void wlr_seat_keyboard_notify_enter(wlr_seat *seat, wlr_surface *surface,
                                        uint32_t *keycodes, size_t num_keycodes, wlr_keyboard_modifiers *modifiers)
    void wlr_seat_set_keyboard(wlr_seat *seat, wlr_keyboard *dev)
    void wlr_seat_keyboard_clear_focus(wlr_seat *seat)

    wlr_keyboard* wlr_seat_get_keyboard(wlr_seat *seat)
    wlr_seat_client* wlr_seat_client_for_wl_client(wlr_seat *seat, wl_client *client)


cdef extern from "wlr/types/wlr_keyboard.h":
    cdef struct wlr_seat_keyboard_state:
        wlr_surface *focused_surface

    cdef struct wlr_keyboard_modifiers:
        uint32_t depressed
        uint32_t latched
        uint32_t locked
        uint32_t group

    cdef struct wlr_keyboard_repeat_info:
        int32_t rate
        int32_t delay

    cdef struct wlr_keyboard_events:
        wl_signal key
        wl_signal modifiers
        wl_signal keymap
        wl_signal repeat_info
        wl_signal destroy

    cdef struct wlr_keyboard:
        wlr_input_device *base
        const wlr_keyboard_impl *impl
        void *data

        # Keymap information
        char *keymap_string
        size_t keymap_size
        xkb_keymap *keymap
        xkb_state *xkb_state

        # XKB indexes
        xkb_led_index_t led_indexes[WLR_LED_COUNT]
        xkb_mod_index_t mod_indexes[WLR_MODIFIER_COUNT]

        # Currently pressed keys
        uint32_t keycodes[WLR_KEYBOARD_KEYS_CAP]
        size_t num_keycodes

        # Current modifier state
        wlr_keyboard_modifiers modifiers

        # Repeat configuration
        wlr_keyboard_repeat_info repeat_info

        # Events
        wlr_keyboard_events events

    enum wlr_keyboard_modifier:
        WLR_MODIFIER_SHIFT
        WLR_MODIFIER_CAPS
        WLR_MODIFIER_CTRL
        WLR_MODIFIER_ALT
        WLR_MODIFIER_MOD2
        WLR_MODIFIER_MOD3
        WLR_MODIFIER_LOGO
        WLR_MODIFIER_MOD5

    cdef struct wlr_keyboard_key_event:
        uint32_t time_msec
        uint32_t keycode
        bint update_state       # if backend doesn't update modifiers on its own
        wl_keyboard_key_state state

    void wlr_keyboard_set_keymap(wlr_keyboard *kb, xkb_keymap *keymap)
    void wlr_keyboard_set_repeat_info(wlr_keyboard *kb, int32_t rate, int32_t delay)


cdef extern from "wlr/interfaces/wlr_keyboard.h":
    cdef struct wlr_keyboard_impl:
        const char *name
        void (*led_update)(wlr_keyboard *keyboard, uint32_t leds)

    void wlr_keyboard_init(wlr_keyboard *keyboard, const wlr_keyboard_impl *impl, const char *name)
    void wlr_keyboard_finish(wlr_keyboard *keyboard)

    void wlr_keyboard_notify_key(wlr_keyboard *keyboard, wlr_keyboard_key_event *event)
    void wlr_keyboard_notify_modifiers(
        wlr_keyboard *keyboard,
        uint32_t mods_depressed, uint32_t mods_latched, uint32_t mods_locked, uint32_t group
    )


cdef extern from "wlr/types/wlr_virtual_keyboard_v1.h":

    cdef struct wlr_virtual_keyboard_manager_v1_events:
        wl_signal new_virtual_keyboard
        wl_signal destroy

    cdef struct wlr_virtual_keyboard_manager_v1:
        wl_global *_global
        wl_list virtual_keyboards
        wlr_virtual_keyboard_manager_v1_events events
        void *data

    cdef struct wlr_virtual_keyboard_v1:
        wlr_keyboard keyboard
        wl_resource *resource
        wlr_seat *seat
        bint has_keymap
        wl_list link

    wlr_virtual_keyboard_manager_v1* wlr_virtual_keyboard_manager_v1_create(wl_display *display)
    wlr_virtual_keyboard_v1 *wlr_input_device_get_virtual_keyboard(wlr_input_device *wlr_dev)


cdef extern from "wlr/types/wlr_cursor.h":
    cdef struct wlr_cursor:
        double x
        double y

    wlr_cursor* wlr_cursor_create()
    void wlr_cursor_destroy(wlr_cursor *cursor)
    void wlr_cursor_attach_output_layout(wlr_cursor *cursor, wlr_output_layout *layout)
    void wlr_cursor_warp(wlr_cursor *cursor, wlr_input_device *device, double lx, double ly)
    void wlr_cursor_move(wlr_cursor *cursor, wlr_input_device *device, double delta_x, double delta_y)


cdef extern from "wlr/types/wlr_pointer.h":
    cdef struct wlr_pointer:
        pass
    cdef struct wlr_pointer_axis_event:
        wlr_pointer *pointer;
        uint32_t time_msec
        wl_pointer_axis_source source
        wl_pointer_axis orientation
        wl_pointer_axis_relative_direction relative_direction
        double delta
        int32_t delta_discrete

cdef extern from "wlr/types/wlr_virtual_pointer_v1.h":
    cdef struct wlr_virtual_pointer_v1:
        wlr_pointer pointer
        # wl_resource *resource
        # Vertical and horizontal:
        wlr_pointer_axis_event axis_event[2];
        wl_pointer_axis axis
        bint axis_valid[2]
        wl_list link

    cdef struct wlr_virtual_pointer_manager_v1_events:
        wl_signal new_virtual_pointer
        wl_signal destroy

    cdef struct wlr_virtual_pointer_manager_v1:
        # wl_global *global
        wl_list virtual_pointers
        wlr_virtual_pointer_manager_v1_events events

    cdef struct wlr_virtual_pointer_v1_new_pointer_event:
        wlr_virtual_pointer_v1 *new_pointer
        # Suggested by client; may be NULL
        wlr_seat *suggested_seat
        wlr_output *suggested_output
    wlr_virtual_pointer_manager_v1* wlr_virtual_pointer_manager_v1_create(wl_display *display)


cdef extern from "wlr/types/wlr_xdg_shell.h":
    cdef enum wlr_xdg_surface_role:
        WLR_XDG_SURFACE_ROLE_NONE
        WLR_XDG_SURFACE_ROLE_TOPLEVEL
        WLR_XDG_SURFACE_ROLE_POPUP
    cdef enum wlr_xdg_surface_state_field:
        WLR_XDG_SURFACE_STATE_WINDOW_GEOMETRY
    cdef struct wlr_xdg_surface_state:
        uint32_t committed
        wlr_box geometry
        uint32_t configure_serial
    ctypedef struct wlr_xdg_surface_events:
        wl_signal destroy
        wl_signal ping_timeout
        wl_signal new_popup
        wl_signal configure
        wl_signal ack_configure
    cdef struct wlr_xdg_surface:
        # wlr_xdg_client *client
        # wl_resource *resource
        wlr_surface *surface
        wl_list link
        wlr_xdg_surface_role role
        # wl_resource *role_resource
        wlr_xdg_toplevel *toplevel
        # wlr_xdg_popup *popup
        wl_list popups
        int configured
        wl_event_source *configure_idle
        uint32_t scheduled_serial
        wl_list configure_list
        wlr_xdg_surface_state current
        wlr_xdg_surface_state pending
        int initialized
        bint initial_commit
        wlr_box geometry
        wlr_xdg_surface_events events
        void *data
    cdef struct wlr_xdg_toplevel_requested:
        int maximized
        int fullscreen
    cdef struct wlr_xdg_toplevel_events:
        wl_signal request_maximize
        wl_signal request_fullscreen
        wl_signal request_minimize
        wl_signal request_move
        wl_signal request_resize
        wl_signal request_show_window_menu
        wl_signal set_parent
        wl_signal set_title
        wl_signal set_app_id
    cdef struct wlr_xdg_toplevel:
        char *title
        char *app_id
        wlr_xdg_toplevel_events events
        wlr_xdg_toplevel_requested requested
    cdef struct wlr_xdg_toplevel_move_event:
        wlr_xdg_toplevel *toplevel
        wlr_seat_client *seat
        uint32_t serial
    cdef struct wlr_xdg_toplevel_resize_event:
        wlr_xdg_toplevel *toplevel
        wlr_seat_client *seat
        uint32_t serial
        uint32_t edges
    cdef struct wlr_xdg_toplevel_show_window_menu_event:
        wlr_xdg_toplevel *toplevel
        wlr_seat_client *seat
        uint32_t serial
        int32_t x
        int32_t y

    ctypedef struct wlr_xdg_shell_events:
        wl_signal new_surface
        wl_signal new_toplevel
        wl_signal new_popup
        wl_signal destroy
    cdef struct wlr_xdg_shell:
        # wl_global *global
        uint32_t version
        wl_list clients;
        wl_list popup_grabs
        uint32_t ping_timeout
        wlr_xdg_shell_events events
        void *data
        wl_listener display_destroy

    wlr_xdg_shell *wlr_xdg_shell_create(wl_display *display, int version)
    uint32_t wlr_xdg_toplevel_set_size(wlr_xdg_toplevel *toplevel, int width, int height) nogil
    uint32_t wlr_xdg_toplevel_set_activated(wlr_xdg_toplevel *toplevel, bint activated) nogil
    uint32_t wlr_xdg_toplevel_set_maximized(wlr_xdg_toplevel *toplevel, bint maximized) nogil
    uint32_t wlr_xdg_toplevel_set_fullscreen(wlr_xdg_toplevel *toplevel, bint fullscreen) nogil
    uint32_t wlr_xdg_toplevel_set_resizing(wlr_xdg_toplevel *toplevel, bint resizing) nogil
    uint32_t wlr_xdg_toplevel_set_tiled(wlr_xdg_toplevel *toplevel, uint32_t tiled_edges) nogil
    uint32_t wlr_xdg_surface_schedule_configure(wlr_xdg_surface *surface) nogil

    void wlr_xdg_surface_get_geometry(wlr_xdg_surface *surface, wlr_box *box)


cdef extern from "wlr/types/wlr_xdg_decoration_v1.h":
    ctypedef enum wlr_xdg_toplevel_decoration_v1_mode:
        WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_NONE
        WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_CLIENT_SIDE
        WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE

    cdef struct wlr_xdg_toplevel_decoration_v1_state:
        wlr_xdg_toplevel_decoration_v1_mode mode

    cdef struct wlr_xdg_decoration_manager_v1_events:
        wl_signal new_toplevel_decoration
        wl_signal destroy

    cdef struct wlr_xdg_decoration_manager_v1:
        wl_list decorations  # List of wlr_xdg_toplevel_decoration_v1
        wlr_xdg_decoration_manager_v1_events events
        void *data

    cdef struct wlr_xdg_toplevel_decoration_v1_events:
        wl_signal destroy
        wl_signal request_mode

    cdef struct wlr_xdg_toplevel_decoration_v1:
        void *resource  # wl_resource
        wlr_xdg_surface *surface
        wlr_xdg_toplevel *toplevel
        wlr_xdg_decoration_manager_v1 *manager

        wl_list link  # wlr_xdg_decoration_manager_v1::decorations

        wlr_xdg_toplevel_decoration_v1_state current
        wlr_xdg_toplevel_decoration_v1_state pending

        wlr_xdg_toplevel_decoration_v1_mode scheduled_mode
        wlr_xdg_toplevel_decoration_v1_mode requested_mode

        bint added

        wlr_xdg_toplevel_decoration_v1_events events

        # Listeners
        wl_listener surface_destroy
        wl_listener surface_configure
        wl_listener surface_ack_configure
        wl_listener surface_commit

        void *data

    wlr_xdg_decoration_manager_v1 *wlr_xdg_decoration_manager_v1_create(wl_display *display) nogil

    void wlr_xdg_toplevel_decoration_v1_set_mode(wlr_xdg_toplevel_decoration_v1 *decoration, wlr_xdg_toplevel_decoration_v1_mode mode) nogil


cdef extern from "wlr/types/wlr_scene.h":
    cdef struct wlr_scene_output:
        pass
    cdef struct wlr_scene_node:
        pass
    cdef struct wlr_scene_tree:
        wlr_scene_node node
    cdef struct wlr_scene:
        wlr_scene_tree tree

    wlr_scene *wlr_scene_create()
    void wlr_scene_node_destroy(wlr_scene_node *node)
    wlr_scene_tree *wlr_scene_xdg_surface_create(wlr_scene_tree *parent, wlr_xdg_surface *xdg_surface)
    wlr_scene_output *wlr_scene_output_create(wlr_scene *scene, wlr_output *output) nogil
    int wlr_scene_output_commit(wlr_scene_output *scene_output, const wlr_output_state *state) nogil


cdef extern from "wlr/backend.h":
    cdef struct wlr_backend_output_state:
        wlr_output *output
        wlr_output_state base

    ctypedef void wlr_backend_impl
    cdef struct wlr_backend_features:
        bint timeline
    cdef struct wlr_backend_events:
        wl_signal destroy
        wl_signal new_input
        wl_signal new_output

    cdef struct wlr_backend:
        wlr_backend_impl *impl
        uint32_t buffer_caps
        wlr_backend_features features
        wlr_backend_events events

    wlr_backend *wlr_backend_autocreate(wl_event_loop *loop, wlr_session **session_ptr)
    bint wlr_backend_start(wlr_backend *backend)
    void wlr_backend_destroy(wlr_backend *backend)
    int wlr_backend_get_drm_fd(wlr_backend *backend)
    bint wlr_backend_test(wlr_backend *backend, const wlr_backend_output_state *states, size_t states_len)
    bint wlr_backend_commit(wlr_backend *backend, const wlr_backend_output_state *states, size_t states_len)


cdef extern from "wlr/backend/multi.h":
    bint wlr_backend_is_multi(wlr_backend *backend)
    void wlr_multi_backend_add(wlr_backend *multi, wlr_backend *backend)
    void wlr_multi_backend_remove(wlr_backend *multi, wlr_backend *backend)


cdef extern from "wlr/backend/headless.h":
    wlr_backend *wlr_headless_backend_create(wl_event_loop *loop)
    wlr_output *wlr_headless_add_output(wlr_backend *backend, unsigned int width, unsigned int height)

cdef extern from "wlr/render/interface.h":
    cdef struct wlr_renderer_impl:
        const wlr_drm_format_set *(*get_texture_formats)(wlr_renderer *renderer, uint32_t buffer_caps)
        void (*destroy)(wlr_renderer *renderer)
        int (*get_drm_fd)(wlr_renderer *renderer)
        wlr_texture *(*texture_from_buffer)(wlr_renderer *renderer, wlr_buffer *buffer);
        wlr_render_pass *(*begin_buffer_pass)(wlr_renderer *renderer, wlr_buffer *buffer, const wlr_buffer_pass_options *options)
        wlr_render_timer *(*render_timer_create)(wlr_renderer *renderer)

    cdef struct wlr_render_timer_impl:
        int (*get_duration_ns)(wlr_render_timer *timer)
        void (*destroy)(wlr_render_timer *timer)

    cdef struct wlr_render_timer:
        const wlr_render_timer_impl *impl

    cdef struct wlr_texture_impl:
        bint (*update_from_buffer)(wlr_texture *texture, wlr_buffer *buffer, pixman_region32_t *damage)
        bint (*read_pixels)(wlr_texture *texture, const wlr_texture_read_pixels_options *options)
        uint32_t (*preferred_read_format)(wlr_texture *texture)
        void (*destroy)(wlr_texture *texture)


cdef extern from "wlr/render/wlr_renderer.h":
    ctypedef struct wlr_renderer:
        pass
    wlr_renderer *wlr_renderer_autocreate(wlr_backend *backend)
    void wlr_renderer_init_wl_display(wlr_renderer *renderer, wl_display *wl_display)
    void wlr_renderer_destroy(wlr_renderer *renderer)
    const wlr_drm_format_set *wlr_renderer_get_texture_formats(wlr_renderer *r, uint32_t buffer_caps)


cdef extern from "wlr/render/drm_format_set.h":
    cdef struct wlr_drm_format:
        uint32_t format
        size_t len
        size_t capacity
        uint64_t *modifiers

    cdef struct wlr_drm_format_set:
        size_t len
        size_t capacity
        wlr_drm_format *formats

    void wlr_drm_format_set_finish(wlr_drm_format_set *set)
    const wlr_drm_format *wlr_drm_format_set_get(const wlr_drm_format_set *set, uint32_t format)
    void wlr_drm_format_finish(wlr_drm_format *format)


cdef extern from "wlr/render/allocator.h":
    cdef struct wlr_allocator_interface:
        pass

    cdef struct wlr_allocator_events:
        wl_signal destroy

    cdef struct wlr_allocator:
        wlr_allocator_interface *impl
        uint32_t buffer_caps
        wlr_allocator_events events

    wlr_allocator *wlr_allocator_autocreate(wlr_backend *backend, wlr_renderer *renderer)
    void wlr_allocator_init(wlr_allocator *alloc, const wlr_allocator_interface *impl, uint32_t buffer_caps)
    void wlr_allocator_destroy(wlr_allocator *alloc)
    wlr_buffer *wlr_allocator_create_buffer(wlr_allocator *alloc, int width, int height, const wlr_drm_format *format)


cdef extern from "wlr/types/wlr_compositor.h":
    cdef enum wlr_surface_state_field:
        WLR_SURFACE_STATE_BUFFER
        WLR_SURFACE_STATE_SURFACE_DAMAGE
        WLR_SURFACE_STATE_BUFFER_DAMAGE
        WLR_SURFACE_STATE_OPAQUE_REGION
        WLR_SURFACE_STATE_INPUT_REGION
        WLR_SURFACE_STATE_TRANSFORM
        WLR_SURFACE_STATE_SCALE
        WLR_SURFACE_STATE_FRAME_CALLBACK_LIST
        WLR_SURFACE_STATE_VIEWPORT
        WLR_SURFACE_STATE_OFFSET
    ctypedef struct wlr_surface_state:
        uint32_t committed
        uint32_t seq
        wlr_buffer *buffer
        int32_t dx, dy
        pixman_region32_t surface_damage
        pixman_region32_t buffer_damage
        pixman_region32_t opaque
        pixman_region32_t input
        wl_output_transform transform
        int32_t scale
        wl_list frame_callback_list

        int width
        int height
        int buffer_width
        int buffer_height

        wl_list subsurfaces_below
        wl_list subsurfaces_above
    cdef struct wlr_compositor_events:
        wl_signal new_surface
        wl_signal destroy
    cdef struct wlr_compositor:
        # struct wl_global *global
        wlr_renderer *renderer
        wlr_compositor_events events

    cdef struct wlr_surface_role:
        const char *name
        bint no_object
        void (*client_commit)(wlr_surface *surface)
        void (*commit)(wlr_surface *surface)
        void (*map)(wlr_surface *surface)
        void (*unmap)(wlr_surface *surface)
        void (*destroy)(wlr_surface *surface)
    ctypedef struct wlr_surface_events:
        wl_signal client_commit
        wl_signal commit
        wl_signal map
        wl_signal unmap
        wl_signal new_subsurface
        wl_signal destroy
    cdef struct wlr_surface:
        #wl_resource resource
        wlr_compositor *compositor
        wlr_client_buffer *buffer
        pixman_region32_t buffer_damage
        pixman_region32_t opaque_region
        pixman_region32_t input_region
        wlr_surface_state current
        wlr_surface_state pending
        wl_list cached
        bint mapped
        wlr_surface_role *role
        #wl_resource *role_resource
        wlr_surface_events events
        wl_list current_outputs
        wlr_addon_set addons
        void *data

    ctypedef void (*wlr_surface_iterator_func_t)(wlr_surface *surface, int sx, int sy, void *user_data)
    void wlr_surface_for_each_surface(wlr_surface *surface, wlr_surface_iterator_func_t iterator, void *user_data)

    wlr_compositor *wlr_compositor_create(wl_display *display, int version, wlr_renderer *renderer)
    void wlr_surface_send_frame_done(wlr_surface *surface, const timespec *when)


cdef extern from "wlr/types/wlr_subcompositor.h":

    cdef struct wlr_subsurface_parent_state:
        int32_t x
        int32_t y
        wl_list link

    cdef struct wlr_subsurface_events:
        wl_signal destroy

    cdef struct wlr_subsurface:
        wl_resource *resource
        wlr_surface *surface
        wlr_surface *parent

        wlr_subsurface_parent_state current
        wlr_subsurface_parent_state pending

        uint32_t cached_seq
        bint has_cache

        bint synchronized
        bint added

        wlr_subsurface_events events

        void *data

    cdef struct wlr_subcompositor_events:
        wl_signal destroy

    cdef struct wlr_subcompositor:
        # wl_global *global
        wlr_subcompositor_events events

    wlr_subcompositor *wlr_subcompositor_create(wl_display *display)


cdef extern from "wlr/types/wlr_data_device.h":
    ctypedef struct wlr_data_device_manager:
        pass
    wlr_data_device_manager *wlr_data_device_manager_create(wl_display *display)
