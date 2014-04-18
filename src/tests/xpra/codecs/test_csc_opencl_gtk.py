#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def test_load_both():
    import pyopencl     #@UnresolvedImport
    import gtk
    assert pyopencl and gtk
    print("test_load_both() OK")

def test_load_codec():
    from xpra.codecs.csc_opencl import colorspace_converter
    assert colorspace_converter
    import gtk.gdk
    assert gtk.gdk

def test_build_kernel():
    import pyopencl     #@UnresolvedImport
    opencl_platforms = pyopencl.get_platforms()
    assert len(opencl_platforms)>0
    devices = opencl_platforms[0].get_devices()
    assert len(devices)>0
    context = pyopencl.create_some_context(interactive=False)
    print("context=%s, devices=%s" % (context, context.get_info(pyopencl.context_info.DEVICES)))
    assert context
    kernel = """
__kernel void EXAMPLE(read_only image2d_t srcY, uint strideY,
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

        p.s0 = 1.0;
        p.s1 = 1.0;
        p.s2 = 1.0;
        p.s3 = 1.0;

        write_imagef(dst, (int2)( gx, gy ), p);
    }
}
"""
    program = pyopencl.Program(context, kernel)
    program.build()
    import gtk.gdk
    assert gtk.gdk
    print("test_build_kernel() OK")


def main():
    #test_load_both()
    #test_load_codec()
    test_build_kernel()


if __name__ == "__main__":
    main()
