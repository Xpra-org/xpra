/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Sam Estep <sam@samestep.com>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 *
 * Reproducer: application replaces all of its window title properties on
 * every render iteration, even when the title has not changed.
 * At a few thousand iterations per second, this generates more than ten
 * thousand PropertyNotify events per second, which used to starve the
 * xpra server's main loop: windows froze, clients could not connect
 * and even `xpra info` timed out.
 *
 * Build:
 *   gcc -O2 -Wall test_window_title_storm.c -lX11 -o test_window_title_storm
 *
 * Arguments:
 *   argv[1]: title updates per second (default 2000, 0 for no rate limit)
 *   argv[2]: duration in seconds (default 0, meaning until interrupted)
 *
 * Run under xpra and verify that the server stays responsive:
 *   xpra start :10 --start="./test_window_title_storm 2000 10"
 *   timeout 2s xpra info :10 >/dev/null && echo responsive
 */

#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;

static void
stop(int signum)
{
    (void) signum;
    running = 0;
}

static double
elapsed_seconds(const struct timespec *start, const struct timespec *now)
{
    return (double) (now->tv_sec - start->tv_sec) +
           (double) (now->tv_nsec - start->tv_nsec) / 1000000000.0;
}

static void
advance_deadline(struct timespec *deadline, long period_ns)
{
    deadline->tv_nsec += period_ns;
    while (deadline->tv_nsec >= 1000000000L) {
        deadline->tv_nsec -= 1000000000L;
        deadline->tv_sec++;
    }
}

int
main(int argc, char **argv)
{
    unsigned long rate = argc > 1 ? strtoul(argv[1], NULL, 10) : 2000;
    unsigned long duration = argc > 2 ? strtoul(argv[2], NULL, 10) : 0;

    Display *display = XOpenDisplay(NULL);
    if (!display) {
        fprintf(stderr, "cannot open display\n");
        return 1;
    }

    signal(SIGINT, stop);
    signal(SIGTERM, stop);

    int screen = DefaultScreen(display);
    Window root = RootWindow(display, screen);
    Window window = XCreateSimpleWindow(
        display, root, 100, 100, 640, 360, 1,
        BlackPixel(display, screen), BlackPixel(display, screen));
    XMapWindow(display, window);
    XFlush(display);

    Atom utf8_string = XInternAtom(display, "UTF8_STRING", False);
    Atom properties[] = {
        XInternAtom(display, "_NET_WM_NAME", False),
        XInternAtom(display, "_NET_WM_ICON_NAME", False),
        XA_WM_NAME,
        XInternAtom(display, "WM_LOCALE_NAME", False),
        XA_WM_ICON_NAME,
        XInternAtom(display, "WM_CLIENT_MACHINE", False),
    };
    Atom types[] = {
        utf8_string,
        utf8_string,
        XA_STRING,
        XA_STRING,
        XA_STRING,
        XA_STRING,
    };
    const unsigned char value[] = "Xpra title property event storm";

    /* Allow the window manager to register the window before the storm. */
    sleep(1);

    struct timespec start;
    struct timespec now;
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &start);
    deadline = start;

    unsigned long updates = 0;
    long period_ns = rate ? 1000000000L / (long) rate : 0;

    while (running) {
        for (size_t i = 0; i < sizeof(properties) / sizeof(properties[0]); i++) {
            XChangeProperty(display, window, properties[i], types[i], 8,
                            PropModeReplace, value, sizeof(value) - 1);
        }
        XFlush(display);
        updates++;

        clock_gettime(CLOCK_MONOTONIC, &now);
        if (duration &&
            elapsed_seconds(&start, &now) >= (double) duration) {
            break;
        }
        if (period_ns) {
            advance_deadline(&deadline, period_ns);
            if (elapsed_seconds(&deadline, &now) > 0) {
                deadline = now;
            }
            clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME,
                            &deadline, NULL);
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &now);
    double elapsed = elapsed_seconds(&start, &now);
    fprintf(stderr,
            "%lu title updates in %.3f seconds (%.1f updates/s)\n",
            updates, elapsed,
            elapsed > 0 ? (double) updates / elapsed : 0);

    XDestroyWindow(display, window);
    XCloseDisplay(display);
    return 0;
}
