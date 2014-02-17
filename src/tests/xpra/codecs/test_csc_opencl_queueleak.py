#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import commands
import pyopencl     #@UnresolvedImport

def get_count():
    r, out = commands.getstatusoutput('ps -efL | wc -l')
    assert r==0
    return int(out)

def test_make_queue(context):
    print("test_make_queue(%s) start count=%s" % (context, get_count()))
    queue = pyopencl.CommandQueue(context)
    print("test_make_queue(%s) queue created: %s" % (context, get_count()))
    queue.finish()
    print("test_make_queue(%s) queue.finish(): %s" % (context, get_count()))
    del queue
    print("test_make_queue(%s) del queue: %s" % (context, get_count()))
    gc.collect()
    print("test_make_queue(%s) end count=%s" % (context, get_count()))

def test_queue_leak():
    opencl_platforms = pyopencl.get_platforms()
    assert len(opencl_platforms)>0
    devices = opencl_platforms[0].get_devices()
    assert len(devices)>0
    context = pyopencl.create_some_context(interactive=True)
    print("context=%s, devices=%s" % (context, context.get_info(pyopencl.context_info.DEVICES)))
    assert context
    kernel = """
__kernel void EXAMPLE(uint w, uint h) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);
}
"""
    program = pyopencl.Program(context, kernel)
    program.build()
    print("test_queue_leak() got program=%s" % program)
    test_make_queue(context)


def main():
    test_queue_leak()


if __name__ == "__main__":
    main()
