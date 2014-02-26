# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This file is vaguely inspired by code from socles, an OpenCL image processing library.
#
# Notes:
# * we use integer arithmetic by pre-multiplying coefficients by 2*20
#   and use a fast bit shift to get the result as an 8-bit unsigned char.
# * each Y/U/V channel is passed in as a single channel image2d
# * we allow downscaling
# * the image sampler is passed in (responsibility of the caller to choose the right one)
# * we deal with odd sized images gracefully by clamping the output (via runtime checks)
#   as well as the input (if sampler_t uses CLAMP_TO_EDGE)


YUV_TO_RGB = {"X"    : [255, "*", 1],
              "A"    : [255, "*", 1],
              "R"    : ["(", "Y", "*", 1.164, ")", "+", "(", "Cb", "*", 1.5958, ")"],
              "G"    : ["(", "Y", "*", 1.164, ")", "-", "(", "Cr", "*", 0.39173, ")", "-", "(", "Cb", "*", 0.8129, ")"],
              "B"    : ["(", "Y", "*", 1.164, ")", "+", "(", "Cr", "*", 2.017, ")"],
              }

def get_RGB_formulae(rgb_channel, bitshift=20):
    #given an RGB channel (R, G or B), return the formulae for it
    #which uses the named variables Y, Cb (aka U) and Cr (aka V)
    f = YUV_TO_RGB[rgb_channel]     #ie: ["Y", "+", 1.5958, "*", "Cb"]
    mf = []
    for i in range(len(f)):
        x = f[i]
        if x==1:
            if True:
                #special case optimization: "* 1" -> "<<2**bitshift"
                assert f[i-1] == "*"
                mf = mf[:-1]
                mf.append("<<")
                x = bitshift
            else:
                x = 2**bitshift
        elif type(x)==float:
            x = int(round(x*(2**bitshift)))    #1.5958 -> 1673318
        mf.append(x)
    return " ".join([str(x) for x in mf])


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
    args = [kname]
    bitshift = 20
    for x in rgb_format:
        args.append(x)
        args.append("(%s)>>%s" % (get_RGB_formulae(x, bitshift), bitshift))
        args.append(x)
    kstr = """
__kernel void %s(read_only image2d_t srcY, read_only image2d_t srcU, read_only image2d_t srcV,
              const uint srcw, const uint srch, const uint w, const uint h,
              const sampler_t sampler, write_only image2d_t dst) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    if ((gx < w) & (gy < h)) {
        const uint srcx = gx*srcw/w;
        const uint srcy = gy*srch/h;
        uint4 p;

        const int Y  = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;
        const int Cr = read_imageui(srcU, sampler, (int2)( srcx, srcy )).s0 - 128;
        const int Cb = read_imageui(srcV, sampler, (int2)( srcx, srcy )).s0 - 128;

        const int %s = %s;
        p.s0 = convert_uchar_sat_rte(%s);
        const int %s = %s;
        p.s1 = convert_uchar_sat_rte(%s);
        const int %s = %s;
        p.s2 = convert_uchar_sat_rte(%s);
        const int %s = %s;
        p.s3 = convert_uchar_sat_rte(%s);

        write_imageui(dst, (int2)( gx, gy ), p);
    }
}
"""
    return kname, kstr % tuple(args)

def gen_yuv422p_to_rgb_kernel(yuv_format, rgb_format):
    assert len(rgb_format) in (3,4), "invalid destination rgb format: %s" % rgb_format
    if len(rgb_format)==3:
        #pad with empty channel:
        rgb_format = rgb_format+"X"
    RGB_args = rgb_mode_to_indexes(rgb_format)
    assert len(RGB_args)==4, "we need 4 RGB components (R,G,B and A or X), not: %s" % RGB_args
    kname = "%s_to_%s" % (yuv_format, indexes_to_rgb_mode(RGB_args))
    args = [kname]
    bitshift = 20
    for x in rgb_format+rgb_format:
        args.append(x)
        args.append("(%s)>>%s" % (get_RGB_formulae(x, bitshift), bitshift))
        args.append(x)
    kstr = """
__kernel void %s(read_only image2d_t srcY, read_only image2d_t srcU, read_only image2d_t srcV,
              const uint srcw, const uint srch, const uint w, const uint h,
              const sampler_t sampler, write_only image2d_t dst) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    if ((gx*2 < w) & (gy < h)) {
        uint4 p;

        uint srcx = gx*2*srcw/w;
        const uint srcy = gy*srch/h;
        int Y         = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;
        const int Cr  = read_imageui(srcU, sampler, (int2)( srcx/2, srcy )).s0 - 128;
        const int Cb  = read_imageui(srcV, sampler, (int2)( srcx/2, srcy )).s0 - 128;

        int %s = %s;
        p.s0 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s1 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s2 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s3 = convert_uchar_sat_rte(%s);

        write_imageui(dst, (int2)( gx*2, gy ), p);

        if (gx*2+1 < w) {
            srcx = (gx*2+1)*srcw/w;
            Y = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;

            %s = %s;
            p.s0 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s1 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s2 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s3 = convert_uchar_sat_rte(%s);

            write_imageui(dst, (int2)( gx*2+1, gy ), p);
        }
    }
}
"""
    return kname, kstr % tuple(args)

def gen_yuv420p_to_rgb_kernel(yuv_format, rgb_format):
    assert len(rgb_format) in (3,4), "invalid destination rgb format: %s" % rgb_format
    if len(rgb_format)==3:
        #pad with empty channel:
        rgb_format = rgb_format+"X"
    RGB_args = rgb_mode_to_indexes(rgb_format)
    assert len(RGB_args)==4, "we need 4 RGB components (R,G,B and A or X), not: %s" % RGB_args
    kname = "%s_to_%s" % (yuv_format, indexes_to_rgb_mode(RGB_args))
    #convert rgb_format into list of 4 channel values:
    args = [kname]
    bitshift = 20
    for x in rgb_format*4:
        args.append(x)
        args.append("(%s)>>%s" % (get_RGB_formulae(x, bitshift), bitshift))
        args.append(x)
    kstr = """
__kernel void %s(read_only image2d_t srcY, read_only image2d_t srcU, read_only image2d_t srcV,
              const uint srcw, const uint srch, const uint w, const uint h,
              const sampler_t sampler, write_only image2d_t dst) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    const uint x = gx*2;
    const uint y = gy*2;
    if ((x < w) & (y < h)) {
        uint4 p;

        uint srcx = x*srcw/w;
        uint srcy = y*srch/h;

        //Y = 1.1643 * p.s0 - 0.0625
        //Y*2**20  = 1220857 * v - 65536
        //Cb*2**20 = 2**20 * v - 2**19;
        //Cr*2**20 = 2**20 * v - 2**19;
        int Y         = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;
        const int Cr  = read_imageui(srcU, sampler, (int2)( srcx/2, srcy/2 )).s0 - 128;
        const int Cb  = read_imageui(srcV, sampler, (int2)( srcx/2, srcy/2 )).s0 - 128;

        int %s = %s;
        p.s0 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s1 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s2 = convert_uchar_sat_rte(%s);
        int %s = %s;
        p.s3 = convert_uchar_sat_rte(%s);

        write_imageui(dst, (int2)( x, y ), p);

        if (x+1 < w) {
            srcx = (x+1)*srcw/w;
            Y = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;

            %s = %s;
            p.s0 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s1 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s2 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s3 = convert_uchar_sat_rte(%s);

            write_imageui(dst, (int2)( x+1, y ), p);
        }

        if (y+1 < h) {
            srcx = x*srcw/w;
            srcy = (y+1)*srch/h;
            Y = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;

            %s = %s;
            p.s0 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s1 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s2 = convert_uchar_sat_rte(%s);
            %s = %s;
            p.s3 = convert_uchar_sat_rte(%s);

            write_imageui(dst, (int2)( x, y+1 ), p);

            if (x+1 < w) {
                srcx = (x+1)*srcw/w;
                Y = read_imageui(srcY, sampler, (int2)( srcx, srcy )).s0 - 16;

                %s = %s;
                p.s0 = convert_uchar_sat_rte(%s);
                %s = %s;
                p.s1 = convert_uchar_sat_rte(%s);
                %s = %s;
                p.s2 = convert_uchar_sat_rte(%s);
                %s = %s;
                p.s3 = convert_uchar_sat_rte(%s);

                write_imageui(dst, (int2)( x+1, y+1 ), p);
            }
        }
    }
}
"""
    return kname, kstr % tuple(args)


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


RGB_TO_YUV = {"Y"   : [0.257,  "*", "R", "+", 0.504, "*", "G", "+", 0.098, "*", "B", "+", 16],
              "U"   : [-0.148, "*", "R", "-", 0.291, "*", "G", "+", 0.439, "*", "B", "+", 128],
              "V"   : [0.439,  "*", "R", "-", 0.368, "*", "G", "-", 0.071, "*", "B", "+", 128],
              }

def get_YUV_formulae(yuv_channel, fmult=2**20, imult=2**20):
    #given an YUV channel (Y, U or V), return the formulae for it
    #which uses the named variables R, G and B
    f = RGB_TO_YUV[yuv_channel]     #ie: ["Y", "+", 1.5958, "*", "Cb"]
    mf = []
    for x in f:
        if type(x)==float:
            x = int(round(x*fmult))         #-0.148 -> -155189
        elif type(x)==int:
            x = int(round(x*imult))         #16 -> 16777216
        mf.append(x)
    return " ".join([str(x) for x in mf])

def get_YUV(yuv_channel, R, G, B, exp=0):
    #exp is how much we bitshift by extra
    #(ie: if R,G and B contain the sum of 4 pixels
    # we bit shift by 2 to get the results
    # the tricky thing is that the floats in the expression
    # are multiplied by 2**p, but the ints by 2**(p+exp)
    # because the ints are not multiplied by R,G or B!)
    p = 20
    f = get_YUV_formulae(yuv_channel, fmult=2**p, imult=2**(p+exp))
    #substitute R, G and B:
    f = f.replace("R", R).replace("G", G).replace("B", B)
    return "(%s)>>%s" % (f, p+exp)

def gen_rgb_to_yuv444p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)
    R = RGB_args[0]                     #ie: 0
    G = RGB_args[1]                     #ie: 1
    B = RGB_args[2]                     #ie: 2
    kname = "%s_to_YUV444P" % indexes_to_rgb_mode(RGB_args)
    #kernel args:
    args = [kname]
    #consts:
    pR = "p.s%s" % R
    pG = "p.s%s" % G
    pB = "p.s%s" % B
    #one U pixel with the sum:
    Y = get_YUV("Y", pR, pG, pB)
    U = get_YUV("U", pR, pG, pB)
    V = get_YUV("V", pR, pG, pB)
    args += [Y, U, V]

    kstr = """
__kernel void %s(read_only image2d_t src,
              const uint srcw, const uint srch, const uint w, const uint h,
              const sampler_t sampler,
              global uchar *dstY, const uint strideY,
              global uchar *dstU, const uint strideU,
              global uchar *dstV, const uint strideV) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    if ((gx < w) & (gy < h)) {
        const uint4 p = read_imageui(src, sampler, (int2)( (gx*srcw)/w, (gy*srch)/h ));

        dstY[gx + gy*strideY] = convert_uchar_sat_rte(%s);
        dstU[gx + gy*strideU] = convert_uchar_sat_rte(%s);
        dstV[gx + gy*strideV] = convert_uchar_sat_rte(%s);
    }
}
"""
    return kname, kstr % tuple(args)

def gen_rgb_to_yuv422p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)
    R = RGB_args[0]                     #ie: 0
    G = RGB_args[1]                     #ie: 1
    B = RGB_args[2]                     #ie: 2
    kname = "%s_to_YUV422P" % indexes_to_rgb_mode(RGB_args)
    #kernel args:
    args = [kname]
    #2 Y pixels:
    for i in range(2):
        Y = get_YUV("Y", "p[%s].s%s" % (i, R), "p[%s].s%s" % (i, G), "p[%s].s%s" % (i, B))
        args.append(Y)
    #consts:
    RR = "+".join(["p[%s].s%s" % (i, R) for i in range(2)])
    GG = "+".join(["p[%s].s%s" % (i, G) for i in range(2)])
    BB = "+".join(["p[%s].s%s" % (i, B) for i in range(2)])
    #one U pixel with the sum:
    U = get_YUV("U", "R", "G", "B", exp=1)
    V = get_YUV("V", "R", "G", "B", exp=1)
    args += [RR, GG, BB, U, V]

    kstr = """
__kernel void %s(read_only image2d_t src,
              uint srcw, uint srch, uint w, uint h,
              const sampler_t sampler,
              global uchar *dstY, uint strideY,
              global uchar *dstU, uint strideU,
              global uchar *dstV, uint strideV) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    if ((gx*2 < w) & (gy < h)) {
        uint srcx = gx*2*srcw/w;
        const uint srcy = gy*srch/h;
        uint4 p[2];
        p[0] = read_imageui(src, sampler, (int2)( srcx, srcy ));
        p[1] = p[0];

        //write up to 2 Y pixels:
        const uint i = gx*2 + gy*strideY;
        dstY[i] = convert_uchar_sat_rte(%s);
        //we process two pixels at a time
        //if the source width is odd, this destination pixel may not exist (right edge of picture)
        //(we only read it via CLAMP_TO_EDGE to calculate U and V, which do exist)
        if (gx*2+1 < w) {
            srcx = (gx*2+1)*srcw/w;
            p[1] = read_imageui(src, sampler, (int2)( srcx, srcy ));
            dstY[i+1] = convert_uchar_sat_rte(%s);
        }

        const int R = %s;
        const int G = %s;
        const int B = %s;
        //write 1 U pixel:
        dstU[gx + gy*strideU] = convert_uchar_sat_rte(%s);
        //write 1 V pixel:
        dstV[gx + gy*strideV] = convert_uchar_sat_rte(%s);
    }
}
"""
    return kname, kstr % tuple(args)

def gen_rgb_to_yuv420p_kernel(rgb_mode):
    RGB_args = rgb_indexes(rgb_mode)    #BGRX -> [2, 1, 0]
    R = RGB_args[0]                     #ie: 0
    G = RGB_args[1]                     #ie: 1
    B = RGB_args[2]                     #ie: 2
    kname = "%s_to_YUV420P" % indexes_to_rgb_mode(RGB_args)     # [0, 1, 2] -> RGB
    #kernel args:
    args = [kname]
    #4 Y pixels:
    for i in range(4):
        Y = get_YUV("Y", "p[%s].s%s" % (i, R), "p[%s].s%s" % (i, G), "p[%s].s%s" % (i, B))
        #ie: (roundint(0.257*2**20) * p[i].s2 + roundint(0.504*2**20) * p[i].s1 + roundint(0.098*2**20) * p[i].s0 + 16*2*20)>>20
        args.append(Y)
    #consts:
    RRRR = "+".join(["p[%s].s%s" % (i, R) for i in range(4)])
    GGGG = "+".join(["p[%s].s%s" % (i, G) for i in range(4)])
    BBBB = "+".join(["p[%s].s%s" % (i, B) for i in range(4)])
    #one U pixel with the sum:
    U = get_YUV("U", "R", "G", "B", exp=2)
    V = get_YUV("V", "R", "G", "B", exp=2)
    args += [RRRR, GGGG, BBBB, U, V]
    kstr = """
__kernel void %s(read_only image2d_t src,
              const uint srcw, const uint srch, const uint w, const uint h,
              const sampler_t sampler,
              global uchar *dstY, const uint strideY,
              global uchar *dstU, const uint strideU,
              global uchar *dstV, const uint strideV) {
    const uint gx = get_global_id(0);
    const uint gy = get_global_id(1);

    if ((gx*2 < w) & (gy*2 < h)) {
        uint srcx = gx*2*srcw/w;
        uint srcy = gy*2*srch/h;
        uint4 p[4];
        p[0] = read_imageui(src, sampler, (int2)( srcx, srcy ));
        p[1] = p[0];
        p[2] = p[0];
        p[3] = p[0];

        uint i = gx*2 + gy*2*strideY;
        dstY[i] = convert_uchar_sat_rte(%s);
        if (gx*2+1 < w) {
            srcx = (gx*2+1)*srcw/w;
            p[1] = read_imageui(src, sampler, (int2)( srcx, srcy ));
            dstY[i+1] = convert_uchar_sat_rte(%s);
        }
        if (gy*2+1 < h) {
            i += strideY;
            srcx = gx*2*srcw/w;
            srcy = (gy*2+1)*srch/h;
            p[2] = read_imageui(src, sampler, (int2)( srcx, srcy ));
            dstY[i] = convert_uchar_sat_rte(%s);
            if (gx*2+1 < w) {
                srcx = (gx*2+1)*srcw/w;
                p[3] = read_imageui(src, sampler, (int2)( srcx, srcy ));
                dstY[i+1] = convert_uchar_sat_rte(%s);
            }
        }

        const int R = %s;
        const int G = %s;
        const int B = %s;
        //write 1 U pixel:
        dstU[gx + gy*strideU] = convert_uchar_sat_rte(%s);
        //write 1 V pixel:
        dstV[gx + gy*strideV] = convert_uchar_sat_rte(%s);
    }
}
"""
    return kname, kstr % tuple(args)


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
