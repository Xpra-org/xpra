#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.clipboard.targets import (
    HTML_TARGETS,
    PLAIN_TEXT_TARGETS,
    TEXT_TARGETS,
    URI_TARGETS,
    _filter_targets,
    choose_eager_targets,
    must_discard,
    must_discard_extra,
)


class TestClipboardTargets(unittest.TestCase):

    def test_filter_keeps_valid(self):
        result = _filter_targets(["UTF8_STRING", "text/plain"])
        assert "UTF8_STRING" in result
        assert "text/plain" in result

    def test_filter_removes_discard(self):
        # "NeXTstep" matches ^NeXT pattern
        result = _filter_targets(["UTF8_STRING", "NeXTstep", "text/plain"])
        assert "NeXTstep" not in result
        assert "UTF8_STRING" in result

    def test_filter_removes_extra(self):
        # SAVE_TARGETS matches ^SAVE_TARGETS$ extra discard pattern
        result = _filter_targets(["UTF8_STRING", "SAVE_TARGETS"])
        assert "SAVE_TARGETS" not in result

    def test_must_discard(self):
        assert must_discard("NeXTstep")
        assert not must_discard("UTF8_STRING")

    def test_must_discard_extra(self):
        assert must_discard_extra("SAVE_TARGETS")
        assert not must_discard_extra("UTF8_STRING")

    def test_filter_empty(self):
        assert _filter_targets([]) == ()

    def test_filter_bytes_targets(self):
        # targets may arrive as bytes
        result = _filter_targets([b"UTF8_STRING", b"text/plain"])
        assert len(result) == 2

    def test_target_groups(self):
        assert "UTF8_STRING" in PLAIN_TEXT_TARGETS
        assert "text/plain" in PLAIN_TEXT_TARGETS
        assert "text/html" in HTML_TARGETS
        assert "text/uri-list" in URI_TARGETS
        assert "text/html" in TEXT_TARGETS
        assert not set(PLAIN_TEXT_TARGETS) & set(HTML_TARGETS)
        assert not set(PLAIN_TEXT_TARGETS) & set(URI_TARGETS)

    def test_choose_eager_targets(self):
        targets = ("custom", "text/html", "UTF8_STRING", "text/uri-list", "UTF8_STRING")
        assert choose_eager_targets(targets) == ("UTF8_STRING", "text/html", "text/uri-list")
        assert choose_eager_targets(targets, ("text/html", "custom")) == ("text/html",)
        assert choose_eager_targets(("custom",), ("custom",)) == ("custom",)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
