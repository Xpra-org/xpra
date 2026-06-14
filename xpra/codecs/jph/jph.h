/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#ifndef XPRA_CODECS_JPH_H
#define XPRA_CODECS_JPH_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int jph_version_major(void);
int jph_version_minor(void);
int jph_version_patch(void);

int jph_encode(const uint8_t *pixels,
               uint32_t width, uint32_t height, uint32_t stride,
               int bytes_per_pixel, int r_offset, int g_offset, int b_offset,
               int quality,
               uint8_t **out, size_t *out_size,
               char *error, size_t error_size);

int jph_decode(const uint8_t *data, size_t data_size,
               uint8_t **pixels, size_t *pixels_size,
               uint32_t *width, uint32_t *height, uint32_t *stride,
               char *error, size_t error_size);

#ifdef __cplusplus
}
#endif

#endif
