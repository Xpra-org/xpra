# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import struct


if sys.version_info[:2]>=(2,5):
    def unpack_header(buf):
        return struct.unpack_from('!cBBBL', buf)
else:
    def unpack_header(buf):
        return struct.unpack('!cBBBL', "".join(buf))


#'P' + protocol-flags + compression_level + packet_index + data_size
def pack_header(proto_flags, level, index, payload_size):
    return struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)

if sys.version_info[0]<3:
    #before v3, python does the right thing without hassle:
    def pack_header_and_data(actual_size, proto_flags, level, index, payload_size, data):
        return struct.pack('!BBBBL%ss' % actual_size, ord("P"), proto_flags, level, index, payload_size, data)
else:
    pack_header_and_data = None
