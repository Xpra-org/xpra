# Docker

| Purpose              | Base Distribution                        | Characteristics                              |
|----------------------|------------------------------------------|----------------------------------------------|
| [minimal](./minimal) | [alpine](https://www.alpinelinux.org/)   | smallest image                               |
| [base](./base)       | [fedora](https://www.fedoraproject.org/) | simple image, well supported but run as root |
| [safer](./safer)     | [fedora](https://www.fedoraproject.org/) | runs as a user, password protected, sandboxed with seccomp and landlock |
| [safer-ubuntu](./safer-ubuntu) | [ubuntu](https://ubuntu.com/)  | same as `safer`, using Ubuntu packages and Xdummy (build with `--build-arg XDUMMY=0` to use Xvfb) |
| [cups](./cups)       | [fedora](https://www.fedoraproject.org/) | not an xpra server: the cups server used for [printing](#printing) with the `base`, `safer` and `safer-ubuntu` images |

The `Dockerfile`s are executable and should create the images if you have `podman` install.\
You may also use `docker`, `buildah`, or any other tool that can handle the `Containerfile` format.

The images expose the xpra server on port 10000, both `tcp` and `udp` for quic connections.

## Running

Example using `podman` with the `xpra-base` image:
```shell
TOOL="podman"       # or "docker"
IMAGE="xpra-base"   # or "xpra-minimal"
$TOOL run --publish 10000:10000/tcp --publish 10000:10000/udp ${IMAGE}
```

## Printing

To forward the client's printers, run the `xpra-cups` image next to the `xpra-base`, `xpra-safer` or `xpra-safer-ubuntu` image,
with both containers sharing the same `/run` volume:
* the xpra server adds the client's printers to the cups server using its socket: `/run/cups/cups.sock`
* the applications print to these printers using the same socket
* the cups server sends the print jobs back to the xpra server using the xpra server's socket in `/run`

The xpra container must be started first, so that the volume is populated from its image.
The `xpra-cups` container does not need any network access:
```shell
TOOL="podman"       # or "docker"
IMAGE="xpra-safer"  # or "xpra-safer-ubuntu"
$TOOL volume create xpra-run
$TOOL run --detach --name xpra --volume xpra-run:/run \
    --env XPRA_PASSWORD=thepassword --publish 14500:14500/tcp --publish 14500:14500/udp ${IMAGE}
$TOOL run --detach --name xpra-cups --network none --volume xpra-run:/run xpra-cups
```
(use port `10000` without `XPRA_PASSWORD` for the `xpra-base` image)

The `xpra-cups` image allows the user running the xpra server to add and remove printers,
using the same default `UID` and `GID` build arguments as the `xpra-safer` images: if you change them, build both images with the same values. \
The `xpra-minimal` image does not support printing.
