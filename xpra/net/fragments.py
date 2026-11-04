# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Splitting video frames into fragments small enough to be sent as datagrams,
and putting them back together on the receiving end.

The frames are split on the boundaries of the units the decoder can use on their own
(ie: h264 NALs containing whole slices), so that a frame can still be decoded
- with some damage - when some of its fragments are lost.
Each fragment holds one or more consecutive units,
a unit that is too big to fit in a single fragment is split into a `group` of fragments,
which is only usable if all the fragments of the group are received.

Parity fragments can also be added to a frame, each one covering a block of consecutive fragments,
any single fragment missing from a block can be rebuilt from the others and the block's parity fragment.
"""

from struct import pack, unpack_from
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from xpra.common import noop
from xpra.util.str_fn import memoryview_to_bytes


def fragment_frame(data, boundaries: Sequence[int], max_size: int) -> list[tuple[bytes, int, int]]:
    """
    Split `data` into fragments of at most `max_size` bytes,
    `boundaries` contains the end offset of each unit (ie: h264 NAL) in `data`.
    Returns a list of `(fragment_data, group_start, group_size)`.
    """
    if max_size <= 0:
        raise ValueError(f"invalid fragment size {max_size}")
    size = len(data)
    if not boundaries or boundaries[-1] != size:
        raise ValueError(f"invalid boundaries for {size} bytes: {boundaries}")
    fragments: list[tuple[bytes, int, int]] = []
    view = memoryview(data)
    start = 0
    end = 0
    for boundary in boundaries:
        if boundary <= end or boundary > size:
            raise ValueError(f"invalid boundary {boundary} after {end}")
        if boundary - start <= max_size:
            # keep adding whole units to the current fragment:
            end = boundary
            continue
        if end > start:
            # flush the units we have so far:
            index = len(fragments)
            fragments.append((memoryview_to_bytes(view[start:end]), index, 1))
            start = end
        if boundary - start <= max_size:
            end = boundary
            continue
        # this unit is too big, split it into a group of fragments:
        group_start = len(fragments)
        count = (boundary - start + max_size - 1) // max_size
        for i in range(count):
            piece_end = min(boundary, start + max_size)
            fragments.append((memoryview_to_bytes(view[start:piece_end]), group_start, count))
            start = piece_end
        end = boundary
    if end > start:
        index = len(fragments)
        fragments.append((memoryview_to_bytes(view[start:end]), index, 1))
    return fragments


# each fragment is covered by its parity fragment along with its size and group,
# so that all of these can be recovered:
PARITY_HEADER = ">HHH"
PARITY_HEADER_SIZE = 6


def xor_bytes(buffers: Sequence[bytes]) -> bytes:
    """ XOR all the buffers, the shorter ones are padded with zeroes """
    size = max(len(buf) for buf in buffers)
    value = 0
    for buf in buffers:
        value ^= int.from_bytes(buf.ljust(size, b"\0"), "big")
    return value.to_bytes(size, "big")


def parity_payload(fragment: tuple[bytes, int, int]) -> bytes:
    data, group_start, group_size = fragment
    return pack(PARITY_HEADER, len(data), group_start, group_size) + data


def make_parity(fragments: Sequence[tuple[bytes, int, int]], parity_count: int) -> list[tuple[bytes, int, int]]:
    """
    Returns `parity_count` parity fragments as `(parity_data, block_start, block_size)`,
    each one covering a block of consecutive fragments.
    """
    count = len(fragments)
    if count == 0 or parity_count <= 0:
        return []
    block_size = (count + parity_count - 1) // parity_count
    parity: list[tuple[bytes, int, int]] = []
    for start in range(0, count, block_size):
        block = fragments[start:start + block_size]
        parity.append((xor_bytes([parity_payload(fragment) for fragment in block]), start, len(block)))
    return parity


def recover_fragment(parity_data: bytes, others: Sequence[tuple[bytes, int, int]]) -> tuple[bytes, int, int]:
    """ rebuild the single fragment missing from a block """
    payload = xor_bytes([parity_data] + [parity_payload(fragment) for fragment in others])
    size, group_start, group_size = unpack_from(PARITY_HEADER, payload)
    if PARITY_HEADER_SIZE + size > len(payload):
        raise ValueError(f"invalid recovered fragment size {size}")
    return payload[PARITY_HEADER_SIZE:PARITY_HEADER_SIZE + size], group_start, group_size


class FrameStatus(Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    LOST = "lost"


@dataclass
class PendingFrame:
    sequence: int
    count: int
    deadline: float
    # the sequence of the last packet sent on the stream before this frame,
    # which must be processed first, and how long we wait for it:
    stream_sequence: int
    stream_deadline: float
    # the fields of the first fragment received, used as the frame's metadata:
    metadata: tuple
    # index -> (data, group_start, group_size)
    fragments: dict[int, tuple[bytes, int, int]] = field(default_factory=dict)
    # block_start -> (parity_data, block_size)
    parity: dict[int, tuple[bytes, int]] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return len(self.fragments) == self.count


@dataclass
class AssembledFrame:
    sequence: int
    status: FrameStatus
    metadata: tuple
    data: bytes
    count: int
    missing: tuple[int, ...]
    # the earlier fragmented frames we have not received anything for:
    lost_sequences: tuple[int, ...] = ()


def assemble(frame: PendingFrame) -> AssembledFrame:
    """ concatenate the fragments of all the groups we have received in full """
    chunks: list[bytes] = []
    missing = tuple(i for i in range(frame.count) if i not in frame.fragments)
    index = 0
    while index < frame.count:
        fragment = frame.fragments.get(index)
        if fragment is None:
            index += 1
            continue
        _data, group_start, group_size = fragment
        if group_start != index:
            # we are missing the start of this group:
            index += 1
            continue
        group = [frame.fragments.get(i) for i in range(group_start, group_start + group_size)]
        if all(group):
            chunks += [item[0] for item in group]
        index = group_start + max(1, group_size)
    if not missing:
        status = FrameStatus.COMPLETE
    elif chunks:
        status = FrameStatus.PARTIAL
    else:
        status = FrameStatus.LOST
    return AssembledFrame(frame.sequence, status, frame.metadata, b"".join(chunks), frame.count, missing)


class FrameAssembler:
    """
    Re-assembles the fragmented frames of a single window.
    Frames are delivered in sequence order:
    a frame waits for the earlier frames we have fragments for, until their deadline,
    and for the packet that was sent on the stream before it (ie: a keyframe), which can be slower than datagrams.
    This class does not use timers or locks:
    the caller must call `expire` once `next_deadline` has passed,
    and all the methods must be called from the same thread.
    """

    def __init__(self, deliver: Callable[[AssembledFrame], None], timeout: float, stream_timeout: float = 1):
        self.deliver = deliver
        self.timeout = timeout
        self.stream_timeout = stream_timeout
        self.pending: dict[int, PendingFrame] = {}
        # the highest sequence delivered, fragments for frames up to this one are too late:
        self.last_sequence = 0
        # the highest sequence processed from the stream:
        self.stream_sequence = 0
        self.stats: dict[str, int] = {
            "fragments": 0,
            "late": 0,
            "invalid": 0,
            "duplicate": 0,
            "parity": 0,
            "recovered": 0,
        } | {status.value: 0 for status in FrameStatus}

    def add(self, sequence: int, index: int, count: int, group_start: int, group_size: int,
            data: bytes, metadata: tuple, now: float, stream_sequence: int = 0) -> None:
        """
        Fragments with an `index` greater or equal to `count` are parity fragments,
        for those, `group_start` and `group_size` are the block of fragments covered.
        """
        is_parity = index >= count
        if is_parity:
            valid = 0 <= group_start < group_start + group_size <= count and index < count * 2
        else:
            valid = 0 <= index and 0 <= group_start <= index < group_start + group_size <= count
        if not valid or count <= 0 or not 0 <= stream_sequence < sequence:
            self.stats["invalid"] += 1
            return
        if sequence <= self.last_sequence:
            self.stats["late"] += 1
            return
        frame = self.pending.get(sequence)
        if frame is None:
            frame = self.pending[sequence] = PendingFrame(sequence, count, now + self.timeout,
                                                          stream_sequence, now + self.stream_timeout, metadata)
        elif frame.count != count or frame.stream_sequence != stream_sequence:
            self.stats["invalid"] += 1
            return
        if is_parity:
            if group_start in frame.parity:
                self.stats["duplicate"] += 1
                return
            self.stats["parity"] += 1
            frame.parity[group_start] = (data, group_size)
        else:
            if index in frame.fragments:
                self.stats["duplicate"] += 1
                return
            self.stats["fragments"] += 1
            frame.fragments[index] = (data, group_start, group_size)
        if frame.parity and not frame.is_complete():
            self.recover(frame)
        self.deliver_ready(now)

    def recover(self, frame: PendingFrame) -> None:
        """ rebuild the fragments we can using the parity fragments """
        for block_start, (parity_data, block_size) in tuple(frame.parity.items()):
            indexes = range(block_start, block_start + block_size)
            missing = [i for i in indexes if i not in frame.fragments]
            if len(missing) != 1:
                continue
            others = [frame.fragments[i] for i in indexes if i != missing[0]]
            try:
                fragment = recover_fragment(parity_data, others)
            except ValueError:
                self.stats["invalid"] += 1
            else:
                _data, group_start, group_size = fragment
                index = missing[0]
                if 0 <= group_start <= index < group_start + group_size <= frame.count:
                    frame.fragments[index] = fragment
                    self.stats["recovered"] += 1
                else:
                    self.stats["invalid"] += 1
            del frame.parity[block_start]

    def get_wakeup(self, frame: PendingFrame, now: float) -> float:
        """ returns 0 if the frame can be delivered now, otherwise when to check again """
        if self.stream_sequence < frame.stream_sequence and frame.stream_deadline > now:
            return frame.stream_deadline
        if not frame.is_complete() and frame.deadline > now:
            return frame.deadline
        return 0

    def deliver_ready(self, now: float) -> None:
        """ deliver the frames that are ready, in order """
        while self.pending:
            sequence = min(self.pending)
            if self.get_wakeup(self.pending[sequence], now):
                return
            self.deliver_frame(self.pending.pop(sequence))

    def deliver_frame(self, frame: PendingFrame) -> None:
        assembled = assemble(frame)
        # all the packets between the last stream packet and this frame were fragmented frames,
        # since frames are delivered in order, those we have not seen are lost:
        first = max(self.last_sequence, frame.stream_sequence) + 1
        assembled.lost_sequences = tuple(range(first, frame.sequence))
        self.stats["lost"] += len(assembled.lost_sequences)
        self.last_sequence = max(self.last_sequence, frame.sequence)
        self.stats[assembled.status.value] += 1
        self.deliver(assembled)

    def expire(self, now: float) -> None:
        self.deliver_ready(now)

    def flush(self, sequence: int, process: Callable[[], None] = noop) -> None:
        """
        A packet with this sequence number was received outside this assembler (ie: on the stream):
        all the earlier frames must be delivered now, with whatever we have,
        then the packet is processed (`process`),
        and finally the frames that were waiting for it can be delivered.
        """
        for seq in sorted(self.pending):
            if seq >= sequence:
                break
            self.deliver_frame(self.pending.pop(seq))
        self.last_sequence = max(self.last_sequence, sequence)
        process()
        self.stream_sequence = max(self.stream_sequence, sequence)
        self.deliver_ready(-1)

    def next_deadline(self, now: float) -> float:
        """ when `expire` should be called, 0 if there is nothing pending """
        if not self.pending:
            return 0
        # only the first frame can be delivered, the others wait for it:
        return self.get_wakeup(self.pending[min(self.pending)], now) or now

    def clear(self) -> None:
        self.pending.clear()
