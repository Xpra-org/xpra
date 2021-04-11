// This file is part of Xpra.
// Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
// Xpra is released under the terms of the GNU GPL v2, or, at your option, any
// later version. See the file COPYING for details.

#include "gdk/gdkx.h"

int is_x11_display(void *display) {
#ifdef GDK_WINDOWING_X11
  if (GDK_IS_X11_DISPLAY (display))
	  return 1;
  else
#endif
	  return 0;
}
