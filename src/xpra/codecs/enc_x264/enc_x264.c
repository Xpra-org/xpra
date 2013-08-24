/* This file is part of Xpra.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>
#include <inttypes.h>

#include <x264.h>


int get_x264_build_no(void)
{
	return X264_BUILD;
}

const char * const *get_preset_names(void) {
	return x264_preset_names;
}

void set_f_rf(x264_param_t *param, float v) {
	param->rc.f_rf_constant = v;
}
