# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import zlib
from typing import Final
from base64 import b64encode

from xpra.util.env import envint
from xpra.log import Logger

log = Logger("client", "terminal")

# base64 payload bytes per escape sequence, always a multiple of 4
# (the kitty protocol requires the payload of every non-final chunk to be a multiple of 4):
MAX_CHUNK: Final[int] = max(4, envint("XPRA_TERMINAL_MAX_CHUNK", 4096) // 4 * 4)

APC: Final[bytes] = b"\x1b_G"           # application program command, kitty graphics introducer
ST: Final[bytes] = b"\x1b\\"            # string terminator
DECSC: Final[bytes] = b"\x1b7"          # save cursor position
DECRC: Final[bytes] = b"\x1b8"          # restore cursor position
CSI: Final[bytes] = b"\x1b["

# the kitty graphics action which transmits animation frame data.
# it is the one action the protocol requires every continuation chunk to repeat:
FRAME_ACTION: Final[str] = "a=f"

MAX_U32: Final[int] = 0xFFFFFFFF
MIN_I32: Final[int] = -0x80000000
MAX_I32: Final[int] = 0x7FFFFFFF

# the image id used for the pointer cursor, kept well clear of any window id:
CURSOR_IMAGE_ID: Final[int] = 0x7FFFFF00
# z-index space: regular windows get 10, 12, 14... by stack order,
# an override-redirect window sits at its parent's z + 1, the cursor sits above everything:
WINDOW_Z_BASE: Final[int] = 10
WINDOW_Z_STEP: Final[int] = 2
OVERRIDE_REDIRECT_Z_OFFSET: Final[int] = 1
CURSOR_Z: Final[int] = 2 ** 30


def _check_u32(name: str, value: int) -> None:
    if not 0 <= value <= MAX_U32:
        raise ValueError(f"invalid {name}: {value} does not fit in 32 bits")


def _check_i32(name: str, value: int) -> None:
    if not MIN_I32 <= value <= MAX_I32:
        raise ValueError(f"invalid {name}: {value} does not fit in a signed 32 bit integer")


def escape(control: str, payload: bytes = b"") -> bytes:
    """ wrap the control data and its (already encoded) payload in a kitty graphics escape sequence """
    if payload:
        return APC + control.encode("ascii") + b";" + payload + ST
    return APC + control.encode("ascii") + ST


def chunked(control: str, payload: bytes, cont: str = "") -> bytes:
    """
    Split an encoded payload into `MAX_CHUNK` sized escape sequences.
    The first chunk carries the full control data, every following chunk carries only `m=`.
    `m=1` means "more data follows", `m=0` terminates the transfer.
    A payload small enough to fit in a single sequence is sent without any `m=` key.

    `cont` is prepended to every continuation chunk: the protocol says
    "Subsequent chunks must have only the `m` and optionally `q` keys.
    When sending animation frame data, subsequent chunks must also specify the `a=f` key."
    Without it the terminal parses the continuations as a whole image transmission
    and silently replaces the image with the frame data.
    """
    size = len(payload)
    if size <= MAX_CHUNK:
        return escape(control, payload)
    prefix = f"{cont}," if cont else ""
    parts = [escape(f"{control},m=1", payload[:MAX_CHUNK])]
    pos = MAX_CHUNK
    while pos < size:
        end = min(pos + MAX_CHUNK, size)
        parts.append(escape(f"{prefix}m={int(end < size)}", payload[pos:end]))
        pos = end
    return b"".join(parts)


def encode_pixels(pixels: bytes, compress: bool) -> tuple[bytes, bool]:
    """
    base64 encode the pixel data, deflating it first when that actually makes it smaller.
    Returns the encoded payload and whether it is compressed (which requires the `o=z` key).
    """
    if compress:
        deflated = zlib.compress(pixels)
        if len(deflated) < len(pixels):
            return b64encode(deflated), True
    return b64encode(pixels), False


def transmit(image_id: int, width: int, height: int, pixels: bytes, alpha=True, compress=True) -> bytes:
    """
    Transmit a whole image: `a=t`.
    `pixels` must be `width * height` row-contiguous RGBA pixels (RGB when `alpha` is false).
    """
    _check_u32("image id", image_id)
    payload, deflated = encode_pixels(pixels, compress)
    control = f"a=t,q=2,i={image_id},f={32 if alpha else 24},s={width},v={height}"
    if deflated:
        control += ",o=z"
    log("transmit(%i, %i, %i, %i bytes, %s, %s)", image_id, width, height, len(pixels), alpha, compress)
    return chunked(control, payload)


def place(image_id: int, placement_id: int, row: int, col: int, x_off: int, y_off: int, z: int) -> bytes:
    """
    Place an image: `a=p`, at the given 1-based terminal cell with intra-cell pixel offsets.
    The cursor is saved and restored around the placement so the terminal state is left untouched.
    Rows and columns below 1 are clamped: the caller owns the clipping policy.
    """
    _check_u32("image id", image_id)
    _check_u32("placement id", placement_id)
    _check_i32("z index", z)
    cup = CSI + b"%i;%iH" % (max(1, row), max(1, col))
    control = f"a=p,q=2,i={image_id},p={placement_id},z={z},C=1,X={x_off},Y={y_off}"
    return DECSC + cup + escape(control) + DECRC


def patch(image_id: int, x: int, y: int, width: int, height: int, pixels: bytes, compress=True) -> bytes:
    """
    Update a rectangle of an image already held by the terminal: `a=f` frame edit of frame 1,
    with `X=1` so the new pixels replace the old ones instead of being alpha blended into them.
    """
    _check_u32("image id", image_id)
    payload, deflated = encode_pixels(pixels, compress)
    control = f"{FRAME_ACTION},q=2,i={image_id},r=1,x={x},y={y},s={width},v={height}"
    if deflated:
        control += ",o=z"
    control += ",X=1"
    log("patch(%i, %i, %i, %i, %i, %i bytes, %s)", image_id, x, y, width, height, len(pixels), compress)
    # the continuation chunks repeat `i` and `r` as well as the `a=f` the
    # protocol requires: kitty (0.45) computes the frame number from each
    # continuation chunk, where a missing `r` means "append a new frame" -
    # the edit of frame 1 silently becomes an invisible animation frame
    # unless every chunk repeats `r`:
    return chunked(control, payload, cont=f"{FRAME_ACTION},i={image_id},r=1")


def transmit_shm(image_id: int, width: int, height: int, name: str, alpha=True) -> bytes:
    """
    Transmit a whole image through a POSIX shared memory object (`t=s`):
    the payload is only the object's name, the raw pixels are read (and the
    object unlinked) by the terminal.  No chunking, no base64 pixel data.
    """
    _check_u32("image id", image_id)
    size = width * height * (4 if alpha else 3)
    control = f"a=t,q=2,i={image_id},f={32 if alpha else 24},s={width},v={height},t=s,S={size}"
    log("transmit_shm(%i, %i, %i, %r)", image_id, width, height, name)
    return escape(control, b64encode(name.encode("ascii")))


def patch_shm(image_id: int, x: int, y: int, width: int, height: int, name: str) -> bytes:
    """
    A frame edit (`a=f`, see `patch`) reading its pixels from a shared memory
    object: a single small escape sequence regardless of the region size,
    which also avoids the chunked frame edits some terminals mishandle.
    """
    _check_u32("image id", image_id)
    size = width * height * 4
    control = f"{FRAME_ACTION},q=2,i={image_id},r=1,x={x},y={y},s={width},v={height},X=1,t=s,S={size}"
    log("patch_shm(%i, %i, %i, %i, %i, %r)", image_id, x, y, width, height, name)
    return escape(control, b64encode(name.encode("ascii")))


def probe_shm(image_id: int, name: str) -> bytes:
    """
    Query (`a=q`) with a shared memory transmission: the terminal only answers
    `OK` when it could actually open and map our object, which is exactly the
    local-terminal detection needed before using `t=s` (a terminal on the far
    side of an ssh connection cannot reach this machine's shared memory).
    Not quieted, since we want the terminal's reply.
    The object must hold a single RGBA pixel (4 bytes).
    """
    _check_u32("image id", image_id)
    return escape(f"a=q,i={image_id},f=32,s=1,v=1,t=s,S=4", b64encode(name.encode("ascii")))


def delete_placement(image_id: int, placement_id: int) -> bytes:
    """ remove a single placement (`d=i`, lowercase: the image data is kept) """
    _check_u32("image id", image_id)
    _check_u32("placement id", placement_id)
    return escape(f"a=d,d=i,i={image_id},p={placement_id},q=2")


def delete_image(image_id: int) -> bytes:
    """ remove an image and free its data (`d=I`, uppercase) """
    _check_u32("image id", image_id)
    return escape(f"a=d,d=I,i={image_id},q=2")


def probe(image_id: int) -> bytes:
    """
    Query support for the graphics protocol: `a=q` with a single transparent RGBA pixel.
    Unlike every other command this one is not quieted, since we want the terminal's reply.
    """
    _check_u32("image id", image_id)
    return escape(f"a=q,i={image_id},f=32,s=1,v=1,t=d", b64encode(b"\0\0\0\0"))


def probe_frame_edit(image_id: int) -> bytes:
    """
    A 1x1 frame edit used to detect `a=f` support, which not every terminal
    implementing the graphics protocol provides (kitty does, Ghostty does not).
    Not quieted, since we want the terminal's reply.
    The image must already be held by the terminal (see `transmit`).
    """
    _check_u32("image id", image_id)
    return escape(f"{FRAME_ACTION},i={image_id},r=1,x=0,y=0,s=1,v=1,X=1", b64encode(b"\0\0\0\xff"))
