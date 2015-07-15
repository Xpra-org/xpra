/*
 * This file is part of Xpra.
 * Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 */

#include <stdint.h>

extern "C" __global__ void BGRA_to_NV12(uint8_t *srcImage, int src_w, int src_h, int srcPitch,
                          uint8_t *dstImage, int dst_w, int dst_h, int dstPitch,
                          int w, int h)
{
    uint32_t gx, gy;
    gx = blockIdx.x * blockDim.x + threadIdx.x;
    gy = blockIdx.y * blockDim.y + threadIdx.y;

    uint32_t src_y = gy*2 * src_h / dst_h;
    uint32_t src_x = gx*2 * src_w / dst_w;

    if ((src_x < w) & (src_y < h)) {
        //4 bytes per pixel, and 2 pixels width/height at a time:
        //byte index:
        uint32_t si = (src_y * srcPitch) + src_x * 4;

        //we may read up to 4 32-bit RGB pixels:
        uint8_t R[4];
        uint8_t G[4];
        uint8_t B[4];
        uint8_t j = 0;
        R[0] = srcImage[si+2];
        G[0] = srcImage[si+1];
        B[0] = srcImage[si];
        for (j=1; j<4; j++) {
            R[j] = R[0];
            G[j] = G[0];
            B[j] = B[0];
        }

        //write up to 4 Y pixels:
        uint32_t di = (gy * 2 * dstPitch) + gx * 2;
        dstImage[di] = __float2int_rn(0.257 * R[0] + 0.504 * G[0] + 0.098 * B[0] + 16);
        if (gx*2 + 1 < src_w) {
            R[1] = srcImage[si+6];
            G[1] = srcImage[si+5];
            B[1] = srcImage[si+4];
            dstImage[di + 1] = __float2int_rn(0.257 * R[1] + 0.504 * G[1] + 0.098 * B[1] + 16);
        }
        if (gy*2 + 1 < src_h) {
            si += srcPitch;
            di += dstPitch;
            R[2] = srcImage[si+2];
            G[2] = srcImage[si+1];
            B[2] = srcImage[si];
            dstImage[di] = __float2int_rn(0.257 * R[2] + 0.504 * G[2] + 0.098 * B[2] + 16);
            if (gx*2 + 1 < src_w) {
                R[3] = srcImage[si+6];
                G[3] = srcImage[si+5];
                B[3] = srcImage[si+4];
                dstImage[di + 1] = __float2int_rn(0.257 * R[3] + 0.504 * G[3] + 0.098 * B[3] + 16);
            }
        }

        //write 1 U and 1 V pixel:
        float u = 0;
        float v = 0;
        for (j=0; j<4; j++) {
            u += -0.148 * R[j] - 0.291 * G[j] + 0.439 * B[j] + 128;
            v +=  0.439 * R[j] - 0.368 * G[j] - 0.071 * B[j] + 128;
        }
        di = (dst_h + gy) * dstPitch + gx * 2;
        dstImage[di]      = __float2int_rn(u / 4.0);
        dstImage[di + 1]  = __float2int_rn(v / 4.0);
    }
}
