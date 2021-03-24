![OpenGL](https://xpra.org/icons/opengl.png)

The native client can use OpenGL for better window rendering performance.

This is in no way related to the [OpenGL capabilities of the server](./OpenGL.md).


# Configuration
This feature normally enabled by default if all the required components are installed correctly, which should be the case with the official packages.

During startup, the client will probe the operating system's OpenGL capabilities to ensure that this acceleration can be enabled safely.\
This check may take a few seconds to complete. It can be skipped using the `opengl=yes` option, alternatively acceleration can be disabled completely with `opengl=no`.

The client will only actually enable this acceleration for some windows as OpenGL acceleration provides no real benefit for very small windows, ephemeral windows or windows that do not receive many screen updates.


# Benefits
The window's pixels are kept in GPU buffers and so re-painting the window can be done quickly and efficiently.

Some screen updates, in particular for some of the [video codecs](./Encodings.md), can also be processed directly on the GPU - at least partially.


# GPUs and drivers
Due to some known bugs and incompatibilities, some drivers are disabled by default. (see [gl driver list](../../xpra/client/gl/gl_drivers.py))

Basic information about the OpenGL driver in use can be found in the "Features" pane of the "Session Info" dialog or the client's command line output.\
For more details, run `xpra opengl`. On MS Windows, there is an `OpenGL_check.exe` shortcut.


# Intel Driver Issues
<details>
  <summary>Why is the Intel opengl driver greylisted?</summary>

Because it doesn't work very well.
See:
* [#1367 enable more opengl chipsets](https://github.com/Xpra-org/xpra/issues/1367) 
* [#1233 whitelist some more intel chipsets](https://github.com/Xpra-org/xpra/issues/1233)
* [#1364 painting random window as solid white upon connection](https://github.com/Xpra-org/xpra/issues/1364)
* window resizing problems: [#1469](https://github.com/Xpra-org/xpra/issues/1469) / [#1468](../issues/1468) - 
* [#1050 fullscreen crash on win32](https://github.com/Xpra-org/xpra/issues/1050)
* [#1024 `glTexParameteri` error](https://github.com/Xpra-org/xpra/issues/1024)
* [#968 rendering dimensions](https://github.com/Xpra-org/xpra/issues/968)
* [#809 rendering fails](https://github.com/Xpra-org/xpra/issues/809)
* OSX crashes: [#808](https://github.com/Xpra-org/xpra/issues/808) / [#563](../issues/563) / [#1087](../issues/1087)
* [#745 windows greyed out](https://github.com/Xpra-org/xpra/issues/745)
* [#565 Linux opengl errors](https://github.com/Xpra-org/xpra/issues/565)
* [#147 original feature ticket - odd behaviour already reported](https://github.com/Xpra-org/xpra/issues/147)
* [#1358 glclear bug in driver](https://github.com/Xpra-org/xpra/issues/1358)
* [#1362 high cpu usage due to non-opengl rendering](https://github.com/Xpra-org/xpra/issues/1362)
</details>

# `OpenGL` Reference Links
* [mesamatrix](https://mesamatrix.net/): mesa driver implementation coverage
* [opengl.org wiki](https://www.opengl.org/wiki/Main_Page)
* [open.gl](http://open.gl/) _This guide will teach you the basics of using OpenGL to develop modern graphics applications_
* [opengl-tutorial.org](http://www.opengl-tutorial.org/) _This site is dedicated to tutorials for OpenGL 3.3 and later !_
* [OpenGL 2 Tutorials](http://www.swiftless.com/opengltuts.html) at [swiftless.com](http://www.swiftless.com)
* [wikibooks.org: OpenGL Programming](http://en.wikibooks.org/wiki/OpenGL_Programming)
* [Premultiplied Alpha (in OpenGL)](http://blog.rarepebble.com/111/premultiplied-alpha-in-opengl/)
* [Modern OpenGL tutorial (python)](http://www.labri.fr/perso/nrougier/teaching/opengl/)
