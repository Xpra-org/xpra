/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Shared log-callback typedef for the oneVPL encoder and decoder.
 * ABOUTME: Each .so still owns its own static dispatch state in its .c file. */

#ifndef VPL_LOG_H
#define VPL_LOG_H

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*vpl_log_fn)(const char *msg);

#ifdef __cplusplus
}
#endif

#endif /* VPL_LOG_H */
