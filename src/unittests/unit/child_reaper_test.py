#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import logging
import unittest
import subprocess

from xpra.os_util import OSEnvContext
from xpra import child_reaper
from xpra.child_reaper import getChildReaper, reaper_cleanup, log


class TestChildReaper(unittest.TestCase):

    def test_childreaper(self):
        for polling in (True, False):
            with OSEnvContext():
                os.environ["XPRA_USE_PROCESS_POLLING"] = str(int(polling))
                self.do_test_child_reaper()


    def do_test_child_reaper(self):
        #force reset singleton:
        child_reaper.singleton = None
        #no-op:
        reaper_cleanup()

        log.logger.setLevel(logging.ERROR)
        cr = getChildReaper()
        #one that exits before we add the process, one that takes longer:
        TEST_CHILDREN = (["echo"], ["sleep", "0.5"])
        count = 0
        for cmd in TEST_CHILDREN:
            cmd_info = " ".join(cmd)
            proc = subprocess.Popen(cmd)
            cr.add_process(proc, cmd_info, cmd_info, False, False, None)
            count += 1
            for _ in range(10):
                if not cr.check():
                    break
                time.sleep(0.1)
            #we can't check the returncode because it may not be set yet!
            #assert proc.poll() is not None, "%s process did not terminate?" % cmd_info
            assert cr.check() is False, "reaper did not notice that the '%s' process has terminated" % cmd_info
            i = cr.get_info()
            children = i.get("children").get("total")
            assert children==count, "expected %s children recorded, but got %s" % (count, children)

        #now check for the forget option:
        proc = subprocess.Popen(["sleep", "60"])
        procinfo = cr.add_process(proc, "sleep 60", "sleep 60", False, True, None)
        assert repr(procinfo)
        count +=1
        assert cr.check() is True, "sleep process terminated too quickly"
        i = cr.get_info()
        children = i.get("children").get("total")
        assert children==count, "expected %s children recorded, but got %s" % (count, children)
        #trying to claim it is dead when it is not:
        #(this will print some warnings)
        cr.add_dead_pid(proc.pid)
        proc.terminate()
        #now wait for the sleep process to exit:
        for _ in range(10):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None
        assert cr.check() is False, "sleep process did not terminate?"
        count -= 1
        i = cr.get_info()
        children = i.get("children").get("total")
        if children!=count:
            raise Exception("expected the sleep process to have been forgotten (%s children)" % count +
            "but got %s children instead in the reaper records" % children)
        reaper_cleanup()
        #can run again:
        reaper_cleanup()
        #nothing for an invalid pid:
        assert cr.get_proc_info(-1) is None


def main():
    from xpra.os_util import WIN32
    if not WIN32:
        unittest.main()

if __name__ == '__main__':
    main()
