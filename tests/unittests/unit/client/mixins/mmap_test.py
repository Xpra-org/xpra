#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from contextlib import nullcontext
from xpra.util.types import AdHocStruct
from xpra.client.mixins import mmap

from unit.test_util import silence_info, silence_error
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

	def test_mmap(self):
		class badfile:
			def close(self):
				raise Exception("test close failure handling")
		import tempfile
		tmp_dir = tempfile.gettempdir()
		for mmap_option, ctx in {
			"off" : nullcontext(),
			"on"  : silence_info(mmap),
			tmp_dir+"/xpra-mmap-test-file-%i" % os.getpid() : silence_info(mmap),
			tmp_dir+"/xpra-fail-mmap-test-file-%i" % os.getpid() : silence_error(mmap),
			}.items():
			opts = AdHocStruct()
			opts.mmap = mmap_option
			opts.mmap_group = False
			with ctx:
				m = self._test_mixin_class(mmap.MmapClient, opts, {
					"mmap.enabled"		: True,
					})
			fail = bool(m.mmap_filename) and m.mmap_filename.find("fail")>=0
			assert m.mmap_enabled == (mmap_option!="off" and not fail)
			assert len(self.exit_codes)==int(fail)
			m.cleanup()
			#no-op:
			m.cleanup()
			m.mmap_tempfile = badfile()
			m.cleanup()

	def make_caps(self, caps=None):
		d = super().make_caps(caps)
		x = self.mixin
		index = x.mmap_token_index
		if x.mmap_filename and x.mmap_filename.find("fail")>=0:
			index -= 10
		d["mmap"] = {
			"enabled"		: True,
			"token"			: x.mmap_token,
			"token_bytes"	: x.mmap_token_bytes,
			"token_index"	: index,
		}
		return d


def main():
	unittest.main()


if __name__ == '__main__':
	main()
