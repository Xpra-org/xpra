/* This file is part of Xpra.
 * Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdlib.h>
#include "memalign.h"

#ifdef _WIN32
#define _STDINT_H
#include <malloc.h>
#endif
#if !defined(__APPLE__) && !defined(__FreeBSD__) && !defined(__DragonFly__) \
		&& !defined(__OpenBSD__)
#include <malloc.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

int pad(int size) {
    return (size + MEMALIGN_ALIGNMENT - 1) & ~(MEMALIGN_ALIGNMENT - 1);
}

void *xmemalign(size_t size)
{
#ifdef _WIN32
    return _aligned_malloc(size, MEMALIGN_ALIGNMENT);
#else
	// assume POSIX:
	void *memptr = NULL;
	if (posix_memalign(&memptr, MEMALIGN_ALIGNMENT, size))
		return NULL;
	return memptr;
#endif
}

void xmemfree(void *ptr)
{
#ifdef _WIN32
    _aligned_free(ptr);
#else
    // assume POSIX:
    free(ptr);
#endif
}


#ifdef __cplusplus
}
#endif
