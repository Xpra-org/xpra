/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 *
 * Minimal wp_viewporter test client.
 *
 * Build from the repository root:
 *
 *   wayland-scanner client-header /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-protocol.c
 *   wayland-scanner client-header /usr/share/wayland-protocols/stable/viewporter/viewporter.xml /tmp/viewporter-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/stable/viewporter/viewporter.xml /tmp/viewporter-protocol.c
 *   cc -Wall -Wextra -I/tmp -o /tmp/test-wayland-viewporter tests/xpra/test_apps/test_wayland_viewporter.c /tmp/xdg-shell-protocol.c /tmp/viewporter-protocol.c $(pkg-config --cflags --libs wayland-client)
 *
 * Run inside the Wayland session:
 *
 *   WAYLAND_DEBUG=1 /tmp/test-wayland-viewporter
 *   WAYLAND_DEBUG=1 /tmp/test-wayland-viewporter --subsurface
 *   WAYLAND_DEBUG=1 /tmp/test-wayland-viewporter --scale 2.0
 *   WAYLAND_DEBUG=1 /tmp/test-wayland-viewporter --upscale --subsurface
 *   WAYLAND_DEBUG=1 /tmp/test-wayland-viewporter --native 800x450 --destination 200x112
 */

#define _GNU_SOURCE

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "viewporter-client-protocol.h"

#define DEFAULT_NATIVE_W 640
#define DEFAULT_NATIVE_H 360
#define DEFAULT_DEST_W   320
#define DEFAULT_DEST_H   180

struct buffer {
    struct wl_buffer *wl_buffer;
    void *data;
    size_t size;
    int width;
    int height;
};

struct client_state {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct wl_subcompositor *subcompositor;
    struct wp_viewporter *viewporter;
    struct wl_surface *surface;
    struct xdg_wm_base *wm_base;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *xdg_toplevel;
    struct wl_surface *child_surface;
    struct wl_subsurface *subsurface;
    struct wp_viewport *viewport;
    struct buffer parent_buffer;
    struct buffer native_buffer;
    int configured;
    int use_subsurface;
    int native_width;
    int native_height;
    int dest_width;
    int dest_height;
};

static int
create_tmpfile(size_t size)
{
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    char template[256];
    int fd;

    if (!runtime) {
        fprintf(stderr, "XDG_RUNTIME_DIR is not set\n");
        return -1;
    }
    snprintf(template, sizeof(template), "%s/xpra-viewporter-XXXXXX", runtime);
    fd = mkstemp(template);
    if (fd < 0) {
        fprintf(stderr, "mkstemp failed: %s\n", strerror(errno));
        return -1;
    }
    unlink(template);
    if (ftruncate(fd, (off_t) size) < 0) {
        fprintf(stderr, "ftruncate failed: %s\n", strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

static int
create_buffer(struct client_state *state, struct buffer *buffer, int width, int height)
{
    struct wl_shm_pool *pool;
    int stride = width * 4;
    int fd;

    buffer->width = width;
    buffer->height = height;
    buffer->size = (size_t) stride * height;
    fd = create_tmpfile(buffer->size);
    if (fd < 0) {
        return -1;
    }
    buffer->data = mmap(NULL, buffer->size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (buffer->data == MAP_FAILED) {
        fprintf(stderr, "mmap failed: %s\n", strerror(errno));
        close(fd);
        return -1;
    }
    pool = wl_shm_create_pool(state->shm, fd, (int) buffer->size);
    buffer->wl_buffer = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_ARGB8888);
    wl_shm_pool_destroy(pool);
    close(fd);
    return 0;
}

static void
fill_checker(struct buffer *buffer, uint32_t c1, uint32_t c2)
{
    uint32_t *pixels = buffer->data;

    for (int y = 0; y < buffer->height; y++) {
        for (int x = 0; x < buffer->width; x++) {
            int checker = ((x / 32) ^ (y / 32)) & 1;
            pixels[y * buffer->width + x] = checker ? c1 : c2;
        }
    }
}

static void
destroy_buffer(struct buffer *buffer)
{
    if (buffer->wl_buffer) {
        wl_buffer_destroy(buffer->wl_buffer);
    }
    if (buffer->data && buffer->data != MAP_FAILED) {
        munmap(buffer->data, buffer->size);
    }
    memset(buffer, 0, sizeof(*buffer));
}

static void
wm_base_ping(void *data, struct xdg_wm_base *wm_base, uint32_t serial)
{
    (void) data;
    xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
    .ping = wm_base_ping,
};

static void
draw(struct client_state *state)
{
    int native_w = state->native_width;
    int native_h = state->native_height;
    int dest_w = state->dest_width;
    int dest_h = state->dest_height;

    if (state->use_subsurface) {
        if (create_buffer(state, &state->parent_buffer, dest_w + 40, dest_h + 40) < 0 ||
            create_buffer(state, &state->native_buffer, native_w, native_h) < 0) {
            exit(1);
        }
        fill_checker(&state->parent_buffer, 0xff303030, 0xff505050);
        fill_checker(&state->native_buffer, 0xff0050c8, 0xffffd040);

        state->child_surface = wl_compositor_create_surface(state->compositor);
        state->subsurface = wl_subcompositor_get_subsurface(state->subcompositor,
                                                            state->child_surface, state->surface);
        wl_subsurface_set_position(state->subsurface, 20, 20);
        state->viewport = wp_viewporter_get_viewport(state->viewporter, state->child_surface);
        wp_viewport_set_destination(state->viewport, dest_w, dest_h);

        wl_surface_attach(state->surface, state->parent_buffer.wl_buffer, 0, 0);
        wl_surface_damage(state->surface, 0, 0, dest_w + 40, dest_h + 40);
        wl_surface_attach(state->child_surface, state->native_buffer.wl_buffer, 0, 0);
        wl_surface_damage(state->child_surface, 0, 0, dest_w, dest_h);
        wl_surface_commit(state->child_surface);
        wl_surface_commit(state->surface);
        fprintf(stderr, "subsurface viewport: native=%dx%d destination=%dx%d\n",
                native_w, native_h, dest_w, dest_h);
    } else {
        if (create_buffer(state, &state->native_buffer, native_w, native_h) < 0) {
            exit(1);
        }
        fill_checker(&state->native_buffer, 0xff00a060, 0xfff0f0f0);
        state->viewport = wp_viewporter_get_viewport(state->viewporter, state->surface);
        wp_viewport_set_destination(state->viewport, dest_w, dest_h);
        wl_surface_attach(state->surface, state->native_buffer.wl_buffer, 0, 0);
        wl_surface_damage(state->surface, 0, 0, dest_w, dest_h);
        wl_surface_commit(state->surface);
        fprintf(stderr, "toplevel viewport: native=%dx%d destination=%dx%d\n",
                native_w, native_h, dest_w, dest_h);
    }
}

static void
xdg_surface_configure(void *data, struct xdg_surface *xdg_surface, uint32_t serial)
{
    struct client_state *state = data;

    xdg_surface_ack_configure(xdg_surface, serial);
    if (!state->configured) {
        state->configured = 1;
        draw(state);
    }
}

static const struct xdg_surface_listener xdg_surface_listener = {
    .configure = xdg_surface_configure,
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
    } else if (strcmp(interface, wl_subcompositor_interface.name) == 0) {
        state->subcompositor = wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
    } else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
        state->wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(state->wm_base, &wm_base_listener, state);
    } else if (strcmp(interface, wp_viewporter_interface.name) == 0) {
        state->viewporter = wl_registry_bind(registry, name, &wp_viewporter_interface, 1);
    }
}

static void
registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
    (void) data;
    (void) registry;
    (void) name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove,
};

static int
parse_size(const char *value, int *width, int *height)
{
    char *end = NULL;
    long w;
    long h;

    errno = 0;
    w = strtol(value, &end, 10);
    if (errno || end == value || (*end != 'x' && *end != 'X')) {
        return -1;
    }
    value = end + 1;
    errno = 0;
    h = strtol(value, &end, 10);
    if (errno || end == value || *end != '\0' || w <= 0 || h <= 0 || w > 16384 || h > 16384) {
        return -1;
    }
    *width = (int) w;
    *height = (int) h;
    return 0;
}

static void
usage(const char *argv0)
{
    fprintf(stderr,
            "Usage: %s [--subsurface] [--native WxH] [--destination WxH]\n"
            "       %s [--subsurface] [--scale FACTOR] [--upscale|--downscale]\n"
            "\n"
            "Defaults: native=%dx%d destination=%dx%d\n"
            "  --scale FACTOR  destination = native * FACTOR\n"
            "  --downscale     native=%dx%d destination=%dx%d\n"
            "  --upscale       native=%dx%d destination=%dx%d\n",
            argv0, argv0,
            DEFAULT_NATIVE_W, DEFAULT_NATIVE_H, DEFAULT_DEST_W, DEFAULT_DEST_H,
            DEFAULT_NATIVE_W, DEFAULT_NATIVE_H, DEFAULT_DEST_W, DEFAULT_DEST_H,
            DEFAULT_DEST_W, DEFAULT_DEST_H, DEFAULT_NATIVE_W, DEFAULT_NATIVE_H);
}

static int
parse_args(struct client_state *state, int argc, char **argv)
{
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--subsurface") == 0) {
            state->use_subsurface = 1;
        } else if (strcmp(argv[i], "--downscale") == 0) {
            state->native_width = DEFAULT_NATIVE_W;
            state->native_height = DEFAULT_NATIVE_H;
            state->dest_width = DEFAULT_DEST_W;
            state->dest_height = DEFAULT_DEST_H;
        } else if (strcmp(argv[i], "--upscale") == 0) {
            state->native_width = DEFAULT_DEST_W;
            state->native_height = DEFAULT_DEST_H;
            state->dest_width = DEFAULT_NATIVE_W;
            state->dest_height = DEFAULT_NATIVE_H;
        } else if (strcmp(argv[i], "--native") == 0) {
            if (++i >= argc || parse_size(argv[i], &state->native_width, &state->native_height) < 0) {
                fprintf(stderr, "invalid --native size\n");
                return -1;
            }
        } else if (strcmp(argv[i], "--destination") == 0) {
            if (++i >= argc || parse_size(argv[i], &state->dest_width, &state->dest_height) < 0) {
                fprintf(stderr, "invalid --destination size\n");
                return -1;
            }
        } else if (strcmp(argv[i], "--scale") == 0) {
            char *end = NULL;
            double scale;

            if (++i >= argc) {
                fprintf(stderr, "missing --scale value\n");
                return -1;
            }
            errno = 0;
            scale = strtod(argv[i], &end);
            if (errno || end == argv[i] || *end != '\0' || scale <= 0.0 || scale > 16.0) {
                fprintf(stderr, "invalid --scale value\n");
                return -1;
            }
            state->dest_width = (int) (state->native_width * scale + 0.5);
            state->dest_height = (int) (state->native_height * scale + 0.5);
            if (state->dest_width <= 0) {
                state->dest_width = 1;
            }
            if (state->dest_height <= 0) {
                state->dest_height = 1;
            }
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            usage(argv[0]);
            return 1;
        } else {
            fprintf(stderr, "unknown option: %s\n", argv[i]);
            return -1;
        }
    }
    return 0;
}

static void
cleanup(struct client_state *state)
{
    if (state->viewport) {
        wp_viewport_destroy(state->viewport);
    }
    if (state->subsurface) {
        wl_subsurface_destroy(state->subsurface);
    }
    if (state->child_surface) {
        wl_surface_destroy(state->child_surface);
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
    destroy_buffer(&state->native_buffer);
    destroy_buffer(&state->parent_buffer);
    if (state->viewporter) {
        wp_viewporter_destroy(state->viewporter);
    }
    if (state->subcompositor) {
        wl_subcompositor_destroy(state->subcompositor);
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
    if (state->display) {
        wl_display_disconnect(state->display);
    }
}

int
main(int argc, char **argv)
{
    struct client_state state = {0};
    int parse_result;

    state.native_width = DEFAULT_NATIVE_W;
    state.native_height = DEFAULT_NATIVE_H;
    state.dest_width = DEFAULT_DEST_W;
    state.dest_height = DEFAULT_DEST_H;
    parse_result = parse_args(&state, argc, argv);
    if (parse_result != 0) {
        return parse_result > 0 ? 0 : 1;
    }
    fprintf(stderr, "viewporter test: native=%dx%d destination=%dx%d mode=%s\n",
            state.native_width, state.native_height, state.dest_width, state.dest_height,
            state.use_subsurface ? "subsurface" : "toplevel");
    state.display = wl_display_connect(NULL);
    if (!state.display) {
        fprintf(stderr, "failed to connect to Wayland display\n");
        return 1;
    }
    state.registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(state.registry, &registry_listener, &state);
    wl_display_roundtrip(state.display);

    if (!state.compositor || !state.shm || !state.wm_base || !state.viewporter ||
        (state.use_subsurface && !state.subcompositor)) {
        fprintf(stderr, "missing globals: compositor=%p shm=%p xdg_wm_base=%p viewporter=%p subcompositor=%p\n",
                (void *) state.compositor, (void *) state.shm, (void *) state.wm_base,
                (void *) state.viewporter, (void *) state.subcompositor);
        cleanup(&state);
        return 1;
    }

    state.surface = wl_compositor_create_surface(state.compositor);
    state.xdg_surface = xdg_wm_base_get_xdg_surface(state.wm_base, state.surface);
    xdg_surface_add_listener(state.xdg_surface, &xdg_surface_listener, &state);
    state.xdg_toplevel = xdg_surface_get_toplevel(state.xdg_surface);
    xdg_toplevel_set_title(state.xdg_toplevel, state.use_subsurface ?
                           "viewporter subsurface test" : "viewporter toplevel test");
    xdg_toplevel_set_app_id(state.xdg_toplevel, "xpra-wayland-viewporter-test");
    wl_surface_commit(state.surface);

    while (wl_display_dispatch(state.display) != -1) {
    }

    cleanup(&state);
    return 0;
}
