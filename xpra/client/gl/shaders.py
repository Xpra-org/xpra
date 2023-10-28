# The following 2 fragprogs are:
# * MIT X11 license, Copyright (c) 2007 by:
# *      Michael Dominic K. <mdk@mdk.am>
# http://www.mdk.org.pl/2007/11/17/gl-colorspace-conversions
# "full-color" version by Antoine Martin <antoine@xpra.org>

YUV_to_RGB = """
struct pixel_in {
    float2 texcoord1 : TEXCOORD0;
    float2 texcoord2 : TEXCOORD1;
    float2 texcoord3 : TEXCOORD2;
    uniform samplerRECT texture1 : TEXUNIT0;
    uniform samplerRECT texture2 : TEXUNIT1;
    uniform samplerRECT texture3 : TEXUNIT2;
    float4 color : COLOR0;
};

struct pixel_out {
    float4 color : COLOR0;
};

pixel_out
main (pixel_in IN)
{
    pixel_out OUT;

    float3 pre;

    pre.r = texRECT (IN.texture1, IN.texcoord1).x;
    pre.g = texRECT (IN.texture2, IN.texcoord2).x - (128.0 / 256.0);
    pre.b = texRECT (IN.texture3, IN.texcoord3).x - (128.0 / 256.0);

    const float3 red   = float3 (1/219, 0.0, 1.371/219) * 255.0;
    const float3 green = float3 (1/219, -0.336/219, -0.698/219) * 255.0;
    const float3 blue  = float3 (1/219, 1.732/219, 0.0) * 255.0;

    OUT.color.r = dot (red, pre);
    OUT.color.g = dot (green, pre);
    OUT.color.b = dot (blue, pre);
    OUT.color.a = IN.color.a;

    return OUT;
}
"""

YUV_to_RGB_FULL = """
struct pixel_in {
    float2 texcoord1 : TEXCOORD0;
    float2 texcoord2 : TEXCOORD1;
    float2 texcoord3 : TEXCOORD2;
    uniform samplerRECT texture1 : TEXUNIT0;
    uniform samplerRECT texture2 : TEXUNIT1;
    uniform samplerRECT texture3 : TEXUNIT2;
    float4 color : COLOR0;
};

struct pixel_out {
    float4 color : COLOR0;
};

pixel_out
main (pixel_in IN)
{
    pixel_out OUT;

    float3 pre;

    pre.r = texRECT (IN.texture1, IN.texcoord1).x;
    pre.g = texRECT (IN.texture2, IN.texcoord2).x - (128.0 / 256.0);
    pre.b = texRECT (IN.texture3, IN.texcoord3).x - (128.0 / 256.0);

    const float3 red   = float3 (1.0/255.0, 0.0, 1.371/255.0) * 255.0;
    const float3 green = float3 (1.0/255.0, -0.336/255.0, -0.698/255.0) * 255.0;
    const float3 blue  = float3 (1.0/255.0, 1.732/255.0, 0.0) * 255.0;

    OUT.color.r = dot (red, pre);
    OUT.color.g = dot (green, pre);
    OUT.color.b = dot (blue, pre);
    OUT.color.a = IN.color.a;

    return OUT;
}
"""

RGBP_to_RGB = """
struct pixel_in {
    float2 texcoord1 : TEXCOORD0;
    float2 texcoord2 : TEXCOORD1;
    float2 texcoord3 : TEXCOORD2;
    uniform samplerRECT texture1 : TEXUNIT0;
    uniform samplerRECT texture2 : TEXUNIT1;
    uniform samplerRECT texture3 : TEXUNIT2;
    float4 color : COLOR0;
};

struct pixel_out {
    float4 color : COLOR0;
};

pixel_out
main (pixel_in IN)
{
    pixel_out OUT;

    OUT.color.r = texRECT(IN.texture1, IN.texcoord1).r;
    OUT.color.g = texRECT(IN.texture2, IN.texcoord2).r;
    OUT.color.b = texRECT(IN.texture3, IN.texcoord3).r;
    OUT.color.a = IN.color.a;

    return OUT;
}
"""

NV12_to_RGB = """
struct pixel_in {
    float2 texcoord1 : TEXCOORD0;
    float2 texcoord2 : TEXCOORD1;
    uniform samplerRECT texture1 : TEXUNIT0;
    uniform samplerRECT texture2 : TEXUNIT1;
    float4 color : COLOR0;
};

struct pixel_out {
    float4 color : COLOR0;
};

pixel_out
main (pixel_in IN)
{
    pixel_out OUT;

    float3 pre;

    pre.r = texRECT (IN.texture1, IN.texcoord1).x - (16.0 / 256.0);
    pre.g = texRECT (IN.texture2, IN.texcoord2).x - (128.0 / 256.0);
    pre.b = texRECT (IN.texture2, IN.texcoord2).y - (128.0 / 256.0);

    const float3 red   = float3 (1.0/219.0, 0.0, 1.371/219.0) * 255.0;
    const float3 green = float3 (1.0/219.0, -0.336/219.0, -0.698/219.0) * 255.0;
    const float3 blue  = float3 (1.0/219.0, 1.732/219.0, 0.0) * 255.0;

    OUT.color.r = pre.r;
    OUT.color.g = pre.r;
    OUT.color.b = pre.r;
    OUT.color.a = IN.color.a;

    return OUT;
}
"""
