# DPI

Xpra synchronizes the DPI from the client to the server, so that applications will render with the correct settings and "look right" on the client.
This may affect fonts, window sizes, cursors sizes, etc.

See also: [image depth](./Image-Depth.md)

## Important caveats:
* support varies greatly depending on the operating system and version, desktop environment, number of monitors attached and their resolution, etc
* with X11, there are far too many places where the DPI can be looked up, many places where it can be overridden
* for virtualized "hardware DPI" which some applications calculate from the virtual monitor dimensions, you will need a patched [Xdummy](./Xdummy) driver and [FakeXinerama](../../../libfakeXinerama): without a patched dummy driver, the hardware DPI - as reported by `xdpyinfo` - cannot be updated at runtime and must be set in advance, either in the `/etc/xpra/xorg.conf` file or on the `Xvfb` command line
* many applications will not reload the DPI settings, so they must be started _after_ the client connects to get the correct DPI value (you may want to use `start-after-connect`)


## Debugging
For [debugging](https://github.com/Xpra-org/xpra/wiki/Debugging) or [reporting issues](https://github.com/Xpra-org/xphttps://github.com/Xpra-org/xpra/issues/new), the most relevant pieces of information can be collected from:
* client and server debug output with `-d dpi` command line switch
* `xdpyinfo` output
* `xrandr` output


## Technical details
* [Physical vs logical DPI on X](https://www.mail-archive.com/xorg-devel@lists.x.org/msg57713.html)
* [Of DPIs, desktops, and toolkits](https://www.happyassassin.net/2015/07/09/of-dpis-desktops-and-toolkits/)
* win32 API:
 * [WM_DPICHANGED](https://msdn.microsoft.com/en-us/library/windows/desktop/dn312083(v=vs.85).aspx)
 * [GetDpiForMonitor](https://msdn.microsoft.com/en-us/library/windows/desktop/dn302058(v=vs.85).aspx)
 * [SetProcessDpiAwareness](https://msdn.microsoft.com/en-us/library/windows/desktop/dn302122.aspx)
 * [Writing DPI-Aware Desktop and Win32 Applications](https://msdn.microsoft.com/en-us/library/windows/desktop/dn469266(v=vs.85).aspx)
* [Scaling Windows - The DPI Arms Race](http://www.anandtech.com/show/7939/scaling-windows-the-dpi-arms-race), in particular: [Windows 8.1 - More DPI Changes](http://www.anandtech.com/show/7939/scaling-windows-the-dpi-arms-race/5)
* [About High Resolution for OS X](https://developer.apple.com/library/mac/documentation/GraphicsAnimation/Conceptual/HighResolutionOSX/Introduction/Introduction.html)
* [Qt: Retina display support for Mac OS, iOS and X11](http://blog.qt.io/blog/2013/04/25/retina-display-support-for-mac-os-ios-and-x11/)
* [xserver forces 96 DPI on randr-1.2-capable drivers, overriding correct autodetection](https://bugs.freedesktop.org/show_bug.cgi?id=23705)
* [please add option to avoid forcing of 96dpi](https://gitlab.freedesktop.org/xorg/xservhttps://github.com/Xpra-org/xpra/issues/253)
* [xserver forces 96 DPI on randr-1.2-capable drivers, overriding correct autodetection](https://bugs.freedesktop.org/show_bug.cgi?id=23705)
* [Xorg: setting DPI manually](https://wiki.archlinux.org/index.php/xorg#Setting_DPI_manually)
* [KDE & Qt Applications and High DPI Displays with Scaling](https://cullmann.io/posts/kde-qt-highdpi-scaling/)
* how different versions of windows [use different icon sizes and where](http://stackoverflow.com/a/3244679/428751)


## xpra DPI issues
* [Ubuntu packaging problems](./Distribution-Packages-Ubuntu)
* [#697](https://github.com/Xpra-org/xpra/issues/697) GTK screen dimension detection is broken with high DPI displays on windows7 and later
* [#163](https://github.com/Xpra-org/xpra/issues/163) pass client DPI preference to server and use sane default value of `96`
* [#976](https://github.com/Xpra-org/xpra/issues/976) client display scaling
* [#919](https://github.com/Xpra-org/xpra/issues/919) frame extents synchronization
* [#887](https://github.com/Xpra-org/xpra/issues/887) chrome DPI
* [#882](https://github.com/Xpra-org/xpra/issues/882) DPI with Ubuntu - not fixable as Ubuntu does not use [Xdummy](./Xdummy)
* [#1086](https://github.com/Xpra-org/xpra/issues/1086) DPI handling improvements, MacOS support
* [#1215](https://github.com/Xpra-org/xpra/issues/1215) patched dummy driver for Debian and Ubuntu
* [#1193](https://github.com/Xpra-org/xpra/issues/1193) bug with client command line switch handling
* [#1526](https://github.com/Xpra-org/xpra/issues/1526) per-monitor DPI with MS Windows clients
* [#1933](https://github.com/Xpra-org/xpra/issues/1933) HIDPI awareness for MacOS
