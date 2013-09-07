# Copyright (C) 2011 Michael Zucchi
# This file is based on code from socles, an OpenCL image processing library.
#
# socles is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# socles is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with socles.  If not, see <http://www.gnu.org/licenses/>.


YUV_TO_RGB = {"X"    : "1.0",
              "A"    : "1.0",
              "R"    : "Y + 1.5958 * Cb",
              "G"    : "Y - 0.39173*Cr-0.81290*Cb",
              "B"    : "Y + 2.017*Cr"
              }

#Cr width div, Cr heigth div, Cb width div, Cb width div
YUV_FORMATS = ("YUV444P", "YUV422P", "YUV420P")

def indexes_to_rgb_mode(RGB_args):
    #ie: 2103==BGRX
    s = ""
    for i in RGB_args:
        s += {0 : "R",
              1 : "G",
              2 : "B",
              3 : "X"}.get(i)
    return s

def rgb_mode_to_indexes(rgb_mode):
    #we can change the RGB order
    #to handle other pixel formats
    #(most are already handled natively by OpenCL but not all
    #and not on all platforms..)
    RGB_ARGS = []
    for c in rgb_mode:
        v = {"R":0, "G":1, "B":2, "X":3, "A":3}.get(c)
        assert v is not None, "invalid channel: %s" % c
        RGB_ARGS.append(v)
    return RGB_ARGS

def rgb_indexes(rgb_mode):
    #we can change the RGB order
    #to handle other pixel formats
    #(most are already handled natively by OpenCL but not all
    #and not on all platforms..)
    RGB_ARGS = []
    for c in rgb_mode:
        if c in ("A", "X"):
            continue
        v = {"R":0, "G":1, "B":2}.get(c)
        assert v is not None, "invalid channel: %s" % c
        RGB_ARGS.append(v)
    return RGB_ARGS


def gen_yuv444p_to_rgb_kernel(yuv_format, rgb_format):
    assert len(rgb_format) in (3,4), "invalid destination rgb format: %s" % rgb_format
    if len(rgb_format)==3:
        #pad with empty channel:
        rgb_format = rgb_format+"X"
    RGB_args = rgb_mode_to_indexes(rgb_format)
    assert len(RGB_args)==4, "we need 4 RGB components (R,G,B and A or X), not: %s" % RGB_args
    kname = "%s_to_%s" % (yuv_format, indexes_to_rgb_mode(RGB_args))
    args = tuple([kname] + [YUV_TO_RGB[c] for c in rgb_format])
    kstr = """
__kernel void %s(read_only image2d_t srcY, uint strideY,
              read_only image2d_t srcU, uint strideU,
              read_only image2d_t srcV, uint strideV,
              uint w, uint h, write_only image2d_t dst) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);
    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP |
                           CLK_FILTER_NEAREST;

    if ((gx < w) & (gy < h)) {
        float4 p;

        float Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx, gy )).s0 - 0.0625;
        float Cr = read_imagef(srcU, sampler, (int2)( gx, gy )).s0 - 0.5f;
        float Cb = read_imagef(srcV, sampler, (int2)( gx, gy )).s0 - 0.5f;

        p.s0 = %s;
        p.s1 = %s;
        p.s2 = %s;
        p.s3 = %s;

        write_imagef(dst, (int2)( gx, gy ), p);
    }
}
"""
    return kname, kstr % args

def gen_yuv422p_to_rgb_kernel(yuv_format, rgb_format):
    assert len(rgb_format) in (3,4), "invalid destination rgb format: %s" % rgb_format
    if len(rgb_format)==3:
        #pad with empty channel:
        rgb_format = rgb_format+"X"
    RGB_args = rgb_mode_to_indexes(rgb_format)
    assert len(RGB_args)==4, "we need 4 RGB components (R,G,B and A or X), not: %s" % RGB_args
    kname = "%s_to_%s" % (yuv_format, indexes_to_rgb_mode(RGB_args))
    args = tuple([kname] + [YUV_TO_RGB[c] for c in rgb_format]*2)
    kstr = """
__kernel void %s(read_only image2d_t srcY, uint strideY,
              read_only image2d_t srcU, uint strideU,
              read_only image2d_t srcV, uint strideV,
              uint w, uint h, write_only image2d_t dst) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);
    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP |
                           CLK_FILTER_NEAREST;

    if ((gx*2 < w) & (gy < h)) {
        float4 p;

        float Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2, gy )).s0 - 0.0625;
        float Cr = read_imagef(srcU, sampler, (int2)( gx*2, gy )).s0 - 0.5f;
        float Cb = read_imagef(srcV, sampler, (int2)( gx*2, gy )).s0 - 0.5f;

        p.s0 = %s;
        p.s1 = %s;
        p.s2 = %s;
        p.s3 = %s;

        write_imagef(dst, (int2)( gx*2, gy ), p);

        if (gx*2+1 < w) {
            Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2+1, gy )).s0 - 0.0625;

            p.s0 = %s;
            p.s1 = %s;
            p.s2 = %s;
            p.s3 = %s;

            write_imagef(dst, (int2)( gx*2+1, gy ), p);
        }
    }
}
"""
    return kname, kstr % args

def gen_yuv420p_to_rgb_kernel(yuv_format, rgb_format):
    assert len(rgb_format) in (3,4), "invalid destination rgb format: %s" % rgb_format
    if len(rgb_format)==3:
        #pad with empty channel:
        rgb_format = rgb_format+"X"
    RGB_args = rgb_mode_to_indexes(rgb_format)
    assert len(RGB_args)==4, "we need 4 RGB components (R,G,B and A or X), not: %s" % RGB_args
    kname = "%s_to_%s" % (yuv_format, indexes_to_rgb_mode(RGB_args))
    args = tuple([kname] + [YUV_TO_RGB[c] for c in rgb_format]*4)
    kstr = """
__kernel void %s(read_only image2d_t srcY, uint strideY,
              read_only image2d_t srcU, uint strideU,
              read_only image2d_t srcV, uint strideV,
              uint w, uint h, write_only image2d_t dst) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);
    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP |
                           CLK_FILTER_NEAREST;

    if ((gx*2 < w) & (gy*2 < h)) {
        float4 p;

        float Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2, gy*2 )).s0 - 0.0625;
        float Cr = read_imagef(srcU, sampler, (int2)( gx*2, gy*2 )).s0 - 0.5f;
        float Cb = read_imagef(srcV, sampler, (int2)( gx*2, gy*2 )).s0 - 0.5f;

        p.s0 = %s;
        p.s1 = %s;
        p.s2 = %s;
        p.s3 = %s;

        write_imagef(dst, (int2)( gx*2, gy*2 ), p);

        if (gx*2+1 < w) {
            Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2+1, gy*2 )).s0 - 0.0625;

            p.s0 = %s;
            p.s1 = %s;
            p.s2 = %s;
            p.s3 = %s;

            write_imagef(dst, (int2)( gx*2+1, gy*2 ), p);
        }

        if (gy*2+1 < h) {
            Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2, gy*2+1 )).s0 - 0.0625;

            p.s0 = %s;
            p.s1 = %s;
            p.s2 = %s;
            p.s3 = %s;

            write_imagef(dst, (int2)( gx*2, gy*2+1 ), p);

            if (gx*2+1 < w) {
                Y = 1.1643 * read_imagef(srcY, sampler, (int2)( gx*2+1, gy*2+1 )).s0 - 0.0625;

                p.s0 = %s;
                p.s1 = %s;
                p.s2 = %s;
                p.s3 = %s;

                write_imagef(dst, (int2)( gx*2+1, gy*2+1 ), p);
            }
        }
    }
}
"""
    return kname, kstr % args


YUV_to_RGB_generators = {
                    "YUV444P"   : gen_yuv444p_to_rgb_kernel,
                    "YUV422P"   : gen_yuv422p_to_rgb_kernel,
                    "YUV420P"   : gen_yuv420p_to_rgb_kernel,
                    }
def gen_yuv_to_rgb_kernels(rgb_mode="RGBX", yuv_modes=YUV_FORMATS):
    YUV_to_RGB_KERNELS = {}
    for yuv in yuv_modes:
        gen = YUV_to_RGB_generators.get(yuv)
        YUV_to_RGB_KERNELS[(yuv, rgb_mode)] = gen(yuv, rgb_mode)
    return YUV_to_RGB_KERNELS




def gen_rgb_to_yuv444p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)
    #kernel args: R, G, B are used 3 times each:
    kname = "%s_to_YUV444P" % indexes_to_rgb_mode(RGB_args)
    args = tuple([kname]+RGB_args*3)

    kstr = """
__kernel void %s(read_only image2d_t src,
              uint w, uint h,
              global uchar *dstY, uint strideY,
              global uchar *dstU, uint strideU,
              global uchar *dstV, uint strideV) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);

    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP |
                           CLK_FILTER_NEAREST;
    //CLK_FILTER_LINEAR
    //const sampler_t sampler = 0;

    if ((gx < w) & (gy < h)) {
        uint4 p = read_imageui(src, sampler, (int2)( gx, gy ));

        float Y =  (0.257 * p.s%s + 0.504 * p.s%s + 0.098 * p.s%s + 16);
        float U = (-0.148 * p.s%s - 0.291 * p.s%s + 0.439 * p.s%s + 128);
        float V =  (0.439 * p.s%s - 0.368 * p.s%s - 0.071 * p.s%s + 128);

        dstY[gx + gy*strideY] = convert_uchar_rte(Y);
        dstU[gx + gy*strideU] = convert_uchar_rte(U);
        dstV[gx + gy*strideV] = convert_uchar_rte(V);
    }
}
"""
    return kname, kstr % args

def gen_rgb_to_yuv422p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)
    #kernel args: R, G, B are used 6 times each:
    kname = "%s_to_YUV422P" % indexes_to_rgb_mode(RGB_args)
    args = tuple([kname]+RGB_args*6)

    kstr = """
__kernel void %s(read_only image2d_t src,
              uint w, uint h,
              global uchar *dstY, uint strideY,
              global uchar *dstU, uint strideU,
              global uchar *dstV, uint strideV) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);

    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP_TO_EDGE |
                           CLK_FILTER_NEAREST;
    //CLK_FILTER_LINEAR
    if ((gx*2 < w) & (gy < h)) {
        uint4 p1 = read_imageui(src, sampler, (int2)( gx*2, gy ));
        uint4 p2 = p1;

        //write up to 2 Y pixels:
        float Y1 =  (0.257 * p1.s%s + 0.504 * p1.s%s + 0.098 * p1.s%s + 16);
        uint i = gx*2 + gy*strideY;
        dstY[i] = convert_uchar_rte(Y1);
        //we process two pixels at a time
        //if the source width is odd, this destination pixel may not exist (right edge of picture)
        //(we only read it via CLAMP_TO_EDGE to calculate U and V, which do exist)
        if (gx*2+1 < w) {
            p2 = read_imageui(src, sampler, (int2)( gx*2+1, gy ));
            float Y2 =  (0.257 * p2.s%s + 0.504 * p2.s%s + 0.098 * p2.s%s + 16);
            dstY[i+1] = convert_uchar_rte(Y2);
        }

        //write 1 U pixel:
        float U1 = (-0.148 * p1.s%s - 0.291 * p1.s%s + 0.439 * p1.s%s + 128);
        float U2 = (-0.148 * p2.s%s - 0.291 * p2.s%s + 0.439 * p2.s%s + 128);
        //some algorithms just ignore U2, we do not and use an average
        //dstU[gx + gy*strideU] = convert_uchar_rte(U1);
        dstU[gx + gy*strideU] = convert_uchar_rte((U1+U2)/2.0);

        //write 1 V pixel:
        float V1 =  (0.439 * p1.s%s - 0.368 * p1.s%s - 0.071 * p1.s%s + 128);
        float V2 =  (0.439 * p2.s%s - 0.368 * p2.s%s - 0.071 * p2.s%s + 128);
        //some algorithms just ignore V2, we do not and use an average
        //dstV[gx + gy*strideV] = convert_uchar_rte(V1);
        dstV[gx + gy*strideV] = convert_uchar_rte((V1+V2)/2.0);
    }
}
"""
    return kname, kstr % args


def gen_rgb_to_yuv420p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)
    #kernel args: R, G, B are used 12 times each:
    kname = "%s_to_YUV420P" % indexes_to_rgb_mode(RGB_args)
    args = tuple([kname]+RGB_args*12)

    kstr = """
__kernel void %s(read_only image2d_t src,
              uint w, uint h,
              global uchar *dstY, uint strideY,
              global uchar *dstU, uint strideU,
              global uchar *dstV, uint strideV) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);

    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP_TO_EDGE |
                           CLK_FILTER_NEAREST;
    //CLK_FILTER_LINEAR
    if ((gx*2 < w) & (gy*2 < h)) {
        uint4 p1 = read_imageui(src, sampler, (int2)( gx*2, gy*2 ));
        uint4 p2 = p1;
        uint4 p3 = p1;
        uint4 p4 = p1;

        //write up to 4 Y pixels:
        float Y1 =  (0.257 * p1.s%s + 0.504 * p1.s%s + 0.098 * p1.s%s + 16);
        //same logic as 422P for missing pixels:
        uint i = gx*2 + gy*2*strideY;
        dstY[i] = convert_uchar_rte(Y1);
        if (gx*2+1 < w) {
            p2 = read_imageui(src, sampler, (int2)( gx*2+1, gy*2 ));
            float Y2 =  (0.257 * p2.s%s + 0.504 * p2.s%s + 0.098 * p2.s%s + 16);
            dstY[i+1] = convert_uchar_rte(Y2);
        }
        if (gy*2+1 < h) {
            i += strideY;
            p3 = read_imageui(src, sampler, (int2)( gx*2, gy*2+1 ));
            float Y3 =  (0.257 * p3.s%s + 0.504 * p3.s%s + 0.098 * p3.s%s + 16);
            dstY[i] = convert_uchar_rte(Y3);
            if (gx*2+1 < w) {
                p4 = read_imageui(src, sampler, (int2)( gx*2+1, gy*2+1 ));
                float Y4 =  (0.257 * p4.s%s + 0.504 * p4.s%s + 0.098 * p4.s%s + 16);
                dstY[i+1] = convert_uchar_rte(Y4);
            }
        }

        //write 1 U pixel:
        float U1 = (-0.148 * p1.s%s - 0.291 * p1.s%s + 0.439 * p1.s%s + 128);
        float U2 = (-0.148 * p2.s%s - 0.291 * p2.s%s + 0.439 * p2.s%s + 128);
        float U3 = (-0.148 * p3.s%s - 0.291 * p3.s%s + 0.439 * p3.s%s + 128);
        float U4 = (-0.148 * p4.s%s - 0.291 * p4.s%s + 0.439 * p4.s%s + 128);
        dstU[gx + gy*strideU] = convert_uchar_rte((U1+U2+U3+U4)/4.0);

        //write 1 V pixel:
        float V1 =  (0.439 * p1.s%s - 0.368 * p1.s%s - 0.071 * p1.s%s + 128);
        float V2 =  (0.439 * p2.s%s - 0.368 * p2.s%s - 0.071 * p2.s%s + 128);
        float V3 =  (0.439 * p3.s%s - 0.368 * p3.s%s - 0.071 * p3.s%s + 128);
        float V4 =  (0.439 * p4.s%s - 0.368 * p4.s%s - 0.071 * p4.s%s + 128);
        dstV[gx + gy*strideV] = convert_uchar_rte((V1+V2+V3+V4)/4.0);
    }
}
"""
    return kname, kstr % args


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
