/**
 * This file is part of Xpra.
 * Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>
#include "evdi_lib.h"

void evdi_connect_compat(evdi_handle handle, const unsigned char *edid,
          const unsigned int edid_length,
          const uint32_t pixel_area_limit,
          const uint32_t pixel_per_second_limit) {
#if LIBEVDI_VERSION_MAJOR>1 || LIBEVDI_VERSION_MINOR>11
	return evdi_connect(handle, edid, edid_length, pixel_area_limit, pixel_per_second_limit);
#else
	return evdi_connect(handle, edid, edid_length, pixel_per_second_limit);
#endif
}

void evdi_enable_cursor_events_compat(evdi_handle handle, int enable) {
#if LIBEVDI_VERSION_MAJOR>1 || LIBEVDI_VERSION_MINOR>9 || (LIBEVDI_VERSION_MINOR==9 && LIBEVDI_VERSION_PATCH>0)
	evdi_enable_cursor_events(handle, enable);
#else
	//cannot be disabled with older API versions!
	if (enable) {
		evdi_enable_cursor_events(handle);
	}
#endif
}
