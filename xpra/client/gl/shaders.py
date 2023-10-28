# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

YUV_to_RGB = """
#version 330 core
out vec4 FragColor;
in vec2 texCoord;
uniform sampler2D Y;
uniform sampler2D U;
uniform sampler2D V;
void main()
{
    vec3 yuv, rgb;
    vec3 yuv2r = vec3(1.164, 0.0, 1.596);
    vec3 yuv2g = vec3(1.164, -0.391, -0.813);
    vec3 yuv2b = vec3(1.164, 2.018, 0.0);

    yuv.x = texture(Y, texCoord).r - 0.0625;
    yuv.y = texture(U, texCoord).r - 0.5;
    yuv.z = texture(V, texCoord).r - 0.5;

    rgb.x = dot(yuv, yuv2r);
    rgb.y = dot(yuv, yuv2g);
    rgb.z = dot(yuv, yuv2b);

    FragColor = vec4(rgb, 1.0);
}
"""

YUV_to_RGB_FULL = """
#version 330 core
out vec4 FragColor;
in vec2 texCoord;
uniform sampler2D Y;
uniform sampler2D U;
uniform sampler2D V;
void main()
{
    vec3 yuv, rgb;
    vec3 yuv2r = vec3(1.0, 0.0, 1.5960271);
    vec3 yuv2g = vec3(1.0, -0.3917616, -0.81296802);
    vec3 yuv2b = vec3(1.0, 2.017231, 0.0);

    yuv.x = texture(Y, texCoord).r;
    yuv.y = texture(U, texCoord).r - 0.5;
    yuv.z = texture(V, texCoord).r - 0.5;

    rgb.x = dot(yuv, yuv2r);
    rgb.y = dot(yuv, yuv2g);
    rgb.z = dot(yuv, yuv2b);

    FragColor = vec4(rgb, 1.0);
}
"""

NV12_to_RGB = """
#version 330 core
out vec4 FragColor;
in vec2 texCoord;
uniform sampler2D Y;
uniform sampler2D UV;
void main()
{
    vec3 yuv, rgb;
    vec3 yuv2r = vec3(1.0, 0.0, 1.5960271);
    vec3 yuv2g = vec3(1.0, -0.3917616, -0.81296802);
    vec3 yuv2b = vec3(1.0, 2.017231, 0.0);

    yuv.x = texture(Y, texCoord).r - 0.0625;
    yuv.y = texture(UV, texCoord).g - 0.5;
    yuv.z = texture(UV, texCoord).r - 0.5;

    rgb.x = dot(yuv, yuv2r);
    rgb.y = dot(yuv, yuv2g);
    rgb.z = dot(yuv, yuv2b);

    FragColor = vec4(rgb, 1.0);
}
"""
