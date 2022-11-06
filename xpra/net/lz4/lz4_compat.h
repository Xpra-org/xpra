/* This file is part of Xpra.
 * Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

//workaround for older versions of lz4

#include <lz4.h>

#if LZ4_VERSION_MAJOR<2 && LZ4_VERSION_MINOR<9
void LZ4_resetStream_fast(LZ4_stream_t* stream) {
	LZ4_resetStream(stream);
}
#endif
