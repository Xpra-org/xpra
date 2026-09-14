/*
 * This file is part of Xpra.
 * Copyright (C) 2013-2026 Antoine Martin <antoine@xpra.org>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>

__device__ __forceinline__ uint8_t quant(float value)
{
    return (uint8_t)min(max(__float2int_rn(value), 0), 255);
}

#define YR 0.257
#define YG 0.504
#define YB 0.098
#define UR -0.148
#define UG -0.291
#define UB 0.439
#define UC 128
#define VR 0.439
#define VG -0.368
#define VB -0.071
#define VC 128

extern "C" __global__ void XRGB_to_NV12_box(uint8_t *srcImage, int src_w, int src_h, int srcPitch,
                              uint8_t *dstImage, int dst_w, int dst_h, int dstPitch,
                              int w, int h)
{
    const int gx = blockIdx.x * blockDim.x + threadIdx.x;
    const int gy = blockIdx.y * blockDim.y + threadIdx.y;
    const int dst_x = gx * 2;
    const int dst_y = gy * 2;
    if (dst_x >= dst_w || dst_y >= dst_h) {
        return;
    }

    // A fixed 2x2 box in each output pixel's source footprint.  This is only
    // selected for downscaling, so it provides an inexpensive low-pass filter.
    float u = 0;
    float v = 0;
    for (int j = 0; j < 2; j++) {
        const int dy = dst_y + j;
        float y = 0;
        for (int i = 0; i < 2; i++) {
            const int dx = dst_x + i;
            for (int syi = 0; syi < 2; syi++) {
                const int sy = min(((4 * dy + 1 + 2 * syi) * src_h) / (4 * dst_h), h - 1);
                for (int sxi = 0; sxi < 2; sxi++) {
                    const int sx = min(((4 * dx + 1 + 2 * sxi) * src_w) / (4 * dst_w), w - 1);
                    const uint32_t si = (sy * srcPitch) + sx * 4;
                    const uint8_t R = srcImage[si+1];
                    const uint8_t G = srcImage[si+2];
                    const uint8_t B = srcImage[si+3];
                    y += YR * R + YG * G + YB * B;
                    u += UR * R + UG * G + UB * B + UC;
                    v += VR * R + VG * G + VB * B + VC;
                }
            }
            dstImage[dy * dstPitch + dx] = quant(y / 4.0);
        }
    }
    const uint32_t di = (dst_h + gy) * dstPitch + dst_x;
    dstImage[di] = quant(u / 16.0);
    dstImage[di + 1] = quant(v / 16.0);
}
