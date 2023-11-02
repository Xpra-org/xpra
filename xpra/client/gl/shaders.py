# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# https://mymusing.co/full-range-vs-narrow-range-color/
# narrow range:
# Y (aka luma) component ranges from 16 to 235
#  hence: 255/(235-16) = 1.1643835616438356
# Cb and Cr (aka U and V) range from 16 to 240
#  hence: 255/(240-16) = 1.1383928571428572

# https://gist.github.com/yohhoy/dafa5a47dade85d8b40625261af3776a
# Y  = a * R + b * G + c * B
# Cb = (B - Y) / d
# Cr = (R - Y) / e
# BT.601	BT.709	BT.2020
# a	0.299	0.2126	0.2627
# b	0.587	0.7152	0.6780
# c	0.114	0.0722	0.0593
# d	1.772	1.8556	1.8814
# e	1.402	1.5748	1.4746
# R = Y + e * Cr
# G = Y - (a * e / b) * Cr - (c * d / b) * Cb
# B = Y + d * Cb

GLSL_VERSION = "330 core"

CS_MULTIPLIERS = {
    "bt601": (0.299, 0.587, 0.114, 1.772, 1.402),
    "bt709": (0.2126, 0.7152, 0.0722, 1.8556, 1.5748),
    "bt2020": (0.2627, 0.6780, 0.0593, 1.8814, 1.4746),
}


def gen_YUV_to_RGB(cs="bt601", full_range=True):
    if cs not in CS_MULTIPLIERS:
        raise ValueError(f"unsupported colorspace {cs}")
    a, b, c, d, e = CS_MULTIPLIERS[cs]
    f = - c * d / b
    g = - a * e / b
    ymult = "" if full_range else " * 1.1643835616438356"
    umult = vmult = "" if full_range else " * 1.1383928571428572"
    return f"""
#version {GLSL_VERSION}
layout(origin_upper_left) in vec4 gl_FragCoord;
uniform vec2 viewport_pos;
uniform sampler2DRect Y;
uniform sampler2DRect U;
uniform sampler2DRect V;
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 pos = gl_FragCoord.xy-viewport_pos.xy;
    highp float y = texture(Y, pos).r {ymult};
    highp float u = (texture(U, pos/2.0).r - 0.5) {umult};
    highp float v = (texture(V, pos/2.0).r - 0.5) {vmult};

    highp float r = y +           {e} * v;
    highp float g = y + {f} * u + {g} * v;
    highp float b = y + {d} * u;

    frag_color = vec4(r, g, b, 1.0);
}}
"""


def gen_NV12_to_RGB(cs="bt601"):
    if cs not in CS_MULTIPLIERS:
        raise ValueError(f"unsupported colorspace {cs}")
    a, b, c, d, e = CS_MULTIPLIERS[cs]
    f = - c * d / b
    g = - a * e / b
    return f"""
#version {GLSL_VERSION}
layout(origin_upper_left) in vec4 gl_FragCoord;
uniform vec2 viewport_pos;
uniform sampler2DRect Y;
uniform sampler2DRect UV;
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 pos = gl_FragCoord.xy-viewport_pos.xy;
    highp float y = texture(Y, pos).r;
    highp float u = texture(UV, pos).r - 0.5;
    highp float v = texture(UV, pos).g - 0.5;

    highp float r = y +           {e} * v;
    highp float g = y + {f} * u + {g} * v;
    highp float b = y + {d} * u;

    frag_color = vec4(r, g, b, 1.0);
}}
"""


VERTEX_SHADER = """
#version 330 core
layout(location=0) in vec4 position;

void main()
{
    gl_Position = vec4(position.x, position.y, 1, 1);
}
"""


OVERLAY_SHADER = f"""
#version {GLSL_VERSION}
layout(origin_upper_left) in vec4 gl_FragCoord;
uniform vec2 viewport_pos;
uniform sampler2DRect rgba;
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 pos = gl_FragCoord.xy-viewport_pos.xy;
    frag_color = texture(rgba, pos);
    if ( frag_color.a < 0.3 ) {{
        discard;
    }}
}}
"""


SOURCE = {
    "vertex": VERTEX_SHADER,
    "overlay": OVERLAY_SHADER,
    "NV12_to_RGB": gen_NV12_to_RGB(),
    "YUV_to_RGB": gen_YUV_to_RGB(),
    "YUV_to_RGB_FULL": gen_YUV_to_RGB(full_range=True),
}
