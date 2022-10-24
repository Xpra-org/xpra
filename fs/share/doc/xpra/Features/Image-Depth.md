# Image Depth

## Usage
Simply specify which pixel bit depth you want to use when starting a session, ie:
```shell
xpra start --pixel-depth=30
```

## Support
* [seamless mode](../Usage/Seamless.md) (aka `xpra start`) supports bit depths 16,24 and 30
* [desktop mode](../Usage/StartDesktop.md) (aka `start-desktop`) supports 8,16,24 and 30
* the native client `xpra attach` supports 16,24,30,48

Testing that high bit depth is actually in use can be tricky, for that the `xpra toolbox` provides a test application.


## Limitations
* the operating system and display must be configured for deep colour support
* transparency is supported in 24-bit mode, which is in effect a 32-bit mode
* with versions older than 4.1, 30-bit rendering is only supported in the [opengl enabled client](./Client-OpenGL.md), and only the `rgb` encoding will preserve high bit depth
* 16-bit mode has no real native encoders and so the pixels are often upsampled to 24-bit before compression which is wasteful
* 8-bit mode is not optimized at all
* see also [DPI](./DPI.md)

## Feature links
* [#1445](https://github.com/Xpra-org/xpra/issues/1445): 8-bit server support
* [#1315](https://github.com/Xpra-org/xpra/issues/1315): 16-bit server support
* [#909](https://github.com/Xpra-org/xpra/issues/909): 30-bit server support
* [#1309](https://github.com/Xpra-org/xpra/issues/1309), [#2839](../issues/2839): 30-bit client support
* [#2828](https://github.com/Xpra-org/xpra/issues/2828): 30-bit opengl rendering of video output
* [#1584](https://github.com/Xpra-org/xpra/issues/1584): HDR / Deep Color support in X11
* [10-bit Color Visual Support Lands In Mesa](https://www.phoronix.com/scan.php?page=news_item&px=Mesa-Lands-10-bit-Color)
Codec support for 10 bit per channel (aka 30 bit):
* [#1441](https://github.com/Xpra-org/xpra/issues/1441): EXR codec
* [#1310](https://github.com/Xpra-org/xpra/issues/1310): vpx
* [#1308](https://github.com/Xpra-org/xpra/issues/1308): nvenc
* [#1462](https://github.com/Xpra-org/xpra/issues/1462): x264
