/* This file is part of Xpra.
 * Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdlib.h>
#include "memalign.h"

//not honoured on MS Windows:
#define MEMALIGN 1

#ifdef _WIN32
#define _STDINT_H
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
#ifdef MEMALIGN
#ifdef _WIN32
	//_aligned_malloc and _aligned_free lead to a memleak
	//well done Microsoft, I didn't think you could screw up this badly
	//and thank you for wasting my time once again
	return malloc(size);
#else
	// assume POSIX:
	void *memptr = NULL;
	if (posix_memalign(&memptr, MEMALIGN_ALIGNMENT, size))
		return NULL;
	return memptr;
#endif
//MEMALIGN not set:
#else
	return malloc(size);
#endif
}

#ifdef __cplusplus
}
#endif
