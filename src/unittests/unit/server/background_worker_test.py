#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.server.background_worker import get_worker, add_work_item, stop_worker


class BackgroundWorkerTest(unittest.TestCase):

    def test_run(self):
        assert get_worker(False) is None
        w = get_worker()
        assert repr(w)
        def error_item():
            raise Exception("work item test error")
        add_work_item(error_item)
        def slow_item():
            time.sleep(1)
        #trigger the warning with more than 10 items:
        for _ in range(11):
            w.add(slow_item)
        stop_worker()
        stop_worker(True)
        #no-op:
        stop_worker(True)
        #let the worker print its messages:
        time.sleep(1)

def main():
    unittest.main()

if __name__ == '__main__':
    main()
