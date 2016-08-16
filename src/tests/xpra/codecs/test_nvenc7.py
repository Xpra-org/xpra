#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs import test_nvenc

def main():
    from xpra.codecs.nvenc7 import encoder
    test_nvenc.set_encoder_module(encoder)
    test_nvenc.test_encode_one()
    #test_nvenc.test_context_leak()
    #test_nvenc.test_memleak()
    test_nvenc.test_dimensions()
    #test_nvenc.test_perf()
    #test_nvenc.test_encode_all_GPUs()
    #test_nvenc.test_context_limits()
    #test_nvenc.test_parallel_encode()


if __name__ == "__main__":
    main()
