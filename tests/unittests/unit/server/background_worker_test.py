#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from unit.test_util import silence_error, LoggerSilencer
from xpra.util import background_worker
from xpra.util.background_worker import get_worker, add_work_item, stop_worker, WorkerThread


def slow_item():
    time.sleep(1)


class BackgroundWorkerTest(unittest.TestCase):

    def test_run(self):
        assert get_worker(False) is None
        w = get_worker()
        assert repr(w)

        def error_item():
            raise Exception("work item test error")

        with silence_error(background_worker):
            add_work_item(error_item)
            time.sleep(0.1)
        # add the same item twice, with "no-duplicates"
        # (should only get added once)
        ndc = []

        def nodupe():
            ndc.append(True)

        w.add(nodupe, False)
        w.add(nodupe, False)
        time.sleep(1)
        with LoggerSilencer(background_worker):
            # trigger the warning with more than 10 items:
            for _ in range(12):
                w.add(slow_item)
            stop_worker()
            stop_worker(True)
        # no-op:
        stop_worker(True)
        # let the worker print its messages:
        time.sleep(1)
        assert len(ndc) == 1, "nodupe item should have been run once only, got %i" % (len(ndc),)

    def test_normal_stop(self):
        w = WorkerThread()
        w.start()
        # noinspection PyTypeChecker
        w.add(None)
        time.sleep(1)
        assert w.exit is True


def main():
    unittest.main()


if __name__ == '__main__':
    main()
