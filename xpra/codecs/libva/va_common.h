/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Common VA-API helpers shared by the libva encoder and decoder. */

#ifndef XPRA_LIBVA_COMMON_H
#define XPRA_LIBVA_COMMON_H

#include <va/va.h>
#ifdef _WIN32
#include <va/va_win32.h>
#else
#include <va/va_drm.h>
#include <va/va_x11.h>
#include <X11/Xlib.h>
#include <fcntl.h>
#include <unistd.h>
#endif

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

typedef enum {
    LIBVA_CODEC_H264 = 0,
    LIBVA_CODEC_VP8  = 1,
    LIBVA_CODEC_VP9  = 2,
} LibVACodec;

typedef void (*libva_log_fn)(const char *msg);

#ifndef VA_CHECK_VERSION
#define VA_CHECK_VERSION(major, minor, micro) \
    ((VA_MAJOR_VERSION > (major)) || \
     (VA_MAJOR_VERSION == (major) && VA_MINOR_VERSION > (minor)) || \
     (VA_MAJOR_VERSION == (major) && VA_MINOR_VERSION == (minor) && VA_MICRO_VERSION >= (micro)))
#endif

static inline int roundup(int n, int m) {
    return (n + m - 1) & ~(m - 1);
}

static inline int clamp_int(int value, int low, int high) {
    if (value < low)
        return low;
    if (value > high)
        return high;
    return value;
}

static inline int codec_from_name(const char *encoding, LibVACodec *codec) {
    if (!encoding)
        return 0;
    if (strcmp(encoding, "h264") == 0) {
        *codec = LIBVA_CODEC_H264;
        return 1;
    }
    if (strcmp(encoding, "vp8") == 0) {
        *codec = LIBVA_CODEC_VP8;
        return 1;
    }
    if (strcmp(encoding, "vp9") == 0) {
        *codec = LIBVA_CODEC_VP9;
        return 1;
    }
    return 0;
}

static inline const char *codec_name(LibVACodec codec) {
    switch (codec) {
        case LIBVA_CODEC_H264:
            return "H.264";
        case LIBVA_CODEC_VP8:
            return "VP8";
        case LIBVA_CODEC_VP9:
            return "VP9";
        default:
            return "unknown";
    }
}

static inline const char *h264_profile_name(VAProfile profile) {
    switch (profile) {
        case VAProfileH264ConstrainedBaseline:
            return "constrained-baseline";
        case VAProfileH264Main:
            return "main";
        case VAProfileH264High:
            return "high";
        case VAProfileH264High10:
            return "high10";
        default:
            return "unknown";
    }
}

static inline const char *entrypoint_name(VAEntrypoint entrypoint) {
    switch (entrypoint) {
        case VAEntrypointVLD:
            return "VLD";
        case VAEntrypointEncSlice:
            return "EncSlice";
        case VAEntrypointEncSliceLP:
            return "EncSliceLP";
        default:
            return "unknown";
    }
}

static inline const char *fourcc_name(unsigned int fourcc) {
    switch (fourcc) {
        case VA_FOURCC_NV12:
            return "NV12";
        case VA_FOURCC_444P:
            return "444P";
        case VA_FOURCC_XYUV:
            return "XYUV";
        case VA_FOURCC_AYUV:
            return "AYUV";
        default:
            return "unknown";
    }
}

static inline int profile_supported(const VAProfile *profiles, int nprofiles, VAProfile profile) {
    for (int i = 0; i < nprofiles; i++) {
        if (profiles[i] == profile)
            return 1;
    }
    return 0;
}

static inline int entrypoint_supported(const VAEntrypoint *entrypoints, int nentrypoints,
                                       VAEntrypoint entrypoint) {
    for (int i = 0; i < nentrypoints; i++) {
        if (entrypoints[i] == entrypoint)
            return 1;
    }
    return 0;
}

#ifdef _WIN32
static inline int libva_open_display(const char *device, int *fd_out, VADisplay *display_out,
                                     int *major_out, int *minor_out,
                                     char *vendor, size_t vendor_size,
                                     char *error, size_t error_size) {
    VADisplay display;
    VAStatus status;
    const char *vstr;

    (void)device;
    *fd_out = -1;
    *display_out = NULL;
    display = vaGetDisplayWin32(NULL);
    if (!display) {
        snprintf(error, error_size, "vaGetDisplayWin32 failed");
        return 0;
    }
    status = vaInitialize(display, major_out, minor_out);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(error, error_size, "vaInitialize failed: %s (%d)",
                 vaErrorStr(status), (int)status);
        return 0;
    }
    vstr = vaQueryVendorString(display);
    snprintf(vendor, vendor_size, "%s", vstr ? vstr : "");
    *display_out = display;
    return 1;
}
#else
/* X11 VADisplays (device "x11" or "x11:<name>") need their Display
 * closed at teardown; VADisplay itself does not own it.  Small per-TU
 * registry, looked up by libva_x11_close() which no-ops for DRM
 * displays.  Rationale: VDPAU-backed VA drivers (nvidia-340 era) have
 * no DRM path at all - vdp_device_create_x11 is VDPAU's only
 * constructor - and such systems may have no render nodes either. */
#define LIBVA_X11_DISPLAYS_MAX 8
static Display *libva_x11_dpys[LIBVA_X11_DISPLAYS_MAX];
static VADisplay libva_x11_vadpys[LIBVA_X11_DISPLAYS_MAX];
static inline void libva_x11_register(VADisplay va, Display *dpy) {
    for (int i = 0; i < LIBVA_X11_DISPLAYS_MAX; i++) {
        if (!libva_x11_vadpys[i]) {
            libva_x11_vadpys[i] = va;
            libva_x11_dpys[i] = dpy;
            return;
        }
    }
    /* table full: the X connection is leaked on close */
}
static inline void libva_x11_close(VADisplay va) {
    for (int i = 0; i < LIBVA_X11_DISPLAYS_MAX; i++) {
        if (libva_x11_vadpys[i] == va) {
            XCloseDisplay(libva_x11_dpys[i]);
            libva_x11_vadpys[i] = NULL;
            libva_x11_dpys[i] = NULL;
            return;
        }
    }
}
static inline int libva_open_display(const char *device, int *fd_out, VADisplay *display_out,
                                     int *major_out, int *minor_out,
                                     char *vendor, size_t vendor_size,
                                     char *error, size_t error_size) {
    int fd;
    VADisplay display;
    VAStatus status;
    const char *vstr;

    *fd_out = -1;
    *display_out = NULL;
    if (strncmp(device, "x11", 3) == 0 && (device[3] == 0 || device[3] == ':')) {
        /* "x11" opens $DISPLAY, "x11:<name>" a specific X display */
        const char *dpy_name = (device[3] == ':') ? device + 4 : NULL;
        Display *dpy = XOpenDisplay(dpy_name);
        if (!dpy) {
            snprintf(error, error_size, "XOpenDisplay failed for %.160s",
                     dpy_name ? dpy_name : "$DISPLAY");
            return 0;
        }
        display = vaGetDisplay(dpy);
        if (!display) {
            snprintf(error, error_size, "vaGetDisplay failed for X11 display");
            XCloseDisplay(dpy);
            return 0;
        }
        status = vaInitialize(display, major_out, minor_out);
        if (status != VA_STATUS_SUCCESS) {
            snprintf(error, error_size, "vaInitialize failed for X11 display: %s (%d)",
                     vaErrorStr(status), (int)status);
            XCloseDisplay(dpy);
            return 0;
        }
        vstr = vaQueryVendorString(display);
        snprintf(vendor, vendor_size, "%s", vstr ? vstr : "");
        libva_x11_register(display, dpy);
        *display_out = display;
        return 1;
    }
    fd = open(device, O_RDWR | O_CLOEXEC);
    if (fd < 0)
        return 0;
    display = vaGetDisplayDRM(fd);
    if (!display) {
        snprintf(error, error_size, "vaGetDisplayDRM failed for %.200s", device);
        close(fd);
        return 0;
    }
    status = vaInitialize(display, major_out, minor_out);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(error, error_size, "vaInitialize failed for %.160s: %s (%d)",
                 device, vaErrorStr(status), (int)status);
        close(fd);
        return 0;
    }
    vstr = vaQueryVendorString(display);
    snprintf(vendor, vendor_size, "%s", vstr ? vstr : "");
    *fd_out = fd;
    *display_out = display;
    return 1;
}
#endif

#endif /* XPRA_LIBVA_COMMON_H */
