/* This file is part of Xpra.
 * Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif

//not honoured on OSX: (*must* be a power of 2!)
#define MEMALIGN_ALIGNMENT 64

void *xmemalign(size_t size);
void xmemfree(void *ptr);
int pad(int size);

#ifdef __cplusplus
}
#endif
