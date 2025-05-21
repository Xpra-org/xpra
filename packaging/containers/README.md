# Containers

## Tools required

* [`buildah`](https://buildah.io/)
* a shell


## [xvfb](./xvfb.sh) image

This container is typically used as part of a pod as it only provides an X11 virtual framebuffer. \
It is based on [alpinelinux](https://alpinelinux.org/) to keep things "_small, simple and secure_".

<details>
  <summary>configuration</summary>

This container does not need any kind of network access,
though it usually needs to share `ipc` and `network` with the xpra server and the X11 applications
so that they can enable `XShm` for performance.

[xvfb.sh](./xvfb.sh) will create a container named `xvfb`,
ready to start the virtual framebuffer on the display number specified.
</details>

<details>
  <summary>disk usage</summary>

This image takes up under 300MB of disk space.\

The biggest cost by far are the OpenGL libraries:
```shell
$ du -sm /usr/lib/* | tail -n 3
38	/usr/lib/libgallium-24.2.8.so
43	/usr/lib/gallium-pipe
154	/usr/lib/libLLVM.so.19.1
```
If none of the applications will be using OpenGL, these can be omitted by running the script with:
```shell
OPENGL=0 ./xvfb.sh
```
</details>


## [xpra](./xpra.sh)

This container runs the xpra server and may use an existing `xvfb` if one is already started. \
This default image configuration is based on [fedora](https://fedoraproject.org/),
but [almalinux](https://almalinux.org/) or [rockylinux](https://rockylinux.org/) can also be used with the same script.

Applications may be added here, or to a separate container.

<details>
  <summary>disk usage</summary>

This image takes up 1GB of disk space.

The biggest cost by far are the media libraries: GStreamer, pulseaudio and the video codecs. \
To remove them, run the script with:
```shell
AUDIO=0 CODECS=0 ./xvfb.sh
```
</details>

## [desktop](desktop.sh)

This container runs a lightweight desktop environment based on [`winbar`](https://github.com/jmanc3/winbar).  \
The default image configuration is based on [Ubuntu Plucky](https://releases.ubuntu.com/plucky/),
but other Debian and Ubuntu releases can also be used.

## Pod

