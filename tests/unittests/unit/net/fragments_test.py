#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from random import Random

from xpra.net.fragments import fragment_frame, FrameAssembler, FrameStatus


def make_frame(sizes) -> tuple[bytes, list[int]]:
    """ a frame made of units of the given sizes, each one filled with its own index """
    data = b"".join(bytes([i & 0xff]) * size for i, size in enumerate(sizes))
    boundaries = []
    end = 0
    for size in sizes:
        end += size
        boundaries.append(end)
    return data, boundaries


class FragmentFrameTest(unittest.TestCase):

    def check(self, sizes, max_size):
        data, boundaries = make_frame(sizes)
        fragments = fragment_frame(data, boundaries, max_size)
        # nothing lost, nothing added:
        self.assertEqual(b"".join(f[0] for f in fragments), data)
        for index, (fragment, group_start, group_size) in enumerate(fragments):
            self.assertLessEqual(len(fragment), max_size)
            self.assertTrue(fragment)
            self.assertTrue(group_start <= index < group_start + group_size)
        # every group starts on a unit boundary:
        starts = {0} | set(boundaries)
        offset = 0
        for index, (fragment, group_start, group_size) in enumerate(fragments):
            if group_start == index:
                self.assertIn(offset, starts)
            offset += len(fragment)
        return fragments

    def test_small_units_are_packed(self):
        fragments = self.check([100] * 10, 350)
        self.assertEqual(len(fragments), 4)
        self.assertEqual([len(f[0]) for f in fragments], [300, 300, 300, 100])
        self.assertEqual([(f[1], f[2]) for f in fragments], [(0, 1), (1, 1), (2, 1), (3, 1)])

    def test_exact_fit(self):
        fragments = self.check([100, 100], 200)
        self.assertEqual(len(fragments), 1)

    def test_large_unit_is_grouped(self):
        fragments = self.check([50, 1000, 50], 300)
        self.assertEqual([(f[1], f[2]) for f in fragments], [(0, 1), (1, 4), (1, 4), (1, 4), (1, 4), (5, 1)])
        self.assertEqual(len(fragments[1][0]), 300)

    def test_single_unit(self):
        self.check([1], 1000)
        self.check([1000], 1000)
        self.check([1001], 1000)

    def test_random(self):
        rng = Random(1)
        for _ in range(200):
            sizes = [rng.randint(1, 3000) for _ in range(rng.randint(1, 30))]
            self.check(sizes, rng.randint(64, 1200))

    def test_invalid(self):
        data, boundaries = make_frame([10, 10])
        for bad in ([], [10], [10, 25], [15, 10, 20], [0, 20]):
            with self.assertRaises(ValueError):
                fragment_frame(data, bad, 100)
        with self.assertRaises(ValueError):
            fragment_frame(data, boundaries, 0)


class FrameAssemblerTest(unittest.TestCase):

    TIMEOUT = 0.05

    def setUp(self):
        self.delivered = []
        self.assembler = FrameAssembler(self.delivered.append, self.TIMEOUT)

    def send(self, sequence: int, fragments, indexes=None, now=0.0, stream_sequence=0):
        count = len(fragments)
        for index in (range(count) if indexes is None else indexes):
            data, group_start, group_size = fragments[index]
            self.assembler.add(sequence, index, count, group_start, group_size, data, ("meta", sequence), now,
                               stream_sequence)

    def test_complete_in_order(self):
        data, boundaries = make_frame([100] * 10)
        fragments = fragment_frame(data, boundaries, 250)
        self.send(1, fragments)
        self.assertEqual(len(self.delivered), 1)
        frame = self.delivered[0]
        self.assertEqual(frame.status, FrameStatus.COMPLETE)
        self.assertEqual(frame.data, data)
        self.assertEqual(frame.metadata, ("meta", 1))
        self.assertEqual(frame.missing, ())

    def test_reordered(self):
        data, boundaries = make_frame([100] * 10)
        fragments = fragment_frame(data, boundaries, 250)
        self.send(1, fragments, reversed(range(len(fragments))))
        self.assertEqual(self.delivered[0].data, data)

    def test_partial(self):
        data, boundaries = make_frame([100] * 10)
        fragments = fragment_frame(data, boundaries, 200)
        self.send(1, fragments, (0, 1, 3, 4))
        self.assertFalse(self.delivered)
        self.assembler.expire(self.TIMEOUT / 2)
        self.assertFalse(self.delivered)
        self.assembler.expire(self.TIMEOUT)
        frame = self.delivered[0]
        self.assertEqual(frame.status, FrameStatus.PARTIAL)
        self.assertEqual(frame.missing, (2, ))
        self.assertEqual(frame.data, fragments[0][0] + fragments[1][0] + fragments[3][0] + fragments[4][0])

    def test_incomplete_group_is_dropped(self):
        data, boundaries = make_frame([50, 1000, 50])
        fragments = fragment_frame(data, boundaries, 300)
        # lose one piece of the large unit, the rest of that group is useless:
        self.send(1, fragments, (0, 1, 3, 4, 5))
        self.assembler.expire(1)
        frame = self.delivered[0]
        self.assertEqual(frame.status, FrameStatus.PARTIAL)
        self.assertEqual(frame.missing, (2, ))
        self.assertEqual(frame.data, fragments[0][0] + fragments[5][0])

    def test_lost(self):
        data, boundaries = make_frame([50, 1000])
        fragments = fragment_frame(data, boundaries, 300)
        # we only have a piece of the large unit:
        self.send(1, fragments, (2, ))
        self.assembler.expire(1)
        self.assertEqual(self.delivered[0].status, FrameStatus.LOST)
        self.assertEqual(self.assembler.stats["lost"], 1)

    def test_delivered_in_sequence_order(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        # frame 2 is complete before frame 1:
        self.send(1, fragments, (0, 1))
        self.send(2, fragments)
        self.assertFalse(self.delivered)
        self.send(1, fragments, (2, 3))
        self.assertEqual([f.sequence for f in self.delivered], [1, 2])

    def test_waits_for_earlier_frame_deadline(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(1, fragments, (0, ), now=0)
        self.send(2, fragments, now=0.01)
        self.assertFalse(self.delivered)
        self.assertEqual(self.assembler.next_deadline(0.02), self.TIMEOUT)
        self.assembler.expire(self.TIMEOUT)
        self.assertEqual([(f.sequence, f.status) for f in self.delivered],
                         [(1, FrameStatus.PARTIAL), (2, FrameStatus.COMPLETE)])
        self.assertEqual(self.assembler.next_deadline(1), 0)

    def test_waits_for_stream_packet(self):
        # frame 2 was sent after the keyframe 1, which is sent on the stream and is slower:
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(2, fragments, stream_sequence=1)
        self.assertFalse(self.delivered)
        self.assembler.expire(self.TIMEOUT * 2)
        self.assertFalse(self.delivered, "frame delivered before the stream packet it follows")
        self.assertEqual(self.assembler.next_deadline(self.TIMEOUT * 2), 1)
        # the stream packet is processed before the frames waiting for it:
        self.assembler.flush(1, lambda: self.delivered.append("stream"))
        self.assertEqual(self.delivered[0], "stream")
        self.assertEqual([f.sequence for f in self.delivered[1:]], [2])
        self.assertEqual(self.delivered[1].lost_sequences, ())

    def test_stream_packet_wait_is_capped(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(2, fragments, stream_sequence=1)
        self.assembler.expire(1)
        self.assertEqual([f.sequence for f in self.delivered], [2])

    def test_lost_sequences(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.assembler.flush(3)
        # we never receive anything for frames 4 and 5:
        self.send(6, fragments, stream_sequence=3)
        self.assertEqual(self.delivered[0].lost_sequences, (4, 5))
        self.send(7, fragments, stream_sequence=3)
        self.assertEqual(self.delivered[1].lost_sequences, ())
        # frame 8 went on the stream:
        self.assembler.flush(8)
        self.send(10, fragments, stream_sequence=8)
        self.assertEqual(self.delivered[2].lost_sequences, (9, ))
        self.assertEqual(self.assembler.stats["lost"], 3)

    def test_late_fragments_are_dropped(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(1, fragments, (0, 1, 2))
        self.assembler.expire(1)
        self.send(1, fragments, (3, ))
        self.assertEqual(len(self.delivered), 1)
        self.assertEqual(self.assembler.stats["late"], 1)

    def test_flush(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(1, fragments, (0, ))
        self.send(3, fragments, (0, ))
        # a packet for sequence 2 is received on the stream:
        self.assembler.flush(2)
        self.assertEqual([f.sequence for f in self.delivered], [1])
        # anything for frame 2 is now too late, frame 3 is still pending:
        self.send(2, fragments, (0, ))
        self.assertEqual(self.assembler.stats["late"], 1)
        self.assertEqual(tuple(self.assembler.pending), (3, ))

    def test_duplicates_and_invalid(self):
        data, boundaries = make_frame([100] * 4)
        fragments = fragment_frame(data, boundaries, 100)
        self.send(1, fragments, (0, 0))
        self.assertEqual(self.assembler.stats["duplicate"], 1)
        for index, count, group_start, group_size in (
            (4, 4, 4, 1),       # index out of range
            (1, 4, 2, 1),       # not in its group
            (1, 4, 0, 5),       # group too big
            (0, 0, 0, 1),       # no fragments
            (1, 5, 1, 1),       # count does not match
        ):
            self.assembler.add(1, index, count, group_start, group_size, b"x", (), 0)
        # the stream packet must come first:
        self.assembler.add(1, 1, 4, 1, 1, b"x", (), 0, 1)
        self.assertEqual(self.assembler.stats["invalid"], 6)
        self.assertFalse(self.delivered)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
