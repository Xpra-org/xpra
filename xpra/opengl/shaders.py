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

# same for the offset:
#  Y: 16/255 = 0.062745098
#  U and V: 0.5 + 0.062745098 = 0.562745098

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

from xpra.codecs.constants import get_subsampling_divs

GLSL_VERSION = "330 core"

CS_MULTIPLIERS: dict[str, tuple[float, float, float, float, float]] = {
    "bt601": (0.299, 0.587, 0.114, 1.772, 1.402),
    "bt709": (0.2126, 0.7152, 0.0722, 1.8556, 1.5748),
    "bt2020": (0.2627, 0.6780, 0.0593, 1.8814, 1.4746),
}


def gen_YUV_to_RGB(fmt="YUV420P", cs="bt601", full_range=True) -> str:
    if cs not in CS_MULTIPLIERS:
        raise ValueError(f"unsupported colorspace {cs}")

    a, b, c, d, e = CS_MULTIPLIERS[cs]
    f = - c * d / b
    g = - a * e / b
    ymult = "" if full_range else " * 1.1643835616438356"
    uvmult = "" if full_range else " * 1.1383928571428572"
    yoffset = "" if full_range else " - 0.062745098"
    defines = []

    def add_div(name: str, xdiv=1, ydiv=1):
        if xdiv == ydiv:
            # just divide by the same integer:
            # ie: "#define Ydiv 1"
            value = xdiv
        else:
            # store each component in a vector:
            # ie: "#define Udiv vec2(2, 1)"
            value = f"vec2({xdiv}, {ydiv})"
        defines.append(f"{name}div {value}")

    divs = get_subsampling_divs(fmt)
    for i, div in enumerate(divs):
        add_div("YUVA"[i], *div)

    has_alpha = fmt.find("A") >= 0
    if has_alpha:
        alphasampler = "uniform sampler2DRect A;"
        alpha = "texture(A, pos/Adiv).r"
    else:
        alphasampler = ""
        alpha = "1.0"

    defines_str = "\n".join(f"#define {define}" for define in defines)
    return f"""
#version {GLSL_VERSION}
layout(origin_upper_left) in vec4 gl_FragCoord;
{defines_str}
uniform vec2 viewport_pos;
uniform vec2 scaling;
uniform sampler2DRect Y;
uniform sampler2DRect U;
uniform sampler2DRect V;
{alphasampler}
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 pos = (gl_FragCoord.xy-viewport_pos.xy)/scaling;
    highp float y = (texture(Y, pos/Ydiv).r{yoffset}){ymult};
    highp float u = (texture(U, pos/Udiv).r - 0.5){uvmult};
    highp float v = (texture(V, pos/Vdiv).r - 0.5){uvmult};
    highp float a = {alpha};

    highp float r = y +           {e} * v;
    highp float g = y + {f} * u + {g} * v;
    highp float b = y + {d} * u;

    frag_color = vec4(r, g, b, a);
}}
"""


def gen_NV12_to_RGB(cs="bt601", full_range=True) -> str:
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
uniform vec2 scaling;
uniform sampler2DRect Y;
uniform sampler2DRect UV;
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 pos = (gl_FragCoord.xy-viewport_pos.xy)/scaling;
    highp float y = texture(Y, pos).r {ymult};
    highp float u = (texture(UV, pos).r - 0.5) {umult};
    highp float v = (texture(UV, pos).g - 0.5) {vmult};

    highp float r = y +           {e} * v;
    highp float g = y + {f} * u + {g} * v;
    highp float b = y + {d} * u;

    frag_color = vec4(r, g, b, 1.0);
}}
"""


VERTEX_SHADER = f"""
#version {GLSL_VERSION}
layout(location=0) in vec4 position;

void main()
{{
    gl_Position = vec4(position.x, position.y, 1, 1);
}}
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
    frag_color = texture(rgba, mod(pos, textureSize(rgba)));
    if ( frag_color.a < 0.3 ) {{
        discard;
    }}
}}
"""

BLEND_SHADER = f"""
#version {GLSL_VERSION}
layout(origin_upper_left) in vec4 gl_FragCoord;
uniform vec2 viewport_pos;
uniform sampler2DRect rgba;
uniform sampler2DRect dst;
uniform float weight = 0.5;
layout(location = 0) out vec4 frag_color;

void main()
{{
    vec2 tex_pos = gl_FragCoord.xy - viewport_pos.xy;
    vec4 tex_color = texture(rgba, mod(tex_pos, textureSize(rgba)));
    vec2 dst_pos = vec2(gl_FragCoord.x, textureSize(dst).y - gl_FragCoord.y);
    vec4 dst_color = texture(dst, dst_pos);

    float w = weight;
    if (tex_color.a < 0.01 ) {{
        w = 1.0;
    }}
    frag_color = mix(tex_color, dst_color, w);
}}
"""

FIXED_COLOR_SHADER = f"""
#version {GLSL_VERSION}
uniform vec4 color;
layout(location = 0) out vec4 frag_color;

void main()
{{
    frag_color = color;
}}
"""

SOURCE: dict[str, str] = {
    "blend": BLEND_SHADER,
    "vertex": VERTEX_SHADER,
    "overlay": OVERLAY_SHADER,
    "fixed-color": FIXED_COLOR_SHADER,
}

for full in (False, True):
    suffix = "_FULL" if full else ""
    SOURCE[f"NV12_to_RGB{suffix}"] = gen_NV12_to_RGB(full_range=full)

    for fmt in (
        "YUV420P", "YUV422P", "YUV444P",
        "YUVA420P", "YUVA422P", "YUVA444P",
    ):
        SOURCE[f"{fmt}_to_RGB{suffix}"] = gen_YUV_to_RGB(fmt, full_range=full)


def main() -> None:
    for shader, source in SOURCE.items():
        print("#"*80)
        print(f"#{shader}:")
        print()
        print(source)
        print()


if __name__ == "__main__":
    main()
