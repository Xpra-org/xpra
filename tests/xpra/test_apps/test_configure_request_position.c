/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 *
 * Reproducer: application sets WM_NORMAL_HINTS with StaticGravity and sends a
 * post-map ConfigureRequest to insist on a remembered screen position.
 *
 * Build:
 *   gcc -O0 -g test_configure_request_position.c -lX11 -o test_configure_request_position
 *
 * Run under xpra to observe ConfigureRequest handling:
 *   xpra start :10 --start=./test_configure_request_position -d window
 */

#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define TARGET_X  1853
#define TARGET_Y   798
#define WIDTH      299
#define HEIGHT     203
#define MIN_W      100
#define MIN_H       18

static void sleep_ms(int ms)
{
    struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

int main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "Cannot open display\n");
        return 1;
    }

    int screen   = DefaultScreen(dpy);
    Window root  = RootWindow(dpy, screen);

    Window win = XCreateSimpleWindow(dpy, root,
                                     TARGET_X, TARGET_Y, WIDTH, HEIGHT, 1,
                                     BlackPixel(dpy, screen),
                                     WhitePixel(dpy, screen));

    /* WM_NORMAL_HINTS: saved position + size + min_size + StaticGravity */
    XSizeHints hints;
    memset(&hints, 0, sizeof(hints));
    hints.flags       = USPosition | PPosition | USSize | PSize | PMinSize | PWinGravity;
    hints.x           = TARGET_X;
    hints.y           = TARGET_Y;
    hints.width       = WIDTH;
    hints.height      = HEIGHT;
    hints.min_width   = MIN_W;
    hints.min_height  = MIN_H;
    hints.win_gravity = StaticGravity;   /* = 10 */
    XSetWMNormalHints(dpy, win, &hints);

    /* WM_NAME */
    XStoreName(dpy, win, "ConfigureRequest StaticGravity reproducer");

    /* _NET_WM_WINDOW_TYPE = [DIALOG, _KDEOVERRIDE, NORMAL] */
    Atom net_wm_type = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE", False);
    Atom types[3];
    types[0] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_DIALOG",       False);
    types[1] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE__KDEOVERRIDE", False);
    types[2] = XInternAtom(dpy, "_NET_WM_WINDOW_TYPE_NORMAL",       False);
    XChangeProperty(dpy, win, net_wm_type, XA_ATOM, 32, PropModeReplace,
                    (unsigned char *)types, 3);

    /* WM_DELETE_WINDOW protocol so we can catch close */
    Atom wm_protocols    = XInternAtom(dpy, "WM_PROTOCOLS",     False);
    Atom wm_delete       = XInternAtom(dpy, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(dpy, win, &wm_delete, 1);

    /* Map — WM will place the window (e.g. centred) */
    XMapWindow(dpy, win);
    XFlush(dpy);

    /* Wait for the WM to finish placing the window, then send ConfigureRequest
     * requesting the remembered position.  With StaticGravity, x/y in an
     * XConfigureWindow request are root-window coordinates. */
    sleep_ms(100);
    XMoveResizeWindow(dpy, win, TARGET_X, TARGET_Y, WIDTH, HEIGHT);
    XFlush(dpy);

    /* Event loop — exit on WM_DELETE_WINDOW */
    XSelectInput(dpy, win, StructureNotifyMask);
    XEvent ev;
    for (;;) {
        XNextEvent(dpy, &ev);
        if (ev.type == ClientMessage &&
            ev.xclient.message_type == wm_protocols &&
            (Atom)ev.xclient.data.l[0] == wm_delete)
            break;
    }

    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
