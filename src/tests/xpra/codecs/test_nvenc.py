#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs import test_nvenc_util

def main():
    from xpra.codecs.nvenc import encoder
    test_nvenc_util.set_encoder_module(encoder)
    test_nvenc_util.test_encode_one()
    #test_nvenc_util.test_context_leak()
    #test_nvenc_util.test_memleak()
    test_nvenc_util.test_dimensions()
    #test_nvenc_util.test_perf()
    #test_nvenc_util.test_encode_all_GPUs()
    #test_nvenc_util.test_context_limits()
    #test_nvenc_util.test_parallel_encode()


if __name__ == "__main__":
    main()
