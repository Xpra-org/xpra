/* This file is part of Xpra.
 * Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
 * Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
 * Parti is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include "vpx/vpx_encoder.h"


int get_packet_kind(const vpx_codec_cx_pkt_t *pkt)
{
	return pkt->kind;
}

char *get_frame_buffer(const vpx_codec_cx_pkt_t *pkt)
{
	return pkt->data.frame.buf;
}

size_t get_frame_size(const vpx_codec_cx_pkt_t *pkt)
{
	return pkt->data.frame.sz;
}
