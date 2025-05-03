# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from typing import Tuple

from xpra.log import Logger
log = Logger("util")

cdef extern from "qrencode.h":
    ctypedef enum QRecLevel:
        QR_ECLEVEL_L    #lowest
        QR_ECLEVEL_M
        QR_ECLEVEL_Q
        QR_ECLEVEL_H    #highest

    ctypedef enum QRencodeMode:
        QR_MODE_NUL         #Terminator (NUL character). Internal use only
        QR_MODE_NUM         #Numeric mode
        QR_MODE_AN          #Alphabet-numeric mode
        QR_MODE_8           #8-bit data mode
        QR_MODE_KANJI       #Kanji (shift-jis) mode
        QR_MODE_STRUCTURE   #Internal use only
        QR_MODE_ECI         #ECI mode
        QR_MODE_FNC1FIRST   #FNC1, first position
        QR_MODE_FNC1SECOND  #FNC1, second position

    ctypedef struct QRcode:
        int version         #version of the symbol
        int width           #width of the symbol
        unsigned char *data #symbol data

    QRcode *QRcode_encodeString8bit(const char *string, int version, QRecLevel level)
    void QRcode_free(QRcode *qrcode)

    void QRcode_APIVersion(int *major_version, int *minor_version, int *micro_version)
    char *QRcode_APIVersionString()


def get_version() -> Tuple[int, int, int]:
    cdef int major_version, minor_version, micro_version
    QRcode_APIVersion(&major_version, &minor_version, &micro_version)
    return major_version, minor_version, micro_version


def encode(s, QRecLevel level=QR_ECLEVEL_M):
    if isinstance(s, str):
        s = s.encode()
    cdef const char *string = s
    cdef QRcode *qrcode = QRcode_encodeString8bit(string, 0, level)
    if not qrcode:
        return None
    log("encode(%s, %i) got qrcode of size %i", s, level, qrcode.width)
    try:
        buf = qrcode.data[:qrcode.width*qrcode.width]
        return buf
    finally:
        QRcode_free(qrcode)

def encode_image(s, QRecLevel level=QR_ECLEVEL_M):
    data = encode(s, level)
    if not data:
        return None
    cdef int l = len(data)
    from math import sqrt
    cdef int size = int(sqrt(l))
    assert size>1, "invalid qrcode size %i" % size
    pixels = bytearray(l)
    for i in range(l):
        pixels[i] = 0 if (data[i] & 0x1) else 255
    from PIL import Image
    return Image.frombytes('L', (size, size), bytes(pixels))
