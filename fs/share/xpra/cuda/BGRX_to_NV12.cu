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

extern "C" __global__ void BGRX_to_NV12(uint8_t *srcImage, int src_w, int src_h, int srcPitch,
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

    // Map every output luma pixel independently.  Mapping only dst_x/dst_y
    // and then incrementing the source coordinate made each 2x2 output block
    // sample a contiguous 2x2 source block, irrespective of the scale.
    uint8_t R[4];
    uint8_t G[4];
    uint8_t B[4];
    for (int j = 0; j < 2; j++) {
        const int dy = dst_y + j;
        // Pixel-centre nearest-neighbour coordinate, clamped for padding.
        const int sy = min(((2 * dy + 1) * src_h) / (2 * dst_h), h - 1);
        for (int i = 0; i < 2; i++) {
            const int dx = dst_x + i;
            const int sx = min(((2 * dx + 1) * src_w) / (2 * dst_w), w - 1);
            const uint32_t si = (sy * srcPitch) + sx * 4;
            const int p = j * 2 + i;
            R[p] = srcImage[si+2];
            G[p] = srcImage[si+1];
            B[p] = srcImage[si];
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
