/*
 * This file is part of Xpra.
 * Copyright (C) 2013-2024 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>

__device__ __forceinline__ uint8_t quant(float value)
{
    return (uint8_t)min(max(__float2int_rn(value), 0), 255);
}

// Y = 0.299 * R + 0.587 * G + 0.114 * B + 0
#define YR 0.299
#define YG 0.587
#define YB 0.114
#define YC 0
// U = -0.168736 * R - 0.331264 * G + 0.5 * B + 128
#define UR -0.168736
#define UG -0.331264
#define UB 0.5
#define UC 128
// V = 0.5 * R - 0.418688 * G - 0.081312 * B + 128
#define VR 0.5
#define VG -0.418688
#define VB -0.081312
#define VC 128

extern "C" __global__ void XRGB_to_YUV444(uint8_t *srcImage, int src_w, int src_h, int srcPitch,
                             uint8_t *dstImage, int dst_w, int dst_h, int dstPitch,
                             int w, int h)
{
    const int gx = blockIdx.x * blockDim.x + threadIdx.x;
    const int gy = blockIdx.y * blockDim.y + threadIdx.y;
    if (gx >= dst_w || gy >= dst_h) {
        return;
    }

    //edge-extend the valid content into the aligned output padding
    const int src_y = min(gy * src_h / dst_h, h - 1);
    const int src_x = min(gx * src_w / dst_w, w - 1);
    const uint32_t si = (src_y * srcPitch) + src_x * 4;
    const uint8_t R = srcImage[si+1];
    const uint8_t G = srcImage[si+2];
    const uint8_t B = srcImage[si+3];

    uint32_t di = (gy * dstPitch) + gx;
    dstImage[di] = quant(YR * R + YG * G + YB * B + YC);
    di += dstPitch*dst_h;
    dstImage[di] = quant(UR * R + UG * G + UB * B + UC);
    di += dstPitch*dst_h;
    dstImage[di] = quant(VR * R + VG * G + VB * B + VC);
}
