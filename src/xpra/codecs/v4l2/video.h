// This file is part of Xpra.
// Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
// Xpra is released under the terms of the GNU GPL v2, or, at your option, any
// later version. See the file COPYING for details.

#ifdef __NetBSD__
#include <sys/videoio.h>
#endif
#ifdef __linux__
#include "linux/videodev2.h"
#endif
