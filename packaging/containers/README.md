# Containers

Containers can be used to do all sorts of things with xpra.

Here are a few ready-to-run solutions, using:
* [Docker](./docker/): example setups based on various distributions
* [podman / buildah](./podman/): scripts for building containers with buildah and running them with podman, ie: [split containers](./podman/split/) running in a pod,
  or the [secure](./podman/secure/) pod for isolating an application which may be hostile
* [printing](./docker/README.md#printing): the [xpra-cups](./docker/cups/Dockerfile) image runs the cups server used for forwarding the client's printers, next to the xpra container
