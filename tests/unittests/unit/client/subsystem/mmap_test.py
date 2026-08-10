#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from contextlib import nullcontext
from xpra.os_util import WIN32
from xpra.util.objects import AdHocStruct, typedict
from xpra.client.subsystem import mmap
from xpra.net.mmap import objects

from unit.test_util import silence_info, silence_error
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


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
            opts.mmap_group = "none"
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

    def test_auto(self):
        # `auto` means `no` on MS Windows, where the server is very rarely local:
        opts = AdHocStruct()
        opts.mmap = "auto"
        opts.mmap_group = "none"
        m = mmap.MmapClient()
        m.init(opts)
        m.load()
        self.assertEqual(m.mmap_supported, not WIN32)
        self.assertEqual(m.mmap_read_area is None, WIN32)
        self.assertIsNone(m.mmap_write_area, "`auto` should never create a write area")
        self.assertFalse(m.get_caps().get("mmap", {}), "no mmap caps should be sent before the areas are mapped")
        m.cleanup()

    def test_unused_area_is_disabled(self):
        # a peer which does not write a token is not using the area:
        # the area must end up disabled so that it can be freed
        area = mmap.MmapArea("read")
        area.mmap = bytearray(1024)
        caps = typedict({"token": 0, "token_index": 0, "token_bytes": 128})
        with silence_info(objects):
            enabled = area.enable_from_caps(caps)
        assert not enabled, "the area should not be enabled without a valid token"
        assert not area.enabled, f"{area} should be disabled"

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
