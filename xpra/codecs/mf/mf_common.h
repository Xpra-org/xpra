/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: Definitions shared between the MediaFoundation encoder and decoder. */

#ifndef MF_COMMON_H
#define MF_COMMON_H

/* Codec identifiers used by both mf_decode and mf_encode */
#define MF_CODEC_H264  0
#define MF_CODEC_HEVC  1
#define MF_CODEC_VP9   2
#define MF_CODEC_AV1   3

/* Logging callback — set before calling any other API functions */
typedef void (*mf_log_fn)(const char *msg);

#endif /* MF_COMMON_H */
