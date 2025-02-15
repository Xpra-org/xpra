![OpenGL](../images/icons/opengl.png)

This documentation is about running OpenGL _applications_ in an xpra session and this has nothing to do with the [client's opengl acceleration](Client-OpenGL.md).

By default, OpenGL applications are supported, but they are executed in a virtual framebuffer context which uses a software renderer, and therefore without any GPU acceleration.


# GPU Acceleration
To take advantage of GPU [OpenGL](https://www.opengl.org/) acceleration, here are some options:

* ## VirtualGL
[VirtualGL](http://www.virtualgl.org/) does API intercept and delegates OpenGL acceleration to a real GPU. Example:
```shell
xpra start --start="vglrun glxgears"
```
Or even better:
```shell
xpra start --exec-wrapper="vglrun" --start="glxgears"
```
That way, xpra will be able to detect the GPU actually used by `start` sub commands.

* ## via WSL - Windows Subsystem for Linux
See [WSL - Windows Subsystem for Linux](WSL.md) OpenGL acceleration.

* ## via Xwayland
From within an X11 session, you can use start the Weston Wayland compositor, then start Xwayland and the xpra server with the `-use-display` option:
```shell
Xwayland :20 &
xpra start :20 --use-display
```
(the Weston window can be hidden)


* ## Shadowing
If the GPU is driving an existing display, you can [shadow](Shadow.md) it.\
The limitation here is that the performance of shadow sessions is inferior to [seamless](Seamless.md) and [desktop](Desktop.md) sessions.


* ## Taking over an existing display
Similarly to the shadow solution, you can tell xpra to take over an existing X11 display and manage it for remote access using the `--use-display` flag:
```shell
xpra start --use-display :0
```
The downside is that the session is no longer accessible from the local display.


***


# Caveats

## GL library conflicts
Proprietary graphics drivers can interfere with software OpenGL, [glvnd](https://github.com/NVIDIA/libglvnd) can solve this issue by allowing multiple OpenGL libraries to co-exist.

## Stability
VirtualGL and Xwayland will tie the OpenGL application to a secondary context (X11 / Wayland server) and if this server is killed or restarted then the application will crash - this is no longer the case with the EGL backend in VirtualGL version 3.

## VirtualGL setup
Please refer to the extensive [documentation](https://github.com/VirtualGL/virtualgl/tree/master/doc). \
Some applications may require workarounds, ie: [12: Using VirtualGL with setuid/setgid Executables
](https://github.com/VirtualGL/virtualgl/blob/master/doc/setuid.txt).

## Mesa configuration
Unless you are using the nvidia drivers, chances are that you will be using [mesa](https://www.mesa3d.org/).
Software rendering uses the [llvmpipe](https://docs.mesa3d.org/drivers/llvmpipe.html) driver.

Mesa's [documentation](https://docs.mesa3d.org/index.html) is extensive, in particular the [environment variables](https://docs.mesa3d.org/envvars.html) can be very useful.
