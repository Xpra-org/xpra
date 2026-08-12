#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.audio.common import OPUS_RTP
from xpra.audio.gstreamer_util import (
    CODEC_ORDER, CODEC_OPTIONS, ENCODER_LATENCY,
    RTP_SINK_CAPS, parse_audio_source,
    get_source_plugins, get_wasapi_defaults,
)


class TestGStreamerUtilStatic(unittest.TestCase):
    """Tests that require no GStreamer installation."""

    def test_opus_rtp_in_codec_order(self):
        assert OPUS_RTP in CODEC_ORDER, f"{OPUS_RTP!r} missing from CODEC_ORDER"
        # must come after plain OPUS so it is never selected as the default
        opus_idx = list(CODEC_ORDER).index("opus")
        rtp_idx = list(CODEC_ORDER).index(OPUS_RTP)
        assert rtp_idx > opus_idx, "OPUS_RTP should appear after OPUS in CODEC_ORDER"

    def test_opus_rtp_in_codec_options(self):
        encodings = [entry[0] for entry in CODEC_OPTIONS]
        assert OPUS_RTP in encodings, f"{OPUS_RTP!r} missing from CODEC_OPTIONS"
        entry = next(e for e in CODEC_OPTIONS if e[0] == OPUS_RTP)
        encoding, encoder, payloader, decoder, depayloader, stream_compressor = entry
        assert encoder == "opusenc", f"unexpected encoder: {encoder!r}"
        assert payloader == "rtpopuspay", f"unexpected payloader: {payloader!r}"
        assert "rtpopusdepay" in decoder, f"rtpopusdepay missing from decoder chain: {decoder!r}"
        assert "opusdec" in decoder, f"opusdec missing from decoder chain: {decoder!r}"
        assert stream_compressor == "", "RTP codec should have no stream compressor"

    def test_opus_rtp_encoder_latency(self):
        assert OPUS_RTP in ENCODER_LATENCY, f"{OPUS_RTP!r} missing from ENCODER_LATENCY"
        assert ENCODER_LATENCY[OPUS_RTP] == 0

    def test_rtp_sink_caps_present(self):
        assert OPUS_RTP in RTP_SINK_CAPS, f"{OPUS_RTP!r} missing from RTP_SINK_CAPS"

    def test_rtp_sink_caps_content(self):
        caps = RTP_SINK_CAPS[OPUS_RTP]
        assert "application/x-rtp" in caps, f"missing media type in caps: {caps!r}"
        assert "encoding-name=OPUS" in caps, f"missing encoding-name in caps: {caps!r}"
        assert "clock-rate=48000" in caps, f"missing clock-rate in caps: {caps!r}"
        assert "payload=96" in caps, f"missing payload type in caps: {caps!r}"

    def test_rtp_sink_caps_payload_matches_payloader_default(self):
        # payload=96 must match rtpopuspay's default pt property.
        # If someone changes one they must change both — this test enforces that.
        caps = RTP_SINK_CAPS[OPUS_RTP]
        from xpra.audio.gstreamer_util import MUXER_DEFAULT_OPTIONS
        custom_pt = MUXER_DEFAULT_OPTIONS.get("rtpopuspay", {}).get("pt")
        if custom_pt is None:
            expected = 96   # rtpopuspay factory default
        else:
            expected = custom_pt
        assert f"payload={expected}" in caps, (
            f"payload in RTP_SINK_CAPS ({caps!r}) does not match "
            f"rtpopuspay pt={expected}"
        )

    def test_win32_source_order_prefers_wasapi(self):
        with patch("xpra.audio.gstreamer_util.POSIX", False), \
                patch("xpra.audio.gstreamer_util.OSX", False), \
                patch("xpra.audio.gstreamer_util.WIN32", True):
            sources = get_source_plugins()
        # `directsoundsrc` cannot capture the playback stream,
        # so it must come after both WASAPI plugins:
        assert sources.index("directsoundsrc") > sources.index("wasapisrc")
        assert sources.index("wasapisrc") > sources.index("wasapi2src")

    def test_wasapi_monitor_device_uses_loopback(self):
        # speaker forwarding captures what is being played back:
        assert get_wasapi_defaults("", True, None) == {"low-latency": True, "loopback": True}

    def test_wasapi_capture_device_without_loopback(self):
        # microphone forwarding records from a capture device:
        assert get_wasapi_defaults("", False, None) == {"low-latency": True}

    def test_wasapi_loopback_can_be_disabled(self):
        with patch("xpra.audio.gstreamer_util.WASAPI_LOOPBACK", False):
            assert get_wasapi_defaults("", True, None) == {"low-latency": True}

    def test_parse_wasapi_source_options(self):
        plugins = ("wasapi2src", "wasapisrc")
        for plugin in ("wasapi2", "wasapi"):
            gst_plugin, options = parse_audio_source(plugins, plugin, "", True, None)
            assert gst_plugin == f"{plugin}src"
            assert options["loopback"] is True
            # an explicit option must override the default:
            _, options = parse_audio_source(plugins, f"{plugin}:loopback=0", "", True, None)
            assert options["loopback"] == "0"


class TestGStreamerUtilPlugins(unittest.TestCase):
    """Tests that require GStreamer to be installed; skipped otherwise."""

    @classmethod
    def setUpClass(cls):
        from xpra.gstreamer.common import import_gst
        if import_gst() is None:
            raise unittest.SkipTest("GStreamer not available")

    def test_has_encoder_returns_bool(self):
        from xpra.audio.gstreamer_util import has_encoder
        result = has_encoder(OPUS_RTP)
        assert isinstance(result, bool)

    def test_has_decoder_returns_bool(self):
        from xpra.audio.gstreamer_util import has_decoder
        result = has_decoder(OPUS_RTP)
        assert isinstance(result, bool)

    def test_codec_registered_when_plugins_present(self):
        from xpra.audio.gstreamer_util import has_encoder, has_decoder, init_codecs, get_encoders, get_decoders
        if not (has_encoder(OPUS_RTP) and has_decoder(OPUS_RTP)):
            raise unittest.SkipTest("rtpopuspay / rtpopusdepay plugins not installed")
        init_codecs()
        assert OPUS_RTP in get_encoders(), f"{OPUS_RTP!r} not registered in encoders"
        assert OPUS_RTP in get_decoders(), f"{OPUS_RTP!r} not registered in decoders"

    def test_rtp_sink_caps_parseable(self):
        from xpra.gstreamer.common import import_gst
        Gst = import_gst()
        caps_str = RTP_SINK_CAPS[OPUS_RTP]
        caps = Gst.Caps.from_string(caps_str)
        assert caps is not None, f"Gst.Caps.from_string failed for: {caps_str!r}"
        assert not caps.is_empty(), f"parsed caps are empty for: {caps_str!r}"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
