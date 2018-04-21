// This file is part of Xpra.
// Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
// Xpra is released under the terms of the GNU GPL v2, or, at your option, any
// later version. See the file COPYING for details.

#include "libavcodec/version.h"
#include "libavformat/avformat.h"

void register_all() {
#if LIBAVCODEC_VERSION_INT < AV_VERSION_INT(58, 9, 100)
     av_register_all();
#endif
}
