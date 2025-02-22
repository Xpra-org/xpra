#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
import unittest

from xpra.util.str_fn import csv
from xpra.common import noop
from xpra.codecs import loader
from xpra.codecs.constants import TransientCodecException

SUSPEND_CODEC_ERROR_LOGGING = os.environ.get("XPRA_SUSPEND_CODEC_ERROR_LOGGING", "1")=="1"
try:
    TEST_CODECS = os.environ.get("XPRA_TEST_CODECS").split(",")
except AttributeError:
    TEST_CODECS = loader.ALL_CODECS


class TestDecoders(unittest.TestCase):

    def test_all_codecs_found(self):
        # the self tests would swallow the exceptions and produce a warning:
        loader.RUN_SELF_TESTS = False
        # test them all:
        missing = []
        for codec_name in TEST_CODECS:
            loader.load_codec(codec_name)
            codec = loader.get_codec(codec_name)
            if not codec:
                missing.append(codec_name)
                continue
            try:
                # try to suspend error logging for full tests,
                # as those may cause errors
                log = getattr(codec, "log", None)
                if SUSPEND_CODEC_ERROR_LOGGING and log and not log.is_debug_enabled():
                    log.setLevel(logging.CRITICAL)
                init_module = getattr(codec, "init_module", noop)
                try:
                    init_module({})
                except Exception as e:
                    print("cannot initialize %s: %s" % (codec, e))
                    print(" test skipped")
                    continue

                selftest = getattr(codec, "selftest", noop)
                try:
                    selftest(True)
                except TransientCodecException as e:
                    print("ignoring TransientCodecException on %s : %s" % (codec, e))

                cleanup_module = getattr(codec, "cleanup_module", noop)
                cleanup_module()
            finally:
                if log:
                    log.setLevel(logging.DEBUG)
        if missing:
            print("Warning: the following codecs are missing and have not been tested:")
            print(f" {csv(missing)}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
