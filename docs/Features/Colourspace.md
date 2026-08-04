# Colourspace

## The session colourspace

A virtual framebuffer (`Xvfb`, `Xdummy` or `Xwayland`) has no colourimetry of its own:
there is no monitor attached, so there is no EDID, no ICC profile,
and the X11 core protocol cannot express primaries at all.
The only sensible interpretation of its contents is
[sRGB](https://en.wikipedia.org/wiki/SRGB) (BT.709 primaries, D65 white point, full range),
which is also what every toolkit assumes when no metadata is available.

The server therefore declares the colourspace it renders into, once, when the session starts:
* the matching ICC profile is set on the root window as `_ICC_PROFILE` / `_ICC_PROFILE_IN_X_VERSION`,
  so that colour managed applications running in the session know what they are rendering into
  (this requires [pillow](https://python-pillow.org/) with `ImageCms` support -
  without it the property is simply left unset, which already means sRGB)
* it is sent to the client as a capability, so that the client can convert the pixels
  to whatever colourspace its own display uses

The colourspace is described by four code points -
primaries, transfer function, matrix coefficients and range -
using the numbering from ITU-T H.273 (ISO/IEC 23091-2),
which is the one the video encoders already use.

It can be inspected with:
```shell
xpra info | grep colourspace
```

## Legacy client profile synchronization

Older versions did the opposite: the client's ICC profile was applied to the virtual framebuffer,
so that applications rendered pre-adapted for that particular client's monitor.
This cannot work for a session that outlives its clients:
it breaks with more than one client connected, with [shadow](../Usage/Shadow.md) mode,
when reconnecting from a different machine,
and when the client's monitors do not all share the same profile
(there is only one root window property).

This behaviour is still available for single client colour managed workflows,
by setting the environment variable on both the client and the server:
```shell
XPRA_SYNC_ICC=1
```

## See also
* [Image Depth](Image-Depth.md) - a wider gamut needs more than 8 bits per channel
* [Encodings](../Usage/Encodings.md)
