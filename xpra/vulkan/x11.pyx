# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# X11 (Xlib) surface support for the platform-independent Vulkan renderer.
#
# This is the only X11 specific part of the Vulkan code: it opens a connection
# to the X server and creates a VkSurfaceKHR for a native window (XID). The
# resulting surface handle is handed to `xpra.vulkan.renderer.VulkanWindow`,
# which contains no platform specific code. Equivalent helpers can be written
# for Wayland, win32 or macOS.

# cython: language_level=3

from libc.stdint cimport uintptr_t
from libc.string cimport memset

from xpra.log import Logger

log = Logger("vulkan")


cdef extern from "X11/Xlib.h":
    ctypedef struct Display
    ctypedef unsigned long Window
    Display *XOpenDisplay(const char *name)
    int XCloseDisplay(Display *display)


cdef extern from "vulkan/vulkan_core.h":
    ctypedef int VkResult
    ctypedef int VkStructureType
    ctypedef void *VkInstance
    ctypedef void *VkSurfaceKHR
    int VK_SUCCESS
    int VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR


cdef extern from "vulkan/vulkan_xlib.h":
    ctypedef int VkXlibSurfaceCreateFlagsKHR

    ctypedef struct VkXlibSurfaceCreateInfoKHR:
        VkStructureType sType
        const void *pNext
        VkXlibSurfaceCreateFlagsKHR flags
        Display *dpy
        Window window

    VkResult vkCreateXlibSurfaceKHR(VkInstance instance, const VkXlibSurfaceCreateInfoKHR *pCreateInfo,
                                    const void *pAllocator, VkSurfaceKHR *pSurface)


# the Vulkan instance extension required to create an xlib surface:
INSTANCE_EXTENSIONS = ("VK_KHR_xlib_surface", )


cdef class X11Surface:
    """
    Owns an X11 display connection and creates a Vulkan xlib surface from it.
    Pass an instance of this as the `owner` to VulkanWindow.init_surface so that
    the display connection is closed when the window is closed.
    """
    cdef Display *display

    def __cinit__(self, display_name: str = ""):
        cdef bytes bname
        cdef const char *cname = NULL
        if display_name:
            bname = display_name.encode("latin1")
            cname = bname
        self.display = XOpenDisplay(cname)
        if self.display == NULL:
            raise RuntimeError("failed to open X11 display %r" % (display_name or "default"))
        log("opened X11 display %r", display_name or "default")

    def create_surface(self, instance: int, xid: int) -> int:
        if self.display == NULL:
            raise RuntimeError("X11 display is closed")
        cdef VkInstance vk_instance = <VkInstance> <uintptr_t> instance
        cdef VkSurfaceKHR surface
        cdef VkXlibSurfaceCreateInfoKHR si
        memset(&si, 0, sizeof(VkXlibSurfaceCreateInfoKHR))
        si.sType = VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR
        si.dpy = self.display
        si.window = <Window> xid
        cdef VkResult r = vkCreateXlibSurfaceKHR(vk_instance, &si, NULL, &surface)
        if r != VK_SUCCESS:
            raise RuntimeError("vkCreateXlibSurfaceKHR failed: VkResult=%i" % (<int> r))
        log("created xlib surface for window %#x", xid)
        return <uintptr_t> surface

    def cleanup(self) -> None:
        if self.display != NULL:
            XCloseDisplay(self.display)
            self.display = NULL
            log("closed X11 display")

    def __dealloc__(self):
        self.cleanup()


def create_vulkan_window(xid: int, width: int, height: int, display_name: str = ""):
    """
    Convenience helper: create a VulkanWindow rendering to an X11 window (XID).
    """
    from xpra.vulkan.renderer import VulkanWindow
    vw = VulkanWindow(width, height, INSTANCE_EXTENSIONS)
    owner = X11Surface(display_name)
    surface = owner.create_surface(vw.instance, xid)
    vw.init_surface(surface, owner)
    return vw
