# Docker

| Purpose              | Base Distribution                        | Characteristics                              |
|----------------------|------------------------------------------|----------------------------------------------|
| [minimal](./minimal) | [alpine](https://www.alpinelinux.org/)   | smallest image                               |
| [base](./base)       | [fedora](https://www.fedoraproject.org/) | simple image, well supported but run as root |
| [safer](./safer)     | [fedora](https://www.fedoraproject.org/) | runs as a user, password protected, sandboxed with seccomp and landlock |
| [safer-ubuntu](./safer-ubuntu) | [ubuntu](https://ubuntu.com/)  | same as `safer`, using Ubuntu packages       |

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