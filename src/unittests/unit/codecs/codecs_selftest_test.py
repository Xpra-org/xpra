#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
import unittest

from xpra.codecs import loader

SUSPEND_CODEC_ERROR_LOGGING = os.environ.get("XPRA_SUSPEND_CODEC_ERROR_LOGGING", "1")=="1"
try:
    TEST_CODECS = os.environ.get("XPRA_TEST_CODECS").split(",")
except AttributeError:
    TEST_CODECS = loader.ALL_CODECS


class TestDecoders(unittest.TestCase):

    def test_all_codecs_found(self):
        #the self tests would swallow the exceptions and produce a warning:
        loader.RUN_SELF_TESTS = False
        #loader.load_codecs()
        #test them all:
        for codec_name in TEST_CODECS:
            loader.load_codec(codec_name)
            codec = loader.get_codec(codec_name)
            if not codec:
                print("WARNING: codec '%s' not found" % (codec_name,))
                continue
            try:
                #try to suspend error logging for full tests,
                #as those may cause errors
                log = getattr(codec, "log", None)
                if SUSPEND_CODEC_ERROR_LOGGING and log and not log.is_debug_enabled():
                    log.logger.setLevel(logging.CRITICAL)
                init_module = getattr(codec, "init_module", None)
                #print("%s.init_module=%s" % (codec, init_module))
                if init_module:
                    try:
                        init_module()
                    except Exception as e:
                        print("cannot initialize %s: %s" % (codec, e))
                        print(" test skipped")
                        continue
                #print("found %s: %s" % (codec_name, codec))
                selftest = getattr(codec, "selftest", None)
                #print("selftest(%s)=%s" % (codec_name, selftest))
                if selftest:
                    selftest(True)
            finally:
                if log:
                    log.logger.setLevel(logging.DEBUG)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
