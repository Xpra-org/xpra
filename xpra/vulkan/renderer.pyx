# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# A minimal, platform-independent Vulkan renderer that paints BGRX pixels into a window.
#
# It uses a plain buffer->image copy (vkCmdCopyBufferToImage) onto the swapchain
# image, which is created in the B8G8R8A8_UNORM format that matches BGRX byte
# ordering. No graphics pipeline and no shaders are needed, so nothing has to be
# compiled to SPIR-V.
#
# This module contains NO platform specific code: it does not know about X11,
# Wayland, win32 or macOS. The caller creates a VkSurfaceKHR using a platform
# specific helper (e.g. xpra.vulkan.x11) and hands the surface handle to
# `VulkanWindow.init_surface`. The required instance extension names are also
# supplied by the platform helper and passed to the constructor.
#
# Note: handles are treated as opaque pointers, which is correct on 64-bit Linux
# (where non-dispatchable Vulkan handles are pointer-sized).

# cython: language_level=3

from libc.stdint cimport uint32_t, uint64_t, uintptr_t
from libc.stdlib cimport malloc, free
from libc.string cimport memset, memcpy

from xpra.util.str_fn import strtobytes
from xpra.log import Logger

log = Logger("vulkan")


cdef extern from "vulkan/vulkan_core.h":
    ctypedef int VkResult
    ctypedef int VkStructureType
    ctypedef int VkFormat
    ctypedef int VkColorSpaceKHR
    ctypedef int VkPresentModeKHR
    ctypedef int VkImageLayout
    ctypedef int VkSharingMode
    ctypedef int VkCommandBufferLevel
    ctypedef uint32_t VkFlags
    ctypedef VkFlags VkBool32
    ctypedef VkFlags VkImageUsageFlags
    ctypedef VkFlags VkImageAspectFlags
    ctypedef VkFlags VkAccessFlags
    ctypedef VkFlags VkPipelineStageFlags
    ctypedef VkFlags VkMemoryPropertyFlags
    ctypedef VkFlags VkBufferUsageFlags
    ctypedef VkFlags VkQueueFlags
    ctypedef VkFlags VkSurfaceTransformFlagBitsKHR
    ctypedef VkFlags VkCompositeAlphaFlagBitsKHR
    ctypedef uint64_t VkDeviceSize

    # opaque handles (pointer-sized on LP64):
    ctypedef void *VkInstance
    ctypedef void *VkPhysicalDevice
    ctypedef void *VkDevice
    ctypedef void *VkQueue
    ctypedef void *VkCommandBuffer
    ctypedef void *VkSurfaceKHR
    ctypedef void *VkSwapchainKHR
    ctypedef void *VkImage
    ctypedef void *VkBuffer
    ctypedef void *VkDeviceMemory
    ctypedef void *VkSemaphore
    ctypedef void *VkFence
    ctypedef void *VkCommandPool

    int VK_SUCCESS
    int VK_SUBOPTIMAL_KHR
    int VK_ERROR_OUT_OF_DATE_KHR
    int VK_TRUE
    uint64_t VK_WHOLE_SIZE
    uint32_t VK_QUEUE_FAMILY_IGNORED

    # structure types we set:
    int VK_STRUCTURE_TYPE_APPLICATION_INFO
    int VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    int VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO
    int VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO
    int VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR
    int VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO
    int VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO
    int VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO
    int VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO
    int VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO
    int VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO
    int VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER
    int VK_STRUCTURE_TYPE_SUBMIT_INFO
    int VK_STRUCTURE_TYPE_PRESENT_INFO_KHR

    int VK_FORMAT_B8G8R8A8_UNORM
    int VK_COLOR_SPACE_SRGB_NONLINEAR_KHR
    int VK_PRESENT_MODE_FIFO_KHR
    int VK_SHARING_MODE_EXCLUSIVE
    int VK_COMMAND_BUFFER_LEVEL_PRIMARY

    int VK_QUEUE_GRAPHICS_BIT
    int VK_IMAGE_USAGE_TRANSFER_DST_BIT
    int VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT
    int VK_BUFFER_USAGE_TRANSFER_SRC_BIT
    int VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
    int VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
    int VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR

    int VK_IMAGE_LAYOUT_UNDEFINED
    int VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL
    int VK_IMAGE_LAYOUT_PRESENT_SRC_KHR
    int VK_IMAGE_ASPECT_COLOR_BIT
    int VK_ACCESS_TRANSFER_WRITE_BIT
    int VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT
    int VK_PIPELINE_STAGE_TRANSFER_BIT
    int VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT
    int VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT

    int VK_MAX_MEMORY_TYPES
    int VK_MAX_MEMORY_HEAPS

    ctypedef struct VkExtent2D:
        uint32_t width
        uint32_t height

    ctypedef struct VkExtent3D:
        uint32_t width
        uint32_t height
        uint32_t depth

    ctypedef struct VkOffset3D:
        int x
        int y
        int z

    ctypedef struct VkApplicationInfo:
        VkStructureType sType
        const void *pNext
        const char *pApplicationName
        uint32_t applicationVersion
        const char *pEngineName
        uint32_t engineVersion
        uint32_t apiVersion

    ctypedef struct VkInstanceCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        const VkApplicationInfo *pApplicationInfo
        uint32_t enabledLayerCount
        const char *const *ppEnabledLayerNames
        uint32_t enabledExtensionCount
        const char *const *ppEnabledExtensionNames

    ctypedef struct VkQueueFamilyProperties:
        VkQueueFlags queueFlags
        uint32_t queueCount
        uint32_t timestampValidBits
        VkExtent3D minImageTransferGranularity

    ctypedef struct VkDeviceQueueCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        uint32_t queueFamilyIndex
        uint32_t queueCount
        const float *pQueuePriorities

    ctypedef struct VkDeviceCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        uint32_t queueCreateInfoCount
        const VkDeviceQueueCreateInfo *pQueueCreateInfos
        uint32_t enabledLayerCount
        const char *const *ppEnabledLayerNames
        uint32_t enabledExtensionCount
        const char *const *ppEnabledExtensionNames
        const void *pEnabledFeatures

    ctypedef struct VkSurfaceCapabilitiesKHR:
        uint32_t minImageCount
        uint32_t maxImageCount
        VkExtent2D currentExtent
        VkExtent2D minImageExtent
        VkExtent2D maxImageExtent
        uint32_t maxImageArrayLayers
        VkSurfaceTransformFlagBitsKHR supportedTransforms
        VkSurfaceTransformFlagBitsKHR currentTransform
        VkCompositeAlphaFlagBitsKHR supportedCompositeAlpha
        VkImageUsageFlags supportedUsageFlags

    ctypedef struct VkSurfaceFormatKHR:
        VkFormat format
        VkColorSpaceKHR colorSpace

    ctypedef struct VkSwapchainCreateInfoKHR:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        VkSurfaceKHR surface
        uint32_t minImageCount
        VkFormat imageFormat
        VkColorSpaceKHR imageColorSpace
        VkExtent2D imageExtent
        uint32_t imageArrayLayers
        VkImageUsageFlags imageUsage
        VkSharingMode imageSharingMode
        uint32_t queueFamilyIndexCount
        const uint32_t *pQueueFamilyIndices
        VkSurfaceTransformFlagBitsKHR preTransform
        VkCompositeAlphaFlagBitsKHR compositeAlpha
        VkPresentModeKHR presentMode
        VkBool32 clipped
        VkSwapchainKHR oldSwapchain

    ctypedef struct VkCommandPoolCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        uint32_t queueFamilyIndex

    ctypedef struct VkCommandBufferAllocateInfo:
        VkStructureType sType
        const void *pNext
        VkCommandPool commandPool
        VkCommandBufferLevel level
        uint32_t commandBufferCount

    ctypedef struct VkCommandBufferBeginInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        const void *pInheritanceInfo

    ctypedef struct VkSemaphoreCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags

    ctypedef struct VkBufferCreateInfo:
        VkStructureType sType
        const void *pNext
        VkFlags flags
        VkDeviceSize size
        VkBufferUsageFlags usage
        VkSharingMode sharingMode
        uint32_t queueFamilyIndexCount
        const uint32_t *pQueueFamilyIndices

    ctypedef struct VkMemoryRequirements:
        VkDeviceSize size
        VkDeviceSize alignment
        uint32_t memoryTypeBits

    ctypedef struct VkMemoryType:
        VkMemoryPropertyFlags propertyFlags
        uint32_t heapIndex

    ctypedef struct VkMemoryHeap:
        VkDeviceSize size
        VkFlags flags

    ctypedef struct VkPhysicalDeviceMemoryProperties:
        uint32_t memoryTypeCount
        VkMemoryType memoryTypes[32]
        uint32_t memoryHeapCount
        VkMemoryHeap memoryHeaps[16]

    ctypedef struct VkMemoryAllocateInfo:
        VkStructureType sType
        const void *pNext
        VkDeviceSize allocationSize
        uint32_t memoryTypeIndex

    ctypedef struct VkImageSubresourceRange:
        VkImageAspectFlags aspectMask
        uint32_t baseMipLevel
        uint32_t levelCount
        uint32_t baseArrayLayer
        uint32_t layerCount

    ctypedef struct VkImageMemoryBarrier:
        VkStructureType sType
        const void *pNext
        VkAccessFlags srcAccessMask
        VkAccessFlags dstAccessMask
        VkImageLayout oldLayout
        VkImageLayout newLayout
        uint32_t srcQueueFamilyIndex
        uint32_t dstQueueFamilyIndex
        VkImage image
        VkImageSubresourceRange subresourceRange

    ctypedef struct VkImageSubresourceLayers:
        VkImageAspectFlags aspectMask
        uint32_t mipLevel
        uint32_t baseArrayLayer
        uint32_t layerCount

    ctypedef struct VkBufferImageCopy:
        VkDeviceSize bufferOffset
        uint32_t bufferRowLength
        uint32_t bufferImageHeight
        VkImageSubresourceLayers imageSubresource
        VkOffset3D imageOffset
        VkExtent3D imageExtent

    ctypedef struct VkSubmitInfo:
        VkStructureType sType
        const void *pNext
        uint32_t waitSemaphoreCount
        const VkSemaphore *pWaitSemaphores
        const VkPipelineStageFlags *pWaitDstStageMask
        uint32_t commandBufferCount
        const VkCommandBuffer *pCommandBuffers
        uint32_t signalSemaphoreCount
        const VkSemaphore *pSignalSemaphores

    ctypedef struct VkPresentInfoKHR:
        VkStructureType sType
        const void *pNext
        uint32_t waitSemaphoreCount
        const VkSemaphore *pWaitSemaphores
        uint32_t swapchainCount
        const VkSwapchainKHR *pSwapchains
        const uint32_t *pImageIndices
        VkResult *pResults

    VkResult vkCreateInstance(const VkInstanceCreateInfo *pCreateInfo, const void *pAllocator, VkInstance *pInstance)
    void vkDestroyInstance(VkInstance instance, const void *pAllocator)
    VkResult vkEnumeratePhysicalDevices(VkInstance instance, uint32_t *pCount, VkPhysicalDevice *pDevices)
    void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice d, uint32_t *pCount, VkQueueFamilyProperties *p)
    void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice d, VkPhysicalDeviceMemoryProperties *p)
    VkResult vkCreateDevice(VkPhysicalDevice d, const VkDeviceCreateInfo *pCreateInfo, const void *pAllocator, VkDevice *pDevice)
    void vkDestroyDevice(VkDevice device, const void *pAllocator)
    void vkGetDeviceQueue(VkDevice device, uint32_t queueFamilyIndex, uint32_t queueIndex, VkQueue *pQueue)
    VkResult vkDeviceWaitIdle(VkDevice device)
    VkResult vkQueueWaitIdle(VkQueue queue)

    VkResult vkCreateCommandPool(VkDevice d, const VkCommandPoolCreateInfo *i, const void *a, VkCommandPool *p)
    void vkDestroyCommandPool(VkDevice device, VkCommandPool commandPool, const void *pAllocator)
    VkResult vkAllocateCommandBuffers(VkDevice d, const VkCommandBufferAllocateInfo *i, VkCommandBuffer *p)
    VkResult vkBeginCommandBuffer(VkCommandBuffer cb, const VkCommandBufferBeginInfo *i)
    VkResult vkEndCommandBuffer(VkCommandBuffer cb)
    VkResult vkResetCommandBuffer(VkCommandBuffer cb, VkFlags flags)
    void vkCmdPipelineBarrier(VkCommandBuffer cb, VkPipelineStageFlags srcStageMask, VkPipelineStageFlags dstStageMask,
                              VkFlags dependencyFlags,
                              uint32_t memoryBarrierCount, const void *pMemoryBarriers,
                              uint32_t bufferMemoryBarrierCount, const void *pBufferMemoryBarriers,
                              uint32_t imageMemoryBarrierCount, const VkImageMemoryBarrier *pImageMemoryBarriers)
    void vkCmdCopyBufferToImage(VkCommandBuffer cb, VkBuffer srcBuffer, VkImage dstImage, VkImageLayout dstImageLayout,
                                uint32_t regionCount, const VkBufferImageCopy *pRegions)

    VkResult vkCreateSemaphore(VkDevice d, const VkSemaphoreCreateInfo *i, const void *a, VkSemaphore *p)
    void vkDestroySemaphore(VkDevice device, VkSemaphore semaphore, const void *pAllocator)

    VkResult vkCreateBuffer(VkDevice d, const VkBufferCreateInfo *i, const void *a, VkBuffer *p)
    void vkDestroyBuffer(VkDevice device, VkBuffer buffer, const void *pAllocator)
    void vkGetBufferMemoryRequirements(VkDevice device, VkBuffer buffer, VkMemoryRequirements *pMemoryRequirements)
    VkResult vkAllocateMemory(VkDevice d, const VkMemoryAllocateInfo *i, const void *a, VkDeviceMemory *p)
    void vkFreeMemory(VkDevice device, VkDeviceMemory memory, const void *pAllocator)
    VkResult vkBindBufferMemory(VkDevice device, VkBuffer buffer, VkDeviceMemory memory, VkDeviceSize memoryOffset)
    VkResult vkMapMemory(VkDevice d, VkDeviceMemory m, VkDeviceSize offset, VkDeviceSize size, VkFlags flags, void **ppData)
    void vkUnmapMemory(VkDevice device, VkDeviceMemory memory)

    VkResult vkQueueSubmit(VkQueue queue, uint32_t submitCount, const VkSubmitInfo *pSubmits, VkFence fence)

    # WSI / swapchain (exported by the loader):
    VkResult vkGetPhysicalDeviceSurfaceSupportKHR(VkPhysicalDevice d, uint32_t qf, VkSurfaceKHR s, VkBool32 *pSupported)
    VkResult vkGetPhysicalDeviceSurfaceCapabilitiesKHR(VkPhysicalDevice d, VkSurfaceKHR s, VkSurfaceCapabilitiesKHR *p)
    VkResult vkGetPhysicalDeviceSurfaceFormatsKHR(VkPhysicalDevice d, VkSurfaceKHR s, uint32_t *pCount, VkSurfaceFormatKHR *p)
    void vkDestroySurfaceKHR(VkInstance instance, VkSurfaceKHR surface, const void *pAllocator)
    VkResult vkCreateSwapchainKHR(VkDevice d, const VkSwapchainCreateInfoKHR *i, const void *a, VkSwapchainKHR *p)
    void vkDestroySwapchainKHR(VkDevice device, VkSwapchainKHR swapchain, const void *pAllocator)
    VkResult vkGetSwapchainImagesKHR(VkDevice d, VkSwapchainKHR s, uint32_t *pCount, VkImage *pImages)
    VkResult vkAcquireNextImageKHR(VkDevice d, VkSwapchainKHR s, uint64_t timeout, VkSemaphore sem, VkFence fence, uint32_t *pImageIndex)
    VkResult vkQueuePresentKHR(VkQueue queue, const VkPresentInfoKHR *pPresentInfo)


cdef void check(VkResult r, str msg):
    if r != VK_SUCCESS:
        raise RuntimeError("%s failed: VkResult=%i" % (msg, <int> r))


cdef class VulkanWindow:
    cdef VkInstance instance
    cdef object _surface_owner
    cdef VkSurfaceKHR surface
    cdef VkPhysicalDevice gpu
    cdef VkDevice device
    cdef uint32_t queue_family
    cdef VkQueue queue
    cdef VkSwapchainKHR swapchain
    cdef VkImage *images
    cdef uint32_t image_count
    cdef VkFormat format
    cdef uint32_t width
    cdef uint32_t height
    cdef VkCommandPool cmd_pool
    cdef VkCommandBuffer cmd_buffer
    cdef VkSemaphore acquire_sem
    cdef VkSemaphore render_sem
    cdef VkBuffer staging
    cdef VkDeviceMemory staging_mem
    cdef VkDeviceSize staging_size
    cdef void *staging_mapped

    def __cinit__(self, unsigned int width, unsigned int height, surface_extensions=()):
        self.width = width
        self.height = height
        self.images = NULL
        self.image_count = 0
        self._surface_owner = None
        self._create_instance(surface_extensions)

    def __repr__(self):
        return "VulkanWindow(%ix%i)" % (self.width, self.height)

    @property
    def instance(self) -> int:
        # the VkInstance handle, for platform surface helpers (as an integer):
        return <uintptr_t> self.instance

    cdef _create_instance(self, surface_extensions):
        cdef VkApplicationInfo app
        memset(&app, 0, sizeof(VkApplicationInfo))
        app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO
        app.pApplicationName = "xpra"
        app.pEngineName = "xpra"
        app.apiVersion = (1 << 22)  # VK_API_VERSION_1_0

        # "VK_KHR_surface" plus whatever the platform surface helper requires
        # (e.g. "VK_KHR_xlib_surface", "VK_KHR_wayland_surface", ...):
        names = [b"VK_KHR_surface"] + [strtobytes(e) for e in surface_extensions]
        cdef uint32_t count = len(names)
        cdef const char **exts = <const char **> malloc(count * sizeof(char *))
        if exts == NULL:
            raise MemoryError()

        cdef VkInstanceCreateInfo ci
        cdef uint32_t i
        try:
            for i in range(count):
                exts[i] = <const char *> names[i]
            memset(&ci, 0, sizeof(VkInstanceCreateInfo))
            ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
            ci.pApplicationInfo = &app
            ci.enabledExtensionCount = count
            ci.ppEnabledExtensionNames = exts
            check(vkCreateInstance(&ci, NULL, &self.instance), "vkCreateInstance")
        finally:
            free(exts)
        log("created Vulkan instance %#x with extensions %s", <uintptr_t> self.instance, names)

    def init_surface(self, surface: int, owner=None) -> None:
        # `surface` is a VkSurfaceKHR handle (as an integer) created by a
        # platform specific helper; `owner` is an optional object whose
        # `cleanup()` method is called when this window is closed, so the
        # helper can release any native resources it holds.
        if not surface:
            raise ValueError("invalid surface handle")
        self.surface = <VkSurfaceKHR> <uintptr_t> surface
        self._surface_owner = owner
        self._pick_device()
        self._create_device()
        self._create_swapchain()
        self._create_commands()

    cdef _pick_device(self):
        cdef uint32_t count = 0
        check(vkEnumeratePhysicalDevices(self.instance, &count, NULL), "vkEnumeratePhysicalDevices")
        if count == 0:
            raise RuntimeError("no Vulkan physical devices found")
        cdef VkPhysicalDevice *devices = <VkPhysicalDevice *> malloc(count * sizeof(VkPhysicalDevice))
        if devices == NULL:
            raise MemoryError()
        cdef uint32_t qcount
        cdef VkQueueFamilyProperties *qprops
        cdef VkBool32 present
        cdef uint32_t i, q
        try:
            check(vkEnumeratePhysicalDevices(self.instance, &count, devices), "vkEnumeratePhysicalDevices")
            for i in range(count):
                qcount = 0
                vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &qcount, NULL)
                if qcount == 0:
                    continue
                qprops = <VkQueueFamilyProperties *> malloc(qcount * sizeof(VkQueueFamilyProperties))
                if qprops == NULL:
                    raise MemoryError()
                try:
                    vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &qcount, qprops)
                    for q in range(qcount):
                        if not (qprops[q].queueFlags & VK_QUEUE_GRAPHICS_BIT):
                            continue
                        present = 0
                        vkGetPhysicalDeviceSurfaceSupportKHR(devices[i], q, self.surface, &present)
                        if present == VK_TRUE:
                            self.gpu = devices[i]
                            self.queue_family = q
                            log("selected physical device %i, queue family %i", i, q)
                            return
                finally:
                    free(qprops)
            raise RuntimeError("no Vulkan device with a graphics+present queue family")
        finally:
            free(devices)

    cdef _create_device(self):
        cdef float priority = 1.0
        cdef VkDeviceQueueCreateInfo qci
        memset(&qci, 0, sizeof(VkDeviceQueueCreateInfo))
        qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO
        qci.queueFamilyIndex = self.queue_family
        qci.queueCount = 1
        qci.pQueuePriorities = &priority

        cdef const char *dexts[1]
        dexts[0] = "VK_KHR_swapchain"

        cdef VkDeviceCreateInfo dci
        memset(&dci, 0, sizeof(VkDeviceCreateInfo))
        dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO
        dci.queueCreateInfoCount = 1
        dci.pQueueCreateInfos = &qci
        dci.enabledExtensionCount = 1
        dci.ppEnabledExtensionNames = dexts
        check(vkCreateDevice(self.gpu, &dci, NULL, &self.device), "vkCreateDevice")
        vkGetDeviceQueue(self.device, self.queue_family, 0, &self.queue)
        log("created logical device and queue")

    cdef _create_swapchain(self):
        cdef VkSurfaceCapabilitiesKHR caps
        check(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(self.gpu, self.surface, &caps),
              "vkGetPhysicalDeviceSurfaceCapabilitiesKHR")

        # pick the extent:
        if caps.currentExtent.width != 0xFFFFFFFF:
            self.width = caps.currentExtent.width
            self.height = caps.currentExtent.height

        # pick a BGRA format, ideally B8G8R8A8_UNORM (matches BGRX byte order):
        cdef uint32_t fcount = 0
        check(vkGetPhysicalDeviceSurfaceFormatsKHR(self.gpu, self.surface, &fcount, NULL),
              "vkGetPhysicalDeviceSurfaceFormatsKHR")
        if fcount == 0:
            raise RuntimeError("no surface formats available")
        cdef VkSurfaceFormatKHR *formats = <VkSurfaceFormatKHR *> malloc(fcount * sizeof(VkSurfaceFormatKHR))
        if formats == NULL:
            raise MemoryError()
        cdef VkColorSpaceKHR colorspace = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR
        cdef uint32_t i
        try:
            check(vkGetPhysicalDeviceSurfaceFormatsKHR(self.gpu, self.surface, &fcount, formats),
                  "vkGetPhysicalDeviceSurfaceFormatsKHR")
            self.format = formats[0].format
            colorspace = formats[0].colorSpace
            for i in range(fcount):
                if formats[i].format == VK_FORMAT_B8G8R8A8_UNORM:
                    self.format = VK_FORMAT_B8G8R8A8_UNORM
                    colorspace = formats[i].colorSpace
                    break
        finally:
            free(formats)
        if self.format != VK_FORMAT_B8G8R8A8_UNORM:
            log.warn("Warning: B8G8R8A8_UNORM swapchain format not available")
            log.warn(" using format %i instead, BGRX pixels may look wrong", <int> self.format)

        cdef uint32_t min_count = caps.minImageCount

        cdef VkSwapchainCreateInfoKHR sci
        memset(&sci, 0, sizeof(VkSwapchainCreateInfoKHR))
        sci.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR
        sci.surface = self.surface
        sci.minImageCount = min_count
        sci.imageFormat = self.format
        sci.imageColorSpace = colorspace
        sci.imageExtent.width = self.width
        sci.imageExtent.height = self.height
        sci.imageArrayLayers = 1
        # we copy into the image and present it:
        sci.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT
        sci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE
        sci.preTransform = caps.currentTransform
        sci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR
        sci.presentMode = VK_PRESENT_MODE_FIFO_KHR   # always supported
        sci.clipped = VK_TRUE
        sci.oldSwapchain = NULL
        check(vkCreateSwapchainKHR(self.device, &sci, NULL, &self.swapchain), "vkCreateSwapchainKHR")

        check(vkGetSwapchainImagesKHR(self.device, self.swapchain, &self.image_count, NULL),
              "vkGetSwapchainImagesKHR")
        self.images = <VkImage *> malloc(self.image_count * sizeof(VkImage))
        if self.images == NULL:
            raise MemoryError()
        check(vkGetSwapchainImagesKHR(self.device, self.swapchain, &self.image_count, self.images),
              "vkGetSwapchainImagesKHR")
        log("created swapchain %ix%i with %i images, format=%i",
            self.width, self.height, self.image_count, <int> self.format)

    cdef _create_commands(self):
        cdef VkCommandPoolCreateInfo pci
        memset(&pci, 0, sizeof(VkCommandPoolCreateInfo))
        pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO
        pci.queueFamilyIndex = self.queue_family
        # allow individual command buffer resets (1 == RESET_COMMAND_BUFFER_BIT):
        pci.flags = 0x00000002
        check(vkCreateCommandPool(self.device, &pci, NULL, &self.cmd_pool), "vkCreateCommandPool")

        cdef VkCommandBufferAllocateInfo ai
        memset(&ai, 0, sizeof(VkCommandBufferAllocateInfo))
        ai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO
        ai.commandPool = self.cmd_pool
        ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY
        ai.commandBufferCount = 1
        check(vkAllocateCommandBuffers(self.device, &ai, &self.cmd_buffer), "vkAllocateCommandBuffers")

        cdef VkSemaphoreCreateInfo semci
        memset(&semci, 0, sizeof(VkSemaphoreCreateInfo))
        semci.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO
        check(vkCreateSemaphore(self.device, &semci, NULL, &self.acquire_sem), "vkCreateSemaphore")
        check(vkCreateSemaphore(self.device, &semci, NULL, &self.render_sem), "vkCreateSemaphore")

    cdef uint32_t _find_memory_type(self, uint32_t type_bits, VkMemoryPropertyFlags want):
        cdef VkPhysicalDeviceMemoryProperties props
        vkGetPhysicalDeviceMemoryProperties(self.gpu, &props)
        cdef uint32_t i
        for i in range(props.memoryTypeCount):
            if (type_bits & (1 << i)) and (props.memoryTypes[i].propertyFlags & want) == want:
                return i
        raise RuntimeError("no suitable memory type found")

    cdef _ensure_staging(self, VkDeviceSize size):
        if self.staging != NULL and self.staging_size >= size:
            return
        # (re)create a larger host-visible staging buffer:
        self._free_staging()

        cdef VkBufferCreateInfo bci
        memset(&bci, 0, sizeof(VkBufferCreateInfo))
        bci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO
        bci.size = size
        bci.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT
        bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE
        check(vkCreateBuffer(self.device, &bci, NULL, &self.staging), "vkCreateBuffer")

        cdef VkMemoryRequirements req
        vkGetBufferMemoryRequirements(self.device, self.staging, &req)

        cdef VkMemoryAllocateInfo mai
        memset(&mai, 0, sizeof(VkMemoryAllocateInfo))
        mai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO
        mai.allocationSize = req.size
        mai.memoryTypeIndex = self._find_memory_type(
            req.memoryTypeBits,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)
        check(vkAllocateMemory(self.device, &mai, NULL, &self.staging_mem), "vkAllocateMemory")
        check(vkBindBufferMemory(self.device, self.staging, self.staging_mem, 0), "vkBindBufferMemory")
        check(vkMapMemory(self.device, self.staging_mem, 0, VK_WHOLE_SIZE, 0, &self.staging_mapped),
              "vkMapMemory")
        self.staging_size = req.size
        log("allocated %i byte staging buffer", <int> req.size)

    def paint_bgrx(self, pixels, unsigned int width, unsigned int height, unsigned int stride) -> None:
        if self.swapchain == NULL:
            raise RuntimeError("swapchain not initialized")
        if stride < width * 4:
            raise ValueError("stride %i too small for width %i" % (stride, width))
        if stride % 4 != 0:
            raise ValueError("stride %i is not a multiple of 4" % stride)

        cdef const unsigned char[::1] buf = pixels
        cdef VkDeviceSize size = <VkDeviceSize> stride * height
        if <Py_ssize_t> size > buf.shape[0]:
            raise ValueError("buffer too small: %i bytes for %ix%i stride=%i" % (buf.shape[0], width, height, stride))

        self._ensure_staging(size)
        memcpy(self.staging_mapped, <const void *> &buf[0], size)

        cdef bint need_recreate = False
        cdef uint32_t index = 0
        cdef VkResult ar = vkAcquireNextImageKHR(self.device, self.swapchain, <uint64_t> -1,
                                                 self.acquire_sem, NULL, &index)
        if ar == VK_ERROR_OUT_OF_DATE_KHR:
            # the surface changed size: recreate and skip this frame
            self._recreate_swapchain()
            return
        if ar == VK_SUBOPTIMAL_KHR:
            # the image was still acquired: render it, then recreate
            need_recreate = True
        elif ar != VK_SUCCESS:
            check(ar, "vkAcquireNextImageKHR")

        cdef uint32_t copy_w = width if width < self.width else self.width
        cdef uint32_t copy_h = height if height < self.height else self.height

        check(vkResetCommandBuffer(self.cmd_buffer, 0), "vkResetCommandBuffer")

        cdef VkCommandBufferBeginInfo begin
        memset(&begin, 0, sizeof(VkCommandBufferBeginInfo))
        begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO
        begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT
        check(vkBeginCommandBuffer(self.cmd_buffer, &begin), "vkBeginCommandBuffer")

        cdef VkImageMemoryBarrier to_dst
        memset(&to_dst, 0, sizeof(VkImageMemoryBarrier))
        to_dst.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER
        to_dst.srcAccessMask = 0
        to_dst.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT
        to_dst.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED
        to_dst.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL
        to_dst.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED
        to_dst.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED
        to_dst.image = self.images[index]
        to_dst.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT
        to_dst.subresourceRange.levelCount = 1
        to_dst.subresourceRange.layerCount = 1
        vkCmdPipelineBarrier(self.cmd_buffer, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                             0, 0, NULL, 0, NULL, 1, &to_dst)

        cdef VkBufferImageCopy region
        memset(&region, 0, sizeof(VkBufferImageCopy))
        region.bufferOffset = 0
        region.bufferRowLength = stride // 4
        region.bufferImageHeight = 0
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT
        region.imageSubresource.layerCount = 1
        region.imageExtent.width = copy_w
        region.imageExtent.height = copy_h
        region.imageExtent.depth = 1
        vkCmdCopyBufferToImage(self.cmd_buffer, self.staging, self.images[index],
                               VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region)

        cdef VkImageMemoryBarrier to_present
        memset(&to_present, 0, sizeof(VkImageMemoryBarrier))
        to_present.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER
        to_present.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT
        to_present.dstAccessMask = 0
        to_present.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL
        to_present.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR
        to_present.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED
        to_present.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED
        to_present.image = self.images[index]
        to_present.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT
        to_present.subresourceRange.levelCount = 1
        to_present.subresourceRange.layerCount = 1
        vkCmdPipelineBarrier(self.cmd_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
                             0, 0, NULL, 0, NULL, 1, &to_present)

        check(vkEndCommandBuffer(self.cmd_buffer), "vkEndCommandBuffer")

        cdef VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT
        cdef VkSubmitInfo submit
        memset(&submit, 0, sizeof(VkSubmitInfo))
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO
        submit.waitSemaphoreCount = 1
        submit.pWaitSemaphores = &self.acquire_sem
        submit.pWaitDstStageMask = &wait_stage
        submit.commandBufferCount = 1
        submit.pCommandBuffers = &self.cmd_buffer
        submit.signalSemaphoreCount = 1
        submit.pSignalSemaphores = &self.render_sem
        check(vkQueueSubmit(self.queue, 1, &submit, NULL), "vkQueueSubmit")

        cdef VkPresentInfoKHR present
        memset(&present, 0, sizeof(VkPresentInfoKHR))
        present.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR
        present.waitSemaphoreCount = 1
        present.pWaitSemaphores = &self.render_sem
        present.swapchainCount = 1
        present.pSwapchains = &self.swapchain
        present.pImageIndices = &index
        cdef VkResult pr = vkQueuePresentKHR(self.queue, &present)
        if pr in (VK_ERROR_OUT_OF_DATE_KHR, VK_SUBOPTIMAL_KHR):
            need_recreate = True
        elif pr != VK_SUCCESS:
            check(pr, "vkQueuePresentKHR")

        # simple synchronization: wait for the frame to complete before reusing resources
        vkQueueWaitIdle(self.queue)
        log("painted %ix%i (copied %ix%i)", width, height, copy_w, copy_h)
        if need_recreate:
            self._recreate_swapchain()

    cdef _recreate_swapchain(self):
        vkDeviceWaitIdle(self.device)
        self._destroy_swapchain()
        self._create_swapchain()

    def resize(self, unsigned int width, unsigned int height) -> None:
        if self.device == NULL:
            return
        vkDeviceWaitIdle(self.device)
        self.width = width
        self.height = height
        self._destroy_swapchain()
        self._create_swapchain()

    cdef _destroy_swapchain(self):
        if self.images != NULL:
            free(self.images)
            self.images = NULL
        self.image_count = 0
        if self.swapchain != NULL:
            vkDestroySwapchainKHR(self.device, self.swapchain, NULL)
            self.swapchain = NULL

    cdef _free_staging(self):
        if self.staging_mapped != NULL:
            vkUnmapMemory(self.device, self.staging_mem)
            self.staging_mapped = NULL
        if self.staging != NULL:
            vkDestroyBuffer(self.device, self.staging, NULL)
            self.staging = NULL
        if self.staging_mem != NULL:
            vkFreeMemory(self.device, self.staging_mem, NULL)
            self.staging_mem = NULL
        self.staging_size = 0

    def close(self) -> None:
        if self.device != NULL:
            vkDeviceWaitIdle(self.device)
            self._free_staging()
            if self.render_sem != NULL:
                vkDestroySemaphore(self.device, self.render_sem, NULL)
                self.render_sem = NULL
            if self.acquire_sem != NULL:
                vkDestroySemaphore(self.device, self.acquire_sem, NULL)
                self.acquire_sem = NULL
            if self.cmd_pool != NULL:
                vkDestroyCommandPool(self.device, self.cmd_pool, NULL)
                self.cmd_pool = NULL
            self._destroy_swapchain()
            vkDestroyDevice(self.device, NULL)
            self.device = NULL
        if self.surface != NULL:
            vkDestroySurfaceKHR(self.instance, self.surface, NULL)
            self.surface = NULL
        # let the platform helper release its native resources now that the
        # surface is gone (e.g. close the X11 display connection):
        if self._surface_owner is not None:
            owner = self._surface_owner
            self._surface_owner = None
            cleanup = getattr(owner, "cleanup", None)
            if cleanup is not None:
                cleanup()
        if self.instance != NULL:
            vkDestroyInstance(self.instance, NULL)
            self.instance = NULL
        log("VulkanWindow closed")

    def __dealloc__(self):
        self.close()
