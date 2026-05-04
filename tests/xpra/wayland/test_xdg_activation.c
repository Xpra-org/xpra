/*
 * Minimal xdg-activation-v1 test client.
 *
 * Build from the repository root:
 *
 *   wayland-scanner client-header /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml /tmp/xdg-shell-protocol.c
 *   wayland-scanner client-header /usr/share/wayland-protocols/staging/xdg-activation/xdg-activation-v1.xml /tmp/xdg-activation-v1-client-protocol.h
 *   wayland-scanner private-code /usr/share/wayland-protocols/staging/xdg-activation/xdg-activation-v1.xml /tmp/xdg-activation-v1-protocol.c
 *   cc -Wall -Wextra -I/tmp -o /tmp/test-xdg-activation ./test_xdg_activation.c /tmp/xdg-shell-protocol.c /tmp/xdg-activation-v1-protocol.c $(pkg-config --cflags --libs wayland-client)
 *
 * Run inside the Wayland session:
 *
 *   /tmp/test-xdg-activation
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "xdg-activation-v1-client-protocol.h"

struct client_state {
    struct wl_display *display;
    struct wl_compositor *compositor;
    struct wl_surface *surface;
    struct xdg_wm_base *wm_base;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *xdg_toplevel;
    struct xdg_activation_v1 *activation;
    char *token;
    bool configured;
    bool activated;
};

static void
wm_base_ping(void *data, struct xdg_wm_base *wm_base, uint32_t serial)
{
    (void)data;
    xdg_wm_base_pong(wm_base, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = {
    .ping = wm_base_ping,
};

static void
xdg_surface_configure(void *data, struct xdg_surface *xdg_surface, uint32_t serial)
{
    struct client_state *state = data;
    xdg_surface_ack_configure(xdg_surface, serial);
    state->configured = true;
}

static const struct xdg_surface_listener xdg_surface_listener = {
    .configure = xdg_surface_configure,
};

static void
token_done(void *data, struct xdg_activation_token_v1 *token, const char *token_name)
{
    struct client_state *state = data;
    free(state->token);
    state->token = strdup(token_name);
    xdg_activation_token_v1_destroy(token);
    fprintf(stderr, "activation token: %s\n", state->token);
}

static const struct xdg_activation_token_v1_listener token_listener = {
    .done = token_done,
};

static void
registry_global(void *data, struct wl_registry *registry, uint32_t name,
                const char *interface, uint32_t version)
{
    struct client_state *state = data;

    if (strcmp(interface, wl_compositor_interface.name) == 0) {
        state->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
    } else if (strcmp(interface, xdg_wm_base_interface.name) == 0) {
        state->wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(state->wm_base, &wm_base_listener, state);
    } else if (strcmp(interface, xdg_activation_v1_interface.name) == 0) {
        state->activation = wl_registry_bind(registry, name, &xdg_activation_v1_interface, 1);
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
    xdg_toplevel_set_title(state->xdg_toplevel, "xdg activation test");
    xdg_toplevel_set_app_id(state->xdg_toplevel, "xpra-xdg-activation-test");
    wl_surface_commit(state->surface);
}

static void
request_token(struct client_state *state)
{
    struct xdg_activation_token_v1 *token;

    token = xdg_activation_v1_get_activation_token(state->activation);
    xdg_activation_token_v1_set_app_id(token, "xpra-xdg-activation-test");
    if (state->surface) {
        xdg_activation_token_v1_set_surface(token, state->surface);
    }
    xdg_activation_token_v1_add_listener(token, &token_listener, state);
    xdg_activation_token_v1_commit(token);
}

static void
activate(struct client_state *state)
{
    xdg_activation_v1_activate(state->activation, state->token, state->surface);
    wl_surface_commit(state->surface);
    state->activated = true;
    fprintf(stderr, "sent xdg_activation_v1.activate\n");
}

int
main(void)
{
    struct client_state state = {0};
    struct wl_registry *registry;

    state.display = wl_display_connect(NULL);
    if (!state.display) {
        fprintf(stderr, "failed to connect to Wayland display\n");
        return 1;
    }

    registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(registry, &registry_listener, &state);
    wl_display_roundtrip(state.display);

    if (!state.compositor || !state.wm_base || !state.activation) {
        fprintf(stderr, "missing globals: compositor=%p xdg_wm_base=%p xdg_activation_v1=%p\n",
                (void *)state.compositor, (void *)state.wm_base, (void *)state.activation);
        return 1;
    }

    create_window(&state);
    wl_display_roundtrip(state.display);
    request_token(&state);

    while (wl_display_dispatch(state.display) != -1) {
        if (state.token && state.configured && !state.activated) {
            activate(&state);
            wl_display_flush(state.display);
        }
        if (state.activated) {
            break;
        }
    }

    wl_display_roundtrip(state.display);
    free(state.token);
    return 0;
}
