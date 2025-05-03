# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict

from libc.stddef cimport wchar_t
from libc.stdint cimport uint64_t, uintptr_t

from xpra.codecs.amf.amf cimport (
    AMF_RESULT, AMFFactory, AMFGuid, AMFSurface, AMFSurfaceVtbl,
    AMFPlane, AMFPlaneVtbl, AMFData, AMFCaps, AMFIOCaps, AMFVariantStruct,
    amf_uint32, amf_uint16, amf_uint8,
)


cdef AMFFactory *get_factory()
cdef void cleanup(self)
cdef tuple get_version()

cdef void check(AMF_RESULT res, message)
cdef object error_str(AMF_RESULT result)

cdef void set_guid(AMFGuid *guid,
                   amf_uint32 _data1, amf_uint16 _data2, amf_uint16 _data3,
                   amf_uint8 _data41, amf_uint8 _data42, amf_uint8 _data43, amf_uint8 _data44,
                   amf_uint8 _data45, amf_uint8 _data46, amf_uint8 _data47, amf_uint8 _data48)

cdef uint64_t get_c_version()

cdef void fill_nv12_surface(AMFSurface *surface, amf_uint8 Y, amf_uint8 U, amf_uint8 V)

cdef object get_caps(AMFCaps *caps, props: Dict)

cdef object get_io_caps(AMFIOCaps *iocaps)

cdef object get_plane_info(AMFPlane *plane)

cdef object get_data_info(AMFData *data)

cdef object get_surface_info(AMFSurface *surface)
