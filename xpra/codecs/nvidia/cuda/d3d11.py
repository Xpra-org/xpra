# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Copy areas of D3D11 textures to CUDA device memory without going through system memory,
using the graphics interoperability functions of the CUDA driver API directly:
pycuda only wraps the OpenGL ones.
"""

import ctypes
from ctypes import Structure, byref, c_int, c_uint, c_uint64, c_void_p, c_size_t
from collections import OrderedDict

from xpra.codecs.nvidia.cuda.errors import cudacheck
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("cuda", "d3d11")

CU_GRAPHICS_REGISTER_FLAGS_NONE = 0
CU_GRAPHICS_MAP_RESOURCE_FLAGS_READ_ONLY = 1
CU_MEMORYTYPE_DEVICE = 2
CU_MEMORYTYPE_ARRAY = 3

# registering a texture is expensive, so we keep the registrations of the textures we see repeatedly
# (the snapshot textures are recycled), and each one holds a reference on its texture:
MAX_REGISTRATIONS = envint("XPRA_CUDA_D3D11_MAX_REGISTRATIONS", 4)


class CUDA_MEMCPY2D(Structure):
    _fields_ = [
        ("srcXInBytes", c_size_t),
        ("srcY", c_size_t),
        ("srcMemoryType", c_int),
        ("srcHost", c_void_p),
        ("srcDevice", c_uint64),
        ("srcArray", c_void_p),
        ("srcPitch", c_size_t),
        ("dstXInBytes", c_size_t),
        ("dstY", c_size_t),
        ("dstMemoryType", c_int),
        ("dstHost", c_void_p),
        ("dstDevice", c_uint64),
        ("dstArray", c_void_p),
        ("dstPitch", c_size_t),
        ("WidthInBytes", c_size_t),
        ("Height", c_size_t),
    ]


FUNCTIONS: dict[str, tuple[str, ...]] = {
    # name: the symbols to try, newest first
    "cuDeviceGet": ("cuDeviceGet", ),
    "cuDeviceGetLuid": ("cuDeviceGetLuid", ),
    "cuGraphicsD3D11RegisterResource": ("cuGraphicsD3D11RegisterResource", ),
    "cuGraphicsResourceSetMapFlags": ("cuGraphicsResourceSetMapFlags_v2", "cuGraphicsResourceSetMapFlags"),
    "cuGraphicsMapResources": ("cuGraphicsMapResources", ),
    "cuGraphicsSubResourceGetMappedArray": ("cuGraphicsSubResourceGetMappedArray", ),
    "cuGraphicsUnmapResources": ("cuGraphicsUnmapResources", ),
    "cuGraphicsUnregisterResource": ("cuGraphicsUnregisterResource", ),
    "cuMemcpy2D": ("cuMemcpy2D_v2", "cuMemcpy2D"),
}


class CUDALibrary:
    """ the driver API functions we need, all returning a `CUresult` """

    def __init__(self, dll):
        for name, symbols in FUNCTIONS.items():
            for symbol in symbols:
                fn = getattr(dll, symbol, None)
                if fn:
                    fn.restype = c_int
                    setattr(self, name, fn)
                    break
            else:
                raise ImportError(f"{dll} does not provide {name!r}")


library: CUDALibrary | None = None


def get_library() -> CUDALibrary:
    global library
    if library is None:
        library = CUDALibrary(ctypes.WinDLL("nvcuda.dll"))
    return library


def get_device_luid(device_ordinal: int, lib=None) -> bytes:
    lib = lib or get_library()
    device = c_int()
    cudacheck(lib.cuDeviceGet(byref(device), device_ordinal), "cuDeviceGet")
    luid = ctypes.create_string_buffer(8)
    node_mask = c_uint()
    cudacheck(lib.cuDeviceGetLuid(luid, byref(node_mask), device), "cuDeviceGetLuid")
    return luid.raw


def com_add_ref(ptr: int) -> None:
    from xpra.platform.win32.d3d11.device import com_add_ref as add_ref
    add_ref(ptr)


def com_release(ptr: int) -> None:
    from xpra.platform.win32.d3d11.device import com_release as release
    release(ptr)


class D3D11Interop:
    """
    The registrations belong to the CUDA context that was current when they were made,
    so this object must only be used with the same context pushed, including `clean()`.
    """

    def __init__(self, device_ordinal: int, lib=None):
        self.lib = lib or get_library()
        self.luid: bytes = get_device_luid(device_ordinal, self.lib)
        self.registrations: OrderedDict[int, c_void_p] = OrderedDict()
        log("D3D11Interop(%i) luid=%s", device_ordinal, self.luid.hex())

    def __repr__(self):
        return f"D3D11Interop({self.luid.hex()})"

    def get_resource(self, texture: int) -> c_void_p:
        resource = self.registrations.get(texture)
        if resource is not None:
            self.registrations.move_to_end(texture)
            return resource
        while len(self.registrations) >= MAX_REGISTRATIONS:
            self.unregister(*self.registrations.popitem(last=False))
        resource = c_void_p()
        # hold a reference so that the texture cannot be freed, and its address re-used, while registered:
        com_add_ref(texture)
        try:
            cudacheck(self.lib.cuGraphicsD3D11RegisterResource(byref(resource), c_void_p(texture),
                                                               CU_GRAPHICS_REGISTER_FLAGS_NONE),
                      "cuGraphicsD3D11RegisterResource")
            cudacheck(self.lib.cuGraphicsResourceSetMapFlags(resource, CU_GRAPHICS_MAP_RESOURCE_FLAGS_READ_ONLY),
                      "cuGraphicsResourceSetMapFlags")
        except Exception:
            if resource:
                self.lib.cuGraphicsUnregisterResource(resource)
            com_release(texture)
            raise
        log("registered texture %#x as %#x", texture, resource.value or 0)
        self.registrations[texture] = resource
        return resource

    def unregister(self, texture: int, resource: c_void_p) -> None:
        try:
            r = self.lib.cuGraphicsUnregisterResource(resource)
            if r:
                log("cuGraphicsUnregisterResource(%#x)=%i", resource.value or 0, r)
        finally:
            com_release(texture)

    def copy_to(self, texture, dst: int, dst_pitch: int, width: int, height: int) -> None:
        """ copy `width` x `height` pixels of a `D3D11Texture` to the device memory at `dst` """
        resource = self.get_resource(texture.texture)
        cudacheck(self.lib.cuGraphicsMapResources(1, byref(resource), None), "cuGraphicsMapResources")
        try:
            array = c_void_p()
            cudacheck(self.lib.cuGraphicsSubResourceGetMappedArray(byref(array), resource, 0, 0),
                      "cuGraphicsSubResourceGetMappedArray")
            copy = CUDA_MEMCPY2D()
            copy.srcXInBytes = texture.x * 4
            copy.srcY = texture.y
            copy.srcMemoryType = CU_MEMORYTYPE_ARRAY
            copy.srcArray = array
            copy.dstMemoryType = CU_MEMORYTYPE_DEVICE
            copy.dstDevice = dst
            copy.dstPitch = dst_pitch
            copy.WidthInBytes = width * 4
            copy.Height = height
            cudacheck(self.lib.cuMemcpy2D(byref(copy)), "cuMemcpy2D")
        finally:
            cudacheck(self.lib.cuGraphicsUnmapResources(1, byref(resource), None), "cuGraphicsUnmapResources")

    def clean(self) -> None:
        registrations = self.registrations
        self.registrations = OrderedDict()
        for texture, resource in registrations.items():
            self.unregister(texture, resource)
