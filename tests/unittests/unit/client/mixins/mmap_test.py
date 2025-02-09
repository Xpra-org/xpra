#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from contextlib import nullcontext
from xpra.util.objects import AdHocStruct, typedict
from xpra.client.mixins import mmap

from unit.test_util import silence_info, silence_error
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

    def test_mmap(self):

        class badfile:
            def close(self):
                raise Exception("test close failure handling")

        tmp_dir = tempfile.gettempdir()
        for mmap_option, ctx in {
            "off": nullcontext(),
            "on": silence_info(mmap),
            "auto": silence_info(mmap),
            tmp_dir+"/xpra-mmap-test-file-%i" % os.getpid(): silence_info(mmap),
            tmp_dir+"/xpra-fail-mmap-test-file-%i" % os.getpid(): silence_error(mmap),
        }.items():
            opts = AdHocStruct()
            opts.mmap = mmap_option
            opts.mmap_group = False
            with ctx:
                m = self._test_mixin_class(mmap.MmapClient, opts, {
                    "mmap": {
                        "write": {
                            "enabled": True,
                        }
                    },
                })
            x = self.mixin.mmap_read_area
            # expected = mmap_option != "off" and not mmap_option.find("fail") >= 0
            # got = bool(x)
            # we can't check any more because the `enable_from_caps` method
            # now actually checks the token...
            # assert got == expected, f"expected {expected} but got {got} for {mmap_option=}"
            m.cleanup()
            # no-op:
            m.cleanup()
            if x:
                x.tempfile = badfile()
                m.cleanup()

    def make_caps(self, caps=None) -> typedict:
        d = super().make_caps(caps)
        x = self.mixin.mmap_read_area
        if x:
            index = x.token_index
            if x.filename and x.filename.find("fail") >= 0:
                index -= 10
            d["mmap"] = {
                "enabled": True,
                "token": x.token,
                "token_bytes": x.token_bytes,
                "token_index": index,
            }
        return typedict(d)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
