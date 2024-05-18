# CUDA kernels

This folder contains the CUDA kernels used by xpra's nvidia codecs
to handle colourspace conversion on the GPU.

The "RGB to YUV" conversions use the `JPEG conversion` constants from:
[ITU-R_BT.601_conversion](https://en.wikipedia.org/wiki/YCbCr#ITU-R_BT.601_conversion)
