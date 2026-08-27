#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import threading

from xpra.codecs.image import ImageWrapper


def make_image() -> ImageWrapper:
    return ImageWrapper(0, 0, 4, 4, b"0"*4*4*4, "RGBX", 24, 4*4, thread_safe=True)


class TestImageWrapperLock(unittest.TestCase):

    def test_with_blocks_free_from_other_thread(self):
        img = make_image()
        entered = threading.Event()
        release = threading.Event()
        freed = threading.Event()

        def holder():
            with img:
                entered.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        assert entered.wait(5), "holder thread did not enter the critical section"
        assert not img.freed

        def freer():
            img.free()
            freed.set()

        f = threading.Thread(target=freer)
        f.start()
        # free() must block behind the still-open `with img:` block:
        assert not freed.wait(0.2)
        release.set()
        t.join(5)
        assert freed.wait(5), "free() never completed after the critical section exited"
        f.join(5)
        assert img.freed

    def test_free_inside_with_same_thread_no_deadlock(self):
        img = make_image()

        def run():
            with img:
                img.free()

        t = threading.Thread(target=run)
        t.start()
        t.join(2)
        assert not t.is_alive(), "free() inside a `with` block on the same thread deadlocked"
        assert img.freed

    def test_enter_on_freed_image_raises(self):
        img = make_image()
        img.free()
        with self.assertRaises(RuntimeError):
            with img:
                pass
        # the lock must not be left held after the raise:
        entered = threading.Event()

        def other_thread():
            try:
                with img:
                    pass
            except RuntimeError:
                pass
            finally:
                entered.set()

        t = threading.Thread(target=other_thread)
        t.start()
        assert entered.wait(2), "lock was left held after __enter__ raised on a freed image"
        t.join(2)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
