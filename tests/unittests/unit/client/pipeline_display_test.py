#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.gtk.dialogs.session_info import format_encoder_pipeline


class PipelineDisplayTest(unittest.TestCase):

	def test_encoder_only(self):
		assert format_encoder_pipeline("webp") == "webp"

	def test_encoder_and_renderer(self):
		assert format_encoder_pipeline("webp", renderer="OpenGL") == "webp \u2192 OpenGL"

	def test_full_pipeline(self):
		assert format_encoder_pipeline("nvenc", decoder="mf", renderer="OpenGL") == "nvenc \u2192 mf \u2192 OpenGL"

	def test_encoder_and_decoder_no_renderer(self):
		assert format_encoder_pipeline("nvenc", decoder="openh264") == "nvenc \u2192 openh264"

	def test_no_decoder_with_renderer(self):
		assert format_encoder_pipeline("png", renderer="Cairo") == "png \u2192 Cairo"

	def test_renderer_only(self):
		assert format_encoder_pipeline("", renderer="OpenGL") == "OpenGL"

	def test_empty(self):
		assert format_encoder_pipeline("") == ""


def main():
	unittest.main()


if __name__ == '__main__':
	main()
