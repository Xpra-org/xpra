#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.server.background_worker import get_worker, add_work_item, stop_worker, Worker_Thread, log


class BackgroundWorkerTest(unittest.TestCase):

    def test_run(self):
        assert get_worker(False) is None
        w = get_worker()
        assert repr(w)
        def error_item():
            raise Exception("work item test error")
        #suspend error logging:
        try:
            saved = log.error
            log.error = log.debug
            add_work_item(error_item)
            time.sleep(0.1)
        finally:
            log.error = saved
        #add the same item twice, with "no-duplicates"
        #(should only get added once)
        ndc = []
        def nodupe():
            ndc.append(True)
        w.add(nodupe, False)
        w.add(nodupe, False)
        time.sleep(1)
        try:
            saved = (log.error, log.warn, log.info)
            log.error = log.warn = log.info = log.debug
            #trigger the warning with more than 10 items:
            def slow_item():
                time.sleep(1)
            for _ in range(12):
                w.add(slow_item)
            stop_worker()
            stop_worker(True)
        finally:
            log.error, log.warn, log.info = saved
        #no-op:
        stop_worker(True)
        #let the worker print its messages:
        time.sleep(1)
        assert len(ndc)==1, "nodupe item should have been run once only, got %i" % (len(ndc), )

    def test_normal_stop(self):
        w = Worker_Thread()
        w.start()
        w.add(None)
        time.sleep(1)
        assert w.exit is True

def main():
    unittest.main()

if __name__ == '__main__':
    main()
