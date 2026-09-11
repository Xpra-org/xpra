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

// Y = 0.257 * R + 0.504 * G + 0.098 * B + 0
#define YR 0.257
#define YG 0.504
#define YB 0.098
#define YC 0
// U = -0.148 * R - 0.291 * G + 0.439 * B + 128
#define UR -0.148
#define UG -0.291
#define UB 0.439
#define UC 128
// V = 0.439 * R - 0.368 * G - 0.071 * B + 128
#define VR 0.439
#define VG -0.368
#define VB -0.071
#define VC 128

extern "C" __global__ void XRGB_to_NV12(uint8_t *srcImage, int src_w, int src_h, int srcPitch,
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

    //edge-extend the valid content into the aligned output padding
    const int src_x = min(dst_x * src_w / dst_w, w - 1);
    const int src_y = min(dst_y * src_h / dst_h, h - 1);
    uint8_t R[4];
    uint8_t G[4];
    uint8_t B[4];
    for (int j = 0; j < 2; j++) {
        const int sy = min(src_y + j, h - 1);
        for (int i = 0; i < 2; i++) {
            const int sx = min(src_x + i, w - 1);
            const uint32_t si = (sy * srcPitch) + sx * 4;
            const int p = j * 2 + i;
            R[p] = srcImage[si+1];
            G[p] = srcImage[si+2];
            B[p] = srcImage[si+3];
            if (dst_x + i < dst_w && dst_y + j < dst_h) {
                const uint32_t di = (dst_y + j) * dstPitch + dst_x + i;
                dstImage[di] = quant(YR * R[p] + YG * G[p] + YB * B[p] + YC);
            }
        }
    }

    //write 1 U and 1 V pixel:
    float u = 0;
    float v = 0;
    for (int j = 0; j < 4; j++) {
        u += UR * R[j] + UG * G[j] + UB * B[j] + UC;
        v += VR * R[j] + VG * G[j] + VB * B[j] + VC;
    }
    const uint32_t di = (dst_h + gy) * dstPitch + dst_x;
    dstImage[di]      = quant(u / 4.0);
    dstImage[di + 1]  = quant(v / 4.0);
}
