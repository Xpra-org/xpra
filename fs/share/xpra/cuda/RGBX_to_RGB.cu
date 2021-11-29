/*
 * This file is part of Xpra.
 * Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>

extern "C" __global__ void RGBX_to_RGB(int src_w, int src_h,
                             int srcPitch, uint8_t *srcImage,
                             int dst_w, int dst_h,
                             int dstPitch, uint8_t *dstImage)
{
    const uint32_t gx = blockIdx.x * blockDim.x + threadIdx.x;
    const uint32_t gy = blockIdx.y * blockDim.y + threadIdx.y;
    const uint32_t src_x = gx * src_w / dst_w;
    const uint32_t src_y = gy * src_h / dst_h;

    if ((src_x < src_w) & (src_y < src_h) & (gx < dst_w) & (gy < dst_h)) {
        uint32_t si = (src_y * srcPitch) + src_x * 4;
        uint32_t di = (gy * dstPitch) + gx*3;
        //A = srcImage[si+3];
        dstImage[di]   = srcImage[si+2];
        dstImage[di+1] = srcImage[si+1];
        dstImage[di+2] = srcImage[si];
    }
}
