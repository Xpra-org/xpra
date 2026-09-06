/*
 * This file is part of Xpra.
 * Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#ifndef XPRA_CODECS_JPH_COMMON_H
#define XPRA_CODECS_JPH_COMMON_H

#include <cstddef>
#include <cstring>

#ifndef __has_include
#define __has_include(x) 0
#endif

#if __has_include(<openjph/ojph_codestream.h>)
#include <openjph/ojph_codestream.h>
#include <openjph/ojph_file.h>
#include <openjph/ojph_mem.h>
#include <openjph/ojph_params.h>
#include <openjph/ojph_version.h>
#else
#include <ojph_codestream.h>
#include <ojph_file.h>
#include <ojph_mem.h>
#include <ojph_params.h>
#include <ojph_version.h>
#endif

static inline void set_error(char *error, size_t error_size, const char *msg)
{
    if (error == nullptr || error_size == 0)
        return;
    if (msg == nullptr)
        msg = "unknown OpenJPH error";
    std::strncpy(error, msg, error_size - 1);
    error[error_size - 1] = 0;
}

#endif
