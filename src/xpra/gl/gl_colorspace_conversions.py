# The following fragprog is:
# * MIT X11 license, Copyright (c) 2007 by:
# *      Michael Dominic K. <mdk@mdk.am>
#http://www.mdk.org.pl/2007/11/17/gl-colorspace-conversions

GL_COLORSPACE_CONVERSIONS = """!!ARBfp1.0
# cgc version 3.1.0010, build date Feb 10 2012
# command line args: -profile arbfp1
# source file: yuv.cg
#vendor NVIDIA Corporation
#version 3.1.0.10
#profile arbfp1
#program main
#semantic main.IN
#var float2 IN.texcoord1 : $vin.TEXCOORD0 : TEX0 : 0 : 1
#var float2 IN.texcoord2 : $vin.TEXCOORD1 : TEX1 : 0 : 1
#var float2 IN.texcoord3 : $vin.TEXCOORD2 : TEX2 : 0 : 1
#var samplerRECT IN.texture1 : TEXUNIT0 : texunit 0 : 0 : 1
#var samplerRECT IN.texture2 : TEXUNIT1 : texunit 1 : 0 : 1
#var samplerRECT IN.texture3 : TEXUNIT2 : texunit 2 : 0 : 1
#var float4 IN.color : $vin.COLOR0 : COL0 : 0 : 1
#var float4 main.color : $vout.COLOR0 : COL : -1 : 1
#const c[0] = 1.1643835 2.017231 0 0.5
#const c[1] = 0.0625 1.1643835 -0.3917616 -0.81296802
#const c[2] = 1.1643835 0 1.5960271
    PARAM c[3] = { { 1.1643835, 2.017231, 0, 0.5 },
            { 0.0625, 1.1643835, -0.3917616, -0.81296802 },
            { 1.1643835, 0, 1.5960271 } };
    TEMP R0;
    TEMP R1;
    TEX R0.x, fragment.texcoord[2], texture[2], RECT;
    ADD R1.z, R0.x, -c[0].w;
    TEX R1.x, fragment.texcoord[0], texture[0], RECT;
    TEX R0.x, fragment.texcoord[1], texture[1], RECT;
    ADD R1.x, R1, -c[1];
    ADD R1.y, R0.x, -c[0].w;
    DP3 result.color.z, R1, c[0];
    DP3 result.color.y, R1, c[1].yzww;
    DP3 result.color.x, R1, c[2];
    MOV result.color.w, fragment.color.primary;
    END
# 10 instructions, 2 R-regs
"""
