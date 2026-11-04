#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The `opus+rtp` pipeline is meant for lossy transports (ie: QUIC datagrams):
verify that the playback side keeps producing audio when packets go missing.
"""

import time
import random
import unittest
from collections.abc import Callable
from unittest.mock import patch, Mock

from xpra.audio.common import OPUS, OPUS_OGG, OPUS_MKA, OPUS_RTP, FLAC
from xpra.gstreamer.common import import_gst, has_plugins

GST_PLUGINS = (
    "audiotestsrc", "audioconvert", "audioresample", "volume", "queue",
    "opusenc", "rtpopuspay", "rtpjitterbuffer", "rtpopusdepay", "opusdec",
    "appsrc", "appsink", "fakesink",
)
# opus+rtp packets are 20ms each:
PACKET_DURATION = 20
LOSS_PCT = 5


def get_gst():
    gst = import_gst()
    if not gst:
        raise unittest.SkipTest("GStreamer is not available")
    if not has_plugins(*GST_PLUGINS):
        raise unittest.SkipTest("some required GStreamer plugins are missing")
    from xpra.audio.gstreamer_util import get_encoders, get_decoders
    if OPUS_RTP not in get_encoders() or OPUS_RTP not in get_decoders():
        raise unittest.SkipTest(f"{OPUS_RTP!r} is not available")
    return gst


def encode_packets(gst, count: int, channels=0, wave="sine") -> list[bytes]:
    """ run the real capture pipeline elements, with a test source, and collect the RTP packets """
    from xpra.audio import src as audio_src
    from xpra.audio.gstreamer_util import get_encoder_elements
    encoder, fmt, _ = get_encoder_elements(OPUS_RTP)
    src_options = {"num-buffers": count, "samplesperbuffer": 48000 * PACKET_DURATION // 1000, "wave": wave}
    with patch.object(audio_src, "CUTTER_THRESHOLD", 0), \
            patch.object(audio_src, "_get_source_channels", return_value=channels):
        els = audio_src.get_source_pipeline_elements("audiotestsrc", src_options, encoder, fmt, {}, codec=OPUS_RTP)
    # the source queue is `leaky=downstream` with a 50ms limit, which is fine for a live
    # source but throws most of the stream away when a test source runs flat out:
    els = [el for el in els if not el.startswith("queue ")]
    els[-1] = "appsink name=sink sync=false"
    pipeline = gst.parse_launch(" ! ".join(els))
    sink = pipeline.get_by_name("sink")
    pipeline.set_state(gst.State.PLAYING)
    packets = []
    try:
        while sample := sink.emit("try-pull-sample", 10 * gst.SECOND):
            buf = sample.get_buffer()
            packets.append(buf.extract_dup(0, buf.get_size()))
    finally:
        pipeline.set_state(gst.State.NULL)
    assert len(packets) >= count, f"expected {count} packets, got {len(packets)}"
    return packets


def random_loss(count: int, pct=LOSS_PCT, seed=0) -> set[int]:
    """
    deterministic random loss of `pct` percent of the packets,
    sparing the head and tail of the stream where a loss cannot be detected from sequence numbers
    """
    lost = set(random.Random(seed).sample(range(5, count - 5), count * pct // 100))
    assert lost, "no packets lost"
    return lost


def feed(push: Callable[[bytes], None], packets: list[bytes], lost: set[int], order=None) -> None:
    """ push the packets at the rate they were produced, because the live appsrc timestamps them on arrival """
    order = order or list(range(len(packets)))
    start = time.monotonic()
    for slot, index in enumerate(order):
        delay = start + slot * PACKET_DURATION / 1000 - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        if index not in lost:
            push(packets[index])


class TestRTPPipelineElements(unittest.TestCase):
    """ No GStreamer needed """

    @staticmethod
    def sink_elements(codec: str, decoder="opusdec", parser="", codec_options=None) -> list[str]:
        from xpra.audio.sink import get_sink_pipeline_elements
        return get_sink_pipeline_elements(codec, decoder, parser, codec_options or {}, "fakesink name=sink")

    def test_rtp_jitterbuffer_before_depayloader(self):
        els = self.sink_elements(OPUS_RTP, "rtpopusdepay ! opusdec")
        jbs = [i for i, el in enumerate(els) if el.startswith("rtpjitterbuffer ")]
        assert len(jbs) == 1, f"expected exactly one jitterbuffer: {els}"
        jb = els[jbs[0]]
        assert "do-lost=True" in jb, f"lost packets must be reported downstream: {jb!r}"
        assert "name=jitterbuffer" in jb, f"jitterbuffer must be named for get_info: {jb!r}"
        decoders = [i for i, el in enumerate(els) if el.startswith("rtpopusdepay")]
        assert decoders and jbs[0] < decoders[0], f"jitterbuffer must come before the depayloader: {els}"
        assert els[0].startswith("appsrc ")
        for attr in ("is-live=True", "do-timestamp=True", "format=time"):
            assert attr in els[0], f"missing {attr!r} on appsrc: {els[0]!r}"

    def test_rtp_decoder_conceals_loss(self):
        els = self.sink_elements(OPUS_RTP, "rtpopusdepay ! opusdec")
        decoder = next(el for el in els if el.startswith("rtpopusdepay"))
        assert "plc=True" in decoder, f"decoder must conceal lost packets: {decoder!r}"
        assert "use-inband-fec=True" in decoder, f"decoder must use FEC: {decoder!r}"

    def test_rtp_decoder_options_can_be_overridden(self):
        els = self.sink_elements(OPUS_RTP, "rtpopusdepay ! opusdec", codec_options={"plc": False})
        decoder = next(el for el in els if el.startswith("rtpopusdepay"))
        assert "plc=False" in decoder, f"caller options must win: {decoder!r}"

    def test_non_rtp_unchanged(self):
        for codec, decoder, parser in (
            (OPUS, "opusparse ! opusdec", ""),
            (FLAC, "flacparse ! flacdec", ""),
        ):
            els = self.sink_elements(codec, decoder, parser)
            assert not [el for el in els if el.startswith("rtpjitterbuffer")], f"no jitterbuffer for {codec}: {els}"
            assert "do-timestamp" not in els[0], f"non-rtp appsrc must not timestamp: {els[0]!r}"
            assert "is-live=False" in els[0], f"non-rtp appsrc must not be live: {els[0]!r}"
            assert els[1] == decoder, f"decoder options must not leak into {codec}: {els}"

    def test_encoder_fec(self):
        from xpra.audio.gstreamer_util import get_encoder_default_options
        rtp = get_encoder_default_options("opusenc", OPUS_RTP)
        assert rtp.get("inband-fec") is True
        assert rtp.get("packet-loss-percentage", 0) > 0
        # the generic opusenc defaults still apply:
        assert "complexity" in rtp
        plain = get_encoder_default_options("opusenc", OPUS)
        assert "inband-fec" not in plain
        assert get_encoder_default_options("opusenc") == plain

    def test_other_opus_encoders_unchanged(self):
        from xpra.audio.gstreamer_util import get_encoder_default_options
        plain = get_encoder_default_options("opusenc")
        assert plain["bitrate-type"] == 1, "non-RTP Opus must keep VBR"
        assert "bitrate" not in plain, "non-RTP Opus must keep the GStreamer bitrate default"
        assert "frame-size" not in plain, "non-RTP Opus must keep the GStreamer frame duration default"
        assert "max-payload-size" not in plain, "the datagram limit must only apply to RTP"
        for codec in (OPUS, OPUS_OGG, OPUS_MKA):
            with self.subTest(codec=codec):
                assert get_encoder_default_options("opusenc", codec) == plain


class TestRTPPacketSizes(unittest.TestCase):

    def test_packets_fit_datagrams(self):
        gst = get_gst()
        for channels in (1, 2):
            for wave in ("sine", "white-noise", "silence"):
                with self.subTest(channels=channels, wave=wave):
                    packets = encode_packets(gst, 100, channels, wave)
                    largest = max(map(len, packets))
                    assert largest < 1000, f"RTP packet too large for a datagram: {largest} bytes"


class TestRTPLossPipeline(unittest.TestCase):
    """ Run the real playback pipeline elements, with an appsink to measure what comes out """

    @classmethod
    def setUpClass(cls):
        cls.gst = get_gst()
        cls.packets = encode_packets(cls.gst, 150)

    def run_pipeline(self, lost: set[int], order=None) -> tuple[int, dict]:
        gst = self.gst
        from xpra.audio.sink import get_sink_pipeline_elements
        from xpra.audio.gstreamer_util import get_decoder_elements, RTP_SINK_CAPS
        decoder, parser, _ = get_decoder_elements(OPUS_RTP)
        els = get_sink_pipeline_elements(OPUS_RTP, decoder, parser, {}, "appsink name=out sync=false emit-signals=true")
        pipeline = gst.parse_launch(" ! ".join(els))
        src = pipeline.get_by_name("src")
        src.set_property("caps", gst.Caps.from_string(RTP_SINK_CAPS[OPUS_RTP]))
        out = pipeline.get_by_name("out")
        output = {"buffers": 0, "duration": 0}

        def new_sample(appsink) -> int:
            buf = appsink.emit("pull-sample").get_buffer()
            output["buffers"] += 1
            output["duration"] += buf.duration
            return gst.FlowReturn.OK

        out.connect("new-sample", new_sample)
        bus = pipeline.get_bus()
        pipeline.set_state(gst.State.PLAYING)
        try:
            def push(data: bytes) -> None:
                r = src.emit("push-buffer", gst.Buffer.new_wrapped(data))
                assert r == gst.FlowReturn.OK, f"push-buffer failed: {r}"

            feed(push, self.packets, lost, order)
            src.emit("end-of-stream")
            msg = bus.timed_pop_filtered(5 * gst.SECOND, gst.MessageType.ERROR | gst.MessageType.EOS)
            assert msg, "timed out waiting for the end of the stream"
            if msg.type == gst.MessageType.ERROR:
                raise AssertionError(f"pipeline error: {msg.parse_error()[0]}")
            stats = pipeline.get_by_name("jitterbuffer").get_property("stats")
            jb = {key: stats.get_value(key) for key in ("num-pushed", "num-lost", "num-late")}
        finally:
            pipeline.set_state(gst.State.NULL)
        return output["duration"] // gst.MSECOND, jb

    def assert_continuous(self, duration: int, jb: dict, lost: set[int]) -> None:
        expected = len(self.packets) * PACKET_DURATION
        # the lost packets are concealed, so the output should be as long as the input:
        assert duration >= expected * 98 // 100, f"only {duration}ms of audio out of {expected}ms, {jb=}"
        assert jb["num-lost"] == len(lost), f"expected {len(lost)} lost packets: {jb=}"

    def test_no_loss(self):
        duration, jb = self.run_pipeline(set())
        self.assert_continuous(duration, jb, set())

    def test_random_loss(self):
        lost = random_loss(len(self.packets))
        duration, jb = self.run_pipeline(lost)
        self.assert_continuous(duration, jb, lost)

    def test_burst_loss_and_reordering(self):
        count = len(self.packets)
        # a burst of 3 lost packets in the middle, and some isolated ones:
        lost = {count // 2, count // 2 + 1, count // 2 + 2, 20, 110}
        # swap a few adjacent packets, which arrive within the jitterbuffer latency:
        order = list(range(count))
        for i in (10, 40, 90, 130):
            order[i], order[i + 1] = order[i + 1], order[i]
        duration, jb = self.run_pipeline(lost, order)
        self.assert_continuous(duration, jb, lost)
        assert jb["num-late"] == 0, f"reordered packets should not be late: {jb=}"


class TestRTPLossAudioSink(unittest.TestCase):
    """ Feed lossy packets to the actual `AudioSink` object """

    def test_audio_sink_random_loss(self):
        gst = get_gst()
        packets = encode_packets(gst, 150)
        lost = random_loss(len(packets), seed=1)
        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        from xpra.audio.sink import AudioSink
        with patch("xpra.audio.sink.get_sink_plugins", return_value=["fakesink"]), \
                patch("xpra.audio.sink.DEFAULT_SINK_PLUGIN_OPTIONS", {}), \
                patch("xpra.audio.device_monitor.AudioDeviceMonitor", Mock()):
            sink = AudioSink("fakesink", {}, [OPUS_RTP], {})
            assert sink.pipeline, "failed to create the pipeline"
            assert sink.jitterbuffer, "no jitterbuffer in the pipeline"
            output = {"buffers": 0, "duration": 0}

            def probe(_pad, info) -> int:
                buf = info.get_buffer()
                output["buffers"] += 1
                if buf.duration != gst.CLOCK_TIME_NONE:
                    output["duration"] += buf.duration
                return gst.PadProbeReturn.OK

            sink.sink.get_static_pad("sink").add_probe(gst.PadProbeType.BUFFER, probe)
            errors = []
            sink.connect("error", lambda _sink, error: errors.append(error))
            loop = GLib.MainLoop()
            info = {}
            index = iter(range(len(packets)))
            start = time.monotonic()

            def tick() -> bool:
                # stay on schedule even if the main loop is late:
                due = int((time.monotonic() - start) * 1000 / PACKET_DURATION) + 1
                while output.setdefault("pushed", 0) < due:
                    i = next(index, None)
                    if i is None:
                        GLib.timeout_add(200, end_of_stream)
                        return False
                    output["pushed"] += 1
                    if i not in lost:
                        sink.add_data(packets[i], {})
                return True

            def end_of_stream() -> bool:
                # all the losses have been detected by now (there are none in the last packets),
                # but the sink's queue may still hold some audio:
                # after an underrun, the sink raises the queue's minimum level,
                # which holds back the tail of the stream until more data arrives - or the end of the stream
                info.update(sink.get_info())
                sink.src.emit("end-of-stream")
                return False

            def state_changed(_sink, state) -> None:
                if state in ("stopped", "error"):
                    info["state"] = state
                    loop.quit()

            sink.connect("state-changed", state_changed)

            def timeout() -> bool:
                loop.quit()
                return False

            try:
                assert sink.start()
                GLib.timeout_add(PACKET_DURATION, tick)
                GLib.timeout_add(20 * 1000, timeout)
                loop.run()
            finally:
                sink.stop()
                sink.cleanup()

        assert info.get("state"), f"timed out: {info}"
        assert not errors, f"the sink pipeline failed: {errors}"
        assert info["state"] != "error", f"the sink pipeline failed: {info}"
        jb = info.get("jitterbuffer", {})
        assert jb.get("lost") == len(lost), f"expected {len(lost)} lost packets: {jb=}"
        expected = len(packets) * PACKET_DURATION
        duration = output["duration"] // gst.MSECOND
        assert duration >= expected * 98 // 100, f"only {duration}ms of audio out of {expected}ms, {jb=}"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
