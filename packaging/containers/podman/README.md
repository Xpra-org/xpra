# Podman Containers

## Tools required

* [`buildah`](https://buildah.io/)
* a shell

## Setups

* [split](./split/): separate containers for the X11 virtual framebuffer, the xpra server and the applications, running in a pod
* [xpra-apps](./xpra-apps/): the same xpra server and applications containers, without the separate X11 virtual framebuffer
* [secure](./secure/): a pod for running an application which may be hostile, which only shares the X11 display with the X server and the xpra server
* [encoder](./encoder/): the `secure` pod, using an xpra encoder server running on the host for GPU accelerated video encoding
* [gpu](./gpu/): the `secure` pod, with the GPU devices given to the xpra server for hardware accelerated video encoding

The [GPU acceleration](./GPU.md) page compares the security implications of the `encoder` and `gpu` variants.
