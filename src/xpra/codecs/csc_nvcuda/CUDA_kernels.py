# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

YUV_FORMATS = ("YUV444P", "YUV422P", "YUV420P")

def rgb_only_name(rgb_format):
    #strip out X and A:
    n = rgb_format.replace("A", "").replace("X", "").upper()
    for x in n:
        assert x in ("R", "G", "B"), "invalid character found in rgb format: '%s' in %s" % (x, rgb_format)
    return n

def gen_rgb_to_nv12_kernel(rgb_format):
    R = rgb_format.find("R")
    G = rgb_format.find("G")
    B = rgb_format.find("B")
    assert R>=0 and G>=0 and B>=0, "invalid format: %s" % rgb_format

    kernel_name = "%s_to_NV12" % rgb_only_name(rgb_format)
    args = [kernel_name] + [R, G, B] * 4;  
    return kernel_name, """
#include <stdint.h>

__global__ void %s(uint8_t *srcImage,    const int srcPitch,
                   uint8_t *dstImage,    const int dstPitch, const int dstHeight,
                   const int w,                const int h)
{
    const uint32_t gx = blockIdx.x * blockDim.x + threadIdx.x;
    const uint32_t gy = blockIdx.y * blockDim.y + threadIdx.y;

    if ((gx*2 < w) & (gy*2 < h)) {
        //4 bytes per pixel, and 2 pixels width/height at a time:
        uint32_t si = (gy * 2 * srcPitch) + gx * 2 * 4;

        //we may read up to 4 32-bit RGB pixels:
        uint8_t R[4];
        uint8_t G[4];
        uint8_t B[4];
        uint8_t j = 0;
        R[0] = srcImage[si+%s];
        G[0] = srcImage[si+%s];
        B[0] = srcImage[si+%s];
        for (j=0; j<4; j++) {
            R[j] = R[0];
            G[j] = G[0];
            B[j] = B[0];
        }

        //write up to 4 Y pixels:
        uint32_t di = (gy * 2 * dstPitch) + gx * 2;
        dstImage[di] = __float2int_rn(0.257 * R[0] + 0.504 * G[0] + 0.098 * B[0] + 16);
        if (gx*2 + 1 < w) {
            R[1] = srcImage[si+%s];
            G[1] = srcImage[si+%s];
            B[1] = srcImage[si+%s];
            dstImage[di + 1] = __float2int_rn(0.257 * R[1] + 0.504 * G[1] + 0.098 * B[1] + 16);
        }
        if (gy*2 + 1 < h) {
            si += srcPitch;
            di += dstPitch;
            R[2] = srcImage[si+2];
            G[2] = srcImage[si+1];
            B[2] = srcImage[si];
            dstImage[di] = __float2int_rn(0.257 * R[2] + 0.504 * G[2] + 0.098 * B[2] + 16);
            if (gx*2 + 1 < w) {
                R[3] = srcImage[si+%s];
                G[3] = srcImage[si+%s];
                B[3] = srcImage[si+%s];
                dstImage[di + 1] = __float2int_rn(0.257 * R[3] + 0.504 * G[3] + 0.098 * B[3] + 16);
            }
        }

        //write 1 U and 1 V pixel:
        float_t u = 0;
        float_t v = 0;
        for (j=0; j<4; j++) {
            u += -0.148 * R[j] - 0.291 * G[j] + 0.439 * B[j] + 128;
            v +=  0.439 * R[j] - 0.368 * G[j] - 0.071 * B[j] + 128;
        }
        di = (dstHeight + gy) * dstPitch + gx * 2;
        dstImage[di]      = __float2int_rn(u / 4.0);
        dstImage[di + 1]  = __float2int_rn(v / 4.0);
    }
}
    """ % args

def gen_rgb_to_yuv444p_kernel(rgb_format):
    R = rgb_format.find("R")
    G = rgb_format.find("G")
    B = rgb_format.find("B")
    assert R>=0 and G>=0 and B>=0, "invalid format: %s" % rgb_format

    kernel_name = "%s_to_YUV444P" % rgb_only_name(rgb_format)
    args = tuple([kernel_name] + [R, G, B])
    kstr = """
#include <stdint.h>

__global__ void %s(uint8_t *srcImage,     const int srcPitch,
                   uint8_t *Y,            const int strideY,
                   uint8_t *U,            const int strideU,
                   uint8_t *V,            const int strideV,
                   const int w,                 const int h)
{
    const uint32_t gx = blockIdx.x * blockDim.x + threadIdx.x;
    const uint32_t gy = blockIdx.y * blockDim.y + threadIdx.y;

    if ((gx < w) & (gy < h)) {
        //4 bytes per pixel:
        const uint32_t si = (gy * srcPitch) + gx * 4;
        const uint8_t R = srcImage[si+%s];
        const uint8_t G = srcImage[si+%s];
        const uint8_t B = srcImage[si+%s];

        Y[(gy * strideY) + gx] = __float2int_rn( 0.257 * R + 0.504 * G + 0.098 * B + 16);
        U[(gy * strideU) + gx] = __float2int_rn(-0.148 * R - 0.291 * G + 0.439 * B + 128);
        V[(gy * strideV) + gx] = __float2int_rn( 0.439 * R - 0.368 * G - 0.071 * B + 128);
    }
}
    """
    return kernel_name, kstr % args

def gen_rgb_to_yuv422p_kernel(rgb_format):
    R = rgb_format.find("R")
    G = rgb_format.find("G")
    B = rgb_format.find("B")
    assert R>=0 and G>=0 and B>=0, "invalid format: %s" % rgb_format

    kernel_name = "%s_to_YUV422P" % rgb_only_name(rgb_format)
    args = tuple([kernel_name] + [R, G, B] * 2)
    kstr ="""
#include <stdint.h>

__global__ void %s(uint8_t *srcImage,     const int srcPitch,
                   uint8_t *Y,            const int strideY,
                   uint8_t *U,            const int strideU,
                   uint8_t *V,            const int strideV,
                   const int w,                 const int h)
{
    const uint32_t gx = blockIdx.x * blockDim.x + threadIdx.x;
    const uint32_t gy = blockIdx.y * blockDim.y + threadIdx.y;

    if ((gx*2 < w) & (gy < h)) {
        //4 bytes per pixel, reading up to 2 pixels at a time:
        const uint32_t si = (gy * srcPitch) + gx * 4 * 2;

        uint8_t R[2];
        uint8_t G[2];
        uint8_t B[2];
        uint8_t j = 0;

        R[0] = srcImage[si+%s];
        G[0] = srcImage[si+%s];
        B[0] = srcImage[si+%s];
        R[1] = R[0];
        G[1] = G[0];
        B[1] = B[0];

        //write up to 2 Y pixels:
        const uint i = gy*strideY + gx*2;
        Y[i] = __float2int_rn(0.257 * R[0] + 0.504 * G[0] + 0.098 * B[0] + 16);
        if (gx*2 + 1 < w) {
            R[1] = srcImage[si+4+%s];
            G[1] = srcImage[si+4+%s];
            B[1] = srcImage[si+4+%s];
            Y[i+1] = __float2int_rn(0.257 * R[1] + 0.504 * G[1] + 0.098 * B[1] + 16);
        }

        //write 1 U and 1 V pixel:
        float sumu = 0;
        float sumv = 0;
        for (j=0; j<2; j++) {
            sumu += -0.148 * R[j] - 0.291 * G[j] + 0.439 * B[j] + 128;
            sumv +=  0.439 * R[j] - 0.368 * G[j] - 0.071 * B[j] + 128;
        }
        U[(gy * strideU) + gx] = __float2int_rn( sumu / 2.0);
        V[(gy * strideV) + gx] = __float2int_rn( sumv / 2.0);
    }
}
    """
    return kernel_name, kstr % args


def gen_rgb_to_yuv420p_kernel(rgb_format):
    R = rgb_format.find("R")
    G = rgb_format.find("G")
    B = rgb_format.find("B")
    assert R>=0 and G>=0 and B>=0, "invalid format: %s" % rgb_format

    kernel_name = "%s_to_YUV420P" % rgb_only_name(rgb_format)
    args = tuple([kernel_name] + [R, G, B] * 4);
    kstr = """
#include <stdint.h>

__global__ void %s(uint8_t *srcImage,     const int srcPitch,
                   uint8_t *Y,            const int strideY,
                   uint8_t *U,            const int strideU,
                   uint8_t *V,            const int strideV,
                   const int w,                 const int h)
{
    const uint32_t gx = blockIdx.x * blockDim.x + threadIdx.x;
    const uint32_t gy = blockIdx.y * blockDim.y + threadIdx.y;

    if ((gx*2 < w) & (gy*2 < h)) {
        //4 bytes per pixel, reading up to 4 pixels at a time (2 in width and 2 in height):
        uint32_t si = (gy * 2 * srcPitch) + gx * 4 * 2;

        uint8_t R[4];
        uint8_t G[4];
        uint8_t B[4];
        uint8_t j = 0;

        R[0] = srcImage[si+%s];
        G[0] = srcImage[si+%s];
        B[0] = srcImage[si+%s];
        for (j=0; j<4; j++) {
            R[j] = R[0];
            G[j] = G[0];
            B[j] = B[0];
        }

        //write up to 4 Y pixels:
        uint i = gy*2*strideY + gx*2;
        Y[i] = __float2int_rn(0.257 * R[0] + 0.504 * G[0] + 0.098 * B[0] + 16);
        if (gx*2 + 1 < w) {
            R[1] = srcImage[si+4+%s];
            G[1] = srcImage[si+4+%s];
            B[1] = srcImage[si+4+%s];
            Y[i+1] = __float2int_rn(0.257 * R[1] + 0.504 * G[1] + 0.098 * B[1] + 16);
        }
        if (gy*2 + 1 < h) {
            i += strideY;
            si += srcPitch;
            R[2] = srcImage[si+%s];
            G[2] = srcImage[si+%s];
            B[2] = srcImage[si+%s];
            Y[i] = __float2int_rn(0.257 * R[2] + 0.504 * G[2] + 0.098 * B[2] + 16);
            if (gx*2 + 1 < w) {
                R[3] = srcImage[si+4+%s];
                G[3] = srcImage[si+4+%s];
                B[3] = srcImage[si+4+%s];
                Y[i+1] = __float2int_rn(0.257 * R[3] + 0.504 * G[3] + 0.098 * B[3] + 16);
            }
        }

        //write 1 U and 1 V pixel:
        float sumu = 0;
        float sumv = 0;
        for (j=0; j<4; j++) {
            sumu += -0.148 * R[j] - 0.291 * G[j] + 0.439 * B[j] + 128;
            sumv +=  0.439 * R[j] - 0.368 * G[j] - 0.071 * B[j] + 128;
        }
        U[(gy * strideU) + gx] = __float2int_rn( sumu / 4.0);
        V[(gy * strideV) + gx] = __float2int_rn( sumv / 4.0);
    }
}
    """
    return kernel_name, kstr % args



RGB_to_YUV_generators = {
                    "YUV444P"   : gen_rgb_to_yuv444p_kernel,
                    "YUV422P"   : gen_rgb_to_yuv422p_kernel,
                    "YUV420P"   : gen_rgb_to_yuv420p_kernel,
                    }

def gen_rgb_to_yuv_kernels(rgb_mode="RGBX", yuv_modes=YUV_FORMATS):
    RGB_to_YUV_KERNELS = {}
    for yuv in yuv_modes:
        gen = RGB_to_YUV_generators.get(yuv)
        assert gen is not None, "no generator found for yuv mode %s" % yuv
        RGB_to_YUV_KERNELS[(rgb_mode, yuv)] = gen(rgb_mode)
    return RGB_to_YUV_KERNELS
