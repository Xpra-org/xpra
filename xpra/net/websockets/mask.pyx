# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, initializedcheck=False, always_allow_keywords=False

from libc.stdint cimport uint32_t, uintptr_t   # pylint: disable=syntax-error
from xpra.buffers.membuf cimport getbuf, MemBuf, buffer_context

from xpra.common import SizedBuffer


def hybi_unmask(data, unsigned int offset, unsigned int datalen) -> memoryview:
    cdef uintptr_t mp
    cdef unsigned int min_len = offset + 4 + datalen
    with buffer_context(data) as bc:
        if len(bc)<(<Py_ssize_t> min_len):
            raise ValueError(f"buffer too small {len(bc)} vs {min_len}: offset={offset}, datalen={datalen}")
        mp = (<uintptr_t> int(bc)) + offset
        return do_hybi_mask(mp, mp + 4, datalen)


def hybi_mask(mask: bytes, data: SizedBuffer) -> memoryview:
    if len(mask) != 4:
        raise ValueError(f"invalid mask buffer size: {len(mask)} bytes")
    with buffer_context(mask) as mbc:
        with buffer_context(data) as dbc:
            return do_hybi_mask(<uintptr_t> int(mbc), <uintptr_t> int(dbc), len(dbc))


cdef memoryview do_hybi_mask(uintptr_t mp, uintptr_t dp, unsigned int datalen):
    # we skip the first 'align' bytes in the output buffer,
    # to ensure that its alignment is the same as the input data buffer
    cdef unsigned int align = (<uintptr_t> dp) & 0x3
    cdef unsigned int initial_chars = 4 - align
    cdef MemBuf out_buf = getbuf(datalen + align, 0)
    cdef uintptr_t op = <uintptr_t> out_buf.get_mem()
    # char pointers:
    cdef unsigned char *mcbuf = <unsigned char *> mp
    cdef unsigned char *dcbuf = <unsigned char *> dp
    cdef unsigned char *ocbuf = <unsigned char *> op
    cdef unsigned int j
    # bytes at a time until we reach the 32-bit boundary:
    for i in range(initial_chars):
        ocbuf[align + i] = dcbuf[i] ^ mcbuf[i & 0x3]
    # 32-bit pointers:
    cdef uint32_t *dbuf
    cdef uint32_t *obuf
    cdef uint32_t mask_value
    cdef unsigned int uint32_steps
    cdef unsigned int last_chars
    if datalen > initial_chars:
        uint32_steps = (datalen - initial_chars) // 4
        if uint32_steps:
            dbuf = <uint32_t*> (dp + initial_chars)
            obuf = <uint32_t*> (op + align + initial_chars)
            mask_value = 0
            for i in range(4):
                mask_value = mask_value << 8
                mask_value += mcbuf[(3 - i + initial_chars) & 0x3]
            for i in range(uint32_steps):
                obuf[i] = dbuf[i] ^ mask_value
        # bytes at a time again at the end:
        last_chars = (datalen - initial_chars) & 0x3
        for i in range(last_chars):
            j = datalen - last_chars + i
            ocbuf[align + j] = dcbuf[j] ^ mcbuf[j & 0x3]
    if align > 0:
        return (memoryview(out_buf)[align:]).toreadonly()
    return memoryview(out_buf).toreadonly()
