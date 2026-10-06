# Podman Containers

## Tools required

* [`buildah`](https://buildah.io/)
* a shell

## Setups

* [split](./split/): separate containers for the X11 virtual framebuffer, the xpra server and the applications, running in a pod
* [xpra-apps](./xpra-apps/): the same xpra server and applications containers, without the separate X11 virtual framebuffer
