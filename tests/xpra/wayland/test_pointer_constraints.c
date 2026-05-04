/*
 * Minimal zwp_pointer_constraints_v1 + zwp_relative_pointer_manager_v1 test.
 *
 * Build from the repository root:
 *
 *   wayland-scanner client-header /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-protocol.c
 *   wayland-scanner client-header /usr/share/wayland-protocols/unstable/relative-pointer/relative-pointer-unstable-v1.xml /tmp/relative-pointer-unstable-v1-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/unstable/relative-pointer/relative-pointer-unstable-v1.xml /tmp/relative-pointer-unstable-v1-protocol.c
 *   wayland-scanner client-header /usr/share/wayland-protocols/unstable/pointer-constraints/pointer-constraints-unstable-v1.xml /tmp/pointer-constraints-unstable-v1-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/unstable/pointer-constraints/pointer-constraints-unstable-v1.xml /tmp/pointer-constraints-unstable-v1-protocol.c
 *   cc -Wall -Wextra -I/tmp -o /tmp/test-pointer-constraints tests/xpra/wayland/test_pointer_constraints.c /tmp/xdg-shell-protocol.c /tmp/relative-pointer-unstable-v1-protocol.c /tmp/pointer-constraints-unstable-v1-protocol.c $(pkg-config --cflags --libs wayland-client)
 *
 * Run inside the Wayland session:
 *
 *   /tmp/test-pointer-constraints
 *   /tmp/test-pointer-constraints --confine
 */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "relative-pointer-unstable-v1-client-protocol.h"
#include "pointer-constraints-unstable-v1-client-protocol.h"

#define WIDTH  640
#define HEIGHT 360

struct client_state {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct wl_seat *seat;
    struct wl_pointer *pointer;
    struct wl_surface *surface;
    struct wl_buffer *buffer;
    struct xdg_wm_base *wm_base;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *xdg_toplevel;
    struct zwp_relative_pointer_manager_v1 *relative_pointer_manager;
    struct zwp_relative_pointer_v1 *relative_pointer;
    struct zwp_pointer_constraints_v1 *pointer_constraints;
    struct zwp_locked_pointer_v1 *locked_pointer;
    struct zwp_confined_pointer_v1 *confined_pointer;
    bool configured;
    bool constraint_requested;
    bool confine;
};

static int
create_shm_file(size_t size)
{
    char name[] = "/xpra-pointer-constraints-XXXXXX";
    int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
    if (fd < 0) {
        perror("shm_open");
        return -1;
    }
    shm_unlink(name);
    if (ftruncate(fd, (off_t)size) < 0) {
        perror("ftruncate");
        close(fd);
        return -1;
    }
    return fd;
}

static struct wl_buffer *
create_buffer(struct client_state *state)
{
    const int stride = WIDTH * 4;
    const int size = stride * HEIGHT;
    int fd = create_shm_file((size_t)size);
    if (fd < 0) {
        return NULL;
    }

    uint32_t *pixels = mmap(NULL, (size_t)size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (pixels == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return NULL;
    }

    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            uint8_t r = (uint8_t)(40 + (x * 160 / WIDTH));
            uint8_t g = (uint8_t)(80 + (y * 120 / HEIGHT));
            uint8_t b = 0x90;
            pixels[y * WIDTH + x] = 0xff000000u | ((uint32_t)r << 16) | ((uint32_t)g << 8) | b;
        }
    }

    struct wl_shm_pool *pool = wl_shm_create_pool(state->shm, fd, size);
    struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, WIDTH, HEIGHT, stride, WL_SHM_FORMAT_XRGB8888);
    wl_shm_pool_destroy(pool);
    munmap(pixels, (size_t)size);
    close(fd);
    return buffer;
}

static void
wm_base_ping(void *data, struct xdg_wm_base *wm_base, uint32_t serial)
{
    (void)data;
    xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
    .ping = wm_base_ping,
};

static void request_constraint(struct client_state *state);

static void
xdg_surface_configure(void *data, struct xdg_surface *xdg_surface, uint32_t serial)
{
    struct client_state *state = data;
    xdg_surface_ack_configure(xdg_surface, serial);
    if (!state->buffer) {
        state->buffer = create_buffer(state);
    }
    wl_surface_attach(state->surface, state->buffer, 0, 0);
    wl_surface_commit(state->surface);
    state->configured = true;
    request_constraint(state);
}

static const struct xdg_surface_listener xdg_surface_listener = {
    .configure = xdg_surface_configure,
};

static void
relative_motion(void *data, struct zwp_relative_pointer_v1 *relative_pointer,
                uint32_t utime_hi, uint32_t utime_lo,
                wl_fixed_t dx, wl_fixed_t dy, wl_fixed_t dx_unaccel, wl_fixed_t dy_unaccel)
{
    (void)data;
    (void)relative_pointer;
    uint64_t usec = ((uint64_t)utime_hi << 32) | utime_lo;
    fprintf(stderr, "relative motion time=%llu dx=%.2f dy=%.2f unaccel=%.2f,%.2f\n",
            (unsigned long long)usec,
            wl_fixed_to_double(dx), wl_fixed_to_double(dy),
            wl_fixed_to_double(dx_unaccel), wl_fixed_to_double(dy_unaccel));
}

static const struct zwp_relative_pointer_v1_listener relative_pointer_listener = {
    .relative_motion = relative_motion,
};

static void
locked(void *data, struct zwp_locked_pointer_v1 *locked_pointer)
{
    (void)data;
    (void)locked_pointer;
    fprintf(stderr, "locked pointer activated\n");
}

static void
unlocked(void *data, struct zwp_locked_pointer_v1 *locked_pointer)
{
    (void)data;
    (void)locked_pointer;
    fprintf(stderr, "locked pointer deactivated\n");
}

static const struct zwp_locked_pointer_v1_listener locked_pointer_listener = {
    .locked = locked,
    .unlocked = unlocked,
};

static void
confined(void *data, struct zwp_confined_pointer_v1 *confined_pointer)
{
    (void)data;
    (void)confined_pointer;
    fprintf(stderr, "confined pointer activated\n");
}

static void
unconfined(void *data, struct zwp_confined_pointer_v1 *confined_pointer)
{
    (void)data;
    (void)confined_pointer;
    fprintf(stderr, "confined pointer deactivated\n");
}

static const struct zwp_confined_pointer_v1_listener confined_pointer_listener = {
    .confined = confined,
    .unconfined = unconfined,
};

static void
request_constraint(struct client_state *state)
{
    if (state->constraint_requested || !state->configured || !state->pointer ||
        !state->relative_pointer_manager || !state->pointer_constraints) {
        return;
    }
    state->constraint_requested = true;
    state->relative_pointer = zwp_relative_pointer_manager_v1_get_relative_pointer(
        state->relative_pointer_manager, state->pointer);
    zwp_relative_pointer_v1_add_listener(state->relative_pointer, &relative_pointer_listener, state);

    if (state->confine) {
        state->confined_pointer = zwp_pointer_constraints_v1_confine_pointer(
            state->pointer_constraints, state->surface, state->pointer, NULL,
            ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
        zwp_confined_pointer_v1_add_listener(state->confined_pointer, &confined_pointer_listener, state);
        fprintf(stderr, "requested confined pointer\n");
    } else {
        state->locked_pointer = zwp_pointer_constraints_v1_lock_pointer(
            state->pointer_constraints, state->surface, state->pointer, NULL,
            ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
        zwp_locked_pointer_v1_add_listener(state->locked_pointer, &locked_pointer_listener, state);
        fprintf(stderr, "requested locked pointer\n");
    }
    wl_display_flush(state->display);
}

static void
pointer_enter(void *data, struct wl_pointer *pointer, uint32_t serial,
              struct wl_surface *surface, wl_fixed_t sx, wl_fixed_t sy)
{
    (void)pointer;
    (void)serial;
    (void)surface;
    fprintf(stderr, "pointer enter %.2f,%.2f\n", wl_fixed_to_double(sx), wl_fixed_to_double(sy));
    request_constraint(data);
}

static void
pointer_leave(void *data, struct wl_pointer *pointer, uint32_t serial, struct wl_surface *surface)
{
    (void)data;
    (void)pointer;
    (void)serial;
    (void)surface;
    fprintf(stderr, "pointer leave\n");
}

static void
pointer_motion(void *data, struct wl_pointer *pointer, uint32_t time, wl_fixed_t sx, wl_fixed_t sy)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer motion time=%u %.2f,%.2f\n", time, wl_fixed_to_double(sx), wl_fixed_to_double(sy));
}

static void
pointer_button(void *data, struct wl_pointer *pointer, uint32_t serial, uint32_t time, uint32_t button, uint32_t state)
{
    (void)data;
    (void)pointer;
    (void)serial;
    fprintf(stderr, "pointer button time=%u button=%u state=%u\n", time, button, state);
}

static void
pointer_axis(void *data, struct wl_pointer *pointer, uint32_t time, uint32_t axis, wl_fixed_t value)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis time=%u axis=%u value=%.2f\n", time, axis, wl_fixed_to_double(value));
}

static void
pointer_frame(void *data, struct wl_pointer *pointer)
{
    (void)data;
    (void)pointer;
}

static void
pointer_axis_source(void *data, struct wl_pointer *pointer, uint32_t axis_source)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis source=%u\n", axis_source);
}

static void
pointer_axis_stop(void *data, struct wl_pointer *pointer, uint32_t time, uint32_t axis)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis stop time=%u axis=%u\n", time, axis);
}

static void
pointer_axis_discrete(void *data, struct wl_pointer *pointer, uint32_t axis, int32_t discrete)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis discrete axis=%u discrete=%d\n", axis, discrete);
}

static void
pointer_axis_value120(void *data, struct wl_pointer *pointer, uint32_t axis, int32_t value120)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis value120 axis=%u value120=%d\n", axis, value120);
}

static void
pointer_axis_relative_direction(void *data, struct wl_pointer *pointer, uint32_t axis, uint32_t direction)
{
    (void)data;
    (void)pointer;
    fprintf(stderr, "pointer axis relative direction axis=%u direction=%u\n", axis, direction);
}

static const struct wl_pointer_listener pointer_listener = {
    .enter = pointer_enter,
    .leave = pointer_leave,
    .motion = pointer_motion,
    .button = pointer_button,
    .axis = pointer_axis,
    .frame = pointer_frame,
    .axis_source = pointer_axis_source,
    .axis_stop = pointer_axis_stop,
    .axis_discrete = pointer_axis_discrete,
    .axis_value120 = pointer_axis_value120,
    .axis_relative_direction = pointer_axis_relative_direction,
};

static void
seat_capabilities(void *data, struct wl_seat *seat, uint32_t capabilities)
{
    struct client_state *state = data;
    if ((capabilities & WL_SEAT_CAPABILITY_POINTER) && !state->pointer) {
        state->pointer = wl_seat_get_pointer(seat);
        wl_pointer_add_listener(state->pointer, &pointer_listener, state);
        request_constraint(state);
    }
}

static void
seat_name(void *data, struct wl_seat *seat, const char *name)
{
    (void)data;
    (void)seat;
    fprintf(stderr, "seat name: %s\n", name);
}

static const struct wl_seat_listener seat_listener = {
    .capabilities = seat_capabilities,
    .name = seat_name,
};

static void
registry_global(void *data, struct wl_registry *registry, uint32_t name,
                const char *interface, uint32_t version)
{
    struct client_state *state = data;

    if (strcmp(interface, wl_compositor_interface.name) == 0) {
        state->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
    } else if (strcmp(interface, wl_shm_interface.name) == 0) {
        state->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
    } else if (strcmp(interface, wl_seat_interface.name) == 0) {
        state->seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 5 ? version : 5);
        wl_seat_add_listener(state->seat, &seat_listener, state);
    } else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
        state->wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(state->wm_base, &wm_base_listener, state);
    } else if (strcmp(interface, zwp_relative_pointer_manager_v1_interface.name) == 0) {
        state->relative_pointer_manager = wl_registry_bind(
            registry, name, &zwp_relative_pointer_manager_v1_interface, 1);
    } else if (strcmp(interface, zwp_pointer_constraints_v1_interface.name) == 0) {
        state->pointer_constraints = wl_registry_bind(
            registry, name, &zwp_pointer_constraints_v1_interface, 1);
    }
}

static void
registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove,
};

static void
create_window(struct client_state *state)
{
    state->surface = wl_compositor_create_surface(state->compositor);
    state->xdg_surface = xdg_wm_base_get_xdg_surface(state->wm_base, state->surface);
    xdg_surface_add_listener(state->xdg_surface, &xdg_surface_listener, state);
    state->xdg_toplevel = xdg_surface_get_toplevel(state->xdg_surface);
    xdg_toplevel_set_title(state->xdg_toplevel, "pointer constraints test");
    xdg_toplevel_set_app_id(state->xdg_toplevel, "xpra-pointer-constraints-test");
    wl_surface_commit(state->surface);
}

static void
cleanup(struct client_state *state)
{
    if (state->locked_pointer) {
        zwp_locked_pointer_v1_destroy(state->locked_pointer);
    }
    if (state->confined_pointer) {
        zwp_confined_pointer_v1_destroy(state->confined_pointer);
    }
    if (state->relative_pointer) {
        zwp_relative_pointer_v1_destroy(state->relative_pointer);
    }
    if (state->pointer) {
        wl_pointer_destroy(state->pointer);
    }
    if (state->buffer) {
        wl_buffer_destroy(state->buffer);
    }
    if (state->xdg_toplevel) {
        xdg_toplevel_destroy(state->xdg_toplevel);
    }
    if (state->xdg_surface) {
        xdg_surface_destroy(state->xdg_surface);
    }
    if (state->surface) {
        wl_surface_destroy(state->surface);
    }
    if (state->pointer_constraints) {
        zwp_pointer_constraints_v1_destroy(state->pointer_constraints);
    }
    if (state->relative_pointer_manager) {
        zwp_relative_pointer_manager_v1_destroy(state->relative_pointer_manager);
    }
    if (state->seat) {
        wl_seat_destroy(state->seat);
    }
    if (state->wm_base) {
        xdg_wm_base_destroy(state->wm_base);
    }
    if (state->shm) {
        wl_shm_destroy(state->shm);
    }
    if (state->compositor) {
        wl_compositor_destroy(state->compositor);
    }
    if (state->registry) {
        wl_registry_destroy(state->registry);
    }
}

int
main(int argc, char **argv)
{
    struct client_state state = {0};
    state.confine = argc > 1 && strcmp(argv[1], "--confine") == 0;

    state.display = wl_display_connect(NULL);
    if (!state.display) {
        fprintf(stderr, "failed to connect to Wayland display\n");
        return 1;
    }

    state.registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(state.registry, &registry_listener, &state);
    wl_display_roundtrip(state.display);
    wl_display_roundtrip(state.display);

    if (!state.compositor || !state.shm || !state.seat || !state.pointer ||
        !state.wm_base || !state.relative_pointer_manager || !state.pointer_constraints) {
        fprintf(stderr, "missing globals: compositor=%p shm=%p seat=%p pointer=%p xdg_wm_base=%p relative=%p constraints=%p\n",
                (void *)state.compositor, (void *)state.shm, (void *)state.seat, (void *)state.pointer,
                (void *)state.wm_base, (void *)state.relative_pointer_manager, (void *)state.pointer_constraints);
        cleanup(&state);
        wl_display_disconnect(state.display);
        return 1;
    }

    create_window(&state);

    while (wl_display_dispatch(state.display) != -1) {
    }

    cleanup(&state);
    wl_display_disconnect(state.display);
    return 0;
}
